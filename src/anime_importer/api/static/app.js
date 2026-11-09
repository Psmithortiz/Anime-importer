"use strict";

// All text coming from the API is inserted with textContent / createElement.
// innerHTML is never used with API data (titles come from external services).

const POLL_INTERVAL_MS = 2000;

const SCREENS = ["start", "preparing", "question", "finished", "failed", "settings"];

const $ = (id) => document.getElementById(id);

let sessionId = null;
let currentView = null;
let pollTimer = null;
let busy = false;
let configured = true;
// Multi-selection of the current question: MAL id -> list status.
const selection = new Map();
// Single selection of a normalization question: option number, or null.
let normalizationChoice = null;

// ---------------------------------------------------------------- API

function describeDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (item && typeof item === "object" ? item.msg || JSON.stringify(item) : String(item)))
      .join("; ");
  }
  return null;
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Could not connect to the server");
  }
  if (!response.ok) {
    let message = null;
    try {
      const data = await response.json();
      message = describeDetail(data.detail);
    } catch {
      // non-JSON body: the generic message is used
    }
    const error = new Error(message || `Server error (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

// ---------------------------------------------------------------- DOM helpers

function el(tag, { text, className, attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function googleUrl(title) {
  return "https://www.google.com/search?q=" + encodeURIComponent(`${title} anime`);
}

function externalLink(text, href, className = "small-link") {
  const link = el("a", { text, className, attrs: { href, target: "_blank", rel: "noopener" } });
  // Opening the link must not select the card/row that contains it.
  link.addEventListener("click", (event) => event.stopPropagation());
  return link;
}

let currentScreen = null;
// Whether the Settings link makes sense at all (not in demo, not if every key is fixed elsewhere).
let settingsLinkAvailable = false;

function updateSettingsLink() {
  $("settings-link").hidden = !settingsLinkAvailable || currentScreen === "settings";
}

function showScreen(name) {
  for (const screen of SCREENS) {
    $(`screen-${screen}`).hidden = screen !== name;
  }
  currentScreen = name;
  updateSettingsLink();
}

// ---------------------------------------------------------------- polling

function stopPolling() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll() {
  if (pollTimer !== null) return;
  const polledId = sessionId;
  pollTimer = setTimeout(async () => {
    pollTimer = null;
    try {
      const view = await api("GET", `/api/sessions/${encodeURIComponent(polledId)}`);
      if (polledId !== sessionId) return; // the user has already switched session
      $("poll-warning").hidden = true;
      render(view);
    } catch {
      if (polledId !== sessionId) return;
      $("poll-warning").hidden = false;
      schedulePoll();
    }
  }, POLL_INTERVAL_MS);
}

// ---------------------------------------------------------------- render

function render(view) {
  currentView = view;
  setBusy(false);
  if (view.status === "preparing") {
    renderPreparing(view);
    schedulePoll();
    return;
  }
  stopPolling();
  if (view.status === "question") renderQuestion(view);
  else if (view.status === "finished") renderFinished(view);
  else renderFailed(view);
}

function renderPhase(prefix, reported, fallbackTotal) {
  const done = reported ? reported.done : 0;
  const total = reported ? reported.total : fallbackTotal;
  $(`${prefix}-msg`).textContent = `${$(`${prefix}-msg`).dataset.label} ${done} / ${total}`;
  const percent = total > 0 ? (done / total) * 100 : 0;
  $(`${prefix}-fill`).style.width = `${percent}%`;
}

function renderPreparing(view) {
  renderPhase("normalizing", view.normalization, view.progress.total);
  renderPhase("resolving", view.resolution, view.progress.total);
  showScreen("preparing");
}

function renderQuestion(view) {
  const { question, progress } = view;
  selection.clear();
  normalizationChoice = null;
  setBusy(false);
  $("question-error").hidden = true;
  const isCandidate = question.kind === "candidate";
  $("confirm-btn").hidden = false;
  $("question-help").textContent =
    "Click or 1-9 to select · Enter to confirm · X to discard · Ctrl+Z to undo";
  $("question-help").hidden = false;
  updateConfirm();

  const percent = progress.total > 0 ? (progress.done / progress.total) * 100 : 0;
  $("progress-fill").style.width = `${percent}%`;
  $("progress-text").textContent = `${progress.done} / ${progress.total}`;

  $("question-title").textContent = question.original_title;
  const query = $("question-query");
  if (question.kind === "candidate" && question.query) {
    query.textContent = `Search: "${question.query}" · `;
    query.hidden = false;
  } else {
    query.hidden = true;
  }
  $("question-fallback").hidden = !(question.kind === "candidate" && question.used_fallback);
  $("question-google").href = googleUrl(question.original_title);

  const container = $("options");
  container.replaceChildren(
    isCandidate ? buildCandidateLayout(question) : buildOptionList(question.options),
  );
  showScreen("question");
}

function buildPoster(option) {
  const placeholder = () => el("div", { text: "No image", className: "poster poster-placeholder" });
  if (!option.image_url) return placeholder();
  const img = el("img", {
    className: "poster",
    attrs: { src: option.image_url, alt: option.label, loading: "lazy" },
  });
  img.addEventListener("error", () => img.replaceWith(placeholder()));
  return img;
}

const MEDIA_TYPE_LABELS = {
  tv: "TV",
  movie: "Movie",
  ova: "OVA",
  ona: "ONA",
  special: "Special",
  music: "Music",
  other: "Other",
};

const STATUS_LABELS = { airing: "Airing", not_yet_aired: "Not yet aired" };

function buildMetaLine(option, bestMatch = false) {
  const parts = [];
  if (option.media_type) parts.push(MEDIA_TYPE_LABELS[option.media_type] || option.media_type);
  if (option.year) parts.push(String(option.year));
  if (option.episodes) parts.push(`${option.episodes} eps`);
  const line = el("div", { className: "card-meta" });
  if (parts.length > 0) line.append(el("span", { text: parts.join(" · ") }));
  if (bestMatch) line.append(el("span", { text: "Best match", className: "tag tag-best" }));
  const statusText = STATUS_LABELS[option.airing_status];
  if (statusText) {
    line.append(el("span", { text: statusText, className: `tag tag-${option.airing_status}` }));
  }
  return line;
}

const LIST_STATUS_LABELS = {
  completed: "Completed",
  watching: "Watching",
  plan_to_watch: "Plan to Watch",
  on_hold: "On Hold",
  dropped: "Dropped",
};

function buildStatusSelect(option) {
  const select = el("select", { attrs: { "aria-label": `Status of ${option.label}` } });
  for (const [value, label] of Object.entries(LIST_STATUS_LABELS)) {
    select.append(el("option", { text: label, attrs: { value } }));
  }
  // Clicks and keys inside the select must not toggle the card or trigger shortcuts.
  for (const type of ["click", "keydown"]) {
    select.addEventListener(type, (event) => event.stopPropagation());
  }
  select.addEventListener("change", () => selection.set(option.mal_id, select.value));
  return select;
}

// Mark or unmark an item (candidate or franchise entry) by its MAL id.
function setSelected(item, on) {
  const card = document.querySelector(`.card[data-mal-id="${item.mal_id}"]`);
  if (!card) return;
  const select = card.querySelector("select");
  if (on) {
    const status = item.suggested_status || "completed";
    selection.set(item.mal_id, status);
    select.value = status;
  } else {
    selection.delete(item.mal_id);
  }
  card.classList.toggle("selected", on);
  select.hidden = !on;
  card.setAttribute("aria-pressed", String(on));
  updateConfirm();
}

function toggleSelection(item) {
  if (busy) return;
  setSelected(item, !selection.has(item.mal_id));
}

// Single selection in a normalization question: marking another option unmarks the previous one.
function toggleNormalization(option) {
  if (busy) return;
  normalizationChoice = normalizationChoice === option.number ? null : option.number;
  for (const row of document.querySelectorAll("#options .option-row")) {
    const on = Number(row.dataset.number) === normalizationChoice;
    row.classList.toggle("selected", on);
    row.setAttribute("aria-pressed", String(on));
  }
  updateConfirm();
}

function updateConfirm() {
  const button = $("confirm-btn");
  const isNormalization = currentView?.question?.kind === "normalization";
  const count = isNormalization ? (normalizationChoice === null ? 0 : 1) : selection.size;
  button.textContent = !isNormalization && count > 0
    ? `Confirm selection (${count}) (Enter)`
    : "Confirm selection (Enter)";
  button.disabled = busy || count === 0;
}

function makeSelectableCard(card, item) {
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  card.setAttribute("aria-pressed", "false");
  card.addEventListener("click", () => toggleSelection(item));
  card.addEventListener("keydown", (event) => {
    if (event.target === card && event.key === " ") {
      event.preventDefault();
      toggleSelection(item);
    }
  });
}

function malLink(item) {
  return externalLink("View on MAL", `https://myanimelist.net/anime/${encodeURIComponent(item.mal_id)}`);
}

function buildCards(options, bestMatchIds = new Set()) {
  const grid = el("div", { className: "cards" });
  for (const option of options) {
    const select = buildStatusSelect(option);
    select.hidden = true;
    const card = el("div", { className: "card", attrs: { "data-mal-id": String(option.mal_id) } }, [
      buildPoster(option),
      el("span", { text: String(option.number), className: "badge" }),
      el("div", { text: option.label, className: "card-label" }),
      buildMetaLine(option, bestMatchIds.has(option.mal_id)),
      el("div", { text: `MAL id ${option.mal_id}`, className: "card-meta" }),
      malLink(option),
      select,
    ]);
    makeSelectableCard(card, option);
    grid.append(card);
  }
  return grid;
}

const RELATION_LABELS = {
  sequel: "Sequel",
  prequel: "Prequel",
  side_story: "Side story",
  parent_story: "Parent story",
  summary: "Summary",
  full_story: "Full story",
  alternative_version: "Alt. version",
  alternative_setting: "Alt. setting",
  spin_off: "Spin-off",
};

function buildFranchiseCard(entry) {
  const select = buildStatusSelect(entry);
  select.hidden = true;
  const card = el(
    "div",
    { className: "card card-compact", attrs: { "data-mal-id": String(entry.mal_id) } },
    [
      buildPoster(entry),
      el("span", { text: RELATION_LABELS[entry.relation] || entry.relation, className: "relation-tag" }),
      el("div", { text: entry.label, className: "card-label" }),
      buildMetaLine(entry),
      malLink(entry),
      select,
    ],
  );
  makeSelectableCard(card, entry);
  return card;
}

function buildFranchiseColumn(question) {
  const entries = question.franchise;
  const grid = el("div", { className: "franchise-grid" }, entries.map(buildFranchiseCard));
  const column = el("aside", { className: "franchise" }, [
    el("h3", { text: `Franchise (${entries.length})` }),
    grid,
  ]);
  if (question.franchise_truncated) {
    column.append(
      el("p", {
        text: "Large franchise: showing the first related entries only.",
        className: "muted small",
      }),
    );
  }
  return column;
}

function buildCandidateLayout(question) {
  const layout = el("div", { className: "question-layout" }, [
    el("div", { className: "candidates" }, [
      buildCards(question.options, new Set(question.preselected || [])),
    ]),
  ]);
  if ((question.franchise || []).length > 0) {
    layout.classList.add("has-franchise");
    layout.append(buildFranchiseColumn(question));
  }
  return layout;
}

function buildOptionList(options) {
  const list = el("div", { className: "option-list" });
  for (const option of options) {
    const text = option.is_original ? `✎ Your line: "${option.label}"` : option.label;
    const row = el("div", { className: option.is_original ? "option-row original" : "option-row" }, [
      el("span", { text: `${option.number}.`, className: "num" }),
      el("span", { text, className: "label" }),
      externalLink("Search on Google", googleUrl(option.label)),
    ]);
    row.dataset.number = String(option.number);
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-pressed", "false");
    row.addEventListener("click", () => toggleNormalization(option));
    row.addEventListener("keydown", (event) => {
      if (event.target === row && event.key === " ") {
        event.preventDefault();
        toggleNormalization(option);
      }
    });
    list.append(row);
  }
  return list;
}

function renderFinished(view) {
  const { summary } = view;
  $("imported-count").textContent = `Imported: ${summary.imported}`;
  $("rejected-count").textContent = `Rejected: ${summary.rejected.length}`;

  const counts = [];
  for (const [status, label] of Object.entries(LIST_STATUS_LABELS)) {
    const count = (summary.by_status || {})[status] || 0;
    if (count > 0) counts.push(el("li", { text: `${label}: ${count}` }));
  }
  $("status-counts").replaceChildren(...counts);

  const holder = $("rejected-table");
  if (summary.rejected.length === 0) {
    holder.replaceChildren();
  } else {
    const head = el("tr", {}, [el("th", { text: "Title" }), el("th", { text: "Reason" })]);
    const rows = summary.rejected.map((item) =>
      el("tr", {}, [el("td", { text: item.title }), el("td", { text: item.reason })]),
    );
    holder.replaceChildren(
      el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]),
    );
  }
  updateDownloadLink();
  $("finished-error").hidden = true;
  showScreen("finished");
}

