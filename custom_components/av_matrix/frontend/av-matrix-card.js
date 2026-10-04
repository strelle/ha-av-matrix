/*
 * AV Matrix card - a broadcast-style crosspoint router panel for the av_matrix integration.
 *
 *  - Panel mode (X-Y): destinations on top, sources below. Pick destination(s), then a source.
 *  - Matrix mode: destinations x sources grid with crosshair, sticky headers.
 *  - Take modes: Direct (tap = switch) or Preset + TAKE (arm one or many, TAKE = salvo).
 *  - Lock, undo, labels/tags (admin), linked displays, routing history, keyboard control.
 *
 * Data: WebSocket "av_matrix/subscribe" (docs/frontend-api.md); falls back to the select entities.
 * Plain web component, no build step. Served and registered by the integration itself.
 */
const CARD_VERSION = "0.1.0";

/* ------------------------------------------------------------------ i18n */
const STRINGS = {
  en: {
    sources_live: "{live}/{total} sources live",
    destinations: "{n} destinations",
    panel: "Panel",
    matrix: "Matrix",
    direct: "Direct",
    preset: "Preset",
    take: "TAKE",
    clear: "Clear",
    undo: "Undo",
    undo_last: "Undo last",
    search: "Search sources",
    live_only: "Live only",
    history: "History",
    no_history: "No routes yet.",
    off: "Off",
    off_sub: "black / no source",
    lock: "Lock destination",
    unlock: "Unlock destination",
    locked: "locked",
    select_dest_first: "Select a destination first",
    dest_locked: "{d} is locked",
    dests_locked: "Locked destinations skipped: {d}",
    dest_offline: "{d} is offline",
    switching: "switching…",
    not_sending: "Source not sending",
    offline_since: "offline · {t}",
    never_seen: "not seen yet",
    status_connected: "Connected",
    status_connecting: "Connecting",
    status_no_source: "No source",
    status_source_lost: "Source lost",
    status_offline: "Device offline",
    edit_labels: "Edit labels",
    edit_hint: "Edit mode: tap a source to rename it",
    label: "Label",
    label_ph: "Friendly name, e.g. Slides",
    tags: "Tags",
    tags_ph: "Comma separated, e.g. stage, camera",
    save: "Save",
    cancel: "Cancel",
    reset: "Remove label",
    display: "Display",
    display_on: "Display on · {i}",
    display_off: "Display off",
    armed: "{n} armed",
    nothing_armed: "Nothing armed",
    arm_hint: "Pick a destination, then a source",
    loading: "Connecting to AV Matrix…",
    no_devices: "No devices yet. Add one under Settings → Devices & services → AV Matrix.",
    not_loaded: "AV Matrix integration not loaded",
    basic_mode: "Basic mode",
    basic_mode_tip: "WebSocket API unavailable - using the select entities",
    route_failed: "Switching failed",
    action_failed: "Action failed",
    ago_now: "just now",
    ago_m: "{n} min ago",
    ago_h: "{n} h ago",
    ago_d: "{n} d ago",
    in_use: "on {n}",
    unknown_user: "",
    origin_select: "select",
    origin_salvo: "salvo",
    origin_undo: "undo",
    origin_service: "service",
    shortcuts: "Keys: / search · arrows move · Enter TAKE · Esc clear · U undo · L lock · 1-9 destination",
    dest_label: "Destination",
    source_label: "Source",
    no_match: "No source matches the filter.",
    label_saved: "Label saved",
    was: "was",
  },
  de: {
    sources_live: "{live}/{total} Quellen live",
    destinations: "{n} Ziele",
    panel: "Panel",
    matrix: "Matrix",
    direct: "Direkt",
    preset: "Preset",
    take: "TAKE",
    clear: "Verwerfen",
    undo: "Rückgängig",
    undo_last: "Letzte rückgängig",
    search: "Quellen suchen",
    live_only: "Nur live",
    history: "Verlauf",
    no_history: "Noch keine Schaltungen.",
    off: "Aus",
    off_sub: "schwarz / keine Quelle",
    lock: "Ziel sperren",
    unlock: "Ziel entsperren",
    locked: "gesperrt",
    select_dest_first: "Zuerst ein Ziel wählen",
    dest_locked: "{d} ist gesperrt",
    dests_locked: "Gesperrte Ziele übersprungen: {d}",
    dest_offline: "{d} ist offline",
    switching: "schaltet…",
    not_sending: "Quelle sendet nicht",
    offline_since: "offline · {t}",
    never_seen: "noch nie gesehen",
    status_connected: "Verbunden",
    status_connecting: "Verbindet",
    status_no_source: "Keine Quelle",
    status_source_lost: "Quelle verloren",
    status_offline: "Gerät offline",
    edit_labels: "Labels bearbeiten",
    edit_hint: "Bearbeiten: Quelle antippen, um sie umzubenennen",
    label: "Label",
    label_ph: "Klarname, z. B. Präsentation",
    tags: "Tags",
    tags_ph: "Kommagetrennt, z. B. Bühne, Kamera",
    save: "Speichern",
    cancel: "Abbrechen",
    reset: "Label entfernen",
    display: "Bildschirm",
    display_on: "Bildschirm an · {i}",
    display_off: "Bildschirm aus",
    armed: "{n} vorgemerkt",
    nothing_armed: "Nichts vorgemerkt",
    arm_hint: "Ziel wählen, dann Quelle",
    loading: "Verbinde mit AV Matrix…",
    no_devices: "Noch keine Geräte. Unter Einstellungen → Geräte & Dienste → AV Matrix hinzufügen.",
    not_loaded: "AV-Matrix-Integration nicht geladen",
    basic_mode: "Basismodus",
    basic_mode_tip: "WebSocket-API nicht verfügbar - Daten aus den Select-Entitäten",
    route_failed: "Schalten fehlgeschlagen",
    action_failed: "Aktion fehlgeschlagen",
    ago_now: "gerade eben",
    ago_m: "seit {n} Min",
    ago_h: "seit {n} Std",
    ago_d: "seit {n} Tg",
    in_use: "auf {n}",
    unknown_user: "",
    origin_select: "Auswahl",
    origin_salvo: "Salvo",
    origin_undo: "Undo",
    origin_service: "Dienst",
    shortcuts: "Tasten: / Suche · Pfeile navigieren · Enter TAKE · Esc verwerfen · U Undo · L Sperre · 1-9 Ziel",
    dest_label: "Ziel",
    source_label: "Quelle",
    no_match: "Keine Quelle passt zum Filter.",
    label_saved: "Label gespeichert",
    was: "vorher",
  },
};

/* ------------------------------------------------------------------ icons (24px, stroke) */
const ICON_PATHS = {
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  unlock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.6-1.7"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  tv: '<rect x="2.5" y="4.5" width="19" height="13" rx="2"/><path d="M8 21h8M12 17.5V21"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  pencil: '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3.5 2"/>',
  matrix:
    '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
  panel:
    '<rect x="3" y="3.5" width="5" height="4" rx="1"/><rect x="9.5" y="3.5" width="5" height="4" rx="1"/><rect x="16" y="3.5" width="5" height="4" rx="1"/><rect x="3" y="11" width="18" height="9.5" rx="1.5"/>',
  warn: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  power: '<path d="M12 2.5v9"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7Z"/>',
  keyboard:
    '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
};
const icon = (name, cls = "") =>
  `<svg class="ic ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON_PATHS[name] || ""}</svg>`;

