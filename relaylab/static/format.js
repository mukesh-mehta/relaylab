export function eventLabel(id) {
  return `evt_${String(id).padStart(6, "0")}`;
}

export function byteLabel(value) {
  return value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KiB`;
}

export function timestamp(value) {
  return new Date(value).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function mergeEvents(current, older) {
  const unique = new Map(current.map(event => [event.id, event]));
  for (const event of older) if (!unique.has(event.id)) unique.set(event.id, event);
  return [...unique.values()].sort((a, b) => b.id - a.id);
}

export function eventQuery({ inbox, query, format, before }) {
  const params = new URLSearchParams({ inbox_id: String(inbox), format, limit: "30" });
  if (query.trim()) params.set("q", query.trim());
  if (before) params.set("before", String(before));
  return params.toString();
}

export function samplePayload(index) {
  const samples = [
    { type: "invoice.paid", data: { invoice_id: "inv_demo_1042", amount: 4200, currency: "USD", customer: "Acme Studio" } },
    { type: "repository.push", data: { repository: "demo/service-api", ref: "refs/heads/main", commits: 3 } },
    { type: "invoice.paid", data: { invoice_id: "inv_demo_1043", amount: 350, currency: "USD", customer: "Northwind" } },
  ];
  return structuredClone(samples[index % samples.length]);
}

export const roadmap = [
  { number: "06", title: "Durable delivery workers", text: "Transactional outbox, worker leases, crash recovery, and bounded HTTP egress.", tag: "DISTRIBUTED SYSTEMS" },
  { number: "07", title: "Retries, ordering & replay", text: "Backoff with jitter, dead-letter queues, idempotency, and per-target ordering.", tag: "RELIABILITY" },
  { number: "08", title: "Signed webhook verification", text: "Raw-byte signatures, timestamp windows, replay prevention, and secret rotation.", tag: "SECURITY" },
  { number: "09", title: "Sandboxed transformations", text: "Versioned transforms with CPU, memory, and output limits in isolated workers.", tag: "RUNTIME ISOLATION" },
  { number: "10", title: "Schema registry & evolution", text: "Versioned JSON Schemas, compatibility checks, validation, and quarantine.", tag: "DATA CONTRACTS" },
  { number: "11", title: "Teams & tenant isolation", text: "Authentication, scoped roles, project ownership, and per-tenant quotas.", tag: "ACCESS CONTROL" },
  { number: "12", title: "Observability & retention", text: "Trace propagation, delivery metrics, backpressure, retention, and load testing.", tag: "OPERATIONS" },
];
