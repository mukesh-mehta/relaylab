"""HTTP capture, inspection API, and local rule simulation."""
import base64
import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path

import click
from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from .db import close_db, get_db, init_db, utcnow
from .engine import simulate, strict_json, text, validate_rule

REDACT_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"}


def rule_dict(row):
    result = dict(row)
    result["conditions"] = json.loads(result["conditions"])
    result["enabled"] = bool(result["enabled"])
    return result


def inbox_dict(row):
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    result["path"] = f"/inbox/{result.pop('token')}"
    return result


def query_integer(name, default=None, maximum=2147483647):
    raw = request.args.get(name)
    if raw is None:
        return default
    if not raw.isascii() or not raw.isdigit() or len(raw) > 10 or not 1 <= int(raw) <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}.")
    return int(raw)


def read_json():
    if not request.is_json:
        from werkzeug.exceptions import UnsupportedMediaType
        raise UnsupportedMediaType("Send application/json.")
    try:
        return strict_json(request.get_data().decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Send valid UTF-8 JSON with finite numbers and reasonable nesting.") from None


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get("RELAYLAB_DATABASE", str(Path(app.instance_path) / "relaylab.sqlite3")),
        MAX_CONTENT_LENGTH=256 * 1024,
        TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"],
    )
    if config:
        app.config.update(config)
    init_db(app)
    app.teardown_appcontext(close_db)

    @app.before_request
    def protect_management():
        if request.path.startswith("/api/") and request.method in ("POST", "PATCH", "DELETE"):
            if request.headers.get("X-RelayLab-Request") != "1":
                return jsonify(error="Missing X-RelayLab-Request header."), 403
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                return jsonify(error="Cross-origin management requests are not allowed."), 403

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(sqlite3.IntegrityError)
    def duplicate(_error):
        return jsonify(error="That name already exists. Choose a different one."), 409

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        get_db().execute("SELECT 1")
        return jsonify(status="ok", version="0.1.0", mode="local-simulation")

    @app.get("/api/stats")
    def stats():
        db = get_db()
        event_stats = dict(db.execute("SELECT count(*) AS events, coalesce(sum(is_json),0) AS json_events, coalesce(sum(byte_count),0) AS bytes FROM events").fetchone())
        run_stats = dict(db.execute("SELECT count(*) AS simulations, coalesce(sum(matched),0) AS matched_runs FROM runs").fetchone())
        return jsonify(**event_stats, **run_stats)

    @app.get("/api/inboxes")
    def inboxes():
        rows = get_db().execute("SELECT i.*, (SELECT count(*) FROM events e WHERE e.inbox_id=i.id) AS event_count FROM inboxes i ORDER BY i.id")
        return jsonify(inboxes=[inbox_dict(row) for row in rows])

    @app.post("/api/inboxes")
    def create_inbox():
        data = read_json()
        if not isinstance(data, dict) or set(data) != {"name"}:
            raise ValueError("Send an object containing only name.")
        name = text(data["name"], "name", 60)
        db = get_db()
        with db:
            cursor = db.execute("INSERT INTO inboxes(name,token,created_at) VALUES(?,?,?)", (name, secrets.token_urlsafe(24), utcnow()))
        return jsonify(inbox_dict(db.execute("SELECT * FROM inboxes WHERE id=?", (cursor.lastrowid,)).fetchone())), 201

    @app.patch("/api/inboxes/<int:inbox_id>")
    def pause_inbox(inbox_id):
        data = read_json()
        if not isinstance(data, dict) or set(data) != {"enabled"} or type(data["enabled"]) is not bool:
            raise ValueError("Send enabled as a boolean.")
        db = get_db()
        with db:
            changed = db.execute("UPDATE inboxes SET enabled=? WHERE id=?", (int(data["enabled"]), inbox_id)).rowcount
        if not changed:
            return jsonify(error="Inbox not found."), 404
        return jsonify(inbox_dict(db.execute("SELECT * FROM inboxes WHERE id=?", (inbox_id,)).fetchone()))

    @app.route("/inbox/<token>", methods=["POST", "PUT", "PATCH"])
    def capture(token):
        db = get_db()
        raw = request.get_data()
        try:
            strict_json(raw.decode("utf-8"))
            is_json = True
        except (ValueError, UnicodeError, RecursionError):
            is_json = False
        headers = {key: "[REDACTED]" if key.lower() in REDACT_HEADERS else value for key, value in request.headers.items()}
        # Serialize pause and capture writes: once a pause commits, later captures
        # cannot slip through based on an earlier enabled read.
        with db:
            db.execute("BEGIN IMMEDIATE")
            inbox = db.execute("SELECT * FROM inboxes WHERE token=?", (token,)).fetchone()
            if inbox is None:
                return jsonify(error="Inbox not found."), 404
            if not inbox["enabled"]:
                return jsonify(error="Inbox is paused."), 410
            cursor = db.execute("""INSERT INTO events(inbox_id,method,query_string,content_type,headers,body,byte_count,sha256,is_json,received_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (inbox["id"], request.method, request.query_string.decode("utf-8", errors="replace"),
                request.content_type or "application/octet-stream", json.dumps(headers), raw, len(raw), hashlib.sha256(raw).hexdigest(), int(is_json), utcnow()))
        return jsonify(accepted=True, event_id=cursor.lastrowid), 202

    @app.get("/api/events")
    def events():
        inbox_id, before, limit = query_integer("inbox_id"), query_integer("before"), query_integer("limit", 30, 100)
        query = request.args.get("q", "").strip()
        if len(query) > 200:
            raise ValueError("Search is limited to 200 characters.")
        format_filter = request.args.get("format", "all")
        if format_filter not in ("all", "json", "other"):
            raise ValueError("format must be all, json, or other.")
        clauses, params = [], []
        if inbox_id:
            clauses.append("e.inbox_id=?"); params.append(inbox_id)
        if before:
            clauses.append("e.id<?"); params.append(before)
        if format_filter != "all":
            clauses.append("e.is_json=?"); params.append(int(format_filter == "json"))
        if query:
            clauses.append("(instr(lower(CAST(e.body AS TEXT)),lower(?))>0 OR instr(lower(e.content_type),lower(?))>0 OR instr(lower(e.method),lower(?))>0)")
            params.extend([query, query, query])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = get_db().execute("""SELECT e.id,e.inbox_id,i.name AS inbox_name,e.method,e.content_type,e.byte_count,e.sha256,e.is_json,e.received_at,
            substr(e.body,1,160) AS preview FROM events e JOIN inboxes i ON e.inbox_id=i.id""" + where + " ORDER BY e.id DESC LIMIT ?", (*params, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            item = dict(row)
            item["preview"] = item["preview"].decode("utf-8", errors="replace")
            item["is_json"] = bool(item["is_json"])
            items.append(item)
        return jsonify(events=items, next_cursor=items[-1]["id"] if len(rows) > limit else None)

    def event_row(event_id):
        from werkzeug.exceptions import NotFound
        row = get_db().execute("SELECT e.*, i.name AS inbox_name FROM events e JOIN inboxes i ON e.inbox_id=i.id WHERE e.id=?", (event_id,)).fetchone()
        if row is None:
            raise NotFound("Event not found.")
        return row

    @app.get("/api/events/<int:event_id>")
    def event(event_id):
        result = dict(event_row(event_id))
        result["body_text"] = result.pop("body").decode("utf-8", errors="replace")
        result["headers"] = json.loads(result["headers"])
        result["is_json"] = bool(result["is_json"])
        # Pretty JSON stays a string, preserving integers larger than JS's safe range.
        result["pretty_json"] = json.dumps(strict_json(result["body_text"]), indent=2, ensure_ascii=True) if result["is_json"] else None
        return jsonify(result)

    @app.get("/api/events/<int:event_id>/raw")
    def raw_body(event_id):
        return Response(event_row(event_id)["body"], mimetype="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="relaylab-event-{event_id}.bin"'})

    @app.get("/api/events/<int:event_id>/fixture")
    def fixture(event_id):
        data = dict(event_row(event_id))
        data["body_base64"] = base64.b64encode(data.pop("body")).decode("ascii")
        data["headers"] = json.loads(data["headers"])
        data["is_json"] = bool(data["is_json"])
        response = jsonify(fixture_version=1, event=data)
        response.headers["Content-Disposition"] = f'attachment; filename="relaylab-event-{event_id}.json"'
        return response

    @app.get("/api/rules")
    def rules():
        return jsonify(rules=[rule_dict(row) for row in get_db().execute("SELECT * FROM rules ORDER BY id")])

    @app.post("/api/rules")
    def create_rule():
        data = validate_rule(read_json())
        db = get_db()
        with db:
            cursor = db.execute("INSERT INTO rules(name,target,mode,conditions,enabled,updated_at) VALUES(?,?,?,?,?,?)",
                (data["name"], data["target"], data["mode"], json.dumps(data["conditions"]), int(data["enabled"]), utcnow()))
        return jsonify(rule_dict(db.execute("SELECT * FROM rules WHERE id=?", (cursor.lastrowid,)).fetchone())), 201

    @app.patch("/api/rules/<int:rule_id>")
    def update_rule(rule_id):
        db = get_db()
        patch = read_json()
        if not isinstance(patch, dict):
            raise ValueError("Send a JSON object.")
        with db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
            if existing is None:
                return jsonify(error="Rule not found."), 404
            old = rule_dict(existing)
            data = validate_rule({**{key: old[key] for key in ("name", "target", "mode", "conditions", "enabled")}, **patch})
            db.execute("UPDATE rules SET name=?,target=?,mode=?,conditions=?,enabled=?,revision=revision+1,updated_at=? WHERE id=?",
                (data["name"], data["target"], data["mode"], json.dumps(data["conditions"]), int(data["enabled"]), utcnow(), rule_id))
        return jsonify(rule_dict(db.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()))

    @app.post("/api/events/<int:event_id>/simulate")
    def simulate_event(event_id):
        db = get_db()
        with db:
            db.execute("BEGIN IMMEDIATE")
            captured = event_row(event_id)
            if not captured["is_json"]:
                return jsonify(error="Routing simulation requires a valid UTF-8 JSON body."), 422
            active_rules = [rule_dict(row) for row in db.execute("SELECT * FROM rules WHERE enabled=1 ORDER BY id")]
            snapshot = simulate(strict_json(captured["body"].decode("utf-8")), active_rules)
            snapshot["event_sha256"] = captured["sha256"]
            timestamp = utcnow()
            cursor = db.execute("INSERT INTO runs(event_id,snapshot,matched,created_at) VALUES(?,?,?,?)",
                (event_id, json.dumps(snapshot), int(bool(snapshot["targets"])), timestamp))
        return jsonify(id=cursor.lastrowid, event_id=event_id, created_at=timestamp, **snapshot), 201

    @app.get("/api/runs")
    def runs():
        event_id, before, limit = query_integer("event_id"), query_integer("before"), query_integer("limit", 20, 100)
        clauses, params = [], []
        if event_id:
            clauses.append("event_id=?"); params.append(event_id)
        if before:
            clauses.append("id<?"); params.append(before)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = get_db().execute("SELECT * FROM runs" + where + " ORDER BY id DESC LIMIT ?", (*params, limit + 1)).fetchall()
        items = [{"id": row["id"], "event_id": row["event_id"], "created_at": row["created_at"], **json.loads(row["snapshot"])} for row in rows[:limit]]
        return jsonify(runs=items, next_cursor=items[-1]["id"] if len(rows) > limit else None)

    @app.cli.command("seed")
    def seed():
        """Create a sample inbox and two rules, without fabricating captured events."""
        from .samples import RULES
        db = get_db()
        with db:
            db.execute("INSERT OR IGNORE INTO inboxes(name,token,created_at) VALUES(?,?,?)", ("Development", secrets.token_urlsafe(24), utcnow()))
            for rule in RULES:
                data = validate_rule(rule)
                db.execute("INSERT OR IGNORE INTO rules(name,target,mode,conditions,enabled,updated_at) VALUES(?,?,?,?,?,?)",
                    (data["name"], data["target"], data["mode"], json.dumps(data["conditions"]), 1, utcnow()))
        click.echo("Sample inbox and rules ready. Start the server, then click Send sample to capture a real request.")

    return app
