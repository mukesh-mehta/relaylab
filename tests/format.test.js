import test from "node:test";
import assert from "node:assert/strict";
import { byteLabel, eventLabel, mergeEvents, eventQuery, samplePayload } from "../relaylab/static/format.js";

test("event identifiers never truncate large IDs", () => {
  assert.equal(eventLabel(42), "evt_000042");
  assert.equal(eventLabel(1234567), "evt_1234567");
});
test("byte sizes use binary KiB with precise boundary handling", () => {
  assert.equal(byteLabel(0), "0 B");
  assert.equal(byteLabel(1023), "1023 B");
  assert.equal(byteLabel(1536), "1.5 KiB");
});
test("paginated events deduplicate without mutating existing arrays", () => {
  const original = [{ id: 4 }, { id: 3 }];
  assert.deepEqual(mergeEvents(original, [{ id: 3 }, { id: 2 }]).map(item => item.id), [4, 3, 2]);
  assert.equal(original.length, 2);
});
test("search parameters round-trip special characters without altering routing", () => {
  const params = new URLSearchParams(eventQuery({ inbox: 3, query: " invoice & 100% ", format: "json", before: 20 }));
  assert.equal(params.get("q"), "invoice & 100%");
  assert.equal(params.get("before"), "20");
  assert.equal(params.get("inbox_id"), "3");
});
test("sample fixtures rotate and return independent objects", () => {
  assert.equal(samplePayload(0).data.amount, 4200);
  assert.equal(samplePayload(1).type, "repository.push");
  assert.equal(samplePayload(2).data.amount, 350);
  const sample = samplePayload(3); sample.data.amount = 0;
  assert.equal(samplePayload(0).data.amount, 4200);
});