const esc = (text) =>
  String(text ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

/* ------------------------------------------------------------------ tiny DOM morph
 * Patches an existing subtree to match freshly parsed HTML. Keeps element identity
 * (focus, scroll position, running CSS animations) - elements with data-k are matched by key. */
function morphChildren(oldParent, newParent, root) {
  const keyed = new Map();
  for (const child of oldParent.children) {
    const key = child.getAttribute("data-k");
    if (key) keyed.set(key, child);
  }
  let cur = oldParent.firstChild;
  for (const next of Array.from(newParent.childNodes)) {
    let match = null;
    const key = next.nodeType === 1 ? next.getAttribute("data-k") : null;
    if (key) {
      const found = keyed.get(key);
      if (found && found.tagName === next.tagName) {
        match = found;
        keyed.delete(key);
      }
    } else if (
      cur &&
      cur.nodeType === next.nodeType &&
      (next.nodeType !== 1 || (cur.tagName === next.tagName && !cur.getAttribute("data-k")))
    ) {
      match = cur;
    }
    if (match) {
      if (match === cur) cur = cur.nextSibling;
      else oldParent.insertBefore(match, cur);
      if (next.nodeType === 1) morphElement(match, next, root);
      else if (match.nodeValue !== next.nodeValue) match.nodeValue = next.nodeValue;
    } else {
      oldParent.insertBefore(next, cur);
    }
  }
  while (cur) {
    const after = cur.nextSibling;
    oldParent.removeChild(cur);
    cur = after;
  }
}

function morphElement(oldEl, newEl, root) {
  const oldAttrs = oldEl.attributes;
  for (let i = oldAttrs.length - 1; i >= 0; i--) {
    const name = oldAttrs[i].name;
    if (!newEl.hasAttribute(name)) oldEl.removeAttribute(name);
  }
  for (const attr of newEl.attributes) {
    if (oldEl.getAttribute(attr.name) !== attr.value) oldEl.setAttribute(attr.name, attr.value);
  }
  if (oldEl.tagName === "INPUT") {
    const value = newEl.getAttribute("value") || "";
    if (root.activeElement !== oldEl && oldEl.value !== value) oldEl.value = value;
    return;
  }
  morphChildren(oldEl, newEl, root);
}

/* ------------------------------------------------------------------ shared routing history
 * One event subscription per HA connection, shared by all cards on the page and kept while
 * the page lives (cards are re-created when switching views). */
const HISTORY_MAX = 50;
const HISTORIES = new WeakMap();
const USER_NAMES = new Map();

function historyFor(hass) {
  const conn = hass.connection;
  let h = HISTORIES.get(conn);
  if (h) return h;
  h = { entries: [], listeners: new Set(), events: null };
  HISTORIES.set(conn, h);
  h.push = (entry) => {
    h.entries.unshift(entry);
    if (h.entries.length > HISTORY_MAX) h.entries.length = HISTORY_MAX;
    h.listeners.forEach((fn) => fn());
  };
  h.events = conn
    .subscribeEvents((ev) => {
      const d = ev.data || {};
      h.push({
        time: ev.time_fired ? Date.parse(ev.time_fired) : Date.now(),
        protocol: d.protocol,
        dest: d.destination,
        dest_name: d.destination_name,
        source: d.source,
        previous: d.previous_source,
        origin: d.origin,
        user_id: (ev.context && ev.context.user_id) || null,
      });
    }, "av_matrix_routed")
    .then(() => true)
    .catch(() => false); // non-admin users may not subscribe to custom events → diff fallback
  return h;
}

/* ------------------------------------------------------------------ the card */
const LONG_PRESS_MS = 450;
const PENDING_TIMEOUT = 8000;
const STATUS_ORDER = ["connected", "connecting", "no_source", "source_lost", "offline"];

class AvMatrixCard extends HTMLElement {
  constructor() {
    super();
    this._config = null;
    this._hass = null;
    this._snap = null;
    this._fallback = false;
    this._error = null;
    this._protocol = null;
    this._modeUser = null; // set when the user toggles panel/matrix
    this._take = "direct";
    this._sel = []; // selected destination ids (panel), first = primary
    this._preset = new Map(); // dest id → source id ("" = off)
    this._pending = new Map(); // dest id → { source, until }
    this._search = "";
    this._tags = new Set();
    this._liveOnly = false;
    this._editMode = false;
    this._historyOpen = false;
    this._navKey = {}; // roving tabindex per group
    this._prevCurrent = new Map(); // dest id → current source (diff history fallback)
    this._ownUndo = []; // dest ids routed from this card, newest last
    this._narrow = false;
    this._lastHtml = "";
    this._width = 0;
  }

  /* ---------------- Lovelace API */
  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    const c = { ...config };
    if (c.show_offline === undefined && c.show_offline_sources !== undefined) c.show_offline = c.show_offline_sources;
    this._config = {
      title: "AV Matrix",
      mode: "panel",
      take_mode: "direct",
      show_offline: true,
      compact: false,
      columns: 0,
      ...c,
    };
    if (!["panel", "matrix"].includes(this._config.mode)) this._config.mode = "panel";
    if (!["direct", "preset"].includes(this._config.take_mode)) this._config.take_mode = "direct";
    this._take = this._config.take_mode;
    this._protocol = this._config.protocol || this._protocol;
    this._modeUser = null;
    this._render();
  }

  set hass(hass) {
    const old = this._hass;
    this._hass = hass;
    if (!old || old.connection !== hass.connection) {
      this._unsubscribe();
      this._subscribe();
    } else if (this._fallback && old.states !== hass.states) {
      this._applySnapshot(this._fallbackSnapshot());
    } else if (!old || old.language !== hass.language) {
      this._render();
    }
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    if (this._hass && !this._unsub && !this._fallback) this._subscribe();
    if (!this._ro && window.ResizeObserver) {
      this._ro = new ResizeObserver((entries) => {
        const w = Math.round(entries[0].contentRect.width);
        if (Math.abs(w - this._width) < 2) return;
        this._width = w;
        const narrow = w > 0 && w < 640;
        this._narrow = narrow;
        this._render();
      });
    }
    if (this._ro) this._ro.observe(this);
    if (!this._tick) this._tick = setInterval(() => this._render(), 15000);
    this._render();
  }

  disconnectedCallback() {
    this._unsubscribe();
    if (this._ro) this._ro.disconnect();
    clearInterval(this._tick);
    this._tick = null;
  }

  getCardSize() {
    const p = this._currentProtocol();
    const dests = p ? this._destinations(p).length : 3;
    return this._mode() === "matrix" ? 3 + dests : 8;
  }

  getGridOptions() {
    return { columns: "full", min_columns: 6, rows: "auto" };
  }

  static getConfigElement() {
    return document.createElement("av-matrix-card-editor");
  }

  static getStubConfig() {
    return { title: "AV Matrix", mode: "panel", take_mode: "direct" };
  }

  /* ---------------- data */
  _subscribe() {
    const hass = this._hass;
    if (!hass || !hass.connection || this._unsub) return;
    this._history = historyFor(hass);
    this._historyListener = () => this._historyOpen && this._render();
    this._history.listeners.add(this._historyListener);
    const unsub = hass.connection.subscribeMessage((snap) => this._applySnapshot(snap), {
      type: "av_matrix/subscribe",
    });
    this._unsub = unsub;
    unsub.catch((err) => {
      if (this._unsub !== unsub) return;
      this._unsub = null;
      const fb = this._fallbackSnapshot();
      if (Object.keys(fb.protocols).length) {
        this._fallback = true;
        this._applySnapshot(fb);
      } else {
        this._error = (err && err.message) || this._t("not_loaded");
        this._render();
      }
    });
  }

  _unsubscribe() {
    if (this._unsub) {
      this._unsub.then((u) => u()).catch(() => {});
      this._unsub = null;
    }
    if (this._history && this._historyListener) this._history.listeners.delete(this._historyListener);
  }

  _applySnapshot(snap) {
    this._snap = snap;
    this._error = null;
    const now = Date.now();
    for (const proto of Object.values(snap.protocols || {})) {
      for (const d of proto.destinations) {
        const p = this._pending.get(d.id);
        if (p && ((p.source || null) === (d.current_source || null) || now > p.until)) this._pending.delete(d.id);
        const prev = this._prevCurrent.get(d.id);
        if (prev !== undefined && prev !== d.current_source && this._history) {
          this._history.events.then((ok) => {
            if (!ok)
              this._history.push({
                time: now,
                protocol: d.protocol,
                dest: d.id,
                dest_name: d.name,
                source: d.current_source,
                previous: prev,
                origin: null,
                user_id: null,
              });
          });
        }
        this._prevCurrent.set(d.id, d.current_source);
      }
    }
    this._render();
  }

  _fallbackSnapshot() {
    const hass = this._hass;
    const out = { version: null, protocols: {} };
    if (!hass || !hass.states) return out;
    const reg = hass.entities || {};
    for (const [eid, st] of Object.entries(hass.states)) {
      if (!eid.startsWith("select.")) continue;
      const a = st.attributes || {};
      const entry = reg[eid];
      if (entry ? entry.platform !== "av_matrix" : !("source_live" in a && "protocol" in a)) continue;
      const key = a.protocol || "ndi";
      const p = (out.protocols[key] ||= { title: key === "ndi" ? "NDI®" : key.toUpperCase(), _src: new Map(), destinations: [] });
      for (const opt of a.options || []) {
        if (opt !== "None" && !p._src.has(opt))
          p._src.set(opt, { id: opt, name: opt, label: null, tags: [], live: true, host: null, last_seen: null });
      }
      const unavailable = st.state === "unavailable" || st.state === "unknown";
      const cur = unavailable || st.state === "None" ? null : st.state;
      if (cur) {
        if (!p._src.has(cur))
          p._src.set(cur, { id: cur, name: cur, label: null, tags: [], live: false, host: null, last_seen: null });
        p._src.get(cur).live = !!a.source_live;
      }
      const dev = entry && entry.device_id && hass.devices ? hass.devices[entry.device_id] : null;
      const name = (dev && (dev.name_by_user || dev.name)) || String(a.friendly_name || eid).replace(/ (Source|Quelle)$/, "");
      p.destinations.push({
        id: eid,
        entity_id: eid,
        name,
        protocol: key,
        current_source: cur,
        current_source_live: !!a.source_live,
        status: unavailable ? "offline" : !cur ? "no_source" : a.source_live ? "connected" : "source_lost",
        resolution: null,
        available: !unavailable,
        locked: !!a.locked,
        can_undo: !!a.can_undo,
        display: null,
      });
    }
    for (const p of Object.values(out.protocols)) {
      p.sources = [...p._src.values()].sort((x, y) => x.name.localeCompare(y.name));
      delete p._src;
      p.destinations.sort((x, y) => x.name.localeCompare(y.name));
    }
    return out;
  }

  _currentProtocol() {
    const protos = (this._snap && this._snap.protocols) || {};
    const keys = Object.keys(protos);
    if (!keys.length) return null;
    if (!this._protocol || !protos[this._protocol]) this._protocol = keys[0];
    return protos[this._protocol];
  }

  _destinations(proto) {
    const wanted = this._config && Array.isArray(this._config.destinations) ? this._config.destinations : null;
    if (!wanted || !wanted.length) return proto.destinations;
    const out = [];
    for (const id of wanted) {
      const d = proto.destinations.find((x) => x.entity_id === id || x.id === id);
      if (d) out.push(d);
    }
    return out;
  }

  _sources(proto) {
    const q = this._search.trim().toLowerCase();
    const showOffline = this._config.show_offline !== false && !this._liveOnly;
    const current = new Set(proto.destinations.map((d) => d.current_source));
    return proto.sources.filter((s) => {
      if (!showOffline && !s.live && !current.has(s.id)) return false;
      if (this._tags.size && !(s.tags || []).some((t) => this._tags.has(t))) return false;
      if (!q) return true;
      return [s.name, s.id, s.host, ...(s.tags || [])].some((v) => v && String(v).toLowerCase().includes(q));
    });
  }

  _mode() {
    if (this._modeUser) return this._modeUser;
    return this._narrow ? "panel" : this._config.mode;
  }

  _isLight() {
    const th = this._hass && this._hass.themes;
    return !!th && th.darkMode === false;
  }

  _isAdmin() {
    return !!(this._hass && this._hass.user && this._hass.user.is_admin) && !this._fallback;
  }

  _lang() {
    const l = (this._hass && (this._hass.locale?.language || this._hass.language)) || "en";
    return l.startsWith("de") ? "de" : "en";
  }

  _t(key, vars) {
    let s = STRINGS[this._lang()][key] ?? STRINGS.en[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
    return s;
  }

  _srcById(proto, id) {
    return id == null ? null : proto.sources.find((s) => s.id === id) || null;
  }

  /** [primary, secondary] text for a source: label over NDI name, else "Stream" over "MACHINE". */
  _names(src, id) {
    if (!src) return id ? [id, ""] : [this._t("off"), ""];
    if (src.label) return [src.label, src.id];
    const m = /^(.*?)\s*\((.+)\)$/.exec(src.id);
    if (m) return [m[2], m[1]];
    return [src.id, src.host || ""];
  }

  _srcName(proto, id) {
    if (id == null || id === "") return this._t("off");
    return this._names(this._srcById(proto, id), id)[0];
  }

  _ago(iso) {
    if (!iso) return this._t("never_seen");
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    if (s < 60) return this._t("ago_now");
    if (s < 3600) return this._t("ago_m", { n: Math.round(s / 60) });
    if (s < 86400) return this._t("ago_h", { n: Math.round(s / 3600) });
    return this._t("ago_d", { n: Math.round(s / 86400) });
  }

  _res(r) {
    if (!r) return "";
    const m = /(\d+)\s*x\s*(\d+)\s*([pi])?\s*([\d.]+)?/i.exec(r);
    if (!m) return r;
    const fps = m[4] ? String(Math.round(parseFloat(m[4]) * 100) / 100) : "";
    return `${m[2]}${(m[3] || "p").toLowerCase()}${fps}`;
  }

  /* ---------------- actions */
  async _call(domain, service, data, failKey = "action_failed") {
    try {
      await this._hass.callService(domain, service, data);
      return true;
    } catch (err) {
      this._toast(`${this._t(failKey)}: ${(err && err.message) || err}`, "err");
      return false;
    }
  }

  /** Switch now (direct mode / TAKE). routes: [[dest, sourceId|null]] */
  async _execute(routes, restorePresets = null) {
    const proto = this._currentProtocol();
    if (!proto || !routes.length) return;
    const blocked = routes.filter(([d]) => d.locked || d.available === false);
    const ok = routes.filter(([d]) => !d.locked && d.available !== false);
    if (blocked.length) {
      this._toast(
        blocked.length === 1 && !ok.length
          ? this._t(blocked[0][0].locked ? "dest_locked" : "dest_offline", { d: blocked[0][0].name })
          : this._t("dests_locked", { d: blocked.map(([d]) => d.name).join(", ") }),
        "warn"
      );
      this._shake(blocked.map(([d]) => d.id));
    }
    if (!ok.length) return;
    const until = Date.now() + PENDING_TIMEOUT;
    for (const [d, s] of ok) this._pending.set(d.id, { source: s, until });
    this._flash(ok);
    this._render();
    const src = (s) => (s == null || s === "" ? "None" : s);
    let success;
    try {
      if (ok.length === 1) {
        await this._hass.callService("av_matrix", "route", { entity_id: ok[0][0].entity_id, source: src(ok[0][1]) });
      } else {
        await this._hass.callService("av_matrix", "salvo", {
          routes: ok.map(([d, s]) => ({ destination: d.entity_id, source: src(s) })),
        });
      }
      success = true;
    } catch (err) {
      success = false;
      for (const [d] of ok) this._pending.delete(d.id);
      if (restorePresets) for (const [k, v] of restorePresets) this._preset.set(k, v);
      this._toast(`${this._t("route_failed")}: ${(err && err.message) || err}`, "err");
    }
    if (success) {
      for (const [d] of ok) {
        this._ownUndo = this._ownUndo.filter((x) => x !== d.id);
        this._ownUndo.push(d.id);
      }
      if (this._fallback) setTimeout(() => this._applySnapshot(this._fallbackSnapshot()), 300);
    }
    this._render();
  }

  _pickSource(sourceId) {
    const proto = this._currentProtocol();
    if (!proto) return;
    if (this._editMode && sourceId) return this._openLabel(sourceId);
    const dests = this._destinations(proto).filter((d) => this._sel.includes(d.id));
    if (!dests.length) {
      this._toast(this._t("select_dest_first"), "info");
      this._shake(["__dests"]);
      return;
    }
    this._crosspoint(dests, sourceId);
  }

  _crosspoint(dests, sourceId) {
    const s = sourceId || "";
    if (this._take === "direct") {
      this._execute(dests.map((d) => [d, s]));
      return;
    }
    const locked = dests.filter((d) => d.locked);
    if (locked.length) {
      this._toast(this._t("dest_locked", { d: locked.map((d) => d.name).join(", ") }), "warn");
      this._shake(locked.map((d) => d.id));
    }
    const free = dests.filter((d) => !d.locked);
    const allSame = free.every((d) => this._preset.get(d.id) === s);
    for (const d of free) {
      if (allSame) this._preset.delete(d.id);
      else if ((d.current_source || "") === s) this._preset.delete(d.id);
      else this._preset.set(d.id, s);
    }
    this._render();
  }

  _doTake() {
    const proto = this._currentProtocol();
    if (!proto || !this._preset.size) return;
    const saved = new Map(this._preset);
    const routes = [];
    for (const [id, s] of this._preset) {
      const d = proto.destinations.find((x) => x.id === id);
      if (d) routes.push([d, s]);
    }
    this._preset.clear();
    this._execute(routes, saved);
  }

  _clear() {
    if (this._preset.size) this._preset.clear();
    else if (this._sel.length > 1) this._sel = this._sel.slice(0, 1);
    this._render();
  }

  _selectDest(id, multi) {
    if (multi) {
      this._sel = this._sel.includes(id) ? this._sel.filter((x) => x !== id) : [...this._sel, id];
    } else {
      this._sel = [id];
    }
    this._render();
  }

  _toggleLock(dests) {
    for (const d of dests) this._call("av_matrix", d.locked ? "unlock" : "lock", { entity_id: d.entity_id });
  }

  _undo(dests) {
    const proto = this._currentProtocol();
    if (!proto) return;
    let targets = (dests || []).filter((d) => d.can_undo && !d.locked);
    if (!dests) {
      const id = [...this._ownUndo].reverse().find((x) => proto.destinations.find((d) => d.id === x && d.can_undo));
      const hist = this._history && this._history.entries.find((e) => e.protocol === this._protocol);
      const pick = id || (hist && hist.dest);
      const d = proto.destinations.find((x) => x.id === pick && x.can_undo);
      targets = d ? [d] : [];
    }
    for (const d of targets) {
      if (d.locked) continue;
      this._pending.set(d.id, { source: undefined, until: Date.now() + 1500 });
      this._call("av_matrix", "undo", { entity_id: d.entity_id }).then(() => this._render());
    }
    this._render();
  }

  _toggleDisplay(dest) {
    const disp = dest.display;
    if (!disp) return;
    const on = disp.state === "on" || disp.state === "playing" || disp.state === "idle";
    this._call("media_player", on ? "turn_off" : "turn_on", { entity_id: disp.entity_id });
  }

  /* ---------------- label dialog (admin) */
  _openLabel(sourceId) {
    if (!this._isAdmin()) return;
    const proto = this._currentProtocol();
    const src = this._srcById(proto, sourceId);
    if (!src) return;
    const dlg = this.shadowRoot.querySelector("dialog");
    const allTags = [...new Set(proto.sources.flatMap((s) => s.tags || []))].sort();
    dlg.innerHTML = `
      <form method="dialog" class="dlg-body">
        <div class="dlg-head">
          <div><div class="dlg-kicker">${esc(this._t("edit_labels"))} · ${esc(proto.title)}</div>
          <div class="dlg-title mono">${esc(src.id)}</div>
          ${src.host ? `<div class="dlg-sub mono">${esc(src.host)}</div>` : ""}</div>
          <button type="button" class="ibtn" data-dlg="cancel" aria-label="${esc(this._t("cancel"))}">${icon("x")}</button>
        </div>
        <label class="fld"><span>${esc(this._t("label"))}</span>
          <input name="label" autocomplete="off" value="${esc(src.label || "")}" placeholder="${esc(this._t("label_ph"))}"></label>
        <label class="fld"><span>${esc(this._t("tags"))}</span>
          <input name="tags" autocomplete="off" value="${esc((src.tags || []).join(", "))}" placeholder="${esc(this._t("tags_ph"))}"></label>
        ${
          allTags.length
            ? `<div class="dlg-tags">${allTags.map((t) => `<button type="button" class="chip" data-addtag="${esc(t)}">#${esc(t)}</button>`).join("")}</div>`
            : ""
        }
        <div class="dlg-actions">
          ${src.label || (src.tags || []).length ? `<button type="button" class="btn ghost danger" data-dlg="reset">${esc(this._t("reset"))}</button>` : "<span></span>"}
          <span class="grow"></span>
          <button type="button" class="btn ghost" data-dlg="cancel">${esc(this._t("cancel"))}</button>
          <button type="submit" class="btn primary" data-dlg="save">${esc(this._t("save"))}</button>
        </div>
      </form>`;
    this._dlgSrc = src.id;
    if (dlg.open) dlg.close();
    dlg.showModal();
    setTimeout(() => dlg.querySelector('input[name="label"]').focus(), 30);
  }

  async _sendLabel(source, label, tags) {
    try {
      await this._hass.connection.sendMessagePromise({ type: "av_matrix/label", protocol: this._protocol, source, label, tags });
      this._toast(this._t("label_saved"), "ok");
    } catch (err) {
      this._toast(`${this._t("action_failed")}: ${(err && err.message) || err}`, "err");
    }
  }

  _bindDialog(dlg) {
    dlg.addEventListener("submit", (e) => {
      e.preventDefault();
      const form = e.target;
      const label = form.elements.label.value.trim();
      const tags = form.elements.tags.value
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
      dlg.close();
      this._sendLabel(this._dlgSrc, label || null, tags.length ? tags : null);
    });
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg) {
        dlg.close();
        return;
      }
      const b = e.target.closest("[data-dlg],[data-addtag]");
      if (!b) return;
      const form = dlg.querySelector("form");
      if (b.dataset.addtag) {
        const cur = form.elements.tags.value
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
        if (!cur.includes(b.dataset.addtag)) cur.push(b.dataset.addtag);
        form.elements.tags.value = cur.join(", ");
      } else if (b.dataset.dlg === "cancel") {
        dlg.close();
      } else if (b.dataset.dlg === "reset") {
        dlg.close();
        this._sendLabel(this._dlgSrc, null, null);
      }
    });
    // keys typed in the dialog must not reach the card / HA shortcuts
    dlg.addEventListener("keydown", (e) => e.stopPropagation());
  }

  /* ---------------- feedback */
  _toast(text, kind = "info") {
    const box = this.shadowRoot && this.shadowRoot.querySelector(".toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.setAttribute("role", kind === "err" ? "alert" : "status");
    el.innerHTML = `${kind === "err" || kind === "warn" ? icon("warn") : ""}<span>${esc(text)}</span>`;
    box.appendChild(el);
    while (box.children.length > 3) box.firstChild.remove();
    setTimeout(() => el.classList.add("out"), kind === "err" ? 6000 : 2600);
    setTimeout(() => el.remove(), kind === "err" ? 6400 : 3000);
  }

  _shake(ids) {
    requestAnimationFrame(() => {
      for (const id of ids) {
        this.shadowRoot.querySelectorAll(`[data-shake="${CSS.escape(id)}"]`).forEach((el) => {
          el.classList.remove("shake");
          void el.offsetWidth;
          el.classList.add("shake");
        });
      }
    });
  }

  _flash(routes) {
    requestAnimationFrame(() => {
      for (const [d, s] of routes) {
        const sel = `[data-flash="${CSS.escape(d.id)}|${CSS.escape(s || "")}"]`;
        this.shadowRoot.querySelectorAll(sel).forEach((el) => {
          el.classList.remove("flash");
          void el.offsetWidth;
          el.classList.add("flash");
        });
      }
    });
  }

  /* ---------------- render */
  _ensureShell() {
    if (this.shadowRoot && this._root) return;
    const sr = this.shadowRoot || this.attachShadow({ mode: "open" });
    sr.innerHTML = `<style>${CSS_TEXT}</style><style class="hover"></style>
      <ha-card><div class="root" tabindex="-1"></div><div class="toasts" aria-live="polite"></div></ha-card>
      <dialog class="dlg"></dialog>`;
    this._root = sr.querySelector(".root");
    this._hoverStyle = sr.querySelector("style.hover");
    this._tpl = document.createElement("template");
    this._bind(sr);
    this._bindDialog(sr.querySelector("dialog"));
  }

  _render() {
    if (!this._config) return;
    this._ensureShell();
    const cls = `root ${this._narrow ? "narrow" : ""} ${this._width && this._width < 420 ? "xs" : ""} ${
      this._config.compact ? "compact" : ""
    } mode-${this._mode()} take-${this._take} ${this._isLight() ? "light" : ""}`;
    if (this._root.className !== cls) this._root.className = cls;
    const html = this._html().replace(/>\s+</g, "><");
    if (html === this._lastHtml) return;
    this._lastHtml = html;
    this._tpl.innerHTML = html;
    morphChildren(this._root, this._tpl.content, this.shadowRoot);
  }

  _html() {
    const protos = (this._snap && this._snap.protocols) || {};
    const proto = this._currentProtocol();
    if (!this._snap || !proto) {
      let msg;
      if (this._error) msg = `<div class="msg err">${icon("warn")}<span>${esc(this._error)}</span></div>`;
      else if (!this._snap) msg = `<div class="msg"><span class="spinner"></span><span>${esc(this._t("loading"))}</span></div>`;
      else msg = `<div class="msg">${esc(this._t("no_devices"))}</div>`;
      return `${this._config.title ? `<div class="hdr"><div class="ttl"><h2>${esc(this._config.title)}</h2></div></div>` : ""}${msg}`;
    }
    const dests = this._destinations(proto);
    // panel selection: keep valid, default to first destination
    this._sel = this._sel.filter((id) => dests.some((d) => d.id === id));
    if (!this._sel.length && dests.length) this._sel = [dests[0].id];
    for (const id of [...this._preset.keys()]) if (!dests.some((d) => d.id === id)) this._preset.delete(id);
    const sources = this._sources(proto);
    const mode = this._mode();
    return `
      ${this._htmlHeader(protos, proto, dests)}
      ${this._editMode ? `<div class="edit-hint" data-k="edithint">${icon("pencil")}<span>${esc(this._t("edit_hint"))}</span></div>` : ""}
      ${mode === "matrix" ? this._htmlMatrix(proto, dests, sources) : this._htmlPanel(proto, dests, sources)}
      ${this._htmlFooter(proto, dests)}
      ${this._historyOpen ? this._htmlHistory(proto) : ""}`;
  }

  _seg(group, items, value) {
    return `<div class="seg" role="radiogroup" data-k="seg-${group}">${items
      .map(
        ([v, label, ic]) =>
          `<button type="button" role="radio" class="${v === value ? "on" : ""}" aria-checked="${v === value}" data-act="${group}" data-v="${esc(v)}" title="${esc(label)}">${ic ? icon(ic) : ""}<span>${esc(label)}</span></button>`
      )
      .join("")}</div>`;
  }

  _htmlHeader(protos, proto, dests) {
    const keys = Object.keys(protos);
    const live = proto.sources.filter((s) => s.live).length;
    const okDests = dests.filter((d) => d.status === "connected").length;
    const allTags = [...new Set(proto.sources.flatMap((s) => s.tags || []))].sort();
    const tabs =
      keys.length > 1
        ? `<div class="tabs" role="tablist" data-k="tabs">${keys
            .map(
              (k) =>
                `<button type="button" role="tab" class="tab ${k === this._protocol ? "on" : ""}" aria-selected="${k === this._protocol}" data-act="proto" data-v="${esc(k)}">${esc(protos[k].title)}</button>`
            )
            .join("")}</div>`
        : `<div class="tabs single" data-k="tabs"><span class="tab on">${esc(proto.title)}</span></div>`;
    const tagChips = allTags
      .map(
        (t) =>
          `<button type="button" class="chip ${this._tags.has(t) ? "on" : ""}" aria-pressed="${this._tags.has(t)}" data-act="tag" data-v="${esc(t)}" data-k="tag-${esc(t)}">#${esc(t)}</button>`
      )
      .join("");
    return `
      <div class="hdr" data-k="hdr">
        <div class="ttl">
          ${this._config.title ? `<h2>${esc(this._config.title)}</h2>` : ""}
          <div class="stats">
            <span class="stat"><i class="led ${live ? "connected" : "no_source"}"></i><b class="num">${esc(this._t("sources_live", { live, total: proto.sources.length }))}</b></span>
            <span class="stat"><i class="led ${okDests === dests.length ? "connected" : "connecting static"}"></i><span class="num">${esc(this._t("destinations", { n: dests.length }))}</span></span>
            ${this._fallback ? `<span class="badge" title="${esc(this._t("basic_mode_tip"))}">${esc(this._t("basic_mode"))}</span>` : ""}
          </div>
        </div>
        <div class="ctrls">
          ${tabs}
          ${this._seg("mode", [["panel", this._t("panel"), "panel"], ["matrix", this._t("matrix"), "matrix"]], this._mode())}
          ${this._seg("takemode", [["direct", this._t("direct"), "bolt"], ["preset", this._t("preset"), null]], this._take)}
          ${
            this._isAdmin()
              ? `<button type="button" class="ibtn tgl ${this._editMode ? "on" : ""}" aria-pressed="${this._editMode}" data-act="edit" title="${esc(this._t("edit_labels"))}" aria-label="${esc(this._t("edit_labels"))}">${icon("pencil")}</button>`
              : ""
          }
        </div>
      </div>
      <div class="filters" data-k="filters">
        <label class="search">${icon("search")}
          <input type="search" data-act="search" placeholder="${esc(this._t("search"))}" value="${esc(this._search)}" aria-label="${esc(this._t("search"))}" autocomplete="off" spellcheck="false">
          <kbd>/</kbd>
        </label>
        <div class="chips">
          <button type="button" class="chip live ${this._liveOnly ? "on" : ""}" aria-pressed="${this._liveOnly}" data-act="liveonly" data-k="liveonly"><i class="led connected"></i>${esc(this._t("live_only"))}</button>
          ${tagChips}
        </div>
      </div>`;
  }

  _destState(d) {
    const pend = this._pending.get(d.id);
    return {
      pend,
      preset: this._preset.has(d.id) ? this._preset.get(d.id) : undefined,
      status: d.available === false ? "offline" : STATUS_ORDER.includes(d.status) ? d.status : "no_source",
    };
  }

  _htmlDestTools(d, compact = false) {
    const disp = d.display;
    const dispOn = disp && (disp.state === "on" || disp.state === "playing" || disp.state === "idle");
    const tools = [];
    tools.push(
      `<button type="button" class="ibtn sm lock ${d.locked ? "on" : ""}" data-act="lock" data-d="${esc(d.id)}" aria-pressed="${d.locked}" title="${esc(this._t(d.locked ? "unlock" : "lock"))}" aria-label="${esc(this._t(d.locked ? "unlock" : "lock"))} · ${esc(d.name)}">${icon(d.locked ? "lock" : "unlock")}</button>`
    );
    tools.push(
      `<button type="button" class="ibtn sm" data-act="undo" data-d="${esc(d.id)}" ${d.can_undo && !d.locked ? "" : "disabled"} title="${esc(this._t("undo"))}" aria-label="${esc(this._t("undo"))} · ${esc(d.name)}">${icon("undo")}</button>`
    );
    if (disp) {
      const tip = disp.error
        ? `${this._t("display")}: ${disp.error}`
        : dispOn
          ? this._t("display_on", { i: disp.source || disp.configured_input || "" })
          : this._t("display_off");
      tools.push(
        `<button type="button" class="ibtn sm tv ${dispOn ? "on" : ""} ${disp.error ? "bad" : ""}" data-act="tv" data-d="${esc(d.id)}" aria-pressed="${!!dispOn}" title="${esc(tip)}" aria-label="${esc(tip)} · ${esc(d.name)}">${icon("tv")}${!compact && dispOn && disp.source ? `<span class="tvin">${esc(disp.source)}</span>` : ""}</button>`
      );
    }
    return tools.join("");
  }

  _htmlPanel(proto, dests, sources) {
    const destKeys = dests.map((d) => d.id);
    if (!destKeys.includes(this._navKey.d)) this._navKey.d = this._sel[0] || destKeys[0];
    const destHtml = dests
      .map((d) => {
        const { pend, preset, status } = this._destState(d);
        const sel = this._sel.includes(d.id);
        const [cur, curSub] = this._names(this._srcById(proto, d.current_source), d.current_source);
        const warn = d.current_source && !d.current_source_live && status !== "offline";
        const res = this._res(d.resolution);
        const multi = this._sel.length > 1 && sel;
        return `
        <div class="dest st-${status} ${sel ? "sel" : ""} ${d.locked ? "locked" : ""} ${pend ? "pending" : ""} ${preset !== undefined ? "armed" : ""}" data-k="d-${esc(d.id)}" data-shake="${esc(d.id)}">
          <button type="button" class="dest-main" data-act="dest" data-d="${esc(d.id)}" data-nav="d" data-key="${esc(d.id)}" tabindex="${d.id === this._navKey.d ? "0" : "-1"}" aria-pressed="${sel}" aria-label="${esc(this._t("dest_label"))} ${esc(d.name)}: ${esc(cur)}">
            <span class="dtop"><i class="led ${status}" title="${esc(this._t("status_" + status))}"></i><span class="dname">${esc(d.name)}</span>${multi ? `<span class="selno">${this._sel.indexOf(d.id) + 1}</span>` : ""}</span>
            <span class="dsrc ${d.current_source ? "" : "none"}">${pend ? `<span class="spinner sm"></span><span class="ell">${esc(this._t("switching"))}</span>` : `<span class="ell">${esc(cur)}</span>`}</span>
            <span class="dsub mono">${esc(pend ? this._srcName(proto, pend.source) : curSub)}</span>
            <span class="dmeta">
              ${res ? `<span class="chip res mono">${esc(res)}</span>` : `<span class="chip res mono dim">${esc(this._t("status_" + status))}</span>`}
              ${d.locked ? `<span class="chip lockchip">${icon("lock")}${esc(this._t("locked"))}</span>` : ""}
              ${warn ? `<span class="chip warnchip" title="${esc(this._t("not_sending"))}">${icon("warn")}${esc(this._t("not_sending"))}</span>` : ""}
            </span>
            ${preset !== undefined ? `<span class="armline"><b>PST</b><span class="ell">→ ${esc(this._srcName(proto, preset))}</span></span>` : ""}
          </button>
          <div class="dtools">${this._htmlDestTools(d)}</div>
        </div>`;
      })
      .join("");

    // sources for the selected destinations
    const selDests = dests.filter((d) => this._sel.includes(d.id));
    const pgm = new Set(selDests.map((d) => d.current_source || ""));
    const pst = new Set(selDests.filter((d) => this._preset.has(d.id)).map((d) => this._preset.get(d.id)));
    const pendSrc = new Set(selDests.filter((d) => this._pending.has(d.id)).map((d) => this._pending.get(d.id).source || ""));
    const usage = new Map();
    for (const d of proto.destinations) usage.set(d.current_source || "", (usage.get(d.current_source || "") || 0) + 1);
    const srcKeys = ["", ...sources.map((s) => s.id)];
    if (!srcKeys.includes(this._navKey.s)) this._navKey.s = srcKeys[0];
    const flashKey = (id) => selDests.map((d) => `${d.id}|${id}`)[0] || "";
    const tile = (id, s) => {
      const isPgm = pgm.has(id);
      const isPst = pst.has(id);
      const isPend = pendSrc.has(id);
      const live = id === "" ? true : s.live;
      const [primary, secondary] = id === "" ? [this._t("off"), this._t("off_sub")] : this._names(s, id);
      const used = usage.get(id) || 0;
      const tags = id && s.tags && s.tags.length ? s.tags.map((t) => `<span class="tag">#${esc(t)}</span>`).join("") : "";
      const foot = !live
        ? `<span class="offl">${esc(this._t("offline_since", { t: this._ago(s.last_seen) }))}</span>`
        : tags;
      const cls = ["src", id === "" ? "black" : "", isPgm ? "pgm" : "", isPst ? "pst" : "", isPend ? "pend" : "", live ? "" : "dead"]
        .filter(Boolean)
        .join(" ");
      const titleTxt = id === "" ? primary : `${id}${s.host ? " · " + s.host : ""}`;
      return `
        <button type="button" class="${cls}" data-k="s-${esc(id)}" data-act="src" data-s="${esc(id)}" data-nav="s" data-key="${esc(id)}" data-flash="${esc(flashKey(id))}" tabindex="${id === this._navKey.s ? "0" : "-1"}" aria-pressed="${isPgm}" title="${esc(titleTxt)}" aria-label="${esc(this._t("source_label"))} ${esc(primary)}${live ? "" : " (offline)"}">
          <span class="tally"></span>
          <span class="sname">${esc(primary)}</span>
          <span class="sid mono">${esc(secondary)}</span>
          <span class="sfoot">${foot}${used && id !== "" ? `<span class="use" title="${esc(this._t("in_use", { n: used }))}"><i></i>${used}</span>` : ""}</span>
        </button>`;
    };
    const cols = parseInt(this._config.columns, 10);
    const style = cols > 0 && !this._narrow ? ` style="grid-template-columns:repeat(${cols},minmax(0,1fr))"` : "";
    const srcHtml = [tile("", null), ...sources.map((s) => tile(s.id, s))].join("");
    return `
      <section class="panel" data-k="panel">
        <div class="dests" role="toolbar" aria-label="${esc(this._t("dest_label"))}" data-shake="__dests">${destHtml}</div>
        <div class="srcs-wrap">
          <div class="srcs" role="group" aria-label="${esc(this._t("source_label"))}"${style}>${srcHtml}</div>
          ${sources.length ? "" : `<div class="msg small">${esc(this._t("no_match"))}</div>`}
        </div>
      </section>`;
  }

  _htmlMatrix(proto, dests, sources) {
    const cols = [{ id: "", s: null }, ...sources.map((s) => ({ id: s.id, s }))];
    const keyOf = (r, c) => `${r}:${c}`;
    if (!this._navKey.x || !/^\d+:\d+$/.test(this._navKey.x)) this._navKey.x = "0:0";
    const head = cols
      .map(({ id, s }, c) => {
        const [primary, secondary] = id === "" ? [this._t("off"), ""] : this._names(s, id);
        const live = id === "" || s.live;
        const used = proto.destinations.some((d) => (d.current_source || "") === id);
        const tip = id === "" ? primary : `${primary}\n${id}${s.host ? " · " + s.host : ""}${live ? "" : "\n" + this._t("offline_since", { t: this._ago(s.last_seen) })}`;
        return `<th scope="col" class="ch ${live ? "" : "dead"} ${used ? "used" : ""} ${id === "" ? "black" : ""}" data-c="${c}" data-k="ch-${esc(id)}" title="${esc(tip)}" ${this._isAdmin() && id ? `data-act="label" data-s="${esc(id)}"` : ""}>
          <div class="chw"><span class="chl"><i class="led ${live ? (used ? "pgm" : "connected") : "no_source"}"></i><span class="chn">${esc(primary)}</span></span></div>
        </th>`;
      })
      .join("");
    const rows = dests
      .map((d, r) => {
        const { pend, preset, status } = this._destState(d);
        const cur = d.current_source || "";
        const warn = d.current_source && !d.current_source_live && status !== "offline";
        const res = this._res(d.resolution);
        const cells = cols
          .map(({ id, s }, c) => {
            const on = cur === id;
            const isPst = preset !== undefined && preset === id;
            const isPend = pend && (pend.source || "") === id;
            const live = id === "" || s.live;
            const name = id === "" ? this._t("off") : this._names(s, id)[0];
            const k = keyOf(r, c);
            const cls = ["xp", on ? "pgm" : "", on && warn ? "lost" : "", isPst ? "pst" : "", isPend ? "pend" : "", live ? "" : "dead"]
              .filter(Boolean)
              .join(" ");
            return `<td role="gridcell" data-r="${r}" data-c="${c}"><button type="button" class="${cls}" data-act="xp" data-d="${esc(d.id)}" data-s="${esc(id)}" data-nav="x" data-key="${k}" data-r="${r}" data-c="${c}" data-flash="${esc(d.id)}|${esc(id)}" tabindex="${this._navKey.x === k ? "0" : "-1"}" aria-pressed="${on}" aria-label="${esc(name)} → ${esc(d.name)}" ${d.locked ? 'aria-disabled="true"' : ""}><i></i></button></td>`;
          })
          .join("");
        return `<tr role="row" data-r="${r}" data-k="r-${esc(d.id)}" class="${d.locked ? "locked" : ""} ${preset !== undefined ? "armed" : ""}" data-shake="${esc(d.id)}">
          <th scope="row" class="rh" data-r="${r}">
            <div class="rhw">
              <i class="led ${status}" title="${esc(this._t("status_" + status))}"></i>
              <div class="rht">
                <div class="rhn">${esc(d.name)}</div>
                <div class="rhs ${pend ? "pending" : ""}">${
                  pend
                    ? `<span class="spinner sm"></span>${esc(this._t("switching"))}`
                    : preset !== undefined
                      ? `<span class="pstx">PST → ${esc(this._srcName(proto, preset))}</span>`
                      : `<span class="cur">${esc(this._srcName(proto, d.current_source))}</span>${res ? `<span class="chip res mono">${esc(res)}</span>` : ""}${warn ? `<span class="warnico" title="${esc(this._t("not_sending"))}">${icon("warn")}</span>` : ""}`
                }</div>
              </div>
              <div class="rtools">${this._htmlDestTools(d, true)}</div>
            </div>
          </th>
          ${cells}
        </tr>`;
      })
      .join("");
    return `
      <section class="mxwrap" data-k="matrix">
        <div class="mxscroll">
          <table class="mx" role="grid" aria-label="${esc(proto.title)} matrix" aria-rowcount="${dests.length + 1}" aria-colcount="${cols.length + 1}">
            <thead><tr role="row"><th class="corner"><div class="cornerw"><span class="cs">${esc(this._t("source_label"))} →</span><span class="cd">${esc(this._t("dest_label"))} ↓</span></div></th>${head}</tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        ${sources.length ? "" : `<div class="msg small">${esc(this._t("no_match"))}</div>`}
      </section>`;
  }

  _htmlFooter(proto, dests) {
    const armed = [...this._preset.entries()]
      .map(([id, s]) => {
        const d = dests.find((x) => x.id === id);
        return d
          ? `<span class="armchip" data-k="arm-${esc(id)}"><b>${esc(d.name)}</b><span class="arr">←</span>${esc(this._srcName(proto, s))}<button type="button" class="x" data-act="disarm" data-d="${esc(id)}" aria-label="${esc(this._t("clear"))} ${esc(d.name)}">${icon("x")}</button></span>`
          : "";
      })
      .join("");
    const n = this._preset.size;
    const canUndo = proto.destinations.some((d) => d.can_undo && !d.locked);
    const histCount = this._history ? this._history.entries.filter((e) => e.protocol === this._protocol).length : 0;
    const preset = this._take === "preset";
    return `
      <div class="ftr ${preset ? "preset" : ""} ${n ? "has-armed" : ""}" data-k="ftr">
        <div class="fl">
          <button type="button" class="btn ghost hist ${this._historyOpen ? "on" : ""}" data-act="history" aria-expanded="${this._historyOpen}">${icon("history")}<span>${esc(this._t("history"))}</span>${histCount ? `<span class="cnt">${histCount}</span>` : ""}${icon("chevron", "chev")}</button>
          <button type="button" class="btn ghost" data-act="undolast" ${canUndo ? "" : "disabled"} title="${esc(this._t("undo_last"))} (U)">${icon("undo")}<span>${esc(this._t("undo_last"))}</span></button>
        </div>
        ${
          preset
            ? `<div class="armbar" aria-live="polite">${n ? `<span class="armlbl">${esc(this._t("armed", { n }))}</span>${armed}` : `<span class="armlbl dim">${esc(this._t("nothing_armed"))} · ${esc(this._t("arm_hint"))}</span>`}</div>
               <div class="fr">
                 <button type="button" class="btn clear" data-act="clear" ${n ? "" : "disabled"}>${esc(this._t("clear"))}<kbd>Esc</kbd></button>
                 <button type="button" class="btn take ${n ? "hot" : ""}" data-act="dotake" ${n ? "" : "disabled"}>${esc(this._t("take"))}<kbd>↵</kbd></button>
               </div>`
            : `<div class="armbar"><span class="kbdhint">${icon("keyboard")}${esc(this._t("shortcuts"))}</span></div>`
        }
      </div>`;
  }

  _userName(id) {
    if (!id) return this._t("unknown_user");
    if (this._hass.user && this._hass.user.id === id) return this._hass.user.name;
    if (USER_NAMES.has(id)) return USER_NAMES.get(id) || "";
    if (this._isAdmin() && !this._usersLoading) {
      this._usersLoading = true;
      this._hass
        .callWS({ type: "config/auth/list" })
        .then((users) => {
          for (const u of users) USER_NAMES.set(u.id, u.name);
          this._render();
        })
        .catch(() => {});
    }
    return "";
  }

  _htmlHistory(proto) {
    const entries = (this._history ? this._history.entries : []).filter((e) => e.protocol === this._protocol);
    const fmt = (t) =>
      new Date(t).toLocaleTimeString(this._hass.language || undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      });
    const rows = entries
      .map((e) => {
        const d = proto.destinations.find((x) => x.id === e.dest);
        const user = this._userName(e.user_id);
        return `<li data-k="h-${e.time}-${esc(e.dest)}">
          <span class="ht mono">${esc(fmt(e.time))}</span>
          <span class="hd">${esc(d ? d.name : e.dest_name || e.dest)}</span>
          <span class="hs"><span class="arr">←</span>${esc(this._srcName(proto, e.source))}</span>
          <span class="hp">${e.previous !== undefined ? `<span class="was">${esc(this._t("was"))}</span><span class="mono">${esc(this._srcName(proto, e.previous))}</span>` : ""}</span>
          <span class="hu">${e.origin ? `<span class="tag">${esc(this._t("origin_" + e.origin))}</span>` : ""}${esc(user)}</span>
        </li>`;
      })
      .join("");
    return `<div class="history" data-k="history"><ol>${rows || `<li class="empty">${esc(this._t("no_history"))}</li>`}</ol></div>`;
  }

  /* ---------------- events (delegated once on the shadow root) */
  _bind(sr) {
    const findDest = (id) => {
      const p = this._currentProtocol();
      return p && p.destinations.find((d) => d.id === id);
    };

    sr.addEventListener("click", (e) => {
      const el = e.target.closest("[data-act]");
      if (!el || el.disabled) return;
      if (this._suppressClick) {
        this._suppressClick = false;
        return;
      }
      const act = el.dataset.act;
      const multi = e.shiftKey || e.metaKey || e.ctrlKey;
      switch (act) {
        case "proto":
          this._protocol = el.dataset.v;
          this._sel = [];
          this._preset.clear();
          this._tags.clear();
          this._render();
          break;
        case "mode":
          this._modeUser = el.dataset.v;
          this._render();
          break;
        case "takemode":
          this._take = el.dataset.v;
          if (this._take === "direct") this._preset.clear();
          this._render();
          break;
        case "edit":
          this._editMode = !this._editMode;
          this._render();
          break;
        case "tag":
          if (this._tags.has(el.dataset.v)) this._tags.delete(el.dataset.v);
          else this._tags.add(el.dataset.v);
          this._render();
          break;
        case "liveonly":
          this._liveOnly = !this._liveOnly;
          this._render();
          break;
        case "dest":
          this._selectDest(el.dataset.d, multi);
          break;
        case "src":
          this._pickSource(el.dataset.s);
          break;
        case "xp": {
          const d = findDest(el.dataset.d);
          if (!d) break;
          if (this._editMode && el.dataset.s) {
            this._openLabel(el.dataset.s);
            break;
          }
          if (d.locked) {
            this._toast(this._t("dest_locked", { d: d.name }), "warn");
            this._shake([d.id]);
            break;
          }
          this._crosspoint([d], el.dataset.s);
          break;
        }
        case "label":
          this._openLabel(el.dataset.s);
          break;
        case "lock": {
          const d = findDest(el.dataset.d);
          if (d) this._toggleLock([d]);
          break;
        }
        case "undo": {
          const d = findDest(el.dataset.d);
          if (d) this._undo([d]);
          break;
        }
        case "undolast":
          this._undo(null);
          break;
        case "tv": {
          const d = findDest(el.dataset.d);
          if (d) this._toggleDisplay(d);
          break;
        }
        case "dotake":
          this._doTake();
          break;
        case "clear":
          this._preset.clear();
          this._render();
          break;
        case "disarm":
          this._preset.delete(el.dataset.d);
          this._render();
          break;
        case "history":
          this._historyOpen = !this._historyOpen;
          this._render();
          break;
        default:
          break;
      }
    });

    sr.addEventListener("input", (e) => {
      if (e.target.dataset && e.target.dataset.act === "search") {
        this._search = e.target.value;
        this._render();
      }
    });

    // right click on a source = edit label (admin)
    sr.addEventListener("contextmenu", (e) => {
      const el = e.target.closest('[data-act="src"],[data-act="xp"],th.ch');
      const id = el && el.dataset.s;
      if (id && this._isAdmin()) {
        e.preventDefault();
        this._openLabel(id);
      }
    });

    // long press: destination = add to multi selection, source = edit label (admin)
    sr.addEventListener("pointerdown", (e) => {
      if (!this._root.contains(sr.activeElement)) this._root.focus({ preventScroll: true });
      const el = e.target.closest('[data-act="dest"],[data-act="src"]');
      clearTimeout(this._lp);
      if (!el || (e.pointerType === "mouse" && e.button !== 0)) return;
      const x = e.clientX;
      const y = e.clientY;
      this._lpStart = { x, y };
      this._lp = setTimeout(() => {
        if (el.dataset.act === "dest") {
          this._selectDest(el.dataset.d, true);
          this._suppressClick = true;
          if (navigator.vibrate) navigator.vibrate(15);
        } else if (el.dataset.s && this._isAdmin()) {
          this._suppressClick = true;
          this._openLabel(el.dataset.s);
        }
      }, LONG_PRESS_MS);
    });
    const cancelLp = (e) => {
      if (e.type === "pointermove" && this._lpStart) {
        if (Math.abs(e.clientX - this._lpStart.x) + Math.abs(e.clientY - this._lpStart.y) < 10) return;
      }
      clearTimeout(this._lp);
    };
    sr.addEventListener("pointermove", cancelLp);
    sr.addEventListener("pointerup", cancelLp);
    sr.addEventListener("pointercancel", cancelLp);

    // crosshair
    sr.addEventListener("pointerover", (e) => {
      const cell = e.target.closest && e.target.closest(".mx [data-r], .mx [data-c]");
      this._setCross(cell ? cell.getAttribute("data-r") : null, cell ? cell.getAttribute("data-c") : null);
    });
    sr.addEventListener("pointerleave", () => this._setCross(null, null), true);
    sr.addEventListener("focusin", (e) => {
      const el = e.target;
      if (el.dataset && el.dataset.nav) {
        const grp = el.dataset.nav;
        this._navKey[grp] = el.dataset.key;
        sr.querySelectorAll(`[data-nav="${grp}"]`).forEach((n) => n.setAttribute("tabindex", n === el ? "0" : "-1"));
        if (grp === "x") this._setCross(el.dataset.r, el.dataset.c);
      }
    });

    sr.addEventListener("keydown", (e) => this._onKey(e));
  }

  _setCross(r, c) {
    if (!this._hoverStyle) return;
    const css = [];
    if (r != null) css.push(`.mx tr[data-r="${r}"] > *{background-color:var(--amx-cross)}`);
    if (c != null) css.push(`.mx [data-c="${c}"]{background-color:var(--amx-cross)}`);
    if (r != null && c != null) css.push(`.mx td[data-r="${r}"][data-c="${c}"]{background-color:var(--amx-cross2)}`);
    const text = css.join("");
    if (this._hoverStyle.textContent !== text) this._hoverStyle.textContent = text;
  }

  _onKey(e) {
    const sr = this.shadowRoot;
    const t = e.composedPath()[0];
    const inInput = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA");
    if (sr.querySelector("dialog[open]")) return;
    const handled = () => {
      e.preventDefault();
      e.stopPropagation();
    };
    if (inInput) {
      if (e.key === "Escape") {
        if (t.value) {
          t.value = "";
          this._search = "";
          this._render();
        } else t.blur();
        handled();
      } else if (e.key === "ArrowDown" || e.key === "Enter") {
        const first = sr.querySelector('[data-nav="s"][tabindex="0"], [data-nav="x"][tabindex="0"]');
        if (first) first.focus();
        handled();
      }
      return;
    }
    if (e.altKey) return;
    const proto = this._currentProtocol();
    if (!proto) return;
    const key = e.key;
    if ((e.ctrlKey || e.metaKey) && key !== "Enter") return;

    if (key.startsWith("Arrow") && t.dataset && t.dataset.nav) {
      if (this._navigate(t, key)) handled();
      return;
    }
    const isButton = t && t.tagName === "BUTTON";
    switch (key) {
      case "/":
        sr.querySelector('input[data-act="search"]').focus();
        handled();
        return;
      case "Escape":
        if (this._preset.size || this._sel.length > 1 || this._editMode) {
          if (!this._preset.size && this._sel.length <= 1) this._editMode = false;
          this._clear();
          handled();
        }
        return;
      case "Enter":
        if (this._preset.size && (!isButton || e.ctrlKey || e.metaKey || t.dataset.act === "dotake")) {
          this._doTake();
          handled();
        }
        return;
      case "u":
      case "U": {
        const dests = this._focusedDests(t);
        this._undo(dests.length ? dests : null);
        handled();
        return;
      }
      case "l":
      case "L": {
        const dests = this._focusedDests(t);
        if (dests.length) this._toggleLock(dests);
        handled();
        return;
      }
      default:
        if (/^[1-9]$/.test(key) && this._mode() === "panel") {
          const d = this._destinations(proto)[parseInt(key, 10) - 1];
          if (d) {
            this._selectDest(d.id, e.shiftKey);
            handled();
          }
        }
    }
  }

  _focusedDests(t) {
    const proto = this._currentProtocol();
    if (!proto) return [];
    if (t && t.dataset && t.dataset.d) {
      const d = proto.destinations.find((x) => x.id === t.dataset.d);
      if (d) return [d];
    }
    if (this._mode() === "panel") return this._destinations(proto).filter((d) => this._sel.includes(d.id));
    return [];
  }

  _navigate(el, key) {
    const sr = this.shadowRoot;
    const grp = el.dataset.nav;
    let next = null;
    if (grp === "x") {
      let r = +el.dataset.r;
      let c = +el.dataset.c;
      if (key === "ArrowUp") r--;
      if (key === "ArrowDown") r++;
      if (key === "ArrowLeft") c--;
      if (key === "ArrowRight") c++;
      next = sr.querySelector(`[data-nav="x"][data-r="${r}"][data-c="${c}"]`);
    } else {
      const list = [...sr.querySelectorAll(`[data-nav="${grp}"]`)];
      const i = list.indexOf(el);
      const top0 = list[0].offsetTop;
      let cols = list.findIndex((n) => n.offsetTop !== top0);
      if (cols < 0) cols = list.length;
      const elTop = el.offsetTop;
      if (key === "ArrowLeft") next = list[i - 1];
      if (key === "ArrowRight") next = list[i + 1];
      if (key === "ArrowDown") {
        next = list[i + cols];
        if (!next && grp === "d") next = sr.querySelector('[data-nav="s"][tabindex="0"]');
        else if (!next && list.some((n) => n.offsetTop > elTop)) next = list[list.length - 1];
      }
      if (key === "ArrowUp") {
        next = list[i - cols];
        if (!next && grp === "s") next = sr.querySelector('[data-nav="d"][tabindex="0"]');
      }
    }
    if (next) {
      next.focus();
      next.scrollIntoView({ block: "nearest", inline: "nearest" });
      return true;
    }
    return false;
  }
}

