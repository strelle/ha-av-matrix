/* Strelle AV Matrix – Mobilansicht: eigene, einhändig bedienbare Oberfläche fürs Telefon.
 * Ziel wählen → Quelle wählen (mit Vorschaubild) → geschaltet. Presets, Rückgängig und System in der Leiste unten.
 * Erkennung über Bildschirmbreite und Zeigerart; über das Menü bzw. den Knopf unten umschaltbar. */
(() => {
  "use strict";
  const { $, $$, esc, api, toast, S, hooks, liveDialog, store, recall, undoLast } = window.AVM;
  const root = $("#mobile");
  const mq = window.matchMedia("(max-width: 700px), (pointer: coarse) and (max-width: 900px)");
  const M = { on: false, view: "route", proto: store.get("avm:m-proto", "ndi"), dest: null, open: new Set(), busy: null, html: "", menu: false };
  const pv = new Map(); // Quelle → { url, state, at, busy, tried }
  const TXT = { loading: "Lade …", unsupported_codec: "Vorschau nicht möglich", offline: "Offline", no_signal: "Kein Signal", stale: "Keine Aktualisierung", unknown_source: "Unbekannt" };
  let pvAvailable = null;
  let visible = new Set();
  const io = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
    for (const e of entries) { if (e.isIntersecting) visible.add(e.target.dataset.pv); else visible.delete(e.target.dataset.pv); }
  }, { rootMargin: "80px" }) : null;

  const wanted = () => { const pref = store.get("avm:view", "auto"); return pref === "mobile" || (pref === "auto" && mq.matches); };
  function apply() {
    M.on = wanted();
    document.body.classList.toggle("mobile-on", M.on);
    root.hidden = !M.on;
    if (M.on) render(true);
    else { root.innerHTML = ""; M.html = ""; }
  }
  mq.addEventListener("change", apply);
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (!b) return;
    store.set("avm:view", b.dataset.view === "mobile" ? (mq.matches ? "auto" : "mobile") : mq.matches ? "desktop" : "auto");
    M.menu = false;
    apply();
    window.scrollTo(0, 0);
  });

  const protos = () => Object.keys((S.snap && S.snap.protocols) || {});
  const proto = () => { const p = (S.snap && S.snap.protocols) || {}; return p[M.proto] || p[protos()[0]] || { sources: [], destinations: [] }; };
  const dests = () => proto().destinations;
  const sel = () => dests().find((d) => d.id === M.dest) || null;
  const STATUS = { connected: "verbunden", connecting: "verbindet …", no_source: "keine Quelle", source_lost: "Quelle fehlt", offline: "offline", error: "Fehler" };
  const srcName = (id) => { if (!id) return "Aus"; const s = proto().sources.find((x) => x.id === id); return s ? s.name : id; };
  const short = (name) => { const m = /\(([^)]+)\)\s*$/.exec(name); return m ? m[1] : name; };
  const groupBy = (list, key) => { const m = new Map(); for (const x of list) { const g = x[key] || ""; if (!m.has(g)) m.set(g, []); m.get(g).push(x); } return [...m]; };

  function pvBlock(s) {
    if (M.proto !== "ndi" || pvAvailable === false) return "";
    const it = pv.get(s.id) || { state: "loading" };
    let state = s.live ? it.state : "offline";
    if (state === "ok" && Date.now() - it.at > (it.slow ? 60000 : 16000)) state = "stale";
    const img = state === "ok" && it.url ? `<img alt="" src="${esc(it.url)}">${it.origin === "device" ? `<span class="pvtag">vom Gerät</span>` : ""}` : `<span class="pvmsg">${TXT[state] || TXT.no_signal}</span>`;
    return `<span class="m-pv st-${state}" data-pv="${esc(s.id)}">${img}</span>`;
  }

  function viewRoute() {
    const d = sel();
    const list = dests();
    const grouped = list.some((x) => x.group);
    const destRow = (x) => `<button class="m-dest ${x.id === M.dest ? "sel" : ""} st-${x.status}" data-mdest="${esc(x.id)}" aria-pressed="${x.id === M.dest}">
        <i class="dot ${x.status === "connected" ? "ok" : x.status === "offline" || x.status === "error" ? "err" : x.status === "no_source" ? "" : "cue"}"></i>
        <span class="m-dn"><b>${esc(grouped ? x.label || x.channel || x.name : x.name)}</b><span class="mono">${esc(x.current_source ? short(srcName(x.current_source)) : "keine Quelle")} · ${STATUS[x.status] || x.status}</span></span>
        ${x.locked ? `<span class="chip">${x.protected ? "fest gesperrt" : "gesperrt"}</span>` : ""}</button>`;
    const destHtml = grouped
      ? groupBy(list, "group").map(([g, items]) => { const open = M.open.has("d:" + g) || items.some((x) => x.id === M.dest);
          return `<details class="m-group" data-mgroup="d:${esc(g)}" ${open ? "open" : ""}><summary>${esc(g)}<span class="chip">${items.length}</span></summary>${open ? items.map(destRow).join("") : ""}</details>`; }).join("")
      : list.map(destRow).join("");
    let srcHtml = `<p class="m-hint">Oben ein Ziel antippen.</p>`;
    if (d) {
      const blocked = d.locked || d.available === false;
      const tile = (s) => { const id = s ? s.id : ""; const pgm = (d.current_source || "") === id; const pend = M.busy === d.id + "|" + id;
        return `<div class="m-src ${pgm ? "pgm" : ""} ${s && !s.live ? "dead" : ""} ${pend ? "pend" : ""}">
          <button class="m-srcmain" data-msrc="${esc(id)}" ${blocked ? "disabled" : ""} aria-pressed="${pgm}">
            ${s ? pvBlock(s) : M.proto === "ndi" && pvAvailable !== false ? `<span class="m-pv st-off"><span class="pvmsg">Aus</span></span>` : ""}
            <b>${esc(s ? (grouped ? s.channel || s.name : short(s.name)) : "Aus")}</b>
            ${s && s.icon_key && !grouped ? `<img class="m-art" src="/static/devices/${esc(s.icon_key)}.svg" alt="">` : ""}
            <span class="mono">${pgm ? "AUF SENDUNG" : pend ? "schaltet …" : s ? (s.live ? esc(s.label ? s.id : (s.group || (s.name.split(" (")[0]))) : "offline") : "keine Quelle"}</span></button>
          ${s && s.live && M.proto === "ndi" && pvAvailable !== false ? `<button class="m-live" data-mlive="${esc(id)}" aria-label="Live-Vorschau ${esc(s.name)}"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 4h5v5M9 20H4v-5M20 4l-6.5 6.5M4 20l6.5-6.5"/></svg></button>` : ""}</div>`; };
      const srcs = proto().sources;
      const body = srcs.some((s) => s.group)
        ? `<div class="m-srcs">${tile(null)}</div>` + groupBy(srcs, "group").map(([g, items]) => { const open = M.open.has("s:" + g) || items.some((s) => s.id === d.current_source);
            return `<details class="m-group" data-mgroup="s:${esc(g)}" ${open ? "open" : ""}><summary>${esc(g)}<span class="chip">${items.length}</span></summary>${open ? `<div class="m-srcs">${items.map(tile).join("")}</div>` : ""}</details>`; }).join("")
        : `<div class="m-srcs">${[null, ...srcs].map(tile).join("")}</div>`;
      srcHtml = `<div class="m-tools"><button class="btn" data-mundo ${d.can_undo && !d.locked ? "" : "disabled"}>Vorherige Quelle</button>
          <button class="btn" data-mlock ${d.protected ? "disabled" : ""}>${d.protected ? "Fest gesperrt" : d.locked ? "Entsperren" : "Sperren"}</button></div>
        ${d.protected ? `<p class="m-hint">${esc(d.protected)}</p>` : d.locked ? `<p class="m-hint">Dieses Ziel ist gesperrt – erst entsperren.</p>` : d.available === false ? `<p class="m-hint">Das Gerät ist offline.</p>` : ""}${body}`;
    }
    return `${protos().length > 1 ? `<div class="seg m-proto" role="group" aria-label="Protokoll">${protos().map((k) => `<button data-mproto="${esc(k)}" aria-pressed="${k === M.proto}">${esc(S.snap.protocols[k].title || k)}</button>`).join("")}</div>` : ""}
      <section><h2><span class="m-step">1</span>Ziel</h2><div class="m-dests">${destHtml || `<p class="m-hint">Noch keine Ziele eingerichtet.</p>`}</div></section>
      <section id="m-sources"><h2><span class="m-step">2</span>Quelle${d ? ` für ${esc(d.name)}` : ""}</h2>${srcHtml}</section>`;
  }

  function viewPresets() {
    const presets = (S.snap && S.snap.presets) || [];
    return `<section><h2>Presets</h2>${presets.map((p) => `<button class="m-preset ${p.active ? "active" : ""} ${M.busy === "p|" + p.id ? "pend" : ""}" data-mpreset="${esc(p.id)}" aria-pressed="${p.active}">
        <b>${esc(p.name)}</b><span class="mono">${p.active ? "AKTIV" : `${p.routes.length} Verbindung${p.routes.length === 1 ? "" : "en"}`} · ${p.routes.map((r) => esc(r.destination_name)).join(", ")}</span></button>`).join("") || `<p class="m-hint">Noch keine Presets. Anlegen und ändern geht in der Desktop-Ansicht.</p>`}</section>`;
  }

  function render(force) {
    if (!M.on) return;
    if (M.view === "system") {
      if (M.html !== "system") { root.innerHTML = shell(`<div id="m-system" class="page"></div>`); M.html = "system"; window.AVM.mountSystem($("#m-system")); }
      return;
    }
    const html = shell(M.view === "presets" ? viewPresets() : viewRoute());
    if (!force && html === M.html) return;
    M.html = html;
    root.innerHTML = html;
    if (io) { io.disconnect(); visible = new Set(); $$("[data-pv]", root).forEach((el) => io.observe(el)); }
  }

  function shell(body) {
    const light = document.documentElement.dataset.theme === "daylight";
    return `<header class="m-top"><button class="sys" data-sys-chip data-mview="system" aria-label="Systemauslastung" hidden></button>
        <div class="m-brand"><img src="/static/brand/strelle-icon.svg" alt="" width="28" height="28"><b>${esc((S.info && S.info.name) || "Strelle AV Matrix")}</b></div>
        <button class="m-menu" data-mmenu aria-expanded="${M.menu}" aria-label="Menü"><svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg></button>
        ${M.menu ? `<div class="m-menupop"><button class="btn" data-view="desktop">Desktop-Ansicht</button>
          <button class="btn" data-mtheme>${light ? "Dunkel" : "Tageslicht"}</button><button class="btn" data-mview="system">System</button></div>` : ""}</header>
      <main class="m-main">${body}</main>
      <nav class="m-bar" aria-label="Bereiche"><button data-mview="route" aria-pressed="${M.view === "route"}">Schalten</button>
        <button data-mview="presets" aria-pressed="${M.view === "presets"}">Presets</button>
        <button data-mundolast ${S.snap && S.snap.can_undo ? "" : "disabled"}>Rückgängig</button>
        <button data-mview="system" aria-pressed="${M.view === "system"}">System</button></nav>`;
  }

  async function act(key, fn, okText) {
    M.busy = key; render();
    try { await fn(); if (okText) toast(okText, "ok"); } catch (err) { toast(err.message || String(err), "err"); }
    M.busy = null; render();
  }

  root.addEventListener("toggle", (e) => {
    const g = e.target.dataset && e.target.dataset.mgroup;
    if (!g) return;
    if (e.target.open) M.open.add(g); else M.open.delete(g);
    render();
  }, true);

  root.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const d = b.dataset;
    if (d.mmenu !== undefined) { M.menu = !M.menu; M.html = ""; return render(true); }
    if (d.mtheme !== undefined) { window.AVM.setTheme(document.documentElement.dataset.theme === "daylight" ? "dark" : "daylight"); M.menu = false; return render(true); }
    if (d.mview) { M.view = d.mview; M.menu = false; M.html = ""; render(true); return window.scrollTo(0, 0); }
    if (d.mproto) { M.proto = d.mproto; store.set("avm:m-proto", M.proto); M.dest = null; return render(); }
    if (d.mdest) { M.dest = d.mdest === M.dest ? null : d.mdest; render(); if (M.dest) $("#m-sources").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    const dest = sel();
    if (d.mlive) return liveDialog(d.mlive, srcName(d.mlive));
    if (d.msrc !== undefined && dest) return act(dest.id + "|" + d.msrc, () => api("POST", "/api/route", { destination: dest.id, source: d.msrc || null, origin: "panel" }), `${dest.name} ← ${d.msrc ? short(srcName(d.msrc)) : "Aus"}`);
    if (d.mundo !== undefined && dest) return act("u", () => api("POST", "/api/undo", { destination: dest.id }), "Vorherige Quelle wiederhergestellt");
    if (d.mlock !== undefined && dest) return act("l", () => api("POST", dest.locked ? "/api/unlock" : "/api/lock", { destination: dest.id }), dest.locked ? "Entsperrt" : "Gesperrt");
    if (d.mpreset) return act("p|" + d.mpreset, () => recall(d.mpreset));
    if (d.mundolast !== undefined) return undoLast();
  });

  /* Vorschaubilder: nur für Kacheln, die gerade im Bild sind */
  async function load(id) {
    const it = pv.get(id) || { state: "loading", url: null, at: 0 };
    pv.set(id, it); it.busy = true; it.tried = Date.now();
    try {
      const res = await fetch(`/api/preview.jpg?source=${encodeURIComponent(id)}&w=320`, { cache: "no-store" });
      const old = it.url;
      if (res.ok) Object.assign(it, { state: "ok", url: URL.createObjectURL(await res.blob()), at: Date.now(), origin: res.headers.get("X-Preview-Origin"), slow: res.headers.get("X-Preview-Origin") === "device" || parseInt(res.headers.get("X-Preview-Size") || "0", 10) > 960 });
      else { const state = res.headers.get("X-Preview-State") || "no_signal"; if (state === "unavailable") pvAvailable = false; Object.assign(it, { state, url: null }); }
      if (old) setTimeout(() => URL.revokeObjectURL(old), 1500);
    } catch (_e) { Object.assign(it, { state: "stale", url: null }); }
    it.busy = false;
    M.html = ""; render();
  }
  setInterval(() => {
    if (!M.on || M.view !== "route" || M.proto !== "ndi" || pvAvailable === false || document.visibilityState !== "visible" || $("#dlg").open) return;
    const now = Date.now();
    let running = [...pv.values()].filter((x) => x.busy).length;
    for (const id of visible) {
      if (running >= 2) break;
      const it = pv.get(id);
      const s = proto().sources.find((x) => x.id === id);
      const wait = it && (it.state === "unsupported_codec" || it.state === "no_signal") ? 60000 : it && it.slow ? 20000 : 5000;
      if (!s || !s.live || (it && (it.busy || now - (it.tried || 0) < wait))) continue;
      running++; load(id);
    }
  }, 600);

  hooks.snap.push(() => { if (M.on) { if (!protos().includes(M.proto) && protos().length) M.proto = protos()[0]; render(); } });
  hooks.info.push(() => M.on && render(true));
  apply();
})();
