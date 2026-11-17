# Verification record

Verified on **17 November 2026**, using Python 3.12 and Node.js 18.

## Automated checks

- **67 Python tests passed.** Coverage includes exact request bytes, SHA-256, binary fixtures, persistence across app instances, pause/resume, body limits, 24 captures from concurrent threads, stable cursor pagination, input validation, JSON Pointer escapes/arrays, strict scalar comparisons, immutable run snapshots, and seeded setup.
- **5 JavaScript tests passed.** Coverage includes event identifiers, byte units, page deduplication, search query encoding, and independent rotating sample payloads.
- JavaScript syntax checks passed.
- Python dependency consistency checked with `pip check`.
- The standalone demo sender sent three real HTTP requests to the running local app; all returned 202 and distinct event IDs.

## Browser checks

- Captured synthetic invoice and repository-push events through the real HTTP endpoint.
- Verified both seeded routing paths and a no-match run.
- Edited a rule's target, then inspected an older run: it retained its original target, conditions, and revision. Restored the seeded target afterward.
- Created new inboxes, switched inbox selection, and verified a paused inbox disables the sample sender. Pause/resume capture status codes are also covered by API tests.
- Searched for repository-push events and verified the filtered list.
- Inspected desktop and 390-pixel mobile layouts. No horizontal document overflow was observed at that mobile width.
- Captured the README screenshot from the running app using synthetic data.
- No browser console warnings or errors were observed in the final inspection.

The inbox creation flow was adjusted so its dialog closes after the new inbox view is ready, avoiding interaction with a stale inbox selector during refresh.

## Boundaries of verification

Browser QA used a separate database at a temporary path. The distributed ZIP does not contain that database or any virtual environment. Export contents were validated through API tests; native download dialogs were not automated. Only Python 3.12 was executed locally. Python 3.11/3.13 and Node 22 are configured in GitHub Actions, but remote CI has not run because no GitHub repository has been connected for this project.

These checks validate the local baseline. They do not establish production performance, public-host security, multi-tenant isolation, or the seven unimplemented roadmap features.
