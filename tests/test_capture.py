import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from relaylab import create_app
from conftest import HEADERS


def test_capture_exact_bytes_and_restart(client, inbox, app):
    payload = b' {"id": 9007199254740993, "message": "hello"}\n'
    response = client.post(inbox["path"] + "?source=test", data=payload, content_type="application/json",
                           headers={"Authorization": "Bearer secret", "X-Api-Key": "hidden", "X-Trace-Id": "trace-1"})
    assert response.status_code == 202
    event_id = response.json["event_id"]
    restarted = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"]}).test_client()
    event = restarted.get(f"/api/events/{event_id}").json
    assert event["body_text"].encode() == payload
    assert event["byte_count"] == len(payload)
    assert event["sha256"] == hashlib.sha256(payload).hexdigest()
    assert event["query_string"] == "source=test"
    assert "9007199254740993" in event["pretty_json"]
    assert event["headers"]["Authorization"] == "[REDACTED]"
    assert event["headers"]["X-Api-Key"] == "[REDACTED]"
    assert event["headers"]["X-Trace-Id"] == "trace-1"
    assert restarted.get(f"/api/events/{event_id}/raw").data == payload


@pytest.mark.parametrize("payload,valid", [
    (b'{"ok":true}', True), (b"null", True), (b"42", True), (b"[]", True),
    (b'"hello"', True), (b"not-json", False), (b"", False), (b"\xff\x00\xfe", False),
    (b'{"n":NaN}', False), (b'{"n":1e400}', False), (b'{"x":1,"x":2}', False),
])
def test_payload_formats_and_lossless_fixtures(client, inbox, payload, valid):
    result = client.put(inbox["path"], data=payload, content_type="application/octet-stream")
    assert result.status_code == 202
    event_id = result.json["event_id"]
    event = client.get(f"/api/events/{event_id}").json
    assert event["is_json"] is valid
    fixture_response = client.get(f"/api/events/{event_id}/fixture")
    assert "attachment" in fixture_response.headers["Content-Disposition"]
    fixture = fixture_response.json
    assert fixture["fixture_version"] == 1
    assert base64.b64decode(fixture["event"]["body_base64"]) == payload
    if not valid:
        assert client.post(f"/api/events/{event_id}/simulate", headers=HEADERS).status_code == 422


def test_pause_resume_and_duplicates_are_distinct_events(client, inbox):
    assert client.patch(f"/api/inboxes/{inbox['id']}", json={"enabled": False}, headers=HEADERS).status_code == 200
    assert client.post(inbox["path"], json={"hello": 1}).status_code == 410
    assert client.get("/api/stats").json["events"] == 0
    client.patch(f"/api/inboxes/{inbox['id']}", json={"enabled": True}, headers=HEADERS)
    first = client.post(inbox["path"], json={"hello": 1}).json
    second = client.post(inbox["path"], json={"hello": 1}).json
    assert first["event_id"] != second["event_id"]
    assert client.get("/api/stats").json["events"] == 2


def test_pagination_is_stable_when_new_events_arrive(client, inbox):
    ids = [client.post(inbox["path"], json={"i": i}).json["event_id"] for i in range(7)]
    page = client.get("/api/events?limit=3").json
    assert [event["id"] for event in page["events"]] == ids[::-1][:3]
    client.post(inbox["path"], json={"i": "new"})
    older = client.get(f"/api/events?limit=3&before={page['next_cursor']}").json
    assert [event["id"] for event in older["events"]] == ids[::-1][3:6]
    last = client.get(f"/api/events?limit=3&before={older['next_cursor']}").json
    assert [event["id"] for event in last["events"]] == ids[:1]
    assert last["next_cursor"] is None


def test_search_is_literal_and_filters_intersect(client, inbox):
    second = client.post("/api/inboxes", json={"name": "Second"}, headers=HEADERS).json
    client.post(inbox["path"], json={"text": "100% Invoice"})
    client.post(inbox["path"], data=b"plain invoice")
    client.post(second["path"], json={"text": "invoice"})
    assert len(client.get("/api/events?q=%25").json["events"]) == 1
    items = client.get(f"/api/events?inbox_id={inbox['id']}&q=INVOICE&format=json").json["events"]
    assert len(items) == 1 and items[0]["is_json"] is True
    assert len(client.get("/api/events?format=other").json["events"]) == 1
    assert client.get("/api/events?q=does-not-exist").json["events"] == []


def test_body_limit_and_methods(client, inbox):
    assert client.post(inbox["path"], data=b"x" * (256 * 1024)).status_code == 202
    assert client.post(inbox["path"], data=b"x" * (256 * 1024 + 1)).status_code == 413
    assert client.get(inbox["path"]).status_code == 405
    assert client.patch(inbox["path"], json={"patched": True}).status_code == 202
    assert client.post("/inbox/missing", json={}).status_code == 404


def test_concurrent_captures_have_unique_ids_and_exact_count(app, client, inbox):
    def send(i):
        with app.test_client() as thread_client:
            response = thread_client.post(inbox["path"], json={"index": i})
            assert response.status_code == 202
            return response.json["event_id"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(send, range(24)))
    assert len(set(ids)) == 24
    assert client.get("/api/stats").json["events"] == 24


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "before=-1", "inbox_id=nope", "limit=999999999999", "format=xml", "q=" + "x" * 201])
def test_invalid_list_parameters(client, query):
    assert client.get("/api/events?" + query).status_code == 400


def test_management_guards_and_assets(client):
    assert client.post("/api/inboxes", json={"name": "x"}).status_code == 403
    assert client.post("/api/inboxes", json={"name": "x"}, headers={**HEADERS, "Origin": "https://elsewhere.test"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "elsewhere.test"}).status_code == 400
    assert client.post("/api/inboxes", data="text", headers=HEADERS).status_code == 415
    assert client.post("/api/inboxes", data="{", content_type="application/json", headers=HEADERS).status_code == 400
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert "frame-ancestors 'none'" in client.get("/").headers["Content-Security-Policy"]


def test_inbox_validation_and_seed_idempotency(client, app, inbox):
    assert client.post("/api/inboxes", json={"name": "Test inbox"}, headers=HEADERS).status_code == 409
    for invalid in ({"name": " "}, {"name": "x" * 61}, [], {"name": "X", "enabled": True}):
        assert client.post("/api/inboxes", json=invalid, headers=HEADERS).status_code == 400
    assert client.patch(f"/api/inboxes/{inbox['id']}", json={"enabled": "false"}, headers=HEADERS).status_code == 400
    assert client.patch("/api/inboxes/999", json={"enabled": False}, headers=HEADERS).status_code == 404
    for _ in range(2):
        assert app.test_cli_runner().invoke(args=["seed"]).exit_code == 0
    assert len(client.get("/api/inboxes").json["inboxes"]) == 2
    assert len(client.get("/api/rules").json["rules"]) == 2
    assert client.get("/api/stats").json["events"] == 0