/* ------------------------------------------------------------------ styles */
const CSS_TEXT = `
:host {
  display: block;
  --amx-tally: var(--av-matrix-tally-color, #e53935);
  --amx-tally-hi: color-mix(in srgb, var(--amx-tally) 78%, #fff);
  --amx-preset: var(--av-matrix-preset-color, #ffb300);
  --amx-ok: var(--success-color, #43a047);
  --amx-warn: var(--warning-color, #ffa600);
  --amx-err: var(--error-color, #db4437);
  --amx-lost: #ff7a3d;
  --amx-fg: var(--primary-text-color, #e6e6e6);
  --amx-fg2: var(--secondary-text-color, #9a9a9a);
  --amx-accent: var(--primary-color, #03a9f4);
  --amx-bg: var(--ha-card-background, var(--card-background-color, #1c1c1c));
  --amx-line: color-mix(in srgb, var(--amx-fg) 10%, transparent);
  --amx-line2: color-mix(in srgb, var(--amx-fg) 18%, transparent);
  --amx-tile: color-mix(in srgb, var(--amx-fg) 4%, transparent);
  --amx-tile2: color-mix(in srgb, var(--amx-fg) 7.5%, transparent);
  --amx-sunk: color-mix(in srgb, var(--amx-bg) 88%, #000);
  --amx-glass: color-mix(in srgb, var(--amx-bg) 72%, transparent);
  --amx-cross: color-mix(in srgb, var(--amx-accent) 7%, transparent);
  --amx-cross2: color-mix(in srgb, var(--amx-accent) 16%, transparent);
  --amx-mono: ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace;
  --amx-r: 12px;
  --amx-hit: 36px;
}
@media (pointer: coarse) { :host { --amx-hit: 44px; } }
.root.light { --amx-sunk: color-mix(in srgb, var(--amx-bg) 95%, #1d2a3a); --amx-tile: var(--amx-bg); --amx-tile2: var(--amx-bg);
  --amx-line: color-mix(in srgb, var(--amx-fg) 13%, transparent); --amx-line2: color-mix(in srgb, var(--amx-fg) 24%, transparent);
  --amx-glass: color-mix(in srgb, var(--amx-bg) 80%, transparent); }
.root.light .src, .root.light .dest { box-shadow: 0 1px 2px rgba(16,24,40,.06); }
.root.light .tab.on, .root.light .seg button.on { box-shadow: 0 1px 2px rgba(16,24,40,.12); }
.root.light .tag, .root.light .chip.res { background: color-mix(in srgb, var(--amx-fg) 6%, transparent); }
* { box-sizing: border-box; }
ha-card { position: relative; overflow: hidden; }
.root { outline: none; padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 12px;
  font-variant-numeric: tabular-nums; color: var(--amx-fg); }
.root.compact { padding: 10px 12px 8px; gap: 8px; }
.mono { font-family: var(--amx-mono); letter-spacing: 0; }
.num { font-variant-numeric: tabular-nums; }
.ic { width: 18px; height: 18px; flex: none; fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round; }
button { font: inherit; color: inherit; -webkit-tap-highlight-color: transparent; }
button:focus { outline: none; }
button:focus-visible, input:focus-visible, .root :focus-visible { outline: 2px solid var(--amx-accent);
  outline-offset: 2px; }
kbd { font-family: var(--amx-mono); font-size: 10px; line-height: 1; padding: 3px 5px; border-radius: 4px;
  border: 1px solid var(--amx-line2); color: var(--amx-fg2); background: var(--amx-tile); }

/* header */
.hdr { display: flex; align-items: center; justify-content: space-between; gap: 10px 16px; flex-wrap: wrap; }
.ttl { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.ttl h2 { margin: 0; font-size: 18px; font-weight: 600; letter-spacing: .01em; line-height: 1.2;
  color: var(--ha-card-header-color, var(--amx-fg)); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stats { display: flex; gap: 6px 14px; flex-wrap: wrap; font-size: 12px; color: var(--amx-fg2); align-items: center; }
.stat { display: inline-flex; align-items: center; gap: 6px; }
.stat b { font-weight: 500; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 99px; border: 1px solid var(--amx-warn); color: var(--amx-warn); }
.ctrls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tabs, .seg { display: inline-flex; padding: 3px; gap: 2px; border-radius: 10px; background: var(--amx-sunk);
  border: 1px solid var(--amx-line); }
.tab, .seg button { border: 0; background: none; cursor: pointer; min-height: 30px; padding: 0 12px; border-radius: 7px;
  font-size: 13px; font-weight: 500; color: var(--amx-fg2); display: inline-flex; align-items: center; gap: 6px;
  transition: background .15s, color .15s; white-space: nowrap; }
.tabs.single .tab { cursor: default; }
.tab.on, .seg button.on { background: var(--amx-tile2); color: var(--amx-fg);
  box-shadow: 0 1px 0 color-mix(in srgb, #fff 6%, transparent) inset, 0 1px 3px rgba(0,0,0,.25); }
.seg button .ic { width: 15px; height: 15px; }
.take-preset .seg[data-k="seg-takemode"] button.on[data-v="preset"] { color: var(--amx-preset); }
.ibtn { border: 1px solid var(--amx-line); background: var(--amx-tile); cursor: pointer; border-radius: 9px;
  width: var(--amx-hit); height: var(--amx-hit); display: inline-flex; align-items: center; justify-content: center;
  color: var(--amx-fg2); transition: background .15s, color .15s, border-color .15s; padding: 0; }
.ibtn:hover:not([disabled]) { color: var(--amx-fg); background: var(--amx-tile2); }
.ibtn[disabled] { opacity: .35; cursor: default; }
.ibtn.tgl.on { color: var(--amx-accent); border-color: color-mix(in srgb, var(--amx-accent) 50%, transparent);
  background: color-mix(in srgb, var(--amx-accent) 12%, transparent); }

/* filters */
.filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.search { position: relative; display: flex; align-items: center; gap: 8px; flex: 0 1 300px; min-width: 200px;
  height: var(--amx-hit); padding: 0 8px 0 10px; border-radius: 10px; background: var(--amx-sunk);
  border: 1px solid var(--amx-line); color: var(--amx-fg2); transition: border-color .15s, box-shadow .15s; }
.search:focus-within { border-color: color-mix(in srgb, var(--amx-accent) 60%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--amx-accent) 18%, transparent); }
.search .ic { width: 16px; height: 16px; }
.search input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; color: var(--amx-fg); font: inherit;
  font-size: 14px; height: 100%; }
.search input::-webkit-search-cancel-button { filter: grayscale(1); }
.search input:focus-visible { outline: none; }
.search:focus-within kbd { display: none; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; line-height: 1; padding: 6px 10px;
  border-radius: 99px; border: 1px solid var(--amx-line); background: var(--amx-tile); color: var(--amx-fg2);
  white-space: nowrap; }
button.chip { cursor: pointer; min-height: 30px; }
@media (pointer: coarse) { button.chip { min-height: 36px; } }
button.chip:hover { color: var(--amx-fg); }
button.chip.on { color: var(--amx-fg); border-color: color-mix(in srgb, var(--amx-accent) 55%, transparent);
  background: color-mix(in srgb, var(--amx-accent) 14%, transparent); }
.chip .ic { width: 12px; height: 12px; }
.chip .led { width: 7px; height: 7px; }

/* status LEDs */
.led { display: inline-block; flex: none; width: 9px; height: 9px; border-radius: 50%; background: #7a7a7a;
  box-shadow: 0 0 0 2px color-mix(in srgb, #7a7a7a 18%, transparent); }
.led.connected { background: var(--amx-ok); box-shadow: 0 0 0 2px color-mix(in srgb, var(--amx-ok) 22%, transparent), 0 0 8px color-mix(in srgb, var(--amx-ok) 60%, transparent); }
.led.connecting { background: #ffd23f; box-shadow: 0 0 0 2px color-mix(in srgb, #ffd23f 25%, transparent);
  animation: amx-pulse 1.1s ease-in-out infinite; }
.led.connecting.static { animation: none; }
.led.no_source { background: color-mix(in srgb, var(--amx-fg2) 70%, transparent); box-shadow: none; }
.led.source_lost { background: var(--amx-lost); box-shadow: 0 0 0 2px color-mix(in srgb, var(--amx-lost) 25%, transparent), 0 0 8px color-mix(in srgb, var(--amx-lost) 55%, transparent); }
.led.offline { background: var(--amx-err); box-shadow: 0 0 0 2px color-mix(in srgb, var(--amx-err) 25%, transparent); }
.led.pgm { background: var(--amx-tally); box-shadow: 0 0 6px var(--amx-tally); }

.edit-hint { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 8px 12px; border-radius: 10px;
  color: var(--amx-accent); background: color-mix(in srgb, var(--amx-accent) 10%, transparent);
  border: 1px dashed color-mix(in srgb, var(--amx-accent) 45%, transparent); }
.edit-hint .ic { width: 16px; height: 16px; }

/* ---------------- panel */
.panel { display: flex; flex-direction: column; gap: 14px; }
.dests { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: 10px; }
.narrow .dests { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.dest { position: relative; border-radius: var(--amx-r); background: linear-gradient(180deg, var(--amx-tile2), var(--amx-tile));
  border: 1px solid var(--amx-line); transition: border-color .15s, box-shadow .2s, transform .15s; min-width: 0; }
.dest::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 3px; border-radius: var(--amx-r) var(--amx-r) 0 0;
  background: transparent; transition: background .2s; }
.dest.st-connected::before { background: color-mix(in srgb, var(--amx-ok) 70%, transparent); }
.dest.st-connecting::before { background: #ffd23f; animation: amx-pulse 1.1s ease-in-out infinite; }
.dest.st-source_lost::before { background: var(--amx-lost); }
.dest.st-offline::before { background: var(--amx-err); }
.dest:hover { border-color: var(--amx-line2); }
.dest.sel { border-color: color-mix(in srgb, var(--amx-fg) 70%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--amx-fg) 70%, transparent), 0 8px 24px -10px rgba(0,0,0,.6);
  background: linear-gradient(180deg, color-mix(in srgb, var(--amx-fg) 12%, transparent), var(--amx-tile2)); }
.dest.armed { border-color: var(--amx-preset); box-shadow: 0 0 0 1px var(--amx-preset), 0 0 22px -6px color-mix(in srgb, var(--amx-preset) 70%, transparent); }
.dest.st-offline .dest-main { opacity: .6; }
.dest-main { display: flex; flex-direction: column; align-items: stretch; gap: 3px; width: 100%; text-align: left;
  border: 0; background: none; cursor: pointer; padding: 12px 12px 10px; border-radius: var(--amx-r) var(--amx-r) 0 0; min-height: 104px; flex: 1; }
.compact .dest-main { min-height: 84px; padding: 9px 10px 8px; }
.dtop { display: flex; align-items: center; gap: 8px; min-width: 0; }
.dname { font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--amx-fg2);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dest.sel .dname { color: var(--amx-fg); }
.selno { margin-left: auto; font-size: 10px; font-weight: 700; min-width: 18px; height: 18px; border-radius: 9px;
  display: inline-grid; place-items: center; background: var(--amx-fg); color: var(--amx-bg); }
.dsrc { font-size: 19px; font-weight: 600; line-height: 1.2; margin-top: 4px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; display: flex; align-items: center; gap: 8px; }
.compact .dsrc { font-size: 16px; }
.ell { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dsrc.none { color: var(--amx-fg2); font-weight: 500; }
.dsub { font-size: 11px; color: var(--amx-fg2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-height: 14px; }
.dmeta { display: flex; gap: 5px; flex-wrap: wrap; margin-top: auto; padding-top: 8px; align-items: center; }
.chip.res { padding: 4px 7px; border-radius: 6px; font-size: 11px; color: var(--amx-fg); background: var(--amx-sunk); }
.chip.res.dim { color: var(--amx-fg2); font-family: inherit; }
.chip.lockchip { padding: 4px 7px; border-radius: 6px; font-size: 11px; color: var(--amx-preset);
  border-color: color-mix(in srgb, var(--amx-preset) 40%, transparent); }
.chip.warnchip { padding: 4px 7px; border-radius: 6px; font-size: 11px; color: var(--amx-lost);
  border-color: color-mix(in srgb, var(--amx-lost) 45%, transparent); background: color-mix(in srgb, var(--amx-lost) 10%, transparent); }
.armline { margin-top: 8px; padding: 5px 8px; border-radius: 7px; font-size: 13px; font-weight: 600; color: #1a1300;
  background: var(--amx-preset); display: flex; gap: 8px; align-items: center; white-space: nowrap; overflow: hidden;
  animation: amx-blink 1s steps(2, jump-none) infinite; }
.armline b { font-family: var(--amx-mono); font-size: 10px; letter-spacing: .1em; opacity: .75; }
.dest { display: flex; flex-direction: column; }
.dtools { display: flex; gap: 2px; justify-content: flex-end; padding: 4px 6px; border-top: 1px solid var(--amx-line); }
.dtools .tv { margin-right: auto; }
.ibtn.sm { width: 32px; height: 32px; border-radius: 8px; background: transparent; border-color: transparent; }
@media (pointer: coarse) { .ibtn.sm { width: 40px; height: 40px; } }
.ibtn.sm:hover:not([disabled]) { border-color: var(--amx-line); }
.ibtn.sm .ic { width: 16px; height: 16px; }
.ibtn.lock.on { color: var(--amx-preset); background: color-mix(in srgb, var(--amx-preset) 14%, transparent); }
.ibtn.tv { width: auto; min-width: 32px; padding: 0 6px; gap: 5px; }
.ibtn.tv.on { color: var(--amx-ok); }
.ibtn.tv.bad { color: var(--amx-lost); }
.tvin { font-size: 10px; font-family: var(--amx-mono); }
.dest.locked .dsrc { color: color-mix(in srgb, var(--amx-fg) 75%, transparent); }
.dest.pending .dsrc { color: var(--amx-tally-hi); }

.srcs-wrap { border-radius: calc(var(--amx-r) + 4px); background: var(--amx-sunk); border: 1px solid var(--amx-line); padding: 10px; }
.srcs { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.compact .srcs { grid-template-columns: repeat(auto-fill, minmax(124px, 1fr)); gap: 6px; }
.narrow .srcs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.src { position: relative; overflow: hidden; display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  min-height: 78px; padding: 12px 11px 9px; text-align: left; cursor: pointer; border-radius: 10px;
  border: 1px solid var(--amx-line); background: linear-gradient(180deg, var(--amx-tile2), var(--amx-tile));
  transition: background .15s, border-color .15s, box-shadow .2s, transform .08s; min-width: 0; }
.compact .src { min-height: 60px; padding: 9px 9px 7px; }
.src:hover { border-color: var(--amx-line2); background: linear-gradient(180deg, color-mix(in srgb, var(--amx-fg) 11%, transparent), var(--amx-tile2)); }
.src:active { transform: scale(.98); }
.src .tally { position: absolute; inset: 0 0 auto 0; height: 3px; background: transparent; }
.sname { font-size: 15px; font-weight: 600; line-height: 1.2; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sid { font-size: 11px; color: var(--amx-fg2); max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sfoot { margin-top: auto; padding-top: 6px; display: flex; gap: 6px; align-items: center; width: 100%; min-height: 18px; font-size: 11px; color: var(--amx-fg2); }
.tag { font-size: 10.5px; padding: 2px 6px; border-radius: 5px; background: var(--amx-tile2); color: var(--amx-fg2); white-space: nowrap; }
.use { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; font-family: var(--amx-mono); font-size: 10.5px; color: var(--amx-fg2); }
.use i { width: 6px; height: 6px; border-radius: 50%; background: var(--amx-tally); box-shadow: 0 0 5px var(--amx-tally); }
.src.black .sname { color: var(--amx-fg2); }
.src.black { background: repeating-linear-gradient(135deg, var(--amx-tile) 0 8px, transparent 8px 16px); }
.src.dead { border-style: dashed; }
.src.dead .sname, .src.dead .sid { opacity: .45; }
.offl { color: var(--amx-fg2); font-style: italic; opacity: .9; }
/* tally: program (red) */
.src.pgm { border-color: color-mix(in srgb, var(--amx-tally) 85%, #000); color: #fff;
  background: linear-gradient(180deg, color-mix(in srgb, var(--amx-tally) 92%, #fff), color-mix(in srgb, var(--amx-tally) 82%, #000));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--amx-tally) 60%, transparent), 0 6px 22px -6px color-mix(in srgb, var(--amx-tally) 80%, transparent); }
.src.pgm .sid, .src.pgm .sfoot, .src.pgm .offl, .src.pgm .sname { color: rgba(255,255,255,.88); opacity: 1; }
.src.pgm .sname { color: #fff; }
.src.pgm .tag { background: rgba(0,0,0,.18); color: #fff; }
.src.pgm .use i { background: #fff; box-shadow: none; }
.src.pgm .tally { background: rgba(255,255,255,.55); }
/* preset (amber, blinking) */
.src.pst { border-color: var(--amx-preset); box-shadow: 0 0 0 1px var(--amx-preset), 0 0 20px -4px color-mix(in srgb, var(--amx-preset) 70%, transparent);
  background: linear-gradient(180deg, color-mix(in srgb, var(--amx-preset) 30%, transparent), color-mix(in srgb, var(--amx-preset) 12%, transparent)); }
.src.pst .tally { background: var(--amx-preset); animation: amx-blink 1s steps(2, jump-none) infinite; }
.src.pst.pgm .tally { background: var(--amx-preset); }
.src.pend { animation: amx-pend .8s ease-in-out infinite alternate; }

/* ---------------- matrix */
.mxwrap { border-radius: calc(var(--amx-r) + 2px); background: var(--amx-sunk); border: 1px solid var(--amx-line); overflow: hidden; }
.mxscroll { overflow: auto; max-height: var(--av-matrix-max-height, 70vh); overscroll-behavior: contain; scrollbar-width: thin; }
.mx { border-collapse: separate; border-spacing: 0; min-width: 100%; }
.mx th, .mx td { padding: 0; transition: background-color .08s; }
.mx thead th { position: sticky; top: 0; z-index: 2; background: var(--amx-glass); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--amx-line2); vertical-align: bottom; }
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) { .mx thead th { background: var(--amx-sunk); } }
.mx th.corner { left: 0; z-index: 4; text-align: left; border-right: 1px solid var(--amx-line2); }
.cornerw { display: flex; flex-direction: column; justify-content: flex-end; gap: 4px; height: 142px; padding: 10px 12px;
  font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--amx-fg2); }
.cornerw .cs { align-self: flex-end; }
.ch { cursor: default; min-width: 48px; }
.ch[data-act] { cursor: context-menu; }
.chw { height: 142px; display: flex; align-items: flex-end; justify-content: center; padding: 8px 0 10px; }
.chl { writing-mode: vertical-rl; transform: rotate(180deg); display: flex; align-items: center; gap: 6px; max-height: 126px;
  white-space: nowrap; overflow: hidden; }
.chn { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
.chs { font-size: 10px; color: var(--amx-fg2); overflow: hidden; text-overflow: ellipsis; }
.chl .led { width: 7px; height: 7px; }
.ch.dead .chn, .ch.dead .chs { opacity: .45; font-style: italic; }
.ch.black .chn { color: var(--amx-fg2); }
.mx th.rh { position: sticky; left: 0; z-index: 1; background: var(--amx-glass); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  text-align: left; border-right: 1px solid var(--amx-line2); font-weight: 400; }
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) { .mx th.rh { background: var(--amx-sunk); } }
.rhw { display: flex; align-items: center; gap: 10px; padding: 6px 8px 6px 12px; min-width: 260px; max-width: 340px; }
.narrow .rhw { min-width: 180px; max-width: 220px; }
.rht { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.rhn { font-size: 13.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rhs { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--amx-fg2); min-width: 0; white-space: nowrap; }
.rhs .cur { overflow: hidden; text-overflow: ellipsis; }
.rhs.pending { color: var(--amx-tally-hi); }
.rhs .chip.res { padding: 2px 5px; font-size: 10px; }
.pstx { color: var(--amx-preset); font-weight: 600; animation: amx-blink 1s steps(2, jump-none) infinite; }
.warnico { color: var(--amx-lost); display: inline-flex; }
.warnico .ic { width: 14px; height: 14px; }
.rtools { display: flex; gap: 0; }
.rtools .ibtn.sm { width: 30px; height: 30px; }
@media (pointer: coarse) { .rtools .ibtn.sm { width: 40px; height: 40px; } }
.rtools .tvin { display: none; }
.mx tbody tr + tr > * { border-top: 1px solid var(--amx-line); }
.mx tbody td + td, .mx thead th.ch + th.ch { border-left: 1px solid color-mix(in srgb, var(--amx-fg) 5%, transparent); }
.mx td { text-align: center; }
.xp { width: var(--amx-hit); height: var(--amx-hit); margin: 5px; border: 0; padding: 0; background: none; cursor: pointer;
  border-radius: 9px; display: inline-grid; place-items: center; position: relative; }
.xp i { width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--amx-line2); background: transparent;
  transition: transform .15s, background .15s, border-color .15s, box-shadow .2s; }
.xp:hover i { border-color: var(--amx-fg2); transform: scale(1.15); }
.xp.dead i { border-style: dashed; opacity: .6; }
.xp.pgm i { width: 20px; height: 20px; border: 0; background: radial-gradient(circle at 35% 30%, var(--amx-tally-hi), var(--amx-tally) 60%);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--amx-tally) 22%, transparent), 0 0 14px color-mix(in srgb, var(--amx-tally) 75%, transparent); }
.xp.pgm.lost i { background: radial-gradient(circle at 35% 30%, #ffb38a, var(--amx-lost) 60%);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--amx-lost) 22%, transparent); }
.xp.pst i { width: 22px; height: 22px; border: 2.5px solid var(--amx-preset); background: color-mix(in srgb, var(--amx-preset) 18%, transparent);
  box-shadow: 0 0 12px color-mix(in srgb, var(--amx-preset) 60%, transparent); animation: amx-blink 1s steps(2, jump-none) infinite; }
.xp.pgm.pst i { background: radial-gradient(circle, var(--amx-tally) 45%, transparent 50%); }
.xp.pend i { animation: amx-pend .8s ease-in-out infinite alternate; border-color: var(--amx-tally); }
.xp[aria-disabled="true"] { cursor: not-allowed; }
.xp[aria-disabled="true"] i { opacity: .5; }
tr.locked .rhn::after { content: ""; }
tr.armed th.rh { box-shadow: inset 3px 0 0 var(--amx-preset); }
.flash { animation: amx-flash .55s ease-out; }
.xp.flash i { animation: amx-pop .45s ease-out; }

/* ---------------- footer / take bar */
.ftr { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px; margin: 0 -4px; border-radius: 14px;
  border: 1px solid var(--amx-line); background: var(--amx-glass); -webkit-backdrop-filter: blur(12px) saturate(1.2);
  backdrop-filter: blur(12px) saturate(1.2); position: sticky; bottom: 8px; z-index: 5; }
.fl, .fr { display: flex; gap: 6px; align-items: center; }
.armbar { flex: 1; min-width: 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 12.5px; }
.armlbl { font-weight: 600; color: var(--amx-preset); margin-right: 4px; font-size: 12px; letter-spacing: .04em; text-transform: uppercase; }
.armlbl.dim { color: var(--amx-fg2); text-transform: none; letter-spacing: 0; font-weight: 400; }
.armchip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 4px 3px 10px; border-radius: 8px; font-size: 12.5px;
  border: 1px solid color-mix(in srgb, var(--amx-preset) 55%, transparent); background: color-mix(in srgb, var(--amx-preset) 14%, transparent); }
.armchip .arr { color: var(--amx-preset); }
.armchip .x { border: 0; background: none; cursor: pointer; padding: 3px; display: inline-flex; border-radius: 6px; color: var(--amx-fg2); }
.armchip .x .ic { width: 13px; height: 13px; }
.kbdhint { display: inline-flex; align-items: center; gap: 8px; color: var(--amx-fg2); font-size: 11.5px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.kbdhint .ic { width: 16px; height: 16px; opacity: .8; }
.narrow .kbdhint, .xs .fl .btn span { display: none; }
@media (pointer: coarse) { .kbdhint { display: none; } }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 7px; cursor: pointer; min-height: var(--amx-hit);
  padding: 0 12px; border-radius: 10px; font-size: 13px; font-weight: 500; border: 1px solid var(--amx-line);
  background: var(--amx-tile); color: var(--amx-fg); transition: background .15s, border-color .15s, box-shadow .2s, opacity .15s; }
.btn:hover:not([disabled]) { background: var(--amx-tile2); }
.btn[disabled] { opacity: .4; cursor: default; }
.btn.ghost { background: transparent; border-color: transparent; color: var(--amx-fg2); }
.btn.ghost:hover:not([disabled]) { color: var(--amx-fg); background: var(--amx-tile); }
.btn .ic { width: 16px; height: 16px; }
.btn .cnt { font-family: var(--amx-mono); font-size: 10.5px; padding: 1px 6px; border-radius: 99px; background: var(--amx-tile2); }
.btn .chev { transition: transform .2s; width: 14px; height: 14px; }
.btn.hist.on .chev { transform: rotate(180deg); }
.btn kbd { margin-left: 2px; }
.btn.clear { min-width: 104px; }
.btn.take { min-width: 132px; min-height: 46px; font-size: 16px; font-weight: 800; letter-spacing: .14em; border-radius: 11px;
  color: color-mix(in srgb, var(--amx-fg) 60%, transparent); background: var(--amx-tile); }
.btn.take kbd { color: inherit; border-color: currentColor; opacity: .6; }
.btn.take.hot { color: #fff; border-color: color-mix(in srgb, var(--amx-tally) 70%, #000);
  background: linear-gradient(180deg, color-mix(in srgb, var(--amx-tally) 90%, #fff), color-mix(in srgb, var(--amx-tally) 80%, #000));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--amx-tally) 50%, transparent), 0 6px 26px -6px var(--amx-tally); animation: amx-take 1.4s ease-in-out infinite; }
.btn.take.hot:hover { filter: brightness(1.08); }
.btn.take.hot kbd { color: #fff; }
.narrow .ftr.preset .armbar { order: 3; flex-basis: 100%; }
.narrow .ftr.preset .fr { margin-left: auto; }
.xs .ftr.preset .fr { flex: 1; }
.xs .ftr.preset .fr .btn { flex: 1; min-width: 0; }
.narrow .btn kbd { display: none; }

/* history */
.history { border-radius: 12px; border: 1px solid var(--amx-line); background: var(--amx-sunk); max-height: 260px; overflow: auto; }
.history ol { list-style: none; margin: 0; padding: 4px 0; }
.history li { display: grid; grid-template-columns: 72px minmax(110px, 180px) minmax(140px, 1.2fr) minmax(120px, 1fr) minmax(120px, auto);
  gap: 10px; align-items: center; padding: 7px 12px; font-size: 12.5px; }
.history li + li { border-top: 1px solid var(--amx-line); }
.history li.empty { display: block; color: var(--amx-fg2); }
.history li:first-child:not(.empty) { animation: amx-in .35s ease-out; }
.ht { color: var(--amx-fg2); font-size: 11.5px; }
.hd { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hs { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hs .arr { color: var(--amx-tally); margin-right: 6px; }
.hp { color: var(--amx-fg2); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hp .was { opacity: .7; margin-right: 5px; }
.hu { color: var(--amx-fg2); display: flex; gap: 6px; align-items: center; justify-content: flex-end; white-space: nowrap; }
.narrow .history li { grid-template-columns: 62px 1fr 1fr; }
.narrow .history .hp, .narrow .history .hu { display: none; }

/* messages, toasts, spinner */
.msg { display: flex; align-items: center; gap: 10px; padding: 12px 4px; color: var(--amx-fg2); }
.msg.small { padding: 10px; font-size: 13px; }
.msg.err { color: var(--amx-err); }
.spinner { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--amx-line2); border-top-color: var(--amx-tally);
  animation: amx-spin .8s linear infinite; flex: none; display: inline-block; }
.spinner.sm { width: 12px; height: 12px; border-width: 2px; }
.toasts { position: absolute; left: 50%; bottom: 76px; transform: translateX(-50%); display: flex; flex-direction: column;
  gap: 6px; align-items: center; z-index: 10; pointer-events: none; width: max-content; max-width: calc(100% - 32px); }
.toast { display: flex; gap: 8px; align-items: center; padding: 9px 14px; border-radius: 10px; font-size: 13px; color: #fff;
  background: rgba(28,28,30,.92); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  border: 1px solid rgba(255,255,255,.12); box-shadow: 0 10px 30px -10px rgba(0,0,0,.6); animation: amx-in .2s ease-out;
  transition: opacity .3s, transform .3s; }
.toast .ic { width: 16px; height: 16px; }
.toast.err { border-color: color-mix(in srgb, var(--amx-err) 70%, transparent); }
.toast.err .ic { color: #ff6b5e; }
.toast.warn .ic { color: var(--amx-preset); }
.toast.ok { border-color: color-mix(in srgb, var(--amx-ok) 60%, transparent); }
.toast.out { opacity: 0; transform: translateY(6px); }
.shake { animation: amx-shake .4s ease-in-out; }

/* dialog */
dialog { border: 1px solid var(--amx-line2); border-radius: 16px; padding: 0; width: min(440px, calc(100vw - 32px));
  color: var(--amx-fg); background: var(--amx-bg, #1c1c1c); box-shadow: 0 30px 80px -20px rgba(0,0,0,.6); }
dialog::backdrop { background: rgba(0,0,0,.45); -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px); }
.dlg-body { display: flex; flex-direction: column; gap: 14px; padding: 18px; }
.dlg-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.dlg-kicker { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--amx-fg2); }
.dlg-title { font-size: 15px; margin-top: 4px; word-break: break-all; }
.dlg-sub { font-size: 11.5px; color: var(--amx-fg2); margin-top: 2px; }
.fld { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--amx-fg2); }
.fld input { height: 42px; border-radius: 10px; border: 1px solid var(--amx-line2); background: var(--amx-sunk); color: var(--amx-fg);
  padding: 0 12px; font: inherit; font-size: 15px; outline: none; }
.fld input:focus { border-color: var(--amx-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--amx-accent) 20%, transparent); }
.dlg-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.dlg-actions { display: flex; gap: 8px; align-items: center; }
.dlg-actions .grow { flex: 1; }
.btn.primary { background: var(--amx-accent); border-color: var(--amx-accent); color: var(--text-primary-color, #fff); font-weight: 600; }
.btn.primary:hover:not([disabled]) { background: color-mix(in srgb, var(--amx-accent) 85%, #fff); }
.btn.danger { color: var(--amx-err); }

/* animations */
@keyframes amx-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
@keyframes amx-blink { 0% { opacity: 1; } 50% { opacity: .45; } 100% { opacity: 1; } }
@keyframes amx-pend { from { box-shadow: 0 0 0 0 color-mix(in srgb, var(--amx-tally) 0%, transparent); }
  to { box-shadow: 0 0 0 3px color-mix(in srgb, var(--amx-tally) 55%, transparent), 0 0 18px color-mix(in srgb, var(--amx-tally) 45%, transparent); } }
@keyframes amx-flash { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--amx-tally) 70%, transparent); filter: brightness(1.5); }
  100% { box-shadow: 0 0 0 14px transparent; filter: none; } }
@keyframes amx-pop { 0% { transform: scale(.4); } 60% { transform: scale(1.25); } 100% { transform: scale(1); } }
@keyframes amx-take { 0%, 100% { box-shadow: 0 0 0 1px color-mix(in srgb, var(--amx-tally) 50%, transparent), 0 6px 26px -8px var(--amx-tally); }
  50% { box-shadow: 0 0 0 1px color-mix(in srgb, var(--amx-tally) 50%, transparent), 0 6px 34px -2px var(--amx-tally); } }
@keyframes amx-spin { to { transform: rotate(360deg); } }
@keyframes amx-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes amx-shake { 0%, 100% { transform: none; } 20%, 60% { transform: translateX(-5px); } 40%, 80% { transform: translateX(5px); } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 1ms !important; animation-iteration-count: 1 !important; transition: none !important; }
  .led.connecting, .pstx, .armline, .src.pst .tally, .xp.pst i { animation: none !important; }
}
`;

