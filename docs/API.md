# RelayLab API v0.1

Base URL: `http://127.0.0.1:5050`. This API is for a single user on localhost. There is no authentication or public-hosting support.

Management writes to `/api/` require `X-RelayLab-Request: 1`. Send `Content-Type: application/json` for JSON bodies. Cross-origin management writes are rejected. The capture endpoint deliberately does not require this custom header; a normal HTTP sender can post to its generated inbox path.

## Inboxes and capture

| Method | Path | Contract |
|---|---|---|
| GET | `/api/health` | Database connectivity, version, and `local-simulation` mode |
| GET | `/api/stats` | Global event/JSON/run/matched-run counts and captured byte total |
| GET | `/api/inboxes` | `{inboxes:[...]}` ordered by ID; each has name, path, enabled, creation time, event count |
| POST | `/api/inboxes` | Body `{"name":"Billing"}`; unique name up to 60 characters; returns 201 |
| PATCH | `/api/inboxes/<id>` | Body `{"enabled":false}` pauses; true resumes |
| POST/PUT/PATCH | `/inbox/<token>` | Capture up to 256 KiB of any body; returns 202 with `{accepted:true,event_id:...}` after commit |

Paused inboxes return 410 and store nothing. Missing inboxes return 404. Names are trimmed and case-sensitive. Tokens are randomly generated; they are routing identifiers, not access-control credentials. Duplicate requests create separate event IDs. JSON parsing never determines capture acceptance within the body limit; it determines whether simulation is available.

## Event inspection and exports

`GET /api/events` returns `{events:[...],next_cursor:<integer-or-null>}`.

Optional query parameters:

| Parameter | Meaning |
|---|---|
| `inbox_id` | Positive inbox ID; omit to inspect all inboxes |
| `q` | Literal substring, up to 200 characters, in body text, method, or content type |
| `format` | `all` (default), `json`, or `other` |
| `limit` | 1–100; default 30 |
| `before` | Positive event ID; return older IDs only |

Results sort by ID descending. Use the returned `next_cursor` as `before`. Newer arrivals do not move this boundary. Body search uses SQLite `lower`/`instr`; full Unicode case-folding and indexed full-text search are not implemented. Binary body search is best-effort text matching. Each list item includes a UTF-8 replacement-decoded preview of the first 160 bytes.

| Method | Path | Result |
|---|---|---|
| GET | `/api/events/<id>` | Full metadata, redacted headers, `body_text`, `is_json`, `pretty_json` |
| GET | `/api/events/<id>/raw` | `application/octet-stream` attachment, exact original body |
| GET | `/api/events/<id>/fixture` | Versioned JSON attachment with base64 body and metadata |

`pretty_json` is **text**, not an embedded JSON object. This preserves large integer rendering in JavaScript. The raw text preview may replace invalid UTF-8; raw downloads/base64 fixtures do not.

Example fixture envelope:

```json
{
  "fixture_version": 1,
  "event": {
    "id": 1,
    "inbox_id": 1,
    "inbox_name": "Billing",
    "method": "POST",
    "query_string": "",
    "content_type": "application/json",
    "headers": {"Content-Type":"application/json"},
    "body_base64": "e30=",
    "byte_count": 2,
    "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "is_json": true,
    "received_at": "2026-11-17T00:00:00+00:00"
  }
}
```

The example represents body bytes `{}`. Fixtures are exports only: there is no import or replay endpoint in v0.1.

## Routing rules

- `GET /api/rules`: `{rules:[...]}` in ascending ID order.
- `POST /api/rules`: create a rule, returning 201.
- `PATCH /api/rules/<id>`: update supplied fields, preserve omitted fields, increment revision. Even a no-op patch records a new revision.

```json
{
  "name": "High-value invoices",
  "target": "finance-review",
  "mode": "all",
  "enabled": true,
  "conditions": [
    {"path": "/type", "op": "equals", "value": "invoice.paid"},
    {"path": "/data/amount", "op": "greater_than", "value": 2000}
  ]
}
```

Names and target labels contain 1–80 characters. Rule names are unique. `mode` defaults to `all`; `enabled` defaults to true. Conditions contain exactly `path`, `op`, and `value`, with 1–8 conditions per rule. Pointers are at most 300 characters. Expected values are JSON scalars; string values are at most 1,000 characters. Unknown fields/operators and invalid typed operands are rejected. See README for matching semantics.

The server adds `id`, `revision`, and `updated_at`. These cannot be set by clients. Rules apply globally to all inboxes. Target values are labels and never fetched as URLs.

## Simulation and history

`POST /api/events/<id>/simulate` requires the management header but no body. It evaluates currently enabled rules in a single snapshot and returns 201:

```json
{
  "id": 1,
  "event_id": 1,
  "created_at": "2026-11-17T00:00:00+00:00",
  "engine_version": 1,
  "event_sha256": "...",
  "targets": ["finance-review"],
  "delivery_performed": false,
  "decisions": [
    {
      "rule_id": 1,
      "revision": 1,
      "name": "High-value invoices",
      "target": "finance-review",
      "mode": "all",
      "matched": true,
      "checks": [
        {"path":"/data/amount","op":"greater_than","value":2000,"present":true,"matched":true}
      ]
    }
  ]
}
```

The example is abbreviated to one condition. A non-JSON body returns 422 and creates no run. A JSON event with no enabled rules creates a valid run with empty `decisions` and `targets`. Repeating a simulation creates a separate run; there is no idempotency key in v0.1.

`GET /api/runs?event_id=1&limit=20&before=123` returns `{runs:[...],next_cursor:...}`. `event_id` and `before` are optional. The default limit is 20 and the maximum is 100. Runs sort newest first and include persisted decisions, not reevaluation against current rules.

## Errors and operational boundaries

Client errors use `{"error":"Readable explanation"}`:

| Status | Meaning |
|---|---|
| 400 | Invalid object, rule, JSON body, host, or query parameter |
| 403 | Missing management header or forbidden management origin |
| 404 | Missing inbox/event/rule/route |
| 405 | Unsupported HTTP method |
| 409 | Duplicate inbox or rule name |
| 410 | Paused capture inbox |
| 413 | Request body larger than 256 KiB |
| 415 | Management JSON body has the wrong content type |
| 422 | Captured body cannot be simulated as strict UTF-8 JSON |

Database/disk failures can produce 500 responses and never successful capture acknowledgements. A lost response can still leave a committed event; sender retries can duplicate it. API responses disable browser caching. No server-side rate limit, deletion endpoint, delivery/retry endpoint, or public authentication API exists yet.
