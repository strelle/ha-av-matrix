/* Strelle AV Matrix Server – Rahmen um die Karte: Verbindung (hass-Ersatz), Presets, Geräte, LLM-Verbindung.
 * Die Karte (av-matrix-card.js) stammt unverändert aus der Home-Assistant-Integration; sie bekommt hier ein
 * kleines Objekt, das sich wie `hass` verhält und alles an diesen Server schickt. Kein Build-Schritt. */
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (_e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_e) { /* egal */ } },
  };

  /* ------------------------------------------------------------ Meldungen */
  function toast(text, kind = "info") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.setAttribute("role", kind === "err" ? "alert" : "status");
    el.textContent = text;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), kind === "err" ? 6500 : 2800);
  }

  async function api(method, path, body, headers = {}) {
    const res = await fetch(path, {
      method,
      headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (_e) { /* kein JSON */ }
    if (!res.ok) {
      const err = new Error((data && data.message) || `HTTP ${res.status}`);
      err.body = data; err.status = res.status;
      throw err;
    }
    return data;
  }

  async function copy(text, what = "Kopiert") {
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else {
        const ta = document.createElement("textarea"); // http im Studionetz: kein Clipboard-API
        ta.value = text; ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
        document.body.appendChild(ta); ta.focus(); ta.select();
        const ok = document.execCommand("copy"); ta.remove();
        if (!ok) throw new Error("copy");
      }
      toast(what, "ok");
    } catch (_e) { toast("Kopieren nicht möglich – bitte von Hand markieren.", "err"); }
  }

  /* ------------------------------------------------------------ Verbindung (WebSocket, wie hass.connection) */
  class Connection {
    constructor() {
      this.nextId = 1; this.pending = new Map(); this.subs = new Map(); this.ws = null; this.open = false; this.queue = [];
      this.onstate = () => {};
      this.connect();
    }
    connect() {
      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      this.ws = ws;
      ws.onopen = () => {
        this.open = true; this.onstate(true);
        for (const [id, sub] of this.subs) ws.send(JSON.stringify({ ...sub.msg, id })); // nach Neustart neu abonnieren
        for (const raw of this.queue.splice(0)) ws.send(raw);
      };
      ws.onmessage = (ev) => {
        let m; try { m = JSON.parse(ev.data); } catch (_e) { return; }
        if (m.type === "event") { const s = this.subs.get(m.id); if (s) s.cb(m.event); return; }
        const p = this.pending.get(m.id);
        if (!p) return;
        this.pending.delete(m.id);
        if (m.success === false) p.reject(Object.assign(new Error((m.error && m.error.message) || "Fehler"), { code: m.error && m.error.code }));
        else p.resolve(m.result);
      };
      ws.onclose = () => {
        if (this.ws !== ws) return;
        this.open = false; this.onstate(false);
        for (const [id, p] of this.pending) { if (!this.subs.has(id)) p.reject(new Error("Verbindung zum Server unterbrochen")); }
        this.pending.clear();
        setTimeout(() => this.connect(), 2000);
      };
      ws.onerror = () => ws.close();
    }
    _send(msg, id) {
      const raw = JSON.stringify({ ...msg, id });
      if (this.open) this.ws.send(raw); else this.queue.push(raw);
    }
    sendMessagePromise(msg) {
      const id = this.nextId++;
      return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this._send(msg, id); });
    }
    subscribeMessage(cb, msg) {
      const id = this.nextId++;
      this.subs.set(id, { cb, msg });
      return new Promise((resolve, reject) => {
        this.pending.set(id, {
          resolve: () => resolve(() => { this.subs.delete(id); if (this.open) this._send({ type: "unsubscribe_events", subscription: id }, this.nextId++); }),
          reject: (e) => { this.subs.delete(id); reject(e); },
        });
        if (this.open) this._send(msg, id); // sonst schickt onopen alle Abos
      });
    }
    subscribeEvents(cb, eventType) { return this.subscribeMessage(cb, { type: "subscribe_events", event_type: eventType }); }
  }

  const conn = new Connection();
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let theme = store.get("avm:theme", "auto");
  const makeHass = () => ({
    connection: conn,
    language: "de",
    locale: { language: "de" },
    user: { id: "panel", name: "Panel", is_admin: true },
    themes: { darkMode: theme === "auto" ? media.matches : theme === "dark" },
    states: {},
    callService: (domain, service, data) => conn.sendMessagePromise({ type: "call_service", domain, service, service_data: data || {} }),
    callWS: (msg) => conn.sendMessagePromise(msg),
    callApi: (method, path, body) => api(method, `/api/ha/${path}`, body),
  });

  /* ------------------------------------------------------------ Zustand */
  const S = { snap: null, info: null, devices: null, tab: "matrix", token: null, busyPreset: null };
  const card = $("#card");

  function applyTheme() {
    const light = theme === "daylight" || (theme === "auto" && !media.matches);
    document.documentElement.dataset.theme = light ? "daylight" : "dark";
    $('meta[name="theme-color"]').content = light ? "#ffffff" : "#121212";
    $$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === theme)));
    if (card.setConfig) {
      card.setConfig({ title: (S.info && S.info.name) || "Strelle AV Matrix", mode: "panel", take_mode: "direct", name_mode: "both", theme });
      card.hass = makeHass();
    }
  }
  $$("[data-theme-set]").forEach((b) => b.addEventListener("click", () => { theme = b.dataset.themeSet; store.set("avm:theme", theme); applyTheme(); }));
  media.addEventListener("change", () => theme === "auto" && applyTheme());

  conn.onstate = (ok) => {
    $("#conn-led").classList.toggle("ok", ok);
    $("#conn-led").title = ok ? "Mit dem Server verbunden" : "Keine Verbindung zum Server – wird neu aufgebaut";
  };

  /* ------------------------------------------------------------ Reiter */
  const TABS = ["matrix", "presets", "devices", "system", "llm"];
  function showTab(tab, push = true) {
    if (!TABS.includes(tab)) tab = "matrix";
    S.tab = tab;
    TABS.forEach((t) => { $(`#page-${t}`).hidden = t !== tab; });
    $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    if (push && location.hash !== `#${tab}`) history.replaceState(null, "", `#${tab}`);
    if (tab === "devices") loadDevices();
    if (tab === "presets") renderPresets();
    if (tab === "llm") renderLlm();
    hooks.tab.forEach((fn) => fn(tab));
  }
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1), false));
  // die Karte will bei "In den Einstellungen öffnen" zu den HA-Integrationen → hier: Geräte
  window.addEventListener("location-changed", () => { history.replaceState(null, "", "/#devices"); showTab("devices", false); });

  /* ------------------------------------------------------------ Presets */
  const allDests = () => Object.values((S.snap && S.snap.protocols) || {}).flatMap((p) => p.destinations);
  const protoOf = (key) => (S.snap && S.snap.protocols[key]) || { sources: [], destinations: [] };

  async function recall(id) {
    S.busyPreset = id; renderPresetBar(); renderPresets();
    try {
      const r = await api("POST", `/api/presets/${encodeURIComponent(id)}/recall`, { origin: "panel" });
      toast(r.skipped_offline && r.skipped_offline.length ? `Preset „${r.name}“ abgerufen – ${r.skipped_offline.length} Ziel(e) offline übersprungen` : `Preset „${r.name}“ abgerufen`, "ok");
    } catch (err) { toast(`Preset nicht abgerufen: ${err.message}`, "err"); }
    S.busyPreset = null; renderPresetBar(); renderPresets();
  }

  async function undoLast() {
    try { await api("POST", "/api/undo"); toast("Letzte Aktion zurückgenommen", "ok"); }
    catch (err) { toast(err.message, "err"); }
  }

  function renderPresetBar() {
    const bar = $("#presetbar");
    const presets = (S.snap && S.snap.presets) || [];
    bar.hidden = !presets.length && !(S.snap && S.snap.can_undo);
    bar.innerHTML = `<span class="kicker">Presets</span>${presets
      .map((p) => `<button class="pkey ${p.active ? "active" : ""} ${S.busyPreset === p.id ? "busy" : ""}" data-recall="${esc(p.id)}"
        title="${esc(p.name)} – ${p.routes.length} Verbindung(en)${p.active ? " · aktiv" : ""}" aria-pressed="${p.active}">${esc(p.name)}</button>`)
      .join("")}<span class="grow"></span>
      <button class="btn sm ghost" data-undo-last ${S.snap && S.snap.can_undo ? "" : "disabled"} title="Letzte Aktion (Einzelschaltung oder Preset) zurücknehmen">Letzte Aktion rückgängig</button>
      <button class="btn sm ghost" data-goto="presets">Presets bearbeiten</button>`;
  }

  function renderPresets() {
    if (S.tab !== "presets") return;
    const page = $("#page-presets");
    const presets = (S.snap && S.snap.presets) || [];
    page.innerHTML = `
      <div class="panel"><div class="row"><div class="grow"><h2>Presets</h2>
        <p class="lead">Ein Preset schaltet mehrere Verbindungen auf einmal. Es leuchtet rot, solange der Ist-Zustand genau dem Preset entspricht.</p></div>
        <button class="btn primary" data-preset-new>Neues Preset</button></div></div>
      ${presets.length ? `<div class="pgrid">${presets.map(presetCard).join("")}</div>` : `<div class="empty">Noch keine Presets. „Neues Preset“ hält den aktuellen Zustand ausgewählter Ziele fest.</div>`}`;
  }

  function presetCard(p) {
    return `<article class="panel pcard ${p.active ? "active" : ""}">
      <div class="row"><h3 class="grow">${esc(p.name)}</h3>${p.active ? `<span class="chip live">aktiv</span>` : `<span class="chip">nicht aktiv</span>`}</div>
      <ul class="proutes">${p.routes.map((r) => `<li title="${esc(r.destination)}">
        <span class="dot ${!r.known || !r.available ? "err" : r.matches ? "ok" : "cue"}" title="${!r.known ? "Ziel unbekannt" : !r.available ? "Gerät offline" : r.matches ? "stimmt mit dem Preset überein" : "weicht ab"}"></span>
        <span class="ell">${esc(r.destination_name)}${r.locked ? " · gesperrt" : ""}</span><span class="arr">←</span>
        <span class="ell mono">${esc(r.source_name ?? "Aus")}</span></li>`).join("")}</ul>
      <div class="row"><button class="btn primary grow" data-recall="${esc(p.id)}" ${S.busyPreset === p.id ? "disabled" : ""}>Abrufen</button>
        <button class="btn" data-preset-edit="${esc(p.id)}">Ändern</button>
        <button class="btn danger" data-preset-del="${esc(p.id)}">Löschen</button></div>
    </article>`;
  }

  function presetDialog(preset) {
    const dlg = $("#dlg");
    const chosen = new Map((preset ? preset.routes : []).map((r) => [r.destination, r.source]));
    const groups = [];
    for (const [key, proto] of Object.entries((S.snap && S.snap.protocols) || {})) {
      const byDev = new Map();
      for (const d of proto.destinations) {
        const g = d.group || `${proto.title || key}-Ziele`;
        if (!byDev.has(g)) byDev.set(g, []);
        byDev.get(g).push(d);
      }
      for (const [g, dests] of byDev) groups.push({ key, title: dests[0].group ? `${proto.title || key} · ${g}` : g, dests });
    }
    const srcOptions = (key, value) => {
      const list = protoOf(key).sources;
      const has = value == null || list.some((s) => s.id === value);
      return `<option value="">Aus (keine Quelle)</option>${has ? "" : `<option value="${esc(value)}" selected>${esc(value)} (nicht im Netz)</option>`}${list
        .map((s) => `<option value="${esc(s.id)}" ${s.id === value ? "selected" : ""}>${esc(s.name)}${s.label ? ` – ${esc(s.id)}` : ""}${s.live ? "" : " (offline)"}</option>`).join("")}`;
    };
    dlg.innerHTML = `<form method="dialog">
      <div class="dhead"><h2>${preset ? "Preset ändern" : "Neues Preset"}</h2><button type="button" class="btn sm ghost" data-close>Schließen</button></div>
      <div class="dbody">
        <label class="fld">Name<input type="text" name="name" maxlength="60" required value="${esc(preset ? preset.name : "")}" placeholder="z. B. Schnitt auf Regie" autocomplete="off"></label>
        <div class="row"><span class="grow muted">Ziele ankreuzen, die zum Preset gehören, und je Ziel die Quelle wählen.</span>
          <button type="button" class="btn sm" data-take-current>Ist-Zustand übernehmen</button></div>
        ${groups.map((g) => {
          const n = g.dests.filter((d) => chosen.has(d.id)).length;
          return `<details class="rgroup" ${n || groups.length <= 3 ? "open" : ""}><summary>${esc(g.title)}<span class="chip cnt">${n}/${g.dests.length}</span></summary>
            ${g.dests.map((d) => {
              const on = chosen.has(d.id);
              const val = on ? chosen.get(d.id) : d.current_source;
              return `<div class="rrow ${on ? "" : "off"} ${d.protected ? "prot" : ""}" data-dest="${esc(d.id)}" data-proto="${esc(g.key)}" data-current="${esc(d.current_source ?? "")}">
                <input type="checkbox" id="pr-${esc(d.id)}" ${on ? "checked" : ""} ${d.protected ? "disabled" : ""}>
                <label for="pr-${esc(d.id)}" title="${esc(d.protected || d.original_name)}">${esc(d.group ? d.label || d.channel || d.name : d.name)}${d.protected ? " · fest gesperrt" : ""}</label>
                <select aria-label="Quelle für ${esc(d.name)}" ${d.protected ? "disabled" : ""}>${srcOptions(g.key, val)}</select></div>`;
            }).join("")}</details>`;
        }).join("") || `<div class="empty">Noch keine Ziele vorhanden – zuerst Geräte einrichten.</div>`}
        <div class="errbox" data-err hidden></div>
      </div>
      <div class="dfoot"><span class="grow"></span><button type="button" class="btn ghost" data-close>Abbrechen</button>
        <button type="submit" class="btn primary">Speichern</button></div></form>`;
    const sync = (row) => {
      row.classList.toggle("off", !$("input", row).checked);
      const det = row.closest("details");
      $(".cnt", det).textContent = `${$$("input:checked", det).length}/${$$(".rrow", det).length}`;
    };
    dlg.onchange = (e) => {
      const row = e.target.closest(".rrow");
      if (!row) return;
      if (e.target.tagName === "SELECT") $("input", row).checked = true;
      sync(row);
    };
    dlg.onclick = (e) => {
      if (e.target.closest("[data-close]")) return dlg.close();
      if (e.target.closest("[data-take-current]")) {
        const rows = $$(".rrow", dlg).filter((r) => $("input", r).checked);
        if (!rows.length) return toast("Erst Ziele ankreuzen.", "err");
        rows.forEach((r) => { $("select", r).value = r.dataset.current; });
        toast("Ist-Zustand der angekreuzten Ziele übernommen", "ok");
      }
    };
    $("form", dlg).onsubmit = async (e) => {
      e.preventDefault();
      const routes = $$(".rrow", dlg).filter((r) => $("input", r).checked).map((r) => ({ destination: r.dataset.dest, source: $("select", r).value || null }));
      const name = $('input[name="name"]', dlg).value.trim();
      const errBox = $("[data-err]", dlg);
      try {
        if (!routes.length) throw new Error("Mindestens ein Ziel ankreuzen.");
        if (preset) await api("PUT", `/api/presets/${encodeURIComponent(preset.id)}`, { name, routes });
        else await api("POST", "/api/presets", { name, routes });
        dlg.close(); toast(`Preset „${name}“ gespeichert`, "ok");
      } catch (err) { errBox.hidden = false; errBox.textContent = err.message; }
    };
    dlg.showModal();
  }

  function confirmDialog(title, text, okLabel, danger = true) {
    return new Promise((resolve) => {
      const dlg = $("#dlg");
      dlg.onchange = null;
      dlg.innerHTML = `<form method="dialog"><div class="dhead"><h2>${esc(title)}</h2></div><div class="dbody"><p style="margin:0">${esc(text)}</p></div>
        <div class="dfoot"><span class="grow"></span><button type="button" class="btn ghost" data-no>Abbrechen</button>
        <button type="button" class="btn ${danger ? "danger" : "primary"}" data-yes>${esc(okLabel)}</button></div></form>`;
      dlg.onclick = (e) => {
        if (e.target.closest("[data-yes]")) { dlg.close(); resolve(true); }
        else if (e.target.closest("[data-no]")) { dlg.close(); resolve(false); }
      };
      dlg.addEventListener("close", () => resolve(false), { once: true });
      dlg.showModal();
    });
  }

  /* ------------------------------------------------------------ Geräte */
  let devTimer = null;
  async function loadDevices() {
    try { S.devices = (await api("GET", "/api/devices")).devices; } catch (_e) { /* bleibt beim alten Stand */ }
    renderDevices();
  }
  function renderDevices() {
    if (S.tab !== "devices") return;
    const page = $("#page-devices");
    const devs = S.devices || [];
    const prot = (S.snap && S.snap.protected) || [];
    const art = (key) => (key ? `<img src="/static/devices/${esc(key)}.svg" alt="" loading="lazy">` : "<span></span>");
    const hasDante = devs.some((d) => d.driver === "dante");
    setTimeout(() => hooks.tab.forEach((fn) => fn("devices-rendered")), 0);
    page.innerHTML = `
      <div class="panel"><div class="row"><div class="grow"><h2>Geräte</h2>
        <p class="lead">NDI®-Decoder werden einzeln eingerichtet (Netzwerksuche oder von Hand). Das Dante®-Netzwerk findet alle Dante-Geräte von selbst.</p></div>
        <button class="btn" data-refresh>Quellen neu einlesen</button><button class="btn primary" data-add>Gerät hinzufügen</button></div></div>
      ${devs.filter((d) => !d.network).map((d) => `<div class="panel dev">${art(d.icon_key)}
        <div><div class="name">${esc(d.name)} ${d.online ? `<span class="chip ok">online</span>` : d.auth_failed ? `<span class="chip err">Anmeldung abgelehnt</span>` : `<span class="chip err">offline</span>`}</div>
          <div class="meta"><span>${esc([d.manufacturer, d.model].filter(Boolean).join(" ") || d.driver_title)}</span>
            ${d.firmware ? `<span>Firmware ${esc(d.firmware)}</span>` : ""}
            <span class="mono">${d.web_url ? `<a href="${esc(d.web_url)}" target="_blank" rel="noopener">${esc(d.host)}</a>` : esc(d.host)}</span>
            ${!d.online && d.last_error ? `<span>${esc(d.last_error)}</span>` : ""}</div></div>
        <div class="row acts"><button class="btn sm" data-rename="${esc(d.id)}" data-name="${esc(d.name)}">Umbenennen</button>
          <button class="btn sm danger" data-remove="${esc(d.id)}" data-name="${esc(d.name)}">Entfernen</button></div></div>`).join("")}
      ${devs.filter((d) => d.network).map((d) => `<div class="panel"><div class="row"><div class="grow"><h3>Dante®-Netzwerk</h3>
          <span class="muted">${d.devices.length} Geräte, automatisch per mDNS gefunden${d.static_hosts.length ? ` · feste Adressen: ${esc(d.static_hosts.join(", "))}` : ""}</span></div>
          <button class="btn sm" data-static="${esc(d.id)}" data-hosts="${esc(d.static_hosts.join(", "))}">Feste Adressen</button>
          <button class="btn sm danger" data-remove="${esc(d.id)}" data-name="Dante®-Netzwerk">Entfernen</button></div>
        <div class="subdevs">${d.devices.map((s) => `<div class="subdev"><span class="dot ${s.online ? "ok" : "err"}" title="${s.online ? "online" : "offline"}"></span>
          <span><b>${esc(s.name)}</b>${s.protected ? ` <span class="chip cue" title="${esc(s.protected)}">fest gesperrt</span>` : ""}</span>
          <span class="muted">${esc([s.manufacturer, s.model].filter(Boolean).join(" ") || "Dante-Gerät")} · ${s.tx_count} TX / ${s.rx_count} RX${s.sample_rate ? ` · ${s.sample_rate / 1000} kHz` : ""}</span>
          <span class="mono">${esc(s.host)}</span></div>`).join("") || `<div class="subdev"><span></span><span class="muted">Noch keine Dante-Geräte gefunden.</span></div>`}</div></div>`).join("")}
      ${devs.length ? "" : `<div class="empty">Noch keine Geräte eingerichtet.</div>`}
      ${hasDante ? "" : `<div class="panel"><div class="row"><div class="grow"><h3>Dante®-Netzwerk</h3><span class="muted">Noch nicht eingerichtet.</span></div><button class="btn" data-add>Einrichten</button></div></div>`}
      <div class="panel" id="pattern-panel"></div>
      <div class="panel"><h3>Feste Sperrliste</h3>
        <p class="lead" style="margin-top:6px">Diese Ziele verändert der Server über keine Schnittstelle – weder Panel noch HTTP, Companion oder MCP. Änderbar nur in der Konfigurationsdatei auf dem Server.</p>
        ${prot.map((r) => `<div class="row" style="padding:6px 0"><span class="chip cue">gesperrt</span><span>${esc(r.reason)}</span>
          <span class="mono muted">${esc([r.protocol, r.host, r.device, r.channels ? `Kanäle ${r.channels.join(", ")}` : "alle Kanäle"].filter(Boolean).join(" · "))}</span></div>`).join("") || `<span class="muted">Keine Einträge.</span>`}</div>`;
  }

  function textDialog(title, label, value, okLabel, hint = "") {
    return new Promise((resolve) => {
      const dlg = $("#dlg");
      dlg.onchange = null; dlg.onclick = null;
      dlg.innerHTML = `<form method="dialog"><div class="dhead"><h2>${esc(title)}</h2></div>
        <div class="dbody"><label class="fld">${esc(label)}<input type="text" name="v" value="${esc(value)}" autocomplete="off"></label>${hint ? `<span class="muted">${esc(hint)}</span>` : ""}</div>
        <div class="dfoot"><span class="grow"></span><button type="button" class="btn ghost" data-no>Abbrechen</button><button type="submit" class="btn primary">${esc(okLabel)}</button></div></form>`;
      let done = false;
      $("form", dlg).onsubmit = (e) => { e.preventDefault(); done = true; const v = $("input", dlg).value; dlg.close(); resolve(v); };
      $("[data-no]", dlg).onclick = () => dlg.close();
      dlg.addEventListener("close", () => !done && resolve(null), { once: true });
      dlg.showModal();
    });
  }

  /* ------------------------------------------------------------ LLM-Verbindung */
  const MASK = "••••••••••••••••••••••••";
  function setupPrompt(info, token) {
    const urls = info.mcp_urls.map((u) => `- ${u.label}: ${u.url}`).join("\n");
    const first = (info.mcp_urls[0] || { url: "" }).url;
    return `Richte bitte die Verbindung zur Strelle AV Matrix (Kreuzschiene für NDI-Video und Dante-Audio) ein.

MCP-Server (Streamable HTTP, nur im Studionetz bzw. im Tailnet erreichbar):
${urls}
Nimm die erste Adresse, die von diesem Rechner aus antwortet (Test: POST mit einer initialize-Anfrage oder GET ${first.replace(/mcp$/, "api/info")}).

Zugangsschlüssel (Bearer-Token, nur für schreibende Werkzeuge nötig): ${token}

So richtest du die Verbindung ein:
- Claude Code: claude mcp add --transport http av-matrix ${first} --header "Authorization: Bearer ${token}"
  (mit --scope user, wenn sie in allen Projekten gelten soll). Danach mit "claude mcp list" prüfen.
- Claude Desktop: in claude_desktop_config.json unter "mcpServers" eintragen:
  "av-matrix": {"command": "npx", "args": ["-y", "mcp-remote", "${first}", "--allow-http", "--header", "Authorization: Bearer ${token}"]}
- claude.ai im Browser erreicht den Server nicht (er ist bewusst nicht aus dem Internet erreichbar).

Was du an der Kreuzschiene darfst:
- Jederzeit lesen: list_devices, list_sources, list_destinations, get_routing, list_presets.
- Schalten nur, wenn ich es ausdrücklich verlange: set_route (eine Quelle auf ein Ziel), recall_preset, save_preset, delete_preset, undo.
- Sag vor jedem Schalten in einem Satz, was sich ändert, und lies danach mit get_routing nach.
- Nach einem Versehen sofort undo.

Was du nicht darfst:
- Ziele mit "protected" sind fest gesperrt (serverseitige Sperrliste). Der Server lehnt jede Änderung ab – versuche nicht, das zu umgehen, auch nicht über andere Wege.
- Ziele mit "locked" hat ein Mensch gesperrt: nicht umgehen, sondern mich fragen.
- Den Zugangsschlüssel nicht in Dateien eines Git-Repos, in Logs oder in Antworten ausschreiben.
- Nichts an den Geräten selbst umstellen (Weboberflächen der Decoder, Dante Controller, Pult).

Beschreibung der HTTP-Schnittstelle, falls du sie brauchst: ${first.replace(/mcp$/, "llms.txt")} und ${first.replace(/mcp$/, "openapi.json")}`;
  }

  async function getToken() {
    if (!S.token) S.token = (await api("GET", "/api/token", undefined, { "X-AVM-Panel": "1" })).token;
    return S.token;
  }

  let tokenShown = false;
  async function renderLlm() {
    if (S.tab !== "llm") return;
    const page = $("#page-llm");
    if (!S.info) { page.innerHTML = `<div class="panel">Lade …</div>`; return; }
    const info = S.info;
    const shown = tokenShown && S.token ? S.token : MASK;
    const first = (info.mcp_urls[0] || { url: "" }).url;
    const cmd = (t) => `claude mcp add --transport http av-matrix ${first} --header "Authorization: Bearer ${t}"`;
    const addr = (list, what) => list.map((u) => `<div class="addr"><span class="lbl muted">${esc(u.label)}</span><span class="url">${esc(u.url)}</span>
      <button class="btn sm" data-copy="${esc(u.url)}" data-what="${esc(what)} kopiert">Kopieren</button></div>`).join("");
    page.innerHTML = `
      <div class="panel"><h2>LLM-Verbindung</h2>
        <p class="lead">Über MCP (Model Context Protocol) kann ein Sprachmodell wie Claude die Kreuzschiene lesen und – mit Zugangsschlüssel – schalten. Der Server ist nur im Studionetz und im Tailnet erreichbar.</p>
        <div class="kicker">MCP-Adresse</div>${addr(info.mcp_urls, "MCP-Adresse")}</div>
      <div class="panel"><h3>Zugangsschlüssel</h3>
        <p class="lead" style="margin-top:6px">Nötig für alles, was schaltet oder Presets ändert. Lesen geht im Studionetz ohne Schlüssel.</p>
        <div class="secret"><span class="val" id="tok">${esc(shown)}</span>
          <button class="btn" data-tok-toggle>${tokenShown ? "Verbergen" : "Anzeigen"}</button>
          <button class="btn" data-tok-copy>Kopieren</button>
          <button class="btn danger" data-tok-rotate>Schlüssel erneuern</button></div>
        <p class="note" style="margin:12px 0 0">Nach „Schlüssel erneuern“ gilt der alte Schlüssel sofort nicht mehr; eingerichtete LLM-Verbindungen brauchen dann den neuen.</p></div>
      <div class="panel"><div class="row"><h3 class="grow">Claude Code: fertige Zeile</h3><button class="btn sm primary" data-cmd-copy>Kopieren</button></div>
        <p class="lead" style="margin-top:6px">Im Terminal ausführen. Mit <code>--scope user</code> gilt die Verbindung in allen Projekten.</p>
        <pre class="block">${esc(cmd(shown))}</pre></div>
      <div class="panel"><div class="row"><h3 class="grow">Einrichtungs-Prompt</h3><button class="btn sm primary" data-prompt-copy>Prompt kopieren</button></div>
        <p class="lead" style="margin-top:6px">In Claude einfügen: Das Modell richtet die Verbindung selbst ein und weiß, was es an der Kreuzschiene darf und was nicht. Beim Kopieren ist der echte Schlüssel enthalten.</p>
        <pre class="block">${esc(setupPrompt(info, shown))}</pre></div>
      <div class="panel"><h3>Panel-Adressen</h3>${addr(info.urls, "Adresse")}
        <p class="lead" style="margin:12px 0 0">Maschinenlesbare Beschreibung der HTTP-Schnittstelle: <a href="/llms.txt" target="_blank" rel="noopener">/llms.txt</a> ·
        <a href="/openapi.json" target="_blank" rel="noopener">/openapi.json</a> · Version ${esc(info.version)}</p></div>`;
    page._cmd = cmd;
  }

  /* ------------------------------------------------------------ Live-Vorschau einer NDI-Quelle */
  let liveTimer = null;
  function liveDialog(source, name) {
    const dlg = $("#dlg");
    dlg.onchange = null;
    dlg.classList.add("live");
    const url = () => `/api/preview.mjpeg?source=${encodeURIComponent(source)}&w=640&fps=12.5&t=${Date.now()}`;
    dlg.innerHTML = `<form method="dialog"><div class="dhead"><div class="grow"><div class="kicker">Live-Vorschau · NDI® · niedrige Bandbreite</div><h2>${esc(name)}</h2></div>
        <button type="button" class="btn sm ghost" data-close>Schließen</button></div>
      <div class="dbody"><div class="livebox"><div class="livemsg">Verbinde …</div></div>
        <div class="row"><span class="mono muted grow" data-livestate>${esc(source)}</span><button type="button" class="btn sm" data-retry hidden>Erneut versuchen</button></div></div></form>`;
    const box = $(".livebox", dlg);
    const stateEl = $("[data-livestate]", dlg);
    let missing = 0;
    const show = (msg) => {
      box.innerHTML = `<div class="livemsg">${esc(msg)}</div>`; // kein eingefrorenes Bild stehen lassen
      $("[data-retry]", dlg).hidden = false;
    };
    const start = () => {
      missing = 0;
      $("[data-retry]", dlg).hidden = true;
      box.innerHTML = `<div class="livemsg">Verbinde …</div><img alt="Live-Vorschau ${esc(name)}"><span class="livetag">LIVE</span>`;
      const img = $("img", box);
      img.onerror = () => show("Kein Signal");
      img.src = url();
    };
    const stop = () => {
      clearInterval(liveTimer);
      const img = $("img", box);
      if (img) img.src = ""; // Stream beenden → der Server schließt den Empfänger nach wenigen Sekunden
      box.innerHTML = "";
      dlg.classList.remove("live");
      if (window.AvMatrixPreview) window.AvMatrixPreview.paused = false;
    };
    clearInterval(liveTimer);
    liveTimer = setInterval(async () => {
      if (!$("img", box)) return;
      try {
        const st = await api("GET", `/api/preview?source=${encodeURIComponent(source)}`);
        const rx = st.live.find((l) => l.source === source);
        if (st.source.state !== "ok") return show(st.source.state === "offline" ? "Quelle ist offline" : "Kein Signal");
        if (!rx && st.hx_decoder === false && missing >= 1) return show("Kein Bild – NDI|HX-Quelle? Der Decoder fehlt auf dem Server");
        missing = rx ? 0 : missing + 1;
        if (missing >= 3) return show("Vorschau beendet");
        if (rx) stateEl.textContent = `${source} · ${rx.frames} Bilder · ${Math.round(rx.seconds)} s`;
      } catch (_e) { show("Keine Verbindung zum Server"); }
    }, 2000);
    dlg.onclick = (e) => {
      if (e.target.closest("[data-close]")) dlg.close();
      else if (e.target.closest("[data-retry]")) start();
    };
    dlg.addEventListener("close", stop, { once: true });
    if (window.AvMatrixPreview) window.AvMatrixPreview.paused = true;
    start();
    dlg.showModal();
  }
  window.addEventListener("avm-preview-open", (e) => liveDialog(e.detail.source, e.detail.name));

  /* ------------------------------------------------------------ Klicks */
  document.addEventListener("click", async (e) => {
    const t = e.target.closest("button, a");
    if (!t || t.closest("#dlg") || t.closest("av-matrix-card") || t.closest("[data-own]")) return;
    const d = t.dataset;
    try {
      if (d.recall) return recall(d.recall);
      if (d.undoLast !== undefined) return undoLast();
      if (d.goto) return showTab(d.goto);
      if (d.presetNew !== undefined) return presetDialog(null);
      if (d.presetEdit) return presetDialog(S.snap.presets.find((p) => p.id === d.presetEdit));
      if (d.presetDel) {
        const p = S.snap.presets.find((x) => x.id === d.presetDel);
        if (await confirmDialog("Preset löschen?", `„${p.name}“ wird gelöscht. Geschaltet wird dabei nichts.`, "Löschen")) {
          await api("DELETE", `/api/presets/${encodeURIComponent(p.id)}`); toast("Preset gelöscht", "ok");
        }
        return;
      }
      if (d.copy) return copy(d.copy, d.what);
      if (d.add !== undefined) { showTab("matrix"); return setTimeout(() => card._openFlow && card._openFlow(null), 60); }
      if (d.refresh !== undefined) { await api("POST", "/api/refresh"); toast("Quellen werden neu eingelesen", "ok"); return setTimeout(loadDevices, 1500); }
      if (d.rename) {
        const v = await textDialog("Gerät umbenennen", "Anzeigename", d.name, "Speichern", "Leer = Name des Geräts verwenden.");
        if (v !== null) { await api("PATCH", `/api/devices/${encodeURIComponent(d.rename)}`, { title: v.trim() }); loadDevices(); }
        return;
      }
      if (d.static) {
        const v = await textDialog("Feste Dante-Adressen", "IP-Adressen, durch Komma getrennt", d.hosts, "Speichern", "Nur nötig, wenn ein Dante-Gerät per mDNS nicht gefunden wird.");
        if (v !== null) { await api("PATCH", `/api/devices/${encodeURIComponent(d.static)}`, { static_hosts: v }); setTimeout(loadDevices, 800); }
        return;
      }
      if (d.remove) {
        if (await confirmDialog("Gerät entfernen?", `„${d.name}“ wird aus der Kreuzschiene entfernt. Am Gerät selbst ändert sich nichts.`, "Entfernen")) {
          await api("DELETE", `/api/devices/${encodeURIComponent(d.remove)}`); toast("Gerät entfernt", "ok"); loadDevices();
        }
        return;
      }
      if (d.tokToggle !== undefined) { if (!tokenShown) await getToken(); tokenShown = !tokenShown; return renderLlm(); }
      if (d.tokCopy !== undefined) return copy(await getToken(), "Zugangsschlüssel kopiert");
      if (d.cmdCopy !== undefined) return copy($("#page-llm")._cmd(await getToken()), "Zeile kopiert");
      if (d.promptCopy !== undefined) return copy(setupPrompt(S.info, await getToken()), "Prompt kopiert");
      if (d.tokRotate !== undefined) {
        if (await confirmDialog("Schlüssel erneuern?", "Der bisherige Zugangsschlüssel gilt sofort nicht mehr. Eingerichtete LLM-Verbindungen müssen den neuen bekommen.", "Erneuern")) {
          S.token = (await api("POST", "/api/token/rotate", undefined, { "X-AVM-Panel": "1" })).token;
          tokenShown = true; renderLlm(); toast("Neuer Zugangsschlüssel erzeugt", "ok");
        }
      }
    } catch (err) { toast(err.message || String(err), "err"); }
  });

  /* ------------------------------------------------------------ Schnittstelle für extras.js / mobile.js */
  const hooks = { snap: [], tab: [], info: [] };
  window.AVM = { $, $$, esc, api, toast, copy, S, conn, showTab, liveDialog, confirmDialog, recall, undoLast, hooks,
    theme: () => theme, setTheme: (t) => { theme = t; store.set("avm:theme", t); applyTheme(); }, store };

  /* ------------------------------------------------------------ Start */
  async function loadInfo() {
    try {
      S.info = await api("GET", "/api/info");
      $("#app-name").textContent = S.info.name;
      document.title = S.info.name;
      $("#app-sub").textContent = `${S.info.mdns_name}:${S.info.port}`;
      $("#app-sub").title = "Adresse dieses Panels";
      applyTheme(); renderLlm();
      hooks.info.forEach((fn) => fn(S.info));
    } catch (_e) { setTimeout(loadInfo, 3000); }
  }

  conn.subscribeMessage((snap) => {
    S.snap = snap;
    hooks.snap.forEach((fn) => fn(snap));
    renderPresetBar();
    if (!$("#dlg").open) renderPresets();
    if (S.tab === "devices") { clearTimeout(devTimer); devTimer = setTimeout(loadDevices, 400); }
  }, { type: "av_matrix/subscribe" }).catch(() => {});

  applyTheme();
  loadInfo();
  showTab(location.hash.slice(1) || "matrix", false);
})();