/* ------------------------------------------------------------------ visual editor */
class AvMatrixCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    else this._render();
  }

  _schema() {
    const de = this._hass && String(this._hass.language || "").startsWith("de");
    return [
      { name: "title", selector: { text: {} } },
      {
        type: "grid",
        name: "",
        schema: [
          {
            name: "mode",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "panel", label: de ? "Panel (X-Y)" : "Panel (X-Y)" },
                  { value: "matrix", label: "Matrix" },
                ],
              },
            },
          },
          {
            name: "take_mode",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "direct", label: de ? "Direkt" : "Direct" },
                  { value: "preset", label: "Preset + TAKE" },
                ],
              },
            },
          },
        ],
      },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "protocol", selector: { select: { mode: "dropdown", custom_value: true, options: ["ndi", "dante"] } } },
          { name: "columns", selector: { number: { min: 0, max: 12, mode: "box" } } },
        ],
      },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "show_offline", selector: { boolean: {} } },
          { name: "compact", selector: { boolean: {} } },
        ],
      },
      { name: "destinations", selector: { entity: { multiple: true, filter: { integration: "av_matrix", domain: "select" } } } },
    ];
  }

  _label(schema) {
    const de = this._hass && String(this._hass.language || "").startsWith("de");
    const L = {
      title: de ? "Titel" : "Title",
      mode: de ? "Ansicht" : "View",
      take_mode: de ? "Schaltmodus" : "Take mode",
      protocol: de ? "Protokoll (Start-Tab)" : "Protocol (start tab)",
      columns: de ? "Spalten Quellen (0 = auto)" : "Source columns (0 = auto)",
      show_offline: de ? "Offline-Quellen zeigen" : "Show offline sources",
      compact: de ? "Kompakt" : "Compact",
      destinations: de ? "Ziele (Auswahl & Reihenfolge, leer = alle)" : "Destinations (selection & order, empty = all)",
    };
    return L[schema.name] || schema.name;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      if (!customElements.get("ha-form")) {
        this.innerHTML = '<p style="padding:8px">Loading editor… (or use the YAML editor)</p>';
        customElements.whenDefined("ha-form").then(() => this._render());
        return;
      }
      this.innerHTML = "";
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => this._label(s);
      this._form.addEventListener("value-changed", (ev) => {
        const cfg = { ...ev.detail.value };
        for (const k of Object.keys(cfg)) {
          if (cfg[k] === "" || cfg[k] === undefined || (Array.isArray(cfg[k]) && !cfg[k].length)) delete cfg[k];
        }
        this._config = cfg;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: cfg }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = this._schema();
    this._form.data = {
      mode: "panel",
      take_mode: "direct",
      show_offline: this._config.show_offline ?? this._config.show_offline_sources ?? true,
      compact: false,
      ...this._config,
    };
  }
}

if (!customElements.get("av-matrix-card-editor")) customElements.define("av-matrix-card-editor", AvMatrixCardEditor);
if (!customElements.get("av-matrix-card")) {
  customElements.define("av-matrix-card", AvMatrixCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "av-matrix-card",
    name: "AV Matrix",
    description: "Broadcast-style crosspoint router panel for the AV Matrix integration (NDI® decoders and more).",
    preview: false,
    documentationURL: "https://github.com/strelle/ha-av-matrix",
  });
  console.info(`%c AV-MATRIX-CARD %c ${CARD_VERSION} `, "background:#e53935;color:#fff;font-weight:700", "");
}
