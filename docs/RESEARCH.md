# Research and project choice

Researched on **17 November 2026**. Primary references:

- [Hookdeck basics](https://hookdeck.com/docs/hookdeck-basics): distinguishes receipt, routing, transformations, delivery, retries, and observability.
- [Svix webhook architecture](https://www.svix.com/webhook-architecture/): describes durable storage before acknowledgement, endpoint-specific queues, signing, retries, and attempt history.
- [RFC 6901: JSON Pointer](https://www.rfc-editor.org/info/rfc6901/): defines path syntax for addressing JSON values.

## Why this idea

A webhook lab is meaningfully different from a personal resource tracker. It provides a useful small baseline—capturing and understanding HTTP events—while naturally supporting difficult extensions. Delivery guarantees, worker crashes, replay, authenticity, sandboxing, compatibility, and tenant isolation remain substantial engineering work.

The selected scope is **5 implemented features and 7 planned features**. That deliberately leaves more unfinished scope than Trailmark's 3 planned features. The roadmap's design contracts are project proposals, not copied claims about the reference products.

## Boundaries

RelayLab is not a production gateway, a clone of these services, or a provider-specific integration. It does not claim their scale or reliability guarantees. No code was copied from the referenced projects. The current simulator has no external delivery side effects, and all sample payloads are synthetic.
