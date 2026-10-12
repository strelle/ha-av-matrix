/* Strelle AV Matrix Server – NDI®-Vorschau in den Kacheln der Karte.
 *
 * Die Karte (av-matrix-card.js) bleibt unverändert aus ha-av-matrix übernommen. Diese Datei hängt sich nur an
 * ihre Panel-Ansicht: jede NDI-Quelle bekommt ein fest reserviertes 16:9-Bild, jedes Ziel das Bild seiner Quelle.
 * Die Bilder kommen vom Server (/api/preview.jpg, echter NDI-Empfang in niedrigster Bandbreite) und werden nur
 * geholt, solange die Kreuzschiene sichtbar ist. Kein Bild ohne Kennzeichnung: fällt eine Quelle weg oder bleibt
 * die Aktualisierung aus, zeigt die Kachel den Zustand statt eines alten Bildes. */
(() => {
  "use strict";
  const Card = customElements.get("av-matrix-card");
  if (!Card) return;
  const proto = Card.prototype;
  if (typeof proto._htmlPanel !== "function" || typeof proto._render !== "function") {
    console.warn("Strelle AV Matrix: Karte hat sich geändert – Vorschau in den Kacheln abgeschaltet");
    return;
  }

  const REFRESH_MS = 4500; // Standbild-Takt je Quelle (der Server puffert 4 s und teilt das Bild mit allen Panels)
  const STALE_MS = 16000; // (für NDI|HX-Quellen 60 s) // älter → nicht mehr als Bild zeigen
  const PARALLEL = 2;
  const WIDTH = 320;
  const TEXT = { loading: "Lade Vorschau …", unsupported_codec: "Vorschau nicht möglich (NDI|HX)", offline: "Offline", no_signal: "Kein Signal", stale: "Keine Aktualisierung", none: "Keine Quelle", unknown_source: "Unbekannt", off: "Aus" };
  const PV = { available: null, paused: false, items: new Map(), cards: new Set(), loading: 0 };

  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const unesc = (t) => t.replace(/&(amp|lt|gt|quot|#39);/g, (_m, e) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" })[e]);
  const WEB = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>`;
  const ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 4h5v5M9 20H4v-5M20 4l-6.5 6.5M4 20l6.5-6.5"/></svg>`;

  const CSS = `
.pv { position: relative; display: block; width: 100%; aspect-ratio: 16 / 9; flex: none; overflow: hidden; border-radius: 8px;
  background: #050505; border: 1px solid var(--p-line-strong); }
.src .pv { margin: 2px 0 6px; }
.dest-main .pv { margin: 6px 0 2px; }
.pv img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; display: block; pointer-events: none; }
.pv .pvmsg { position: absolute; inset: 0; display: grid; place-items: center; padding: 4px; text-align: center; font-family: var(--amx-mono);
  font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #a3a19c;
  background: repeating-linear-gradient(135deg, #131416 0 8px, #0b0b0c 8px 16px); }
.pv.st-no_signal .pvmsg, .pv.st-stale .pvmsg { color: #ffb020; }
.pv.st-offline .pvmsg { color: #ff8a84; }
.pv.st-loading .pvmsg { background: #0b0b0c; color: #6d7178; }
.pv .pvopen { position: absolute; right: 4px; bottom: 4px; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 8px;
  background: rgba(10,10,10,.78); border: 1px solid rgba(255,255,255,.45); color: #fff; cursor: zoom-in; }
.pv .pvopen svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.pv .pvopen:hover { background: var(--p-accent); border-color: var(--p-accent); }
@media (pointer: coarse) { .pv .pvopen { width: 42px; height: 42px; } }
/* Funktionsfarben bleiben lesbar: Rahmen um das Bild in der Farbe der Taste */
.src.pgm .pv { border-color: var(--p-on-signal); box-shadow: 0 0 0 2px var(--p-live); }
.src.pst .pv { border-color: var(--p-on-signal); box-shadow: 0 0 0 2px var(--p-cue); }
.src.dead .pv { opacity: .8; }
.src .shost { font-size: 13px; color: var(--p-muted); max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.src.pgm .shost { color: inherit; opacity: .8; }
.pv .pvweb { right: auto; left: 4px; cursor: pointer; }
.pv .pvtag { position: absolute; left: 4px; top: 4px; padding: 1px 6px; border-radius: 5px; background: rgba(10,10,10,.8); color: #fff;
  font-family: var(--amx-mono); font-size: 11px; letter-spacing: .04em; }
.pv .pvweb svg { fill: none; }
.pv.st-unsupported_codec .pvmsg { color: #a3a19c; font-size: 11px; }
`;

  function item(id) {
    let it = PV.items.get(id);
    if (!it) PV.items.set(id, (it = { state: "loading", url: null, at: 0, busy: false, tried: 0 }));
    return it;
  }

  function block(id, liveFlag, title, src) {
    const web = src && src.web_url ? `<span class="pvopen pvweb" data-pvweb="${esc(src.web_url)}" role="link" title="Weboberfläche öffnen: ${esc(src.host)}" aria-label="Weboberfläche ${esc(src.host)}">${WEB}</span>` : "";
    return blockInner(id, liveFlag, title).replace(/<\/span>$/, web + "</span>");
  }

  function blockInner(id, liveFlag, title) {
    if (id === "") return `<span class="pv st-off"><span class="pvmsg">${TEXT.off}</span></span>`;
    if (id == null) return `<span class="pv st-none"><span class="pvmsg">${TEXT.none}</span></span>`;
    const it = item(id);
    let state = liveFlag === false ? "offline" : it.state;
    if (state === "ok" && Date.now() - it.at > (it.slow ? 60000 : STALE_MS)) state = "stale";
    const open = state === "offline" || state === "unsupported_codec" ? "" : `<span class="pvopen" data-pvopen="${esc(id)}" role="button" title="Live-Vorschau: ${esc(title || id)}" aria-label="Live-Vorschau ${esc(title || id)}">${ICON}</span>`;
    const tag = it.origin === "device" ? `<span class="pvtag" title="Standbild vom Gerät selbst, nicht aus dem NDI-Feed">vom Gerät</span>` : "";
    if (state === "ok" && it.url) return `<span class="pv st-ok" data-pv="${esc(id)}"><img alt="" draggable="false" src="${esc(it.url)}">${tag}${open}</span>`;
    return `<span class="pv st-${state}" data-pv="${esc(id)}"><span class="pvmsg">${TEXT[state] || TEXT.no_signal}</span>${open}</span>`;
  }

  const origPanel = proto._htmlPanel;
  proto._htmlPanel = function (p, dests, sources) {
    let html = origPanel.call(this, p, dests, sources);
    this._pvWanted = new Set();
    if (this._protocol !== "ndi" || PV.available === false) return html;
    const byId = new Map((p.sources || []).map((s) => [s.id, s]));
    const dById = new Map((p.destinations || []).map((d) => [d.id, d]));
    const want = (id) => {
      const s = byId.get(id);
      if (s && s.live) this._pvWanted.add(id);
      return s;
    };
    // IP-Zeile wie bei den Zielen (wenn sie nicht ohnehin als Gerätename dasteht) und Link zur Weboberfläche
    html = html.replace(/(<button type="button" class="src[^"]*" data-k="s-[^"]*" data-act="src" data-s="([^"]*)"[\s\S]*?<span class="sid mono">)([^<]*)(<\/span>)/g, (_m, head, rawId, secondary, close) => {
      const s = byId.get(unesc(rawId));
      if (!s || !s.host) return _m;
      const ip = unesc(secondary).includes(s.host) ? "" : `<span class="shost mono">${esc(s.host)}</span>`;
      return head + secondary + close + ip;
    });
    // Quellen-Kacheln: Bild direkt unter der Tally-Leiste
    html = html.replace(/(<button type="button" class="src[^"]*" data-k="s-[^"]*" data-act="src" data-s="([^"]*)"[^>]*>\s*<span class="tally"><\/span>)/g, (_m, head, rawId) => {
      const id = unesc(rawId);
      if (id === "") return head + block("");
      const s = want(id);
      return head + block(id, s ? s.live : false, s ? s.name : id, s);
    });
    // Ziel-Kacheln: was der Decoder gerade zeigt = Bild der zugewiesenen Quelle
    html = html.replace(/(<button type="button" class="dest-main" data-act="dest" data-d="([^"]*)"[^>]*>[\s\S]*?)(<span class="dband">)/g, (_m, head, rawId, band) => {
      const d = dById.get(unesc(rawId));
      if (!d || !d.current_source) return head + block(null) + band;
      if (d.current_source_renamed_to) // der Decoder steht noch auf dem alten Namen der Quelle
        return head + `<span class="pv st-stale"><span class="pvmsg">Alter Quellenname –<br>neu zuweisen</span></span>` + band;
      const s = want(d.current_source);
      return head + block(d.current_source, s ? s.live : false, s ? s.name : d.current_source) + band;
    });
    return html;
  };

  const origRender = proto._render;
  proto._render = function () {
    const result = origRender.apply(this, arguments);
    const sr = this.shadowRoot;
    if (sr && !sr.querySelector("style[data-avm-preview]")) {
      const st = document.createElement("style");
      st.dataset.avmPreview = "1";
      st.textContent = CSS;
      sr.appendChild(st);
      // Klick auf das Vorschau-Symbol öffnet die Live-Vorschau und schaltet NICHT (vor der Karte abfangen)
      const stop = (e) => {
        const hit = e.target.closest && e.target.closest("[data-pvopen],[data-pvweb]");
        if (!hit) return;
        e.stopPropagation();
        e.preventDefault();
        if (e.type !== "click") return;
        if (hit.dataset.pvweb) return void window.open(hit.dataset.pvweb, "_blank", "noopener");
        const src = (this._snap && this._snap.protocols.ndi ? this._snap.protocols.ndi.sources : []).find((s) => s.id === hit.dataset.pvopen);
        window.dispatchEvent(new CustomEvent("avm-preview-open", { detail: { source: hit.dataset.pvopen, name: src ? src.name : hit.dataset.pvopen } }));
      };
      for (const type of ["click", "pointerdown", "pointerup", "mousedown", "touchstart", "contextmenu"]) sr.addEventListener(type, stop, true);
    }
    PV.cards.add(this);
    return result;
  };

  function rerender() {
    for (const card of PV.cards) if (card.isConnected) card._render();
  }

  async function load(id) {
    const it = item(id);
    it.busy = true;
    it.tried = Date.now();
    PV.loading++;
    let changed = false;
    try {
      const res = await fetch(`/api/preview.jpg?source=${encodeURIComponent(id)}&w=${WIDTH}`, { cache: "no-store" });
      if (res.ok) {
        const url = URL.createObjectURL(await res.blob());
        const old = it.url;
        // NDI|HX kommt in voller Auflösung und ist teuer zu dekodieren: seltener holen (der Server puffert 20 s)
        it.origin = res.headers.get("X-Preview-Origin") || "ndi";
        Object.assign(it, { state: "ok", url, at: Date.now(), slow: it.origin === "device" || parseInt(res.headers.get("X-Preview-Size") || "0", 10) > 960 });
        if (old) setTimeout(() => URL.revokeObjectURL(old), 1500);
        changed = true;
      } else {
        const state = res.headers.get("X-Preview-State") || "no_signal";
        if (state === "unavailable") PV.available = false;
        changed = it.state !== state || !!it.url;
        if (it.url) URL.revokeObjectURL(it.url);
        Object.assign(it, { state, url: null, at: Date.now() });
      }
    } catch (_e) {
      changed = it.state !== "stale" || !!it.url; // Server nicht erreichbar: kein altes Bild stehen lassen
      if (it.url) URL.revokeObjectURL(it.url);
      Object.assign(it, { state: "stale", url: null });
    }
    it.busy = false;
    PV.loading--;
    if (changed) rerender();
  }

  function tick() {
    // während die große Live-Vorschau offen ist, ruhen die Kacheln (flüssig nur für die eine angeklickte Quelle)
    if (PV.available === false || PV.paused || document.visibilityState !== "visible") return;
    const wanted = new Set();
    for (const card of PV.cards) {
      if (!card.isConnected || card.offsetParent === null) continue; // Kreuzschiene nicht sichtbar → nichts holen
      for (const id of card._pvWanted || []) wanted.add(id);
    }
    const now = Date.now();
    let stale = false;
    for (const [id, it] of PV.items) {
      const limit = it.slow ? 60000 : STALE_MS;
      if (it.state === "ok" && now - it.at > limit && !wanted.has(id)) {
        if (it.url) URL.revokeObjectURL(it.url); // nicht mehr sichtbar: Bild verwerfen
        PV.items.delete(id);
      } else if (it.state === "ok" && now - it.at > limit) stale = true;
    }
    if (stale) rerender();
    const wait = (it) => (it.state === "unsupported_codec" || it.state === "no_signal" ? 60000 : it.slow ? 20000 : REFRESH_MS);
    const due = [...wanted].map((id) => [id, item(id)]).filter(([, it]) => !it.busy && now - it.tried > wait(it)).sort((a, b) => a[1].tried - b[1].tried);
    for (const [id] of due) {
      if (PV.loading >= PARALLEL) break;
      load(id);
    }
  }

  fetch("/api/preview")
    .then((r) => r.json())
    .then((s) => {
      PV.available = !!s.available;
      if (!PV.available) console.info("Strelle AV Matrix: NDI-Vorschau nicht verfügbar –", s.reason);
      rerender();
    })
    .catch(() => {});
  setInterval(tick, 500);
  document.addEventListener("visibilitychange", tick);
  window.AvMatrixPreview = PV;
})();
