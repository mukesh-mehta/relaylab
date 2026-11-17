# RelayLab engineering roadmap

**Status: all seven workstreams below are unimplemented.** Features 1–5 in README form the runnable baseline. These are proposed contracts and acceptance criteria, not descriptions of code that already exists.

The unfinished work is intentionally larger than the baseline. It requires reasoning about transactions, distributed failure, hostile inputs, isolation, data evolution, and operations. Avoid completing a feature by adding UI controls alone.

## Suggested sequence and dependencies

1. Define database migrations and implement **6: delivery workers**.
2. Add **7: retries/ordering/replay** against real worker crash scenarios.
3. Develop **8: signature verification** alongside the delivery work.
4. Add **10: schema registry**, then **9: isolated transforms** against explicit input/output contracts.
5. Complete **11: tenant isolation** before any shared deployment; design ownership columns early to avoid a later rewrite.
6. Instrument each component as it is built; finish **12: observability/retention** with controlled load and failure tests.

These dependencies guide implementation; they do not mean running the baseline requires any of these services.

## 6. Durable outbound delivery workers

**Problem:** A simulation records target labels but cannot deliver an event. Simply calling `requests.post()` inside ingestion would tie acknowledgement latency to the receiver and lose work on a crash.

**Proposed design**

- Introduce versioned migrations and tables for `destinations`, `deliveries`, and `delivery_attempts`. Keep the captured event body immutable.
- Separate a logical target label from a configured destination URL. Preserve the exact destination configuration version selected for a delivery.
- Create delivery intents transactionally with the operation that schedules them: no gap between committing a scheduling decision and recording its work.
- Claim queued work with an expiring lease and fencing token. A late worker must not complete a newer worker's lease. Record an attempt independently from the final delivery state.
- For multiple worker processes, choose and justify PostgreSQL row locking or another shared durable queue. SQLite remains the local simulator's default, not a claimed distributed queue.
- Use bounded timeouts and response sizes. Revalidate allowed addresses/redirects and avoid DNS-rebinding and private-network egress. Start with explicit destination allowlists.

**Acceptance tests**

- Kill the process immediately before and after the transaction commit; no committed delivery intent disappears.
- Kill a worker after the receiver accepted the body but before the worker recorded success. Recover without claiming exactly-once side effects; document the possible duplicate.
- Run multiple workers against the same queue; stale lease completions are rejected and queue progress continues.
- A hanging endpoint cannot block another destination indefinitely; response-body limits and egress restrictions are enforced.

**Done means:** a separate worker command, database migration and rollback/recovery instructions, real HTTP integration tests, inspectable attempt records, and a working opt-in delivery path. The local simulator remains usable without a worker.

## 7. Retry, ordering, and replay engine

**Depends on:** feature 6.

**Problem:** A single failed attempt does not define whether, when, or in what order to retry. Manual replay can duplicate business side effects.

**Proposed design**

- Define an explicit state machine: `queued → leased → succeeded`, or `retry_wait → queued`, with terminal `dead_lettered` and `cancelled` states. Specify legal transitions and lease-expiry behavior.
- Persist attempt numbers and `next_attempt_at`; use exponential backoff with bounded jitter and an injected clock/random source for deterministic tests.
- Specify retryable status codes, transport errors, bounded `Retry-After`, max attempts, and maximum retry age. Preserve the reason when a delivery becomes terminal.
- Support a per-destination concurrency cap and optional per-key ordering. Define whether a blocked earlier event stalls later events in the same ordering partition.
- Give a logical delivery a stable idempotency key across attempts. Give replay a new execution identity plus `replay_of`, actor, and reason. Do not promise to make an arbitrary receiver idempotent.
- Deduplicate replay command submissions with a client command key. Repeated HTTP requests to the replay API must not silently enqueue multiple replay jobs.

**Acceptance tests**

