import { eventLabel, byteLabel, timestamp, mergeEvents, eventQuery, samplePayload, roadmap } from "./format.js";

const $ = selector => document.querySelector(selector);
const state = { inbox: null, inboxes: [], events: [], next: null, query: "", format: "all", selected: null, rules: [], history: [], historyNext: null, view: "capture" };
let eventRequest = 0;
let detailRequest = 0;
let sampleIndex = 0;
let editingRule = null;
let toastTimer;
let debounce;
let polling = false;

function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

async function api(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(path, { method, headers: { "Content-Type": "application/json", "X-RelayLab-Request": "1" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  } catch { throw new Error("Cannot reach RelayLab. Start the Python server and retry."); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 6000);
}

function showError(error) {
  $("#global-error span").textContent = error.message;
  $("#global-error").hidden = false;
  $("#stream-state").textContent = "Connection error";
}

async function busy(button, action) {
  button.disabled = true;
  try { await action(); } catch (error) { toast(error.message); }
  finally {
    button.disabled = false;
    if (button.id === "simulate") button.disabled = !state.selected?.is_json;
    if (button.id === "send-sample" || button.id === "pause-inbox") renderEndpoint();
  }
}

async function refreshStats() {
  const data = await api("/api/stats");
  $("#stat-events").textContent = data.events;
  $("#stat-json").textContent = data.json_events;
  $("#stat-runs").textContent = data.simulations;
  $("#stat-matched").textContent = data.matched_runs;
}

async function loadInboxes() {
  const data = await api("/api/inboxes");
  state.inboxes = data.inboxes;
  if (!state.inbox || !data.inboxes.some(inbox => inbox.id === state.inbox)) state.inbox = data.inboxes[0]?.id ?? null;
  const options = data.inboxes.map(inbox => {
    const option = node("option", "", inbox.name);
    option.value = inbox.id; option.selected = inbox.id === state.inbox;
    return option;
  });
  $("#inbox-select").replaceChildren(...(options.length ? options : [node("option", "", "Create an inbox to start")]));
  renderEndpoint();
}

function renderEndpoint() {
  const inbox = state.inboxes.find(item => item.id === state.inbox);
  $("#endpoint-url").textContent = inbox ? `${location.origin}${inbox.path}` : "Create an inbox to get a local endpoint";
  $("#inbox-state").textContent = inbox ? (inbox.enabled ? "Listening" : "Paused") : "No inbox";
  $("#inbox-state").className = `pill${inbox?.enabled ? " green" : ""}`;
  $("#copy-endpoint").disabled = !inbox;
  $("#pause-inbox").disabled = !inbox;
  $("#pause-inbox").textContent = inbox?.enabled ? "Pause inbox" : "Resume inbox";
  $("#send-sample").disabled = !inbox?.enabled;
}

async function loadEvents(append = false) {
  const ticket = ++eventRequest;
  if (!state.inbox) { state.events = []; state.next = null; renderEvents(); return true; }
  $("#stream-state").textContent = "Refreshing…";
  try {
    const data = await api(`/api/events?${eventQuery({ inbox: state.inbox, query: state.query, format: state.format, before: append ? state.next : null })}`);
    if (ticket !== eventRequest) return;
    state.events = append ? mergeEvents(state.events, data.events) : data.events;
    state.next = data.next_cursor;
    renderEvents();
    $("#global-error").hidden = true;
    $("#stream-state").textContent = $("#live").checked ? "Live · every 5s" : "Manual refresh";
    return true;
  } catch (error) { if (ticket === eventRequest) showError(error); return false; }
}

function renderEvents() {
  $("#event-count").textContent = state.events.length;
  $("#load-more").hidden = !state.next;
  $("#page-info").textContent = state.events.length ? `${state.events.length} events shown · newest first` : "No captured events in this view";
  if (!state.events.length) {
    const empty = node("div", "empty");
    empty.append(node("span", "", "⌁"), node("h3", "", state.query || state.format !== "all" ? "No matching events" : "Waiting for a signal"),
      node("p", "", state.inbox ? "Send a sample or POST to your capture endpoint." : "Create an inbox to receive your first request."));
    $("#event-list").replaceChildren(empty);
    return;
  }
  $("#event-list").replaceChildren(...state.events.map(event => {
    const button = node("button", `event-row${event.id === state.selected?.id ? " selected" : ""}`);
    button.setAttribute("aria-label", `Inspect ${eventLabel(event.id)}`);
    button.setAttribute("aria-pressed", String(event.id === state.selected?.id));
    const left = node("div", "event-content");
    const title = node("div", "event-title");
    title.append(node("span", "method", event.method), node("strong", "mono", eventLabel(event.id)), node("span", "event-format", event.is_json ? "JSON" : "RAW"));
    left.append(title, node("p", "event-preview", event.preview.replace(/\s+/g, " ") || "(empty body)"));
    const right = node("div", "event-time");
    right.append(node("span", "", new Date(event.received_at).toLocaleTimeString()), node("small", "", byteLabel(event.byte_count)));
    button.append(left, right);
    button.addEventListener("click", () => selectEvent(event.id));
    return button;
  }));
}

function switchTab(name) {
  for (const pane of ["payload", "headers", "decisions"]) {
    $(`#${pane}-pane`).hidden = pane !== name;
    $(`[data-tab="${pane}"]`).setAttribute("aria-selected", String(pane === name));
  }
}

function clearSelection() {
  detailRequest++;
  state.selected = null;
  $("#event-detail").hidden = true;
  $("#inspector-empty").hidden = false;
}

async function selectEvent(id) {
  const ticket = ++detailRequest;
  try {
    const event = await api(`/api/events/${id}`);
    if (ticket !== detailRequest) return;
    state.selected = event;
    $("#event-detail").hidden = false;
    $("#inspector-empty").hidden = true;
    $("#detail-title").textContent = eventLabel(event.id);
    const meta = [event.method, event.content_type, byteLabel(event.byte_count), timestamp(event.received_at)];
    $("#detail-meta").replaceChildren(...meta.map(value => node("span", "", value)));
    const hash = node("span", "hash mono", `SHA-256 ${event.sha256}`);
    hash.title = event.sha256;
    $("#detail-meta").append(hash);
    if (event.query_string) $("#detail-meta").append(node("span", "hash mono", `Query: ${event.query_string}`));
    $("#headers-code").textContent = JSON.stringify(event.headers, null, 2);
    $("#raw-toggle").checked = false;
    renderPayload();
    $("#simulate").disabled = !event.is_json;
    $("#simulate").title = event.is_json ? "Evaluate enabled rules" : "Only valid UTF-8 JSON can be simulated";
    $("#download-raw").href = `/api/events/${id}/raw`;
    $("#download-fixture").href = `/api/events/${id}/fixture`;
    $("#decision-results").replaceChildren(node("p", "hint", "Run a simulation to evaluate the currently enabled rules. Past runs are available in Run history."));
    switchTab("payload"); renderEvents();
  } catch (error) { if (ticket === detailRequest) toast(error.message); }
}

function renderPayload() {
  if (!state.selected) return;
  const pretty = state.selected.is_json && !$("#raw-toggle").checked;
  $("#payload-label").textContent = pretty ? "JSON BODY · FORMATTED" : "RAW TEXT · UTF-8 PREVIEW";
  $("#payload-code").textContent = pretty ? state.selected.pretty_json : state.selected.body_text;
}

function decisionNodes(run) {
  const summary = node("div", "decision-summary");
  summary.append(node("span", `pill ${run.targets.length ? "green" : ""}`, run.targets.length ? "Matched" : "No match"),
    node("strong", "", run.targets.length ? run.targets.join(" · ") : "No target selected"),
    node("small", "", `Run #${run.id} · ${timestamp(run.created_at)}`));
  const nodes = [summary];
  if (!run.decisions.length) nodes.push(node("p", "hint", "No enabled rules were present. Create a rule in Routing lab and simulate again."));
  for (const decision of run.decisions) {
    const block = node("div", "decision");
    const title = node("div", "decision-title");
    title.append(node("span", decision.matched ? "success" : "muted", decision.matched ? "✓" : "−"),
      node("strong", "", decision.name), node("small", "muted", `rev ${decision.revision} · ${decision.mode.toUpperCase()}`));
    block.append(title);
    for (const check of decision.checks) block.append(node("p", "check mono", `${check.matched ? "✓" : "×"} ${check.path || "(root)"} ${check.op} ${JSON.stringify(check.value)}${check.present ? "" : " · absent"}`));
    nodes.push(block);
  }
  return nodes;
}

async function loadRules() {
  state.rules = (await api("/api/rules")).rules;
  if (!state.rules.length) {
    const empty = node("div", "empty panel");
    empty.append(node("h3", "", "Give your events a direction"), node("p", "", "Create your first rule, then simulate a captured JSON event."));
    $("#rule-list").replaceChildren(empty); return;
  }
  $("#rule-list").replaceChildren(...state.rules.map(rule => {
    const card = node("article", "rule-card");
    const heading = node("div", "rule-heading");
    heading.append(node("span", "rule-icon", "⑂"), node("h3", "", rule.name), node("span", `pill ${rule.enabled ? "green" : ""}`, rule.enabled ? "Enabled" : "Disabled"));
    const info = node("div", "rule-info");
    info.append(node("code", "", `→ ${rule.target}`), node("span", "muted", `Revision ${rule.revision} · ${rule.mode.toUpperCase()}`));
    const conditions = node("div", "rule-conditions");
    for (const condition of rule.conditions) conditions.append(node("p", "mono", `${condition.path || "(root)"} ${condition.op} ${JSON.stringify(condition.value)}`));
    const actions = node("div", "rule-actions");
    const edit = node("button", "secondary", "Edit rule");
    edit.setAttribute("aria-label", `Edit ${rule.name}`);
    edit.addEventListener("click", () => openRule(rule));
    const toggle = node("button", "text-button", rule.enabled ? "Disable" : "Enable");
    toggle.setAttribute("aria-label", `${rule.enabled ? "Disable" : "Enable"} ${rule.name}`);
    toggle.addEventListener("click", () => busy(toggle, async () => {
      await api(`/api/rules/${rule.id}`, { method: "PATCH", body: { enabled: !rule.enabled } });
      await loadRules(); toast("Rule updated. Existing run snapshots are unchanged.");
    }));
    actions.append(edit, toggle);
    card.append(heading, info, conditions, actions); return card;
  }));
}

async function loadHistory(append = false) {
  const data = await api(`/api/runs?limit=20${append && state.historyNext ? `&before=${state.historyNext}` : ""}`);
  state.history = append ? [...state.history, ...data.runs] : data.runs;
  state.historyNext = data.next_cursor;
  $("#more-history").hidden = !data.next_cursor;
  if (!state.history.length) { $("#history-list").replaceChildren(node("div", "empty panel", "No simulations yet. Select an event and run its routing simulation.")); return; }
  $("#history-list").replaceChildren(...state.history.map(run => {
    const details = node("details", "history-card");
    const summary = node("summary", "");
    summary.append(node("strong", "mono", `run_${String(run.id).padStart(4, "0")}`), node("span", "mono", eventLabel(run.event_id)),
      node("span", `pill ${run.targets.length ? "green" : ""}`, run.targets.length ? `${run.targets.length} target(s)` : "No match"), node("time", "muted", timestamp(run.created_at)));
    const contents = node("div", "history-content");
    contents.append(...decisionNodes(run), node("p", "hint mono", `Event SHA-256: ${run.event_sha256}`));
    details.append(summary, contents); return details;
  }));
}

async function changeView(view) {
  state.view = view;
  for (const name of ["capture", "rules", "history", "roadmap"]) {
    $(`#${name}-view`).hidden = name !== view;
    const button = $(`[data-view="${name}"]`);
    button.classList.toggle("active", name === view);
    if (name === view) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  }
  const titles = { capture: ["Event stream", "Follow the payload.", "A clear view of your webhooks, from arrival to routing decision."],
    rules: ["Routing lab", "Make the decision explicit.", "Build deterministic rules. See exactly why an event matches."],
    history: ["Run history", "Every decision, accounted for.", "Inspect the rule snapshots behind previous simulations."],
    roadmap: ["Roadmap", "A foundation. Room to go deep.", "Seven substantial engineering challenges beyond the working local core."] };
  [$("#breadcrumb").textContent, $("#page-title").textContent, $("#page-description").textContent] = titles[view];
  try { if (view === "rules") await loadRules(); if (view === "history") await loadHistory(); }
  catch (error) { showError(error); }
}

function openRule(rule = null) {
  editingRule = rule?.id ?? null;
  const form = $("#rule-form"); form.reset();
  $("#rule-dialog-title").textContent = rule ? "Edit routing rule" : "Create a routing rule";
  if (rule) for (const key of ["name", "target", "mode"]) form.elements[key].value = rule[key];
  form.elements.enabled.checked = rule?.enabled ?? true;
  form.elements.conditions.value = JSON.stringify(rule?.conditions ?? [
    { path: "/type", op: "equals", value: "invoice.paid" },
    { path: "/data/amount", op: "greater_than", value: 2000 },
  ], null, 2);
  $("#rule-error").hidden = true;
  $("#rule-dialog").showModal(); form.elements.name.focus();
}

document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => changeView(button.dataset.view)));
document.querySelectorAll("[data-tab]").forEach(button => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
  button.addEventListener("keydown", event => {
    const tabs = [...document.querySelectorAll("[data-tab]")];
    let next;
    if (event.key === "ArrowRight") next = (tabs.indexOf(button) + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (tabs.indexOf(button) + tabs.length - 1) % tabs.length;
    if (next !== undefined) { event.preventDefault(); tabs[next].focus(); switchTab(tabs[next].dataset.tab); }
  });
});
$("#raw-toggle").addEventListener("change", renderPayload);
$("#inbox-select").addEventListener("change", async event => {
  state.inbox = Number(event.target.value); clearSelection(); renderEndpoint(); await loadEvents();
});
$("#search").addEventListener("input", event => {
  state.query = event.target.value; eventRequest++; clearTimeout(debounce);
  debounce = setTimeout(() => loadEvents(), 200);
});
$("#format-filter").addEventListener("change", event => { state.format = event.target.value; loadEvents(); });
$("#live").addEventListener("change", () => loadEvents());
$("#refresh").addEventListener("click", event => busy(event.currentTarget, async () => { await loadInboxes(); await loadEvents(); await refreshStats(); }));
$("#load-more").addEventListener("click", event => busy(event.currentTarget, async () => { $("#live").checked = false; await loadEvents(true); }));
$("#copy-endpoint").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#endpoint-url").textContent); toast("Endpoint URL copied."); }
  catch { toast("Clipboard unavailable. Select and copy the endpoint URL above."); }
});
$("#pause-inbox").addEventListener("click", event => busy(event.currentTarget, async () => {
  const inbox = state.inboxes.find(item => item.id === state.inbox);
  await api(`/api/inboxes/${inbox.id}`, { method: "PATCH", body: { enabled: !inbox.enabled } });
  await loadInboxes(); toast(inbox.enabled ? "Inbox paused. New requests receive HTTP 410." : "Inbox resumed.");
}));
$("#send-sample").addEventListener("click", event => busy(event.currentTarget, async () => {
  const inbox = state.inboxes.find(item => item.id === state.inbox);
  const response = await api(inbox.path, { method: "POST", body: samplePayload(sampleIndex++) });
  state.query = ""; state.format = "all"; $("#search").value = ""; $("#format-filter").value = "all";
  await loadEvents(); await refreshStats(); await selectEvent(response.event_id);
  toast("Sample captured through the real HTTP endpoint.");
}));
$("#simulate").addEventListener("click", event => busy(event.currentTarget, async () => {
  const id = state.selected.id;
  const run = await api(`/api/events/${id}/simulate`, { method: "POST" });
  if (state.selected?.id === id) { $("#decision-results").replaceChildren(...decisionNodes(run)); switchTab("decisions"); }
  await refreshStats(); toast(`Run #${run.id} saved. ${run.targets.length} target label(s) matched.`);
}));
$("#new-inbox").addEventListener("click", () => { $("#inbox-form").reset(); $("#inbox-error").hidden = true; $("#inbox-dialog").showModal(); });
$("#new-rule").addEventListener("click", () => openRule());
document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => {
  const dialog = document.getElementById(button.dataset.close);
  if (!dialog.querySelector('[type="submit"]').disabled) dialog.close();
}));
for (const id of ["inbox-dialog", "rule-dialog"]) document.getElementById(id).addEventListener("cancel", event => {
  if (event.currentTarget.querySelector('[type="submit"]').disabled) event.preventDefault();
});
$("#inbox-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type="submit"]'); button.disabled = true;
  try {
    const inbox = await api("/api/inboxes", { method: "POST", body: { name: form.elements.name.value } });
    state.inbox = inbox.id; clearSelection();
    await loadInboxes(); await changeView("capture"); await loadEvents();
    $("#inbox-dialog").close(); toast("Inbox created. Your endpoint is ready.");
  } catch (error) { $("#inbox-error").textContent = error.message; $("#inbox-error").hidden = false; }
  finally { button.disabled = false; }
});
$("#rule-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type="submit"]'); button.disabled = true;
  try {
    let conditions;
    try { conditions = JSON.parse(form.elements.conditions.value); } catch { throw new Error("Conditions must be valid JSON."); }
    const body = { name: form.elements.name.value, target: form.elements.target.value, mode: form.elements.mode.value, conditions, enabled: form.elements.enabled.checked };
    await api(editingRule ? `/api/rules/${editingRule}` : "/api/rules", { method: editingRule ? "PATCH" : "POST", body });
    $("#rule-dialog").close(); await loadRules(); toast("Rule saved. Select an event to test it.");
  } catch (error) { $("#rule-error").textContent = error.message; $("#rule-error").hidden = false; }
  finally { button.disabled = false; }
});
$("#refresh-history").addEventListener("click", event => busy(event.currentTarget, () => loadHistory()));
$("#more-history").addEventListener("click", event => busy(event.currentTarget, () => loadHistory(true)));
$("#roadmap-grid").replaceChildren(...roadmap.map(item => {
  const card = node("article", "roadmap-card");
  card.append(node("span", "roadmap-number", item.number), node("span", "eyebrow", item.tag), node("h3", "", item.title), node("p", "", item.text), node("span", "pill", "Planned"));
  return card;
}));

async function initialize() {
  try {
    await loadInboxes();
    const loaded = await loadEvents();
    await refreshStats();
    if (loaded) $("#global-error").hidden = true;
  }
  catch (error) { showError(error); }
}
$("#retry").addEventListener("click", initialize);
setInterval(async () => {
  if (polling || document.hidden || state.view !== "capture" || !$("#live").checked || document.querySelector("dialog[open]")) return;
  polling = true;
  try { await loadEvents(); await refreshStats(); } catch (error) { showError(error); }
  finally { polling = false; }
}, 5000);
initialize();
