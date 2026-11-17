# Architecture and extension boundaries

## Current components

The Python process serves the JavaScript interface and a same-origin API. There is no background worker, broker, cache, scheduler, or external service in the current runtime. `app.py` handles HTTP and transactions; `db.py` owns connection lifecycle/schema creation; `engine.py` implements pure routing semantics.

The frontend has four views: capture, routing rules, run history, and a read-only roadmap. Captured data and decisions always come from the Python API. Only synthetic sample-body generation, formatting, and view state run in the browser.

## Data model

| Table | Responsibility | Important fields |
|---|---|---|
| `inboxes` | Named receive endpoints | Unique name/token, enabled flag |
| `events` | Immutable captured messages | Inbox FK, raw BLOB, hash, timestamp, metadata, JSON classification |
| `rules` | Current rule definitions | Unique name, target label, conditions, mode, enabled, revision |
| `runs` | Stored simulation decisions | Event FK, timestamp, complete decision snapshot, matched flag |

There is no separate historical rule-version table. The current rule row changes in place; run snapshots preserve the revision and evaluated conditions that mattered to each run. A revision counter plus snapshots is not a general version registry.

Schema version 1 is recorded in SQLite's `user_version`. Unknown future versions fail startup. This is a version guard, not a migration framework. Feature 6 must introduce actual migrations before altering persisted data.

## Capture transaction

1. Read at most the configured Flask body limit, preserving bytes.
2. Classify strict UTF-8 JSON, compute the body hash, and redact known credential headers.
3. Acquire `BEGIN IMMEDIATE`, read the inbox's enabled state, and insert the event.
4. Commit, then return 202 with the event ID.

Pause updates and capture inserts serialize through SQLite's write lock. Once a pause commits, a later capture transaction observes the paused state. The API acknowledges only after the write commits; it cannot guarantee the client received that acknowledgement. A retry after a lost response creates a second capture. The hash is descriptive and is not used to deduplicate.

Connections are per Flask application context, enable foreign keys, and close on teardown. WAL permits readers alongside a writer; writers still serialize, with a 10-second lock timeout. This is appropriate for a local lab, not a claim of multi-node capacity.

## Simulation transaction

1. Acquire a write transaction and load the immutable event.
2. Reject bodies that were not classified as strict UTF-8 JSON.
3. Read enabled current rules in ascending ID order.
4. Evaluate conditions without I/O or code execution.
5. Persist a run containing condition checks, rule names/revisions, targets, engine version, and body hash.
6. Commit and return the snapshot.

The write transaction prevents a rule edit from changing the set midway through a simulation. This favors coherent local snapshots over write throughput. Disabled rules are omitted. All enabled rules are evaluated, and matched target labels are deduplicated. A no-match run is still recorded.

The engine's `MISSING` sentinel distinguishes absent paths from JSON null. JSON Pointer arrays accept nonnegative canonical indexes; `01`, negative indexes, and `-` are unresolved. Scalars compare without Python's bool-as-int coercion. Parser rejects duplicate keys and non-finite numbers so routing does not depend on ambiguous JSON interpretation.

## UI consistency and pagination

Event cursors are numeric IDs with `id < before`, not offset pages. New arrivals therefore cannot shift older-page boundaries. The browser deduplicates appended rows by ID. Search predicates are parameterized and substring-based, including literal `%` and `_`.

Event-list and event-detail requests use generation counters to discard stale responses after selection/filter changes. Polling is non-overlapping within its timer loop, stops while a modal is open, and skips hidden browser tabs. Loading older events turns off polling to avoid replacing the expanded list. A refresh returns the newest page.

The browser inserts payloads and user-controlled labels with `textContent`; it does not render captured HTML. Formatted JSON remains a Python-produced string to preserve integer digits. Downloaded raw bodies use an attachment content disposition and an octet-stream media type.

## Security boundary

The process listens on loopback with trusted localhost hosts. The management API requires a custom header and rejects mismatched browser origins. No CORS policy opens management reads to other sites. These measures reduce accidental browser-origin access but do not authenticate local programs or provide tenant isolation.

Capture URLs accept normal HTTP sender traffic intentionally. The receiver does not verify signatures. A generated inbox token is not advertised as a secret security boundary. Header redaction covers only a small explicit list; payload/query/custom-header sanitization is the operator's responsibility in this local version.

SQLite and fixtures are unencrypted files. Snapshots can be modified by someone with database access; no tamper-evident audit claim is made. There is no public gateway, TLS termination, rate-limiting layer, retention worker, or credential manager.

## Extension seams

- **Delivery:** add a separate scheduling boundary and durable delivery intent. Do not add network I/O to `simulate()` or capture acknowledgements.
- **Retries:** use persisted job state and injectable time, not timer threads in the web process.
- **Verification:** signature checks need original bytes before trusting or processing an event. Keep capture/hash semantics explicit if acceptance policy changes.
- **Transforms:** preserve original bytes; store versioned derived outputs separately and execute outside the API process.
- **Schemas:** record validation policy/version with an execution; do not silently reinterpret historical runs.
- **Tenancy:** scope every table and worker query; the current global rules model must become explicit project ownership.
- **Retention:** define how history references an intentionally expired body before adding deletion jobs.

The proposed contracts in ROADMAP are design work still to implement. They should not be mistaken for dormant services or guaranteed extension APIs.
