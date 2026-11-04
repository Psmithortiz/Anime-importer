"use strict";

// Todo texto que viene de la API se inserta con textContent / createElement.
// Nunca se usa innerHTML con datos de la API (los títulos vienen de servicios externos).

const POLL_INTERVAL_MS = 2000;

const SCREENS = ["start", "normalizing", "question", "finished", "failed"];

const $ = (id) => document.getElementById(id);

let sessionId = null;
let currentView = null;
let pollTimer = null;
let busy = false;

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
    throw new Error("No se pudo conectar con el servidor");
  }
  if (!response.ok) {
    let message = null;
    try {
      const data = await response.json();
      message = describeDetail(data.detail);
    } catch {
      // cuerpo no JSON: se usa el mensaje genérico
    }
    const error = new Error(message || `Error del servidor (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

// ---------------------------------------------------------------- helpers de DOM

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
  // Abrir el link no debe elegir la tarjeta/fila que lo contiene.
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
      if (polledId !== sessionId) return; // el usuario ya cambió de sesión
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
  $("normalizing-msg").textContent = `Normalizando ${view.progress.total} títulos con Gemini…`;
  showScreen("normalizing");
}

function renderQuestion(view) {
  const { question, progress } = view;
  setBusy(false);
  $("question-error").hidden = true;

  const percent = progress.total > 0 ? (progress.done / progress.total) * 100 : 0;
  $("progress-fill").style.width = `${percent}%`;
  $("progress-text").textContent = `${progress.done} / ${progress.total}`;

  $("question-title").textContent = question.original_title;
  const query = $("question-query");
  if (question.kind === "candidate" && question.query) {
    query.textContent = `Búsqueda: "${question.query}" · `;
    query.hidden = false;
  } else {
    query.hidden = true;
  }
  $("question-google").href = googleUrl(question.original_title);

  const container = $("options");
  container.replaceChildren(
    question.kind === "candidate" ? buildCards(question.options) : buildOptionList(question.options),
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
  const placeholder = () => el("div", { text: "Sin imagen", className: "poster poster-placeholder" });
  if (!option.image_url) return placeholder();
  const img = el("img", {
    className: "poster",
    attrs: { src: option.image_url, alt: option.label, loading: "lazy" },
  });
  img.addEventListener("error", () => img.replaceWith(placeholder()));
  return img;
}

function buildCards(options) {
  const grid = el("div", { className: "cards" });
  for (const option of options) {
    const card = el("div", { className: "card" }, [
      buildPoster(option),
      el("span", { text: String(option.number), className: "badge" }),
      el("div", { text: option.label, className: "card-label" }),
      el("div", { text: `MAL id ${option.mal_id}`, className: "card-meta" }),
      externalLink("Ver en MAL", `https://myanimelist.net/anime/${encodeURIComponent(option.mal_id)}`),
    ]);
    makeActivatable(card, () => submit(() => choose(option.number)));
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
      externalLink("Buscar en Google", googleUrl(option.label)),
    ]);
    makeActivatable(row, () => submit(() => choose(option.number)));
    list.append(row);
  }
  return list;
}

function renderFinished(view) {
  const { summary } = view;
  $("imported-count").textContent = `Importados: ${summary.imported}`;
  $("rejected-count").textContent = `Rechazados: ${summary.rejected.length}`;

  const holder = $("rejected-table");
  if (summary.rejected.length === 0) {
    holder.replaceChildren();
  } else {
    const head = el("tr", {}, [el("th", { text: "Título" }), el("th", { text: "Motivo" })]);
    const rows = summary.rejected.map((item) =>
      el("tr", {}, [el("td", { text: item.title }), el("td", { text: item.reason })]),
    );
    holder.replaceChildren(
      el("table", {}, [el("thead", {}, [head]), el("tbody", {}, rows)]),
    );
  }
  $("download-link").href = `/api/sessions/${encodeURIComponent(view.id)}/export.xml`;
  showScreen("finished");
}

function renderFailed(view) {
  $("failed-msg").textContent = view.error || "Ocurrió un error inesperado.";
  showScreen("failed");
}

// ---------------------------------------------------------------- acciones

function setBusy(flag) {
  busy = flag;
  $("screen-question").classList.toggle("busy", flag);
  $("discard-btn").disabled = flag;
}

// Ejecuta una acción choose/discard bloqueando la UI y los atajos mientras está en curso.
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

function discard() {
  return api("POST", `/api/sessions/${encodeURIComponent(sessionId)}/discard`);
}

function countLines(text) {
  return text.split(/\r?\n/).filter((line) => line.trim() !== "").length;
}

function updateLineCount() {
  const count = countLines($("titles-input").value);
  $("line-count").textContent = count === 1 ? "1 título" : `${count} títulos`;
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
  if (target instanceof HTMLElement && target.matches("input, textarea")) return;

  if (event.key === "x" || event.key === "X") {
    event.preventDefault();
    submit(discard);
    return;
  }
  if (/^[1-9]$/.test(event.key)) {
    const number = Number(event.key);
    if (currentView.question.options.some((option) => option.number === number)) {
      event.preventDefault();
      submit(() => choose(number));
    }
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
