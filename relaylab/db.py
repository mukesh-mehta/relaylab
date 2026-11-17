"""Connection lifecycle and the version-one local schema."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS inboxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    token TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inbox_id INTEGER NOT NULL REFERENCES inboxes(id),
    method TEXT NOT NULL,
    query_string TEXT NOT NULL,
    content_type TEXT NOT NULL,
    headers TEXT NOT NULL,
    body BLOB NOT NULL,
    byte_count INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    is_json INTEGER NOT NULL CHECK(is_json IN (0,1)),
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_inbox_id ON events(inbox_id, id DESC);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    target TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('all','any')),
    conditions TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    snapshot TEXT NOT NULL,
    matched INTEGER NOT NULL CHECK(matched IN (0,1)),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_event_id ON runs(event_id, id DESC);
PRAGMA user_version = 1;
"""


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def init_db(app):
    path = Path(app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError(f"Unsupported database version: {version}")
        connection.executescript(SCHEMA)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()
