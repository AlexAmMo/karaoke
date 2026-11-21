"use strict";

const $ = (id) => document.getElementById(id);
const captions = {search: "Busca una canción", queue: "Próximos turnos"};
const statuses = {ready: "Lista", waiting: "En espera", missing: "Copia incompleta", working: "Preparando", review: "Pendiente de revisión", error: "Necesita atención", host: "Pendiente en el ordenador", starting: "Empezando", singing: "Cantando"};
const browse = {
  search: {q: "", page: 0},

};
let invite = new URLSearchParams(location.hash.slice(1)).get("join") || "";
if (invite) history.replaceState(null, "", location.pathname);
let session = null;
let state = null;
let tab = "search";
let connected = false;
let disconnectedSince = 0;
let roomClosed = false;
let stateRequest = 0;
let browseRequest = 0;
let pollTimer, browseTimer, feedbackTimer, candidateTimer;
let submitting = false;
let uncertainAction = null;
let renderedList = "";
let renderedPlayer = "";
let renderedResults = [];
let artworkAttempts = 0;
let confirmedItem = null;
let currentSheet = null;
let refreshSheet = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", "#i-" + name);
  svg.setAttribute("aria-hidden", "true");
  svg.append(use);
  return svg;
}

function button(text, handler, className = "", symbol = "") {
  const node = element("button", className);
  node.type = "button";
  if (symbol) node.append(icon(symbol));
  if (text) node.append(document.createTextNode(text));
  node.addEventListener("click", handler);
  return node;
}

function iconButton(label, name, handler, className = "row-action") {
  const node = button("", handler, className, name);
  node.setAttribute("aria-label", label);
  node.title = label;
  return node;
}

function detail(title, subtitle) {
  const text = element("span", "details");
  text.append(element("span", "title", title));
  if (subtitle) text.append(element("span", "sub", subtitle));
  return text;
}

function cover(item) {
  const name = item.artist || item.title || "Karaoke";
  const colour = Array.from(name).reduce((sum, c) => sum + c.codePointAt(0), 0) % 5;
  const node = element("span", "cover t" + colour);
  node.setAttribute("aria-hidden", "true");
  const initials = name.trim().split(/\s+/u).slice(0, 2).map(word => Array.from(word)[0]).join("").toUpperCase();
  node.textContent = initials;
  if (item.cover?.startsWith("/api/cover/")) {
    const img = element("img");
    img.alt = "";
    img.loading = "lazy";
    img.addEventListener("error", () => { node.textContent = initials; }, {once: true});
    img.src = item.cover;
    node.replaceChildren(img);
  }
  return node;
}

function token() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
}

async function api(route, payload, method = "POST") {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), route === "mic-offer" ? 28000 : 11000);
  try {
    const options = {method, credentials: "same-origin", cache: "no-store", signal: abort.signal};
    if (method === "POST") {
      options.headers = {"Content-Type": "application/json"};
      options.body = JSON.stringify(payload || {});
    }
    const response = await fetch("/api/" + route, options);
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 410 && data.room_closed === true) {
        showJoin();
        window.closeKaraokeMicrophone?.();
        roomClosed = true;
        $("join").hidden = true;
        $("closed-room").hidden = false;
      }
      const err = new Error(data.error || "Karaoke no pudo completar la acción.");
      err.status = response.status;
      throw err;
    }
    return data;
  } finally { clearTimeout(timer); }
}

