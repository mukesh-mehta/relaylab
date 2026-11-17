# Contributing to RelayLab

Run README's setup and tests. Start each change on a focused branch. This repository deliberately leaves seven large features unfinished; consult ROADMAP before designing one.

Before implementing a roadmap item, record its state transitions, persistence boundaries, threat model, and failure recovery contract. Prefer an issue/design discussion before introducing brokers, a database replacement, credentials, or a code execution runtime.

Preserve the current invariants:

- Capture body bytes without reserialization and commit before acknowledging.
- Keep rule evaluation deterministic, typed, and free of side effects.
- Preserve historical run snapshots when editing rules.
- Keep v0.1 runnable without optional delivery infrastructure.
- Use temporary databases in tests and synthetic payloads in examples/screenshots.

Add behavior-oriented tests for changes, especially concurrency and failure recovery. Do not use sleep-based timing when a fake clock or synchronization primitive makes a test deterministic. Avoid committing real webhook payloads, fixture exports, databases, credentials, or `.venv`.

Useful commit prefixes: `feat:`, `fix:`, `test:`, `docs:`. A pull request should explain the changed behavior, tests performed, migration/recovery steps if relevant, and remaining limits. Mark a roadmap feature complete only when its full acceptance contract is satisfied.