function updateDownloadLink() {
  $("download-link").href = `/api/sessions/${encodeURIComponent(currentView.id)}/export.xml`;
}

function renderFailed(view) {
  $("failed-msg").textContent = view.error || "An unexpected error occurred.";
  $("failed-error").hidden = true;
  showScreen("failed");
}

// ---------------------------------------------------------------- actions

function setBusy(flag) {
  busy = flag;
  $("screen-question").classList.toggle("busy", flag);
  $("discard-btn").disabled = flag;
  $("lookup-msg").hidden = !flag;
  for (const select of document.querySelectorAll("#options select")) select.disabled = flag;
  $("retry-btn").disabled = flag;
  updateUndoButtons();
  updateConfirm();
}

// Undo is only possible when the server says so and no request is in flight.
function updateUndoButtons() {
  const disabled = busy || !currentView || !currentView.can_undo;
  $("undo-btn").disabled = disabled;
  $("undo-finished-btn").disabled = disabled;
}

// Run a choose/discard action, blocking the UI and the shortcuts while it is in flight.
async function submit(action) {
  if (busy || !currentView || currentView.status !== "question") return;
  setBusy(true);
  try {
    const view = await action();
    render(view);
  } catch (error) {
    const box = $("question-error");
    box.textContent = error.message;
    box.hidden = false;
    setBusy(false);
  }
}