function message(text, undoId = "") {
  clearTimeout(feedbackTimer);
  $("feedback").textContent = text;
  if (undoId) {
    const undo = button("Deshacer", () => command("remove", undoId, {}, "Turno retirado"));
    $("feedback").append(undo);
  }
  feedbackTimer = setTimeout(() => { $("feedback").textContent = ""; }, undoId ? 8000 : 3500);
}
function announce(text) {
  if ($("sheet").open) {
    let note = $("sheet-error");
    if (!note) {
      note = element("p", "error");
      note.id = "sheet-error";
      note.setAttribute("role", "alert");
      $("sheet-content").prepend(note);
    }
    note.textContent = text;
  } else message(text);
}
function showJoin(error = "") {
  if (roomClosed) return;
  clearTimeout(pollTimer);
  clearTimeout(browseTimer);
  stateRequest++;
  browseRequest++;
  closeSheet();
  session = null;
  state = null;
  connected = false;
  uncertainAction = null;
  $("loading").hidden = true;
  $("controller").hidden = $("nav").hidden = $("settings-button").hidden = true;
  $("join").hidden = false;
  $("manual-code").hidden = Boolean(invite);
  $("code").required = !invite;
  $("join-error").hidden = !error;
  $("join-error").textContent = error;
  try { $("name").value = localStorage.getItem("karaoke.guest-name") || ""; } catch {}
}
async function enter(user) {
  if (roomClosed) return;
  session = user;
  invite = "";
  $("join").hidden = $("loading").hidden = true;
  $("controller").hidden = $("nav").hidden = $("settings-button").hidden = false;
  renderedPlayer = renderedList = "";
  activateTab("search");
  await refresh();
}
$("join-form").addEventListener("submit", async event => {
  event.preventDefault();
  const name = $("name").value.trim();
  if (!name) { $("name").focus(); return; }
  $("enter").disabled = true;
  try {
    const user = await api("join", {name, ...(invite ? {secret: invite} : {code: $("code").value.trim()})});
    try { localStorage.setItem("karaoke.guest-name", name); } catch {}
    await enter(user);
  } catch (err) {
    $("join-error").hidden = false;
    $("join-error").textContent = err.status ? err.message : "No se encuentra el ordenador. Comprueba la wifi y vuelve a intentarlo.";
    if (invite && (err.status === 401 || err.status === 403)) {
      invite = "";
      $("manual-code").hidden = false;
      $("code").required = true;
    }
  } finally { $("enter").disabled = false; }
});