- With fake time, verify precise transition and scheduling behavior for 429, 503, timeouts, permanent 4xx, and malformed `Retry-After`.
- Crash/restart during `retry_wait`; the schedule survives without an in-memory timer.
- Simultaneously submit the same replay command and prove one command result is created.
- Demonstrate ordering with a failed first event, independent keys, lease expiry, cancellation, and a poison message.

**Done means:** durable scheduling, documented delivery semantics, replay API/UI, dead-letter inspection, and controlled failure tests. A retry button that immediately resends once is insufficient.

## 8. Signature verification and replay protection

**Depends on:** migration infrastructure from 6; outbound signing integrates with 6. Can begin before 7.

**Problem:** Capturing a request proves arrival, not who sent it. Raw-byte signatures fail if bodies are reserialized, while signature verification without freshness checks permits replay.

**Proposed design**

- Implement one explicitly documented signature protocol first, preferably a reviewed standard; distinguish it from provider-specific adapters.
- Verify the exact raw body plus protocol-defined timestamp/message identifier. Compare signatures in constant time and support bounded overlap during key rotation.
- Enforce a configurable timestamp window and reject future timestamps outside an allowed skew. Use a clock dependency in tests.
- Store replay identifiers atomically with acceptance, scoped by inbox/key identity and bounded by expiration. Concurrent duplicates must not both pass.
- Keep secrets in a configured secret source, exclude them from response payloads/logs/fixtures, and record only a verification outcome and key version.
- Define signature failure behavior before storing bodies; do not silently mark an unverifiable request as trusted. Design outbound signing separately from inbound verification.

**Acceptance tests**

- Known signature vectors, a one-byte mutation, whitespace changes, malformed encodings, duplicate signature fields, absent timestamps, and wrong keys.
- Boundary timestamps, clock skew, old/new key overlap, revoked keys, and post-rotation retries.
- Two workers receive the same signed identifier concurrently; at most one is accepted under the replay policy.
- Export/log inspection shows no secret values; signature failures cannot trigger outbound delivery.

**Done means:** protocol documentation, reproducible vectors, migration-backed replay storage, rotation procedure, and tests for races and trust boundaries.

## 9. Sandboxed payload transformations

**Depends on:** 6 for the delivery pipeline; coordinate input/output validation with 10.

**Problem:** Arbitrary user transforms are executable programs. Running Python `eval` or JavaScript `Function` in the API process would share its filesystem, network, memory, and failure domain.

**Proposed design**

- Select a deliberately restricted transform language or isolated runtime. Record the threat model and the limits the chosen isolation actually enforces.
- Store immutable transform versions with source digest, runtime version, declared input/output schema, and an explicit activation reference.
- Run in a separate process/container or suitable sandbox with no ambient secrets, no network, a restricted filesystem, and CPU/memory/output/deadline limits.
- Define deterministic inputs: injected time/randomness or no access to them. Keep the original body; store transformed output and its hash separately.
- Activation and rollback select a version; historical executions keep their original version. Failed transforms quarantine/block delivery rather than using partial output.

**Acceptance tests**

- Infinite loops, memory growth, huge outputs, unexpected encoding, filesystem/network attempts, and process termination.
- API ingestion remains responsive when transforms fail or time out.
- The same pinned transform/input gives reproducible output under the documented determinism contract.
- Rollback affects new work only; existing attempt lineage still identifies the transform used.

**Done means:** an actual isolation boundary, enforcement tests, version lifecycle, execution records, and documented residual risks. A try/except around in-process evaluation is not isolation.

## 10. Schema registry and compatibility checks

**Depends on:** migration infrastructure; integrate before transform activation and hosted delivery contracts.

**Problem:** Syntactically valid JSON can still violate a consumer's contract. Compatibility across schema versions is more complex than validating a few examples.

**Proposed design**

- Choose a supported JSON Schema dialect and a deliberately bounded subset for compatibility analysis. Version schemas immutably by subject and version.
- Separate document validation from compatibility checking. Define backward/forward/full modes against explicit producer-consumer semantics.
- For constructs the checker cannot prove safe, return `unknown/unsupported`; do not claim compatibility from sample data alone.
- Disable or tightly control remote reference resolution. Bound schema depth, reference cycles, pattern complexity, errors returned, and validation time.
- Attach a schema version and validation result to processing decisions; quarantine invalid events while retaining original captured bytes and actionable errors.
- Define promotion/rollback and how pending deliveries resolve their contract version.

