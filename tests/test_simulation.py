import pytest

from conftest import HEADERS

RULE = {"name": "Invoices", "target": "billing", "mode": "all", "conditions": [
    {"path": "/type", "op": "equals", "value": "invoice.paid"},
]}


def test_rule_updates_do_not_rewrite_past_runs(client, inbox):
    event_id = client.post(inbox["path"], json={"type": "invoice.paid"}).json["event_id"]
    rule = client.post("/api/rules", json=RULE, headers=HEADERS).json
    run = client.post(f"/api/events/{event_id}/simulate", headers=HEADERS)
    assert run.status_code == 201
    assert run.json["targets"] == ["billing"]
    assert run.json["decisions"][0]["revision"] == 1
    assert client.patch(f"/api/rules/{rule['id']}", json={"target": "finance-v2"}, headers=HEADERS).json["revision"] == 2
    newer = client.post(f"/api/events/{event_id}/simulate", headers=HEADERS).json
    assert newer["targets"] == ["finance-v2"]
    history = client.get(f"/api/runs?event_id={event_id}").json["runs"]
    assert history[1]["targets"] == ["billing"]
    assert history[1]["decisions"][0]["revision"] == 1
    assert history[0]["decisions"][0]["revision"] == 2
    assert client.get("/api/stats").json["matched_runs"] == 2


def test_disabled_and_zero_rules_produce_auditable_no_match(client, inbox):
    event_id = client.post(inbox["path"], json={}).json["event_id"]
    first = client.post(f"/api/events/{event_id}/simulate", headers=HEADERS).json
    assert first["decisions"] == [] and first["targets"] == []
    rule = client.post("/api/rules", json=RULE, headers=HEADERS).json
    client.patch(f"/api/rules/{rule['id']}", json={"enabled": False}, headers=HEADERS)
    second = client.post(f"/api/events/{event_id}/simulate", headers=HEADERS).json
    assert second["decisions"] == []
    assert client.get("/api/stats").json["simulations"] == 2
    assert client.get("/api/stats").json["matched_runs"] == 0


def test_duplicate_or_invalid_updates_leave_original_unchanged(client):
    first = client.post("/api/rules", json=RULE, headers=HEADERS).json
    second = client.post("/api/rules", json={**RULE, "name": "Other"}, headers=HEADERS).json
    assert client.post("/api/rules", json=RULE, headers=HEADERS).status_code == 409
    assert client.patch(f"/api/rules/{second['id']}", json={"name": first["name"]}, headers=HEADERS).status_code == 409
    assert client.patch(f"/api/rules/{first['id']}", json={"conditions": []}, headers=HEADERS).status_code == 400
    rules = client.get("/api/rules").json["rules"]
    assert rules[0]["revision"] == 1
    assert rules[1]["name"] == "Other" and rules[1]["revision"] == 1


@pytest.mark.parametrize("changes", [{"conditions": []}, {"conditions": RULE["conditions"] * 9}, {"enabled": 1}, {"mode": "script"}, {"name": " "}, {"target": "x" * 81}, {"code": "exec()"}])
def test_rule_validation(client, changes):
    assert client.post("/api/rules", json={**RULE, **changes}, headers=HEADERS).status_code == 400
    assert client.get("/api/rules").json["rules"] == []


def test_history_pagination_and_missing_resources(client, inbox):
    event_id = client.post(inbox["path"], json={}).json["event_id"]
    for _ in range(4):
        client.post(f"/api/events/{event_id}/simulate", headers=HEADERS)
    page = client.get("/api/runs?limit=2").json
    older = client.get(f"/api/runs?limit=2&before={page['next_cursor']}").json
    assert [run["id"] for run in page["runs"] + older["runs"]] == [4, 3, 2, 1]
    assert older["next_cursor"] is None
    for suffix in ("", "/raw", "/fixture"):
        assert client.get("/api/events/999" + suffix).status_code == 404
    assert client.post("/api/events/999/simulate", headers=HEADERS).status_code == 404
    assert client.patch("/api/rules/999", json={}, headers=HEADERS).status_code == 404