function connectionNotice() {
  const host = $("connection");
  host.replaceChildren();
  host.hidden = connected && !uncertainAction;
  if (connected) disconnectedSince = 0;
  if (!connected) {
    disconnectedSince ||= Date.now();
    if (Date.now() - disconnectedSince < 15000) host.textContent = "Reconectando con el ordenador…";
    else host.append(document.createTextNode("No se encuentra el ordenador. Comprueba la wifi o escanea el QR de la sala actual. "),
      button("Reintentar", () => { void refresh(); }));
  }
  else if (uncertainAction) {
    host.append(document.createTextNode("Falta confirmar la última acción."),
      button("Comprobar", () => {
        const {payload, done, origin} = uncertainAction;
        void sendAction(payload, done, origin);
      }));
  }
}
function fail(err) {
  if (roomClosed) return;
  if (err.status === 401 && session) {
    showJoin("La sesión ha terminado. Escanea el QR actual o introduce su código.");
    return;
  }
  if (!err.status) { connected = false; connectionNotice(); }
  announce(err.status ? err.message : "Se ha perdido la conexión con Karaoke.");
}
async function refresh() {
  clearTimeout(pollTimer);
  if (!session || document.hidden) return;
  const seq = ++stateRequest;
  try {
    const data = await api("state", {});
    if (seq !== stateRequest || !session) return;
    const libraryChanged = state && JSON.stringify(data.library_revision) !== JSON.stringify(state.library_revision);
    state = data;
    if (libraryChanged && tab === "search") void loadResults();
    connected = true;
    connectionNotice();
    renderPlayer();
    $("queue-count").textContent = data.queue.length ? "(" + data.queue.length + ")" : "";
    if (tab === "queue") renderQueue();
    refreshSheet?.();
  } catch (err) {
    if (seq !== stateRequest) return;
    if (err.status === 401) fail(err);
    else { connected = false; connectionNotice(); }
  } finally {
    if (seq === stateRequest && session && !document.hidden) {
      pollTimer = setTimeout(refresh, connected ? 1000 : 2500);
    }
  }
}
async function sendAction(payload, done, origin = currentSheet) {
  if (!connected || submitting || (uncertainAction && uncertainAction.payload !== payload)) {
    announce(uncertainAction ? "Comprueba primero la última acción." : (!connected ? "Espera a que vuelva la conexión." : "Enviando la acción…"));
    return;
  }
  submitting = true;
  payload.request_id ||= token();
  try {
    const result = await api("action", payload);
    uncertainAction = null;
    await refresh();
    if (session) done?.(result, origin);
  } catch (err) {
    if (!err.status) uncertainAction = {payload, done, origin};
    else uncertainAction = null;
    fail(err);
    if (err.status === 409 && session) {
      closeOrigin(origin);
      await refresh();
      announce(err.message);
    }
  } finally { submitting = false; if (session) connectionNotice(); }
}
function command(op, id, extra = {}, msg = "") {
  void sendAction({op, id, revision: state?.revision, ...extra}, (_, origin) => {
    closeOrigin(origin);
    if (msg) message(msg);
    if (tab !== "queue") void loadResults();
  });
}
function add(item, names = [session.name]) {
  if (confirmedItem?.id === item.id && confirmedItem.until > Date.now()) return;
  void sendAction({op: "add", id: item.id, names}, (result, origin) => {
    closeOrigin(origin);
    confirmedItem = {id: item.id, until: Date.now() + 1400};
    if (tab !== "queue") renderSongRows(renderedResults);
    setTimeout(() => {
      if (confirmedItem?.id === item.id && Date.now() >= confirmedItem.until) {
        confirmedItem = null;
        if (tab !== "queue") renderSongRows(renderedResults);
      }
    }, 1500);
    message(item.assisted ? "Petición enviada al ordenador" : "Turno añadido a la cola", result.id);
  });
}
function renderPlayer() {
  const active = state.queue.find(item => item.id === state.active);
  const item = active || state.queue.find(row => row.status === "ready");
  const key = JSON.stringify([item, state.active, state.paused]);
  if (key === renderedPlayer) return;
  renderedPlayer = key;
  const area = $("transport");
  area.replaceChildren();
  if (!item) return;
  const player = element("div", "player");
  const text = detail(item.title, (item.names || []).join(" + "));
  text.prepend(element("span", "player-label", active ? (state.paused ? "En pausa" : "Cantando ahora") : "Próximo turno"));
  const actions = element("div", "player-actions");
  const op = active ? (state.paused ? "resume" : "pause") : "start";
  const label = {start:"Empezar a cantar", resume:"Reanudar canción", pause:"Pausar canción"}[op];
  const play = iconButton(label, op === "pause" ? "pause" : "play", () => command(op, item.id), "utility main-action");
  play.disabled = item.status === "starting";
  actions.append(play);
  if (active) actions.append(iconButton("Terminar canción", "stop", () => confirmAction("¿Terminar la canción?", item.title, "Terminar canción", () => command("end", item.id)), "utility"));
  player.append(cover(item), text, actions);
  area.append(player);
}
function activateTab(section) {
  clearTimeout(browseTimer);
  browseRequest++;
  tab = section;
  renderedList = "";
  renderedResults = [];
  artworkAttempts = 0;
  $("list").replaceChildren();
  $("list-status").textContent = "";
  $("heading").textContent = captions[tab];
  document.querySelectorAll("[data-tab]").forEach(btn => {
    if (btn.dataset.tab === tab) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  const isQueue = tab === "queue";
  $("query-form").hidden = isQueue;
  $("preparations").hidden = !isQueue;
  $("list-heading").hidden = $("pagination").hidden = true;
  if (isQueue) { if (state) renderQueue(); }
  else {
    $("query").value = browse[tab].q;
    $("query").placeholder = "Artista, canción o enlace";
    $("query-label").textContent = $("query").placeholder;
    void loadResults();
  }
  window.scrollTo(0, 0);
}
function replaceList(rows) {
  const list = $("list");
  const active = list.contains(document.activeElement) ? document.activeElement.dataset.focusKey : null;
  list.replaceChildren(...rows);
  if (active) Array.from(list.querySelectorAll("[data-focus-key]")).find(el => el.dataset.focusKey === active)?.focus({preventScroll:true});
}
function renderSongRows(items) {
  renderedResults = items;
  const rows = items.map(item => {
    const li = element("li", "song");
    const open = button("", () => openSong(item), "song-main");
    open.dataset.focusKey = "song:" + item.id;
    const sub = [item.artist, item.language, item.status_label];
    open.append(cover(item), detail(item.title, sub.filter(Boolean).join(" · ")));
    li.append(open);
    if ((item.available && !item.assisted) || item.saved) {
      const confirmed = confirmedItem?.id === item.id && confirmedItem.until > Date.now();
      const control = iconButton("Añadir " + item.title, confirmed ? "check" : "plus", () => add(item));
      control.dataset.focusKey = "add:" + item.id;
      control.classList.toggle("confirmed", Boolean(confirmed));
      if (confirmed) control.setAttribute("aria-disabled", "true");
      li.append(control);
    }
    return li;
  });
  replaceList(rows);
}
async function loadResults() {
  clearTimeout(browseTimer);
  if (!session || tab === "queue" || document.hidden) return;
  const section = tab;
  const seq = ++browseRequest;
  const {q, page} = browse[section];
  const emptySearch = section === "search" && !q.trim();
  $("list-heading").hidden = true;
  try {
    const data = await api("search", {q: q.trim(), page, saved_only: $("saved-only").checked});
    if (!session || seq !== browseRequest) return;
    const key = JSON.stringify(data.items);
    if (key !== renderedList) {
      renderedList = key;
      renderSongRows(data.items);
    }
    $("list-status").textContent = data.busy ? "Buscando canciones…" : (data.items.length ? "" :
      ($("saved-only").checked ? "Sin canciones descargadas. Desactiva el filtro para consultar el catálogo." : emptySearch ? "Escribe un artista o una canción para empezar." : "Sin coincidencias. Prueba con otro título o artista."));
    $("pagination").hidden = !page && !data.more;
    $("prev").hidden = !page;
    $("next").hidden = !data.more;
    if (data.busy || data.items.some(item => item.availability === "working")) browseTimer = setTimeout(loadResults, 800);
    else if (data.items.some(item => !item.cover) && artworkAttempts++ < 3) {
      browseTimer = setTimeout(loadResults, 2500);
    }
  } catch (err) {
    if (seq !== browseRequest) return;
    fail(err);
    if (session) {
      $("list-status").textContent = err.status ? err.message : "Esperando conexión…";
      if (!err.status) browseTimer = setTimeout(loadResults, 2200);
    }
  }
}
function renderQueue() {
  const jobs = state.preparations || [];
  const key = JSON.stringify([state.queue, jobs]);
  if (key === renderedList) return;
  renderedList = key;
  $("preparations").hidden = !jobs.length;
  const downloads = jobs.map(job => {
    const entry = element("div", "song");
    const retry = ["error", "cancelled"].includes(job.state);
    entry.append(detail(job.title, statuses[job.state] || "Cancelada"));
    const verb = retry ? "Reintentar" : "Cancelar";
    const op = retry ? "retry-preparation" : "cancel-preparation";
    entry.append(button(verb, () => retry ? command(op, job.id) : confirmAction("¿Cancelar la descarga?", job.title, verb, () => command(op, job.id))));
    return entry;
  });
  $("preparation-list").replaceChildren(...downloads);
  $("list-status").textContent = state.queue.length ? "" : "La cola está vacía.";
  const rows = state.queue.map((item, index) => {
    const li = element("li", "song");
    const open = button("", () => openTurn(item), "song-main");
    open.dataset.focusKey = item.id;
    const description = detail(item.title, [item.artist, (item.names || []).join(" + "), statuses[item.status]].filter(Boolean).join(" · "));
    if (item.message) description.append(element("span", "sub", item.message));
    open.append(cover(item), description);
    const more = iconButton("Opciones del turno " + (index + 1) + ", " + item.title, "more", () => openTurn(item));
    more.dataset.focusKey = "options:" + item.id;
    li.append(open, more);
    return li;
  });
  replaceList(rows);
}
function closeOrigin(origin) {
  if (origin && currentSheet === origin) closeSheet();
}
function closeSheet() {
  clearTimeout(candidateTimer);
  currentSheet = null;
  refreshSheet = null;
  if ($("sheet").open) $("sheet").close();
}
function sheet(title) {
  clearTimeout(candidateTimer);
  currentSheet = Symbol();
  refreshSheet = null;
  $("sheet-title").textContent = title;
  $("sheet-content").replaceChildren();
  if (!$("sheet").open) $("sheet").showModal();
  else $("sheet-close").focus();
  return $("sheet-content");
}
function confirmAction(title, subject, verb, action) {
  const content = sheet(title);
  content.append(element("p", "muted", subject));
  const actions = element("div", "sheet-actions");
  actions.append(button("Volver", closeSheet), button(verb, action, "danger"));
  content.append(actions);
}
function singerFields(content, names) {
  const fields = [];
  for (let i = 0; i < 2; i++) {
    const input = element("input");
    input.id = "singer-" + i;
    input.value = names[i] || "";
    input.maxLength = 32;
    input.autocomplete = "off";
    input.required = !i;
    const label = element("label", "", i ? "Segunda voz (opcional)" : "Cantante");
    label.htmlFor = input.id;
    fields.push(input);
    content.append(label, input);
  }
  return () => {
    if (!fields[0].value.trim()) {
      fields[0].focus();
      announce("Escribe el nombre de quien va a cantar.");
      return null;
    }
    return fields.map(field => field.value.trim()).filter(Boolean);
  };
}
function describeEdition(item) {
  const kind = {original:"Con voz", instrumental:"Instrumental"}[item.variant] || "";
  return [item.source, item.edition, kind].filter(Boolean).join(" · ") || item.title;
}
function openSong(item) {
  const content = sheet(item.title);
  content.append(element("p", "muted", [item.artist, item.language].filter(Boolean).join(" · ")));
  const editions = item.editions || [];
  const variants = [item, ...editions.filter(row => row.id !== item.id)];
  const libraryId = item.id.startsWith("lib:") ? item.id : item.library_id;
  let selected = item;
  if (editions.length > 1 || (item.id.startsWith("lib:") && variants.length > 1)) {
    const label = element("label", "", "Edición");
    label.htmlFor = "edition";
    const options = element("select");
    options.id = "edition";
    variants.forEach((row, index) => {
      const editionTitle = index === 0 && !item.id.startsWith("lib:") ? "Elegir automáticamente" : describeEdition(row);
      const option = element("option", "", editionTitle + (row.assisted ? " · Elegir en el ordenador" : ""));
      option.value = String(index);
      option.disabled = !(row.available || row.assisted || row.saved || row.availability === "failed");
      options.append(option);
    });
    const preferred = variants.findIndex(row => row.id === item.id && (row.available || row.assisted || row.saved));
    if (preferred >= 0) options.selectedIndex = preferred;
    selected = variants[options.selectedIndex] || item;
    options.addEventListener("change", () => { selected = variants[options.selectedIndex]; updateActions(); });
    content.append(label, options);
  }
  const addLabel = () => selected.assisted ? "Pedir al anfitrión" : "Añadir a la cola";
  let addControl, saveControl;
  function updateActions() {
    if (addControl) addControl.lastChild.textContent = addLabel();
    if (saveControl) {
      saveControl.hidden = !selected.assisted && !["direct", "failed"].includes(selected.availability);
      saveControl.textContent = selected.availability === "failed" ? "Reintentar descarga" : "Solo descargar";
    }
  }
  if (item.availability === "failed") content.append(element("p", "small muted", "La preparación de esta edición falló. Puedes reintentarla."));
  if (item.available || item.assisted || item.saved || variants.some(s => s.available || s.assisted || s.availability === "failed")) {
    const names = singerFields(content, [session.name]);
    addControl = button(addLabel(), () => {
      const values = names();
      if (values && selected) add(selected, values);
    }, "primary full", "plus");
    saveControl = button("Solo descargar", () => command("save", selected.id, {}, selected.assisted ? "Solicitud enviada al ordenador" : "Preparando la canción"), "full");
    content.append(addControl, saveControl);
    updateActions();
  } else content.append(element("p", "small muted", item.availability === "missing" ? "Falta el audio o el mapa. Vuelve a importar el paquete en el ordenador." : "Esta ficha no tiene descarga integrada."));
  if (libraryId) {
    const actions = element("div", "sheet-actions");
    const previewing = Boolean(state?.previewing);
    const preview = button(previewing ? "Detener escucha" : "Escuchar en el PC", () => command(previewing ? "stop-preview" : "preview", libraryId));
    preview.disabled = !previewing && Boolean(state?.active);
    actions.append(preview);
    if (item.variant !== "instrumental") actions.append(button("Buscar instrumental", () => openInstrumentals({...item, id: libraryId})));
    actions.append(button("Eliminar de la biblioteca", () => confirmAction("¿Eliminar esta canción?", item.title, "Eliminar canción",
      () => command("delete", libraryId, {confirm:true}, "Canción eliminada")), "danger"));
    content.append(actions);
  }
}
async function openInstrumentals(item) {
  const content = sheet("Buscar instrumental");
  const key = currentSheet;
  content.append(element("p", "muted", item.title));
  const box = element("div");
  content.append(box);
  box.textContent = "Buscando versiones…";
  async function update() {
    if (currentSheet !== key || !session || !$("sheet").open) return;
    try {
      const data = await api("action", {op:"instrumentals", id:item.id});
      if (currentSheet !== key) return;
      box.replaceChildren();
      if (data.message || (!data.items?.length && !data.busy)) {
        box.append(element("p", "small muted", data.message || "No hay versiones compatibles disponibles."));
      }
      if (data.prepared) {
        box.append(button("Añadir instrumental a la cola", () => add({...item, id: data.prepared}), "primary full", "plus"));
      } else if (!data.busy) {
        (data.items || []).forEach(candidate => {
          box.append(button(candidate.title, () => {
            void sendAction({op:"prepare-instrumental", id:item.id, candidate:candidate.id}, () => { void update(); });
          }, "full"));
        });
      }
      if (data.busy) candidateTimer = setTimeout(update, 1000);
    } catch (err) { if (currentSheet === key) fail(err); }
  }
  await update();
}
function openTurn(stale) {
  const item = state.queue.find(row => row.id === stale.id);
  if (!item) { message("Este turno ya ha terminado."); return; }
  let editRevision = state.revision;
  const originalVoices = JSON.stringify([item.names, item.voices]);
  const content = sheet(item.title);
  const status = element("p", "muted");
  status.setAttribute("aria-live", "polite");
  const explanation = element("p", "small muted");
  content.append(status, explanation);
  const actions = element("div", "sheet-actions");
  const up = button("Subir turno", () => command("up", item.id), "", "up");
  const down = button("Bajar turno", () => command("down", item.id), "", "down");
  const start = button("Empezar a cantar", () => command("start", item.id), "primary");
  const retry = button("Reintentar", () => command("retry", item.id));
  const pause = button("Pausar", () => command(state.paused ? "resume" : "pause", item.id), "primary");
  const end = button("Terminar canción", () => confirmAction("¿Terminar la canción?", item.title,
    "Terminar canción", () => command("end", item.id)), "danger");
  actions.append(up, down, start, retry, pause, end);
  content.append(actions);
  const editor = element("div");
  const editCommand = (op, id, extra, message) => command(op, id, {...extra, revision:editRevision}, message);
  if (state.singers?.length) window.karaokeVoiceEditor?.(editor,item,state,editRevision,editCommand);
  const names = singerFields(editor, item.names || []);
  editor.append(button("Guardar cantantes", () => {
    const values = names();
    if (values) editCommand("rename", item.id, {names:values}, "Cantantes actualizados");
  }, "full"));
  editor.append(button("Quitar de la cola", () => {
    const revision = state.revision;
    confirmAction("¿Quitar este turno?", item.title, "Quitar turno",
      () => command("remove", item.id, {revision}, "Turno retirado"));
  }, "danger full"));
  content.append(editor);
  refreshSheet = () => {
    const scroll = $("sheet").scrollTop;
    const latest = state.queue.find(row => row.id === item.id);
    const active = latest && (item.id === state.active || ["starting", "singing"].includes(latest.status));
    const summary = latest ? [latest.artist, statuses[latest.status]].filter(Boolean).join(" · ") : "Este turno ya ha terminado.";
    if (status.textContent !== summary) status.textContent = summary;
    const hint = latest?.message || (latest?.status === "host" ? "Elige la edición en el ordenador para continuar." : "");
    if (explanation.textContent !== hint) explanation.textContent = hint;
    explanation.hidden = !hint;
    const pending = state.queue.filter(row => row.id !== state.active && !["starting", "singing"].includes(row.status));
    const position = pending.findIndex(row => row.id === item.id);
    up.hidden = !latest || active || position < 1;
    down.hidden = !latest || active || position + 1 >= pending.length;
    start.hidden = !latest || active || latest.status !== "ready" || !!state.active;
    retry.hidden = !latest || active || latest.status !== "error";
    pause.hidden = end.hidden = !active;
    pause.disabled = latest?.status === "starting";
    const caption = state.paused ? "Reanudar" : "Pausar";
    if (pause.textContent !== caption) pause.textContent = caption;
    actions.hidden = ![...actions.children].some(control => !control.hidden);
    editor.hidden = !latest || active;
    // Preparation and queue changes must not stale the form. A competing edit
    // to these voices still retains the original server conflict check.
    if (latest && JSON.stringify([latest.names, latest.voices]) === originalVoices) editRevision = state.revision;
    $("sheet").scrollTop = scroll;
  };
  refreshSheet();
}
$("settings-button").addEventListener("click", () => {
  if (!state) return;
  const content = sheet("Ajustes de la sesión");
  const initialMusic = state.music;
  const initialPitch = state.pitch_precision;
  const range = element("input");
  const label = element("label");
  label.htmlFor = "volume";
  range.id = "volume";
  range.type = "range"; range.min = "0"; range.max = "100"; range.value = String(initialMusic);
  const showValue = () => { label.textContent = "Volumen de la música · " + range.value + " %"; };
  range.addEventListener("input", showValue);
  showValue();

  const pitchLabel = element("label", "", "Precisión de afinación");
  pitchLabel.htmlFor = "pitch-precision";
  const pitch = element("select");
  pitch.id = "pitch-precision";
  ["Flexible · hasta 2 semitonos", "Normal · hasta 1 semitono", "Estricta · misma nota"].forEach((text, level) => {
    pitch.add(new Option(text, String(level)));
  });
  pitch.value = String(initialPitch);
  const hint = element("p", "muted small", "La precisión se aplica a todos los cantantes desde la próxima canción.");
  hint.id = "pitch-hint";
  pitch.setAttribute("aria-describedby", hint.id);
  const save = button("Guardar ajustes", () => {
    const changes = {};
    if (Number(range.value) !== initialMusic) changes.music = Number(range.value);
    if (Number(pitch.value) !== initialPitch) changes.pitch_precision = Number(pitch.value);
    if (Object.keys(changes).length) command("settings", "", {changes}, "Ajustes guardados");
    else closeSheet();
  }, "primary full");
  content.append(label, range, pitchLabel, pitch, hint, save);
  window.karaokePeople?.(content, {api, action:sendAction, state, session});
});
$("sheet-close").addEventListener("click", closeSheet);
$("sheet").addEventListener("close", () => { if (!$("sheet").open) { clearTimeout(candidateTimer); currentSheet = null; refreshSheet = null; } });
document.querySelectorAll("[data-tab]").forEach(btn => btn.addEventListener("click", () => activateTab(btn.dataset.tab)));
$("saved-only").addEventListener("change", () => {
  browse.search.page = 0;
  renderedList = "";
  if ($("saved-only").checked) renderSongRows(renderedResults.filter(item => item.saved));
  void loadResults();
});
$("query").maxLength = 240;
$("query").addEventListener("input", () => {
  browse[tab] = {q:$("query").value, page:0};
  clearTimeout(browseTimer);
  browseRequest++;
  renderedList = "";
  renderedResults = [];
  artworkAttempts = 0;
  replaceList([]);
  $("pagination").hidden = true;
  $("list-heading").hidden = true;
  $("list-status").textContent = "Buscando canciones…";
  browseTimer = setTimeout(loadResults, 280);
});
$("query-form").addEventListener("submit", event => { event.preventDefault(); void loadResults(); });
function pageBy(step) {
  artworkAttempts = 0;
  browse[tab].page = Math.max(0, browse[tab].page + step);
  $("pagination").hidden = true;
  void loadResults();
}
$("prev").addEventListener("click", () => pageBy(-1));
$("next").addEventListener("click", () => pageBy(1));
document.addEventListener("visibilitychange", () => {
  clearTimeout(pollTimer); clearTimeout(browseTimer);
  if (!document.hidden && session) { void refresh(); if (tab !== "queue") void loadResults(); }
});
window.addEventListener("online", () => { if (session) { void refresh(); void loadResults(); } });
window.addEventListener("offline", () => { if (session) { connected = false; connectionNotice(); } });

(async function boot() {
  try {
    const user = await api("me", null, "GET");
    if (invite) showJoin();
    else await enter(user);
  } catch (err) {
    showJoin(err.status === 401 ? "" : "Comprueba que el móvil y el ordenador están en la misma red.");
  }
})();