**Acceptance tests**

- Required-field additions/removals, enum narrowing, numeric boundaries, object openness, nullable fields, and nested arrays under every supported mode.
- Cyclic references, unavailable remote references, pathological patterns, and oversized error sets.
- Unknown constructs fail conservatively; an invalid event cannot bypass a configured validation gate.
- A schema update never rewrites the result or version of a historical execution.

**Done means:** registry API/UI, persisted versions, a documented supported compatibility subset, quarantine workflow, and semantic regression tests.

## 11. Multi-tenant projects and access control

**Depends on:** migrations and a deployment design. Must be complete before shared/public use.

**Problem:** Current inbox identifiers route traffic but the management API trusts a single local user. Adding a login page alone does not create data isolation.

**Proposed design**

- Add users, organizations/projects, memberships, and roles. Define viewer/operator/admin permissions and ownership on every event, inbox, rule, run, destination, and job.
- Choose session authentication for the browser and scoped, revocable tokens for integrations. Specify expiry, rotation, CSRF protection, and account recovery.
- Centralize authorization and include tenant scope in every query, cursor, export, worker claim, and object lookup. Do not rely on the UI hiding controls.
- Define per-tenant ingestion/storage/work quotas and fair scheduling; prevent one tenant from exhausting shared workers.
- Migrate existing local data into an explicit default project with a reversible/exportable path. Keep local-only mode an explicit configuration, not an accidental authentication bypass.

**Acceptance tests**

- Cross-tenant guessed IDs for every read, write, export, history, and replay endpoint.
- A removed member or revoked token loses access; cached permissions cannot keep it alive indefinitely.
- Worker queries cannot deliver another tenant's payload using the wrong credentials.
- Role changes, migration failures, CSRF attempts, quota exhaustion, and account/session expiry.

**Done means:** a full authorization matrix, negative integration tests, ownership migrations, scoped credentials, and a production deployment guide.

## 12. Operational observability, retention, and backpressure

**Depends on:** 6/7 for delivery metrics; 11 for tenant-aware quotas and retention.

**Problem:** A total-events counter does not show queue health, latency, saturation, disk growth, or data-loss risk.

**Proposed design**

- Propagate trace context through ingestion, scheduling, attempts, and retries, with bounded input handling. Separate logical event traces from individual attempts.
- Export queue age/depth, lease expiry, attempt latency, retries, dead letters, transform failures, and rejection rates. Define units and avoid event-ID/URL labels with unbounded cardinality.
- Add retention policies for bodies, metadata, and attempts. Implement bounded deletion jobs with checkpoints; preserve referential integrity and explicitly mark expired payloads.
- Define disk-watermark and queue-depth admission policies before saturation. Return actionable errors/Retry-After while preserving the commit-before-ack invariant.
- Build synthetic workloads with bursty arrivals, slow endpoints, skewed tenants, large bodies, and process restarts. Establish targets from measurements rather than invented throughput claims.

**Acceptance tests**

- Controlled overload produces bounded queues/memory and predictable rejection behavior, not silent loss.
- A failed retention batch resumes correctly; history distinguishes an expired payload from a missing/corrupt record.
- Trace/metric exports contain no bodies, signatures, or secrets; cardinality remains bounded during a large event stream.
- Load reports include environment, workload, error rate, p50/p95/p99 latency, queue age, and recovery after failure.

**Done means:** instrumentation, retention workers, dashboards or reproducible queries, capacity/failure reports, and recovery runbooks.

## Completion rule

A feature moves to “implemented” only when its documented behavior works end to end, failure tests pass, setup is reproducible, and README/API/architecture documentation agrees with the code. Keep experimental work clearly marked; preserve the usable local core throughout.