function choose(number) {
  return api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/choose`, { option: number });
}

function chooseMany() {
  const selections = [...selection.entries()]
    .sort(([a], [b]) => a - b)
    .map(([malId, status]) => ({ mal_id: malId, status }));
  return api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/choose-many`, { selections });
}

function confirmSelection() {
  if (currentView?.question?.kind === "normalization") {
    if (normalizationChoice === null) return;
    const number = normalizationChoice;
    submit(() => choose(number));
    return;
  }
  if (selection.size === 0) return;
  submit(chooseMany);
}

function discard() {
  return api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/discard`);
}

function canUndoNow() {
  return (
    !busy &&
    currentView !== null &&
    (currentView.status === "question" || currentView.status === "finished") &&
    currentView.can_undo === true
  );
}

async function undo() {
  if (!canUndoNow()) return;
  const errorBox = $(currentView.status === "question" ? "question-error" : "finished-error");
  errorBox.hidden = true;
  setBusy(true);
  try {
    render(await api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/undo`));
  } catch (error) {
    // 409 / 503: the screen does not change, the message is shown on it.
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    setBusy(false);
  }
}

async function retry() {
  if (busy || !currentView || currentView.status !== "failed") return;
  $("failed-error").hidden = true;
  setBusy(true);
  try {
    render(await api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/retry`));
  } catch (error) {
    $("failed-error").textContent = error.message;
    $("failed-error").hidden = false;
    setBusy(false);
  }
}

// Open an existing session (from the URL hash or from the recent list).
async function openSession(id) {
  if (busy) return;
  busy = true;
  sessionId = id;
  try {
    const view = await api("GET", `/api/sessions/${encodeURIComponent(id)}`);
    location.hash = id;
    render(view);
  } catch (error) {
    goToStart();
    if (error.status !== 404) {
      $("start-error").textContent = error.message;
      $("start-error").hidden = false;
    }
  } finally {
    busy = false;
  }
}

function recentSummary(item) {
  const titles = item.preview.join(" · ");
  return item.title_count > 3 ? `${titles} and ${item.title_count - 3} more` : titles;
}

function buildRecentItem(item) {
  const answers = `${item.decision_count} ${item.decision_count === 1 ? "answer" : "answers"}`;
  const when = new Date(item.updated_at).toLocaleString();
  const row = el("li", { className: "recent-item" }, [
    el("span", { text: recentSummary(item), className: "recent-titles" }),
    el("span", { text: `${answers} · ${when}`, className: "muted small" }),
  ]);
  row.setAttribute("role", "button");
  row.setAttribute("tabindex", "0");
  row.addEventListener("click", () => openSession(item.id));
  row.addEventListener("keydown", (event) => {
    if (event.target === row && event.key === "Enter") {
      event.preventDefault();
      openSession(item.id);
    }
  });
  return row;
}

async function loadRecent() {
  try {
    const items = await api("GET", "/api/sessions?limit=10");
    $("recent-list").replaceChildren(...items.map(buildRecentItem));
    $("recent").hidden = items.length === 0;
  } catch {
    // The list is optional: without it the start screen works as before.
    $("recent").hidden = true;
  }
}

function countLines(text) {
  return text.split(/\r?\n/).filter((line) => line.trim() !== "").length;
}

function updateLineCount() {
  const count = countLines($("titles-input").value);
  $("line-count").textContent = count === 1 ? "1 title" : `${count} titles`;
  $("start-btn").disabled = count === 0;
}

function goToStart() {
  stopPolling();
  sessionId = null;
  currentView = null;
  history.replaceState(null, "", location.pathname + location.search);
  $("start-error").hidden = true;
  $("poll-warning").hidden = true;
  updateLineCount();
  showScreen("start");
  loadRecent();
}

async function startImport() {
  const button = $("start-btn");
  button.disabled = true;
  $("start-error").hidden = true;
  try {
    const view = await api("POST", "/api/sessions", { text: $("titles-input").value });
    sessionId = view.id;
    location.hash = view.id;
    render(view);
  } catch (error) {
    $("start-error").textContent = error.message;
    $("start-error").hidden = false;
    updateLineCount();
  }
}

function onKeydown(event) {
  if (!currentView) return;
  const target = event.target;
  if (target instanceof HTMLElement && target.matches("input, textarea, select")) return;

  const isUndo =
    (event.ctrlKey || event.metaKey) &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key || "").toLowerCase() === "z";
  if (isUndo) {
    if (currentView.status === "question" || currentView.status === "finished") {
      event.preventDefault();
      undo();
    }
    return;
  }

  if (busy || currentView.status !== "question") return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;

  if (event.key === "x" || event.key === "X") {
    event.preventDefault();
    submit(discard);
    return;
  }
  const { question } = currentView;
  if (event.key === "Enter") {
    // If focus is on a button or link, Enter keeps its native action.
    if (target instanceof HTMLElement && target.matches("button, a")) return;
    event.preventDefault();
    confirmSelection();
    return;
  }
  if (/^[1-9]$/.test(event.key)) {
    const number = Number(event.key);
    const option = question.options.find((item) => item.number === number);
    if (!option) return;
    event.preventDefault();
    if (question.kind === "candidate") toggleSelection(option);
    else toggleNormalization(option);
  }
}

function readFileInto(file) {
  const reader = new FileReader();
  reader.addEventListener("load", () => {
    $("titles-input").value = String(reader.result);
    updateLineCount();
  });
  reader.readAsText(file);
}

const DEMO_NOTICE =
  "Demo mode: recorded MyAnimeList and Gemini responses, no API keys needed. " +
  "Titles outside the sample list won't be found.";

const KEY_LABELS = {
  GEMINI_API_KEY: {
    label: "Gemini API key",
    url: "https://aistudio.google.com/apikey",
    field: "gemini_api_key",
  },
  MAL_CLIENT_ID: {
    label: "MAL client ID",
    url: "https://myanimelist.net/apiconfig",
    field: "mal_client_id",
  },
};

const SOURCE_TEXT = {
  environment: "Set by an environment variable",
  config_file: "saved in the config file",
  missing: "Not set",
};

// Inputs of the settings screen: API field name -> input element.
const settingsInputs = new Map();

function renderSettings(config) {
  const container = $("settings-keys");
  container.replaceChildren();
  settingsInputs.clear();
  for (const key of config.keys) {
    const meta = KEY_LABELS[key.name];
    if (!meta) continue;
    const locked = key.source === "environment";
    const inputId = `settings-${meta.field}`;
    const input = el("input", {
      attrs: { id: inputId, type: "password", autocomplete: "off", spellcheck: "false" },
    });
    input.disabled = locked;
    settingsInputs.set(meta.field, input);
    const current = key.masked
      ? `${key.masked} · ${SOURCE_TEXT[key.source]}`
      : SOURCE_TEXT[key.source];
    const link = el("a", {
      text: "Get one",
      className: "small-link",
      attrs: { href: meta.url, target: "_blank", rel: "noopener noreferrer" },
    });
    container.append(
      el("div", { className: "key-field" }, [
        el("label", { text: meta.label, attrs: { for: inputId } }),
        input,
        el("p", { className: "muted small key-status" }, [
          el("span", { text: `${current} · ` }),
          link,
        ]),
      ]),
    );
  }
  $("settings-save-btn").hidden = [...settingsInputs.values()].every((input) => input.disabled);
}

function setSettingsMessage(text) {
  $("settings-message").textContent = text || "";
  $("settings-message").hidden = !text;
}

async function openSettings() {
  stopPolling();
  $("settings-error").hidden = true;
  setSettingsMessage("");
  $("settings-intro").textContent = configured
    ? "API keys used to talk to Gemini and MyAnimeList."
    : "Enter your API keys to start. They are saved in a config file in your user folder.";
  $("settings-back-btn").hidden = !configured;
  try {
    renderSettings(await api("GET", "/api/config"));
  } catch (error) {
    $("settings-error").textContent = error.message;
    $("settings-error").hidden = false;
  }
  showScreen("settings");
}

async function saveSettings() {
  if (busy) return;
  const updates = {};
  for (const [field, input] of settingsInputs) {
    const value = input.value.trim();
    if (value !== "") updates[field] = value;
  }
  $("settings-error").hidden = true;
  if (Object.keys(updates).length === 0) {
    $("settings-error").textContent = "Enter at least one key.";
    $("settings-error").hidden = false;
    return;
  }
  busy = true;
  $("settings-save-btn").disabled = true;
  try {
    const config = await api("PUT", "/api/config", updates);
    for (const input of settingsInputs.values()) input.value = ""; // keys must not stay in the DOM
    configured = config.configured;
    renderSettings(config);
    if (config.restart_required) {
      setSettingsMessage("Saved. Restart the app to use the new keys.");
    } else if (config.configured) {
      goToStart();
    } else {
      setSettingsMessage("Saved. Enter the remaining key to continue.");
    }
  } catch (error) {
    $("settings-error").textContent = error.message;
    $("settings-error").hidden = false;
  } finally {
    busy = false;
    $("settings-save-btn").disabled = false;
  }
}

// The Settings link is useless in demo mode and when every key is fixed by the environment.
async function refreshSettingsLink(info) {
  settingsLinkAvailable = false;
  updateSettingsLink();
  if (info.demo) return;
  let config;
  try {
    config = await api("GET", "/api/config");
  } catch {
    return; // Without the endpoint there is nothing to configure.
  }
  const editable = config.keys.some((key) => key.source !== "environment");
  settingsLinkAvailable = editable;
  updateSettingsLink();
}

async function loadInfo() {
  let info;
  try {
    info = await api("GET", "/api/info");
  } catch {
    // The info endpoint is optional: without it the app behaves as in normal mode.
    return null;
  }
  configured = info.configured !== false;
  await refreshSettingsLink(info);
  if (!info.demo) return info;
  $("demo-banner").textContent = DEMO_NOTICE;
  $("demo-banner").hidden = false;
  if (info.sample_text && $("titles-input").value.trim() === "") {
    $("titles-input").value = info.sample_text;
    updateLineCount();
  }
  return info;
}

async function init() {
  $("titles-input").addEventListener("input", updateLineCount);
  $("file-input").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (file) readFileInto(file);
    event.target.value = "";
  });
  $("start-btn").addEventListener("click", startImport);
  $("discard-btn").addEventListener("click", () => submit(discard));
  $("confirm-btn").addEventListener("click", confirmSelection);
  $("undo-btn").addEventListener("click", undo);
  $("undo-finished-btn").addEventListener("click", undo);
  $("retry-btn").addEventListener("click", retry);
  for (const button of document.querySelectorAll(".new-import")) {
    button.addEventListener("click", goToStart);
  }
  document.addEventListener("keydown", onKeydown);

  $("settings-link").addEventListener("click", openSettings);
  $("settings-save-btn").addEventListener("click", saveSettings);
  $("settings-back-btn").addEventListener("click", goToStart);

  const info = await loadInfo();
  if (info && !info.demo && !info.configured) {
    await openSettings();
    return;
  }

  const id = decodeURIComponent(location.hash.slice(1));
  if (!id) {
    goToStart();
    return;
  }
  await openSession(id);
}

init();
