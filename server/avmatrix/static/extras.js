/* Strelle AV Matrix – Systemauslastung (Anzeige + Seite), QR-Code zum Verbinden, Testbild-Quelle. */
(() => {
  "use strict";
  const { $, esc, api, toast, copy, S, hooks, showTab, store } = window.AVM;
  const fmt = (v, unit = "", digits = 0) => (v == null ? "–" : `${Number(v).toFixed(digits).replace(".", ",")}${unit}`);
  const dur = (s) => {
    if (s == null) return "–";
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? `${d} T ${h} h` : h ? `${h} h ${m} min` : m ? `${m} min` : `${Math.round(s)} s`;
  };
  const clock = (iso) => { try { return new Date(iso).toLocaleTimeString("de-AT"); } catch (_e) { return ""; } };
  const ORIGIN = { panel: "Panel", companion: "Companion", http: "HTTP", mcp: "MCP", preset: "Preset", salvo: "Salve", undo: "Rückgängig", api: "API", extern: "Extern" };
  const WARN_ICON = `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"><path d="M12 3 2.5 20h19zM12 10v4.5M12 17.6v.2"/></svg>`;

  /* ---------------------------------------------------------------- Anzeige in der Kopfzeile */
  const chips = () => document.querySelectorAll("[data-sys-chip], #sys-chip");
  function renderChip(sum) {
    const warn = sum.warnings && sum.warnings.length ? sum.warnings[0].text : "";
    const bar = (v, max = 100) => `<i class="mb"><b style="width:${Math.max(4, Math.min(100, ((v || 0) / max) * 100))}%"></b></i>`;
    const html = warn
      ? `<span class="syswarn">${WARN_ICON}<span>Warnung: ${esc(warn)}</span></span>`
      : `<span class="sv" title="CPU-Auslastung"><em>CPU</em> ${bar(sum.cpu_percent)}<b>${fmt(sum.cpu_percent, " %")}</b></span>
         <span class="sv" title="Arbeitsspeicher belegt"><em>RAM</em> ${bar(sum.memory_percent)}<b>${fmt(sum.memory_percent, " %")}</b></span>
         <span class="sv" title="CPU-Temperatur"><b>${fmt(sum.temperature_c, " °C")}</b></span>`;
    chips().forEach((el) => { el.hidden = false; el.classList.toggle("warn", !!warn); el.innerHTML = html; el.setAttribute("aria-label", warn ? `Warnung: ${warn}` : "Systemauslastung"); });
  }
  async function pollChip() {
    if (document.visibilityState !== "visible" || sysVisible()) return;
    try { renderChip(await api("GET", "/api/system?summary=1")); } catch (_e) { /* Verbindung weg: LED zeigt es */ }
  }
  setInterval(pollChip, 5000);
  setTimeout(pollChip, 800);
  document.addEventListener("click", (e) => { if (e.target.closest("[data-goto-system]")) window.AVM.openSystem(); });

  /* ---------------------------------------------------------------- Seite „System" */
  let sysTarget = null;
  let sysTimer = null;
  const sysVisible = () => !!(sysTarget && sysTarget.isConnected && sysTarget.offsetParent !== null);
  const meter = (label, pct, text, cls = "") => `<div class="meter ${cls}"><span class="ml">${esc(label)}</span><span class="mt"><b style="width:${Math.max(0, Math.min(100, pct || 0))}%"></b></span><span class="mv mono">${esc(text)}</span></div>`;
  function spark(history, key, max) {
    const pts = history.filter((h) => h[key] != null);
    if (pts.length < 2) return `<svg class="spark" viewBox="0 0 300 48" preserveAspectRatio="none"></svg>`;
    const t0 = pts[0].t, span = Math.max(1, pts[pts.length - 1].t - t0);
    const top = max || Math.max(10, ...pts.map((p) => p[key]));
    const d = pts.map((p, i) => `${i ? "L" : "M"}${(((p.t - t0) / span) * 300).toFixed(1)},${(46 - (Math.min(p[key], top) / top) * 44).toFixed(1)}`).join("");
    return `<svg class="spark" viewBox="0 0 300 48" preserveAspectRatio="none" aria-hidden="true"><path d="${d}"/></svg>`;
  }
  function renderSystem(d) {
    const h = d.host, m = h.memory, p = d.processes, a = d.activity;
    const span = d.history.length > 1 ? dur(d.history[d.history.length - 1].t - d.history[0].t) : "";
    renderChip({ cpu_percent: h.cpu_percent, memory_percent: m.percent, temperature_c: h.temperature_c, warnings: d.warnings });
    sysTarget.innerHTML = `
      ${d.warnings.length ? `<div class="panel warnbox" role="alert">${WARN_ICON}<div><b>Warnung</b>${d.warnings.map((w) => `<div>${esc(w.text)}</div>`).join("")}</div></div>` : ""}
      <div class="sysgrid">
        <div class="panel"><h3>Rechner</h3>
          ${meter("CPU gesamt", h.cpu_percent, fmt(h.cpu_percent, " %", 1))}
          <div class="cores">${h.cores_percent.map((c, i) => meter(`Kern ${i + 1}`, c, fmt(c, " %"), "sm")).join("")}</div>
          ${meter("RAM", m.percent, `${m.used_mb} / ${m.total_mb} MB · frei ${m.free_mb} MB`)}
          ${meter("Speicherplatz", h.disk.percent, `${fmt(h.disk.total_gb - h.disk.free_gb, "", 1)} / ${fmt(h.disk.total_gb, " GB", 1)} · frei ${fmt(h.disk.free_gb, " GB", 1)}`)}
          <dl class="kv">
            <dt>Load (1/5/15 min)</dt><dd class="mono">${h.load.map((l) => fmt(l, "", 2)).join(" · ")} bei ${h.cores} Kernen</dd>
            <dt>Temperatur</dt><dd class="mono">${fmt(h.temperature_c, " °C", 1)}</dd>
            <dt>Takt</dt><dd class="mono">${h.cpu_mhz ? `${h.cpu_mhz} von ${h.cpu_max_mhz} MHz` : "–"}</dd>
            <dt>Unterspannung</dt><dd>${h.undervoltage == null ? "nicht lesbar" : h.undervoltage ? "ja – Netzteil prüfen" : "nein"}</dd>
            <dt>Drosselung</dt><dd>${h.throttled == null ? "Firmware-Status ohne Root nicht lesbar (Takt und Temperatur siehe oben)" : h.throttled ? "ja" : "nein"}</dd>
            <dt>Netzwerk</dt><dd class="mono">↓ ${fmt(h.network.rx_kbit, " kbit/s")} · ↑ ${fmt(h.network.tx_kbit, " kbit/s")}</dd>
            <dt>Rechner läuft seit</dt><dd>${dur(h.uptime_s)}</dd>
          </dl></div>
        <div class="panel"><h3>Wer erzeugt die Last?</h3>
          <p class="lead" style="margin-top:6px">CPU in Prozent eines Kerns (${h.cores} Kerne = ${h.cores * 100} %).</p>
          ${meter("Matrix-Dienst", p.matrix.cpu_percent / h.cores, `${fmt(p.matrix.cpu_percent, " %", 1)} · ${p.matrix.rss_mb} MB`)}
          ${meter("Companion", p.companion.cpu_percent / h.cores, p.companion.processes ? `${fmt(p.companion.cpu_percent, " %", 1)} · ${p.companion.rss_mb} MB` : "läuft nicht")}
          <dl class="kv"><dt>Matrix-Dienst</dt><dd>läuft seit ${dur(p.matrix.uptime_s)} · ${p.matrix.threads} Threads</dd>
            <dt>Companion</dt><dd>${p.companion.processes} Prozesse (Hauptprozess, Module, Oberflächen)</dd></dl>
          <h3 style="margin-top:14px">Verlauf ${span ? `<span class="muted" style="font-weight:500">· ${span}</span>` : ""}</h3>
          <div class="sparks"><div><span class="kicker">CPU gesamt</span>${spark(d.history, "cpu", 100)}</div>
            <div><span class="kicker">Matrix-Dienst</span>${spark(d.history, "matrix")}</div>
            <div><span class="kicker">Companion</span>${spark(d.history, "companion")}</div>
            <div><span class="kicker">Temperatur</span>${spark(d.history, "temp", 90)}</div></div></div>
        <div class="panel"><h3>Was der Server gerade tut</h3>
          <dl class="kv">
            <dt>NDI-Empfänger</dt><dd>${a.ndi_receivers.length ? a.ndi_receivers.map((r) => `<div><b>${esc(r.source)}</b><br><span class="mono muted">Live · niedrigste Bandbreite · ${fmt(r.fps, " B/s", 1)} · seit ${dur(r.seconds)} · ${r.viewers} Zuschauer</span></div>`).join("") : a.preview_available === false ? "Vorschau nicht verfügbar" : `keiner offen${a.ndi_receivers_open ? ` (${a.ndi_receivers_open} Standbild läuft)` : ""}`}
              <div class="muted">${a.ndi_stills_total} Empfänger seit dem Start geöffnet und wieder geschlossen</div></dd>
            <dt>Testbild</dt><dd>${a.testpattern.enabled ? (a.testpattern.running ? (a.testpattern.connections ? `sendet an ${a.testpattern.connections} Empfänger` : "bereit, kein Empfänger verbunden") : "eingeschaltet, sendet nicht") : "aus"}</dd>
            <dt>Verbundene Clients</dt><dd>${a.clients.panels} Panel · ${a.clients.event_streams} Ereignis-Stream (Companion) · MCP: ${a.clients.mcp_calls} Aufrufe${a.clients.mcp_last_s != null ? `, zuletzt vor ${dur(a.clients.mcp_last_s)}` : ""}</dd>
          </dl>
          <h3 style="margin-top:14px">Geräteverbindungen</h3>
          ${a.devices.map((x) => `<div class="row" style="padding:5px 0"><span class="dot ${x.online ? "ok" : "err"}"></span><b>${esc(x.name)}</b><span class="muted grow">${esc(x.online ? x.detail || "erreichbar" : x.error || "offline")}</span><span class="mono muted">${x.last_poll_s == null ? "" : `vor ${fmt(x.last_poll_s, " s", 0)}`}</span></div>`).join("") || `<span class="muted">Keine Geräte eingerichtet.</span>`}</div>
        <div class="panel"><h3>Letzte Schaltvorgänge</h3>
          ${a.routes.map((r) => `<div class="logrow"><span class="mono muted">${clock(r.time)}</span><span class="chip">${esc(ORIGIN[r.origin] || r.origin)}</span><span class="ell"><b>${esc(r.destination)}</b> ← ${esc(r.source ?? "Aus")}</span></div>`).join("") || `<span class="muted">Seit dem Start wurde nichts geschaltet.</span>`}
          <h3 style="margin-top:14px">Letzte Fehler</h3>
          ${a.errors.map((r) => `<div class="logrow"><span class="mono muted">${clock(r.time)}</span><span class="chip">${esc(r.where)}</span><span>${esc(r.message)}</span></div>`).join("") || `<span class="muted">Keine Warnungen oder Fehler.</span>`}</div>
      </div>
      <p class="muted" style="margin:0">Gemessen wird nur, solange jemand zuschaut (jetzt alle ${fmt(d.monitor.interval_s, " s")}; eine Messung kostet ${fmt(d.monitor.sample_cost_ms, " ms", 1)}).</p>`;
  }
  async function pollSystem() {
    if (!sysVisible() || document.visibilityState !== "visible") return;
    try { renderSystem(await api("GET", "/api/system")); } catch (err) { sysTarget.innerHTML = `<div class="panel">Keine Verbindung zum Server.</div>`; }
  }
  window.AVM.mountSystem = (el) => {
    sysTarget = el;
    if (!el.innerHTML) el.innerHTML = `<div class="panel">Lade …</div>`;
    clearInterval(sysTimer);
    sysTimer = setInterval(pollSystem, 2000);
    pollSystem();
  };
  window.AVM.openSystem = () => showTab("system");
  hooks.tab.push((tab) => { if (tab === "system") window.AVM.mountSystem($("#page-system")); });

  /* ---------------------------------------------------------------- QR-Code zum Verbinden (nur große Bildschirme) */
  const qrBtn = $("#qr-btn"), qrPop = $("#qr-pop");
  let qrKind = store.get("avm:qr", "");
  function renderQr() {
    const list = (S.info && S.info.connect) || [];
    if (!list.length) { qrPop.innerHTML = `<p class="muted">Keine Adresse gefunden.</p>`; return; }
    const cur = list.find((c) => c.kind === qrKind) || list[0];
    const kinds = list.filter((c) => c.kind === "lan_ip" || c.kind === "tailscale_name" || (c.kind === "tailscale_ip" && !list.some((x) => x.kind === "tailscale_name")));
    qrPop.innerHTML = `<div class="kicker">Am Telefon öffnen</div>
      <img class="qr" src="/api/qr.svg?target=${encodeURIComponent(cur.kind)}" alt="QR-Code für ${esc(cur.url)}" width="264" height="264">
      <div class="qrurl mono">${esc(cur.url.replace(/^http:\/\//, "").replace(/\/$/, ""))}</div>
      ${kinds.length > 1 ? `<div class="seg" role="group" aria-label="Netz">${kinds.map((c) => `<button data-qr="${esc(c.kind)}" aria-pressed="${c.kind === cur.kind}">${c.kind === "lan_ip" ? "Studionetz" : "Tailscale (unterwegs)"}</button>`).join("")}</div>` : ""}
      <p class="muted">${cur.kind === "lan_ip" ? "Das Telefon muss im Studio-WLAN sein." : "Das Telefon braucht die Tailscale-App und muss im Tailnet angemeldet sein."}</p>
      <button class="btn sm ghost" data-qr-copy="${esc(cur.url)}">Adresse kopieren</button>`;
  }
  const toggleQr = (open) => { qrPop.hidden = !open; qrBtn.setAttribute("aria-expanded", String(open)); if (open) renderQr(); };
  qrBtn.addEventListener("click", () => toggleQr(qrPop.hidden));
  qrPop.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.qr) { qrKind = b.dataset.qr; store.set("avm:qr", qrKind); renderQr(); }
    else if (b.dataset.qrCopy) copy(b.dataset.qrCopy, "Adresse kopiert");
  });
  document.addEventListener("click", (e) => { if (!qrPop.hidden && !e.target.closest(".qrwrap")) toggleQr(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleQr(false); });

  /* ---------------------------------------------------------------- Testbild-Quelle (Seite Geräte) */
  async function renderPattern(change) {
    const el = $("#pattern-panel");
    if (!el) return;
    let st;
    try { st = change === undefined ? await api("GET", "/api/testpattern") : await api("POST", "/api/testpattern", { enabled: change }); }
    catch (err) { toast(err.message, "err"); return; }
    const state = !st.available ? "NDI SDK nicht installiert – die Quelle kann nicht senden" : !st.enabled ? "aus" : st.connections ? `sendet an ${st.connections} Empfänger` : "bereit – sendet, sobald ein Empfänger verbunden ist";
    el.dataset.own = "";
    el.innerHTML = `<div class="row"><div class="grow"><h3>Testbild-Quelle</h3>
        <p class="lead" style="margin:6px 0 0">Eigene NDI®-Quelle <b>${esc(st.source)}</b> mit Logo, Testbild, Uhr und dem QR-Code zum Verbinden – auf einen Decoder legen, damit sie auf einem Studiobildschirm steht. Gesendet wird nur, solange ein Empfänger verbunden ist (1 Bild je Sekunde).</p>
        <p style="margin:8px 0 0"><span class="chip ${st.enabled && st.available ? "ok" : ""}">${esc(state)}</span></p></div>
      <a href="/api/testpattern.jpg" target="_blank" rel="noopener" title="Testbild in voller Größe"><img class="patimg" src="/api/testpattern.jpg?t=${Date.now()}" alt="Vorschau des Testbilds" width="240" height="135"></a>
      <button class="btn ${st.enabled ? "" : "primary"}" data-pattern="${st.enabled ? "off" : "on"}" role="switch" aria-checked="${st.enabled}">${st.enabled ? "Ausschalten" : "Einschalten"}</button></div>`;
  }
  hooks.tab.push((tab) => { if (tab === "devices-rendered") { renderPattern(); renderSources(); } });

  /* ---------------------------------------------------------------- NDI-Quellen: Gerätetyp und Symbol von Hand */
  const TYPES = [["auto", "Automatisch"], ["camera", "Kamera"], ["computer", "Rechner"], ["encoder", "Encoder / Wandler"], ["testpattern", "Testbild"], ["unknown", "NDI-Quelle (neutral)"]];
  const TYPE_NAME = Object.fromEntries(TYPES);
  function renderSources() {
    const panel = $("#pattern-panel");
    if (!panel) return;
    let el = $("#sources-panel");
    if (!el) { el = document.createElement("div"); el.className = "panel"; el.id = "sources-panel"; el.dataset.own = ""; panel.after(el); }
    const list = (S.snap && S.snap.protocols.ndi ? S.snap.protocols.ndi.sources : []).filter((x) => x.device_type);
    el.innerHTML = `<h3>NDI®-Quellen</h3>
      <p class="lead" style="margin-top:6px">Das Symbol richtet sich nach dem Gerätetyp. Er wird am Namen bzw. an der Weboberfläche des Geräts erkannt; ist nichts sicher erkennbar, bleibt es beim neutralen Symbol. Hier lässt er sich von Hand festlegen – das hat Vorrang und bleibt gespeichert.</p>
      ${list.map((x) => `<div class="srow"><img src="/static/devices/${esc(x.icon_key)}.svg" alt="" width="60" height="40">
        <span class="sn"><b>${esc(x.name)}</b><span class="mono muted">${esc(x.id)}${x.live ? "" : ` · offline, zuletzt gesehen ${x.last_seen ? new Date(x.last_seen).toLocaleTimeString("de-AT") : "nie"}`}</span>
          ${x.live ? "" : `<button class="btn sm ghost" data-forget="${esc(x.id)}" style="align-self:flex-start;margin-top:4px">Vergessen</button>`}</span>
        <span class="mono muted">${x.web_url ? `<a href="${esc(x.web_url)}" target="_blank" rel="noopener" title="Weboberfläche öffnen">${esc(x.host)}</a>` : esc(x.host || "")}</span>
        <select data-srctype="${esc(x.id)}" aria-label="Gerätetyp von ${esc(x.name)}">${TYPES.map(([v, l]) => `<option value="${v}" ${(x.device_type_manual ? x.device_type : "auto") === v ? "selected" : ""}>${v === "auto" ? `Automatisch (${TYPE_NAME[x.device_type_auto] || x.device_type_auto})` : l}</option>`).join("")}</select></div>`).join("") || `<span class="muted">Noch keine NDI-Quellen im Netz gefunden.</span>`}`;
  }
  hooks.snap.push(() => { if (S.tab === "devices" && document.activeElement && document.activeElement.tagName !== "SELECT") renderSources(); });
  document.addEventListener("click", async (e) => {
    const b = e.target.closest && e.target.closest("[data-forget]");
    if (!b) return;
    try { await api("POST", "/api/source/forget", { protocol: "ndi", source: b.dataset.forget }); toast("Quelle vergessen", "ok"); }
    catch (err) { toast(err.message, "err"); }
  });
  document.addEventListener("change", async (e) => {
    const sel = e.target.closest && e.target.closest("[data-srctype]");
    if (!sel) return;
    try { await api("POST", "/api/label", { protocol: "ndi", source: sel.dataset.srctype, type: sel.value }); toast("Gerätetyp gespeichert", "ok"); sel.blur(); }
    catch (err) { toast(err.message, "err"); }
  });
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-pattern]"); if (b) renderPattern(b.dataset.pattern === "on"); });
})();
