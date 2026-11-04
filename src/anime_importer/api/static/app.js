"use strict";

// All text coming from the API is inserted with textContent / createElement.
// innerHTML is never used with API data (titles come from external services).

const POLL_INTERVAL_MS = 2000;

const SCREENS = ["start", "normalizing", "question", "finished", "failed"];

const $ = (id) => document.getElementById(id);

let sessionId = null;
let currentView = null;
let pollTimer = null;
let busy = false;
// Multi-selection of the current question: option number -> list status.
const selection = new Map();

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

function showScreen(name) {
  for (const screen of SCREENS) {
    $(`screen-${screen}`).hidden = screen !== name;
  }
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
  if (view.status === "normalizing") {
    renderNormalizing(view);
    schedulePoll();
    return;
  }
  stopPolling();
  if (view.status === "question") renderQuestion(view);
  else if (view.status === "finished") renderFinished(view);
  else renderFailed(view);
}

function renderNormalizing(view) {
  $("normalizing-msg").textContent = `Normalizing ${view.progress.total} titles with Gemini…`;
  showScreen("normalizing");
}

function renderQuestion(view) {
  const { question, progress } = view;
  selection.clear();
  setBusy(false);
  $("question-error").hidden = true;
  const isCandidate = question.kind === "candidate";
  $("confirm-btn").hidden = !isCandidate;
  $("question-help").hidden = !isCandidate;
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
  $("question-google").href = googleUrl(question.original_title);

  const container = $("options");
  container.replaceChildren(
    isCandidate ? buildCards(question.options) : buildOptionList(question.options),
  );
  showScreen("question");
}

function makeActivatable(node, handler) {
  node.setAttribute("role", "button");
  node.setAttribute("tabindex", "0");
  node.addEventListener("click", handler);
  node.addEventListener("keydown", (event) => {
    if (event.target === node && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      handler();
    }
  });
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

function buildMetaLine(option) {
  const parts = [];
  if (option.media_type) parts.push(MEDIA_TYPE_LABELS[option.media_type] || option.media_type);
  if (option.year) parts.push(String(option.year));
  if (option.episodes) parts.push(`${option.episodes} eps`);
  const line = el("div", { className: "card-meta" });
  if (parts.length > 0) line.append(el("span", { text: parts.join(" · ") }));
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
  select.addEventListener("change", () => selection.set(option.number, select.value));
  return select;
}

function toggleSelection(option) {
  if (busy) return;
  const card = document.querySelector(`.card[data-number="${option.number}"]`);
  if (!card) return;
  const select = card.querySelector("select");
  if (selection.has(option.number)) {
    selection.delete(option.number);
    card.classList.remove("selected");
    select.hidden = true;
  } else {
    const status = option.suggested_status || "completed";
    selection.set(option.number, status);
    select.value = status;
    card.classList.add("selected");
    select.hidden = false;
  }
  card.setAttribute("aria-pressed", String(selection.has(option.number)));
  updateConfirm();
}

function updateConfirm() {
  const button = $("confirm-btn");
  button.textContent = selection.size > 0
    ? `Confirm selection (${selection.size}) (Enter)`
    : "Confirm selection (Enter)";
  button.disabled = busy || selection.size === 0;
}

function buildCards(options) {
  const grid = el("div", { className: "cards" });
  for (const option of options) {
    const select = buildStatusSelect(option);
    select.hidden = true;
    const card = el("div", { className: "card", attrs: { "data-number": String(option.number) } }, [
      buildPoster(option),
      el("span", { text: String(option.number), className: "badge" }),
      el("div", { text: option.label, className: "card-label" }),
      buildMetaLine(option),
      el("div", { text: `MAL id ${option.mal_id}`, className: "card-meta" }),
      externalLink("View on MAL", `https://myanimelist.net/anime/${encodeURIComponent(option.mal_id)}`),
      select,
    ]);
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-pressed", "false");
    card.addEventListener("click", () => toggleSelection(option));
    card.addEventListener("keydown", (event) => {
      if (event.target === card && event.key === " ") {
        event.preventDefault();
        toggleSelection(option);
      }
    });
    grid.append(card);
  }
  return grid;
}

function buildOptionList(options) {
  const list = el("div", { className: "option-list" });
  for (const option of options) {
    const row = el("div", { className: "option-row" }, [
      el("span", { text: `${option.number}.`, className: "num" }),
      el("span", { text: option.label, className: "label" }),
      externalLink("Search on Google", googleUrl(option.label)),
    ]);
    makeActivatable(row, () => submit(() => choose(option.number)));
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
  $("overwrite-checkbox").checked = false;

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
  showScreen("finished");
}

function updateDownloadLink() {
  const overwrite = $("overwrite-checkbox").checked;
  $("download-link").href =
    `/api/sessions/${encodeURIComponent(currentView.id)}/export.xml?overwrite=${overwrite}`;
}

function renderFailed(view) {
  $("failed-msg").textContent = view.error || "An unexpected error occurred.";
  showScreen("failed");
}

// ---------------------------------------------------------------- actions

function setBusy(flag) {
  busy = flag;
  $("screen-question").classList.toggle("busy", flag);
  $("discard-btn").disabled = flag;
  for (const select of document.querySelectorAll("#options select")) select.disabled = flag;
  updateConfirm();
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
    .map(([option, status]) => ({ option, status }));
  return api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/choose-many`, { selections });
}

function confirmSelection() {
  if (selection.size === 0) return;
  submit(chooseMany);
}

function discard() {
  return api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/discard`);
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
  if (busy || !currentView || currentView.status !== "question") return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target;
  if (target instanceof HTMLElement && target.matches("input, textarea, select")) return;

  if (event.key === "x" || event.key === "X") {
    event.preventDefault();
    submit(discard);
    return;
  }
  const { question } = currentView;
  if (event.key === "Enter" && question.kind === "candidate") {
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
    else submit(() => choose(number));
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
  $("overwrite-checkbox").addEventListener("change", updateDownloadLink);
  for (const button of document.querySelectorAll(".new-import")) {
    button.addEventListener("click", goToStart);
  }
  document.addEventListener("keydown", onKeydown);

  const id = decodeURIComponent(location.hash.slice(1));
  if (!id) {
    goToStart();
    return;
  }
  sessionId = id;
  try {
    render(await api("GET", `/api/sessions/${encodeURIComponent(id)}`));
  } catch (error) {
    goToStart();
    if (error.status !== 404) {
      $("start-error").textContent = error.message;
      $("start-error").hidden = false;
    }
  }
}

init();
