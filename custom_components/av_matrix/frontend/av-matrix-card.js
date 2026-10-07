/*
 * AV Matrix card - a broadcast-style crosspoint router panel for the av_matrix integration.
 *
 *  - Panel mode (X-Y): destinations on top, sources below. Pick destination(s), then a source.
 *  - Matrix mode: destinations x sources grid with crosshair, sticky headers.
 *  - Take modes: Direct (tap = switch) or Preset + TAKE (arm one or many, TAKE = salvo).
 *  - Lock, undo, labels/tags (admin), linked displays, routing history, keyboard control.
 *  - Admin: hint for discovered receivers + "add receiver" dialog (drives the config flow in the card).
 *
 * Data: WebSocket "av_matrix/subscribe" (docs/frontend-api.md); falls back to the select entities.
 * Plain web component, no build step. Served and registered by the integration itself.
 */
const CARD_VERSION = "0.6.0";

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
    status_error: "Error",
    off_sub_grouped: "no subscription",
    all_devices: "All devices",
    from_device: "Sources",
    to_device: "Destinations",
    group_count: "{n} ch",
    expand: "Expand {g}",
    collapse: "Collapse {g}",
    sub_none: "Not subscribed",
    sub_subscribed: "Subscribed",
    sub_self: "Subscribed (own device)",
    sub_in_progress: "Connecting",
    sub_unresolved: "Unresolved",
    sub_idle: "Idle",
    sub_warning: "Warning",
    sub_error: "Error",
    edit_labels: "Edit labels",
    edit_hint: "Edit mode: tap a source or destination to rename it",
    label: "Label",
    label_ph: "Friendly name, e.g. Slides",
    label_ph_dest: "Friendly name, e.g. Foyer left",
    names: "Names",
    names_label: "Label",
    names_original: "Original",
    names_both: "Both",
    names_tip_label: "Show labels (original name where there is none) · N",
    names_tip_original: "Show the original names (device / network) · N",
    names_tip_both: "Label with the original name underneath · N",
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
    shortcuts: "Keys: / search · arrows move · Enter TAKE · Esc clear · U undo · L lock · N names · 1-9 destination",
    dest_label: "Destination",
    source_label: "Source",
    no_match: "No source matches the filter.",
    label_saved: "Label saved",
    was: "was",
    on_air: "On air",
    armed_state: "Preset",
    mod_dests: "Destinations",
    mod_sources: "Sources",
    for_dests: "for {d}",
    add_receiver: "Add receiver",
    add_short: "Add",
    found_one: "1 new receiver found",
    found_n: "{n} new receivers found",
    found_sub: "on the network, not in the matrix yet",
    found_add: "Add",
    found_tip: "{name} was found on the network - add it to the matrix",
    found_kicker: "New receiver found",
    loading_flow: "Loading…",
    flow_next: "Next",
    flow_submit: "Add",
    flow_busy: "Testing connection…",
    flow_scanning: "Searching the network…",
    flow_close: "Close",
    flow_ignore: "Ignore",
    flow_ignored: "{name} ignored",
    flow_added: "{name} added",
    flow_failed: "Setup failed",
    flow_gone: "This device is no longer waiting (added or ignored elsewhere, or Home Assistant restarted).",
    flow_settings: "Settings",
    flow_settings_tip: "Open Settings → Devices & services",
    flow_settings_needed: "This step needs the Home Assistant settings.",
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
    status_error: "Fehler",
    off_sub_grouped: "kein Abo",
    all_devices: "Alle Geräte",
    from_device: "Quellen",
    to_device: "Ziele",
    group_count: "{n} Kan.",
    expand: "{g} aufklappen",
    collapse: "{g} zuklappen",
    sub_none: "Nicht abonniert",
    sub_subscribed: "Abonniert",
    sub_self: "Abonniert (eigenes Gerät)",
    sub_in_progress: "Verbinde",
    sub_unresolved: "Nicht aufgelöst",
    sub_idle: "Inaktiv",
    sub_warning: "Warnung",
    sub_error: "Fehler",
    edit_labels: "Labels bearbeiten",
    edit_hint: "Bearbeiten: Quelle oder Ziel antippen, um es umzubenennen",
    label: "Label",
    label_ph: "Klarname, z. B. Präsentation",
    label_ph_dest: "Klarname, z. B. Foyer links",
    names: "Namen",
    names_label: "Label",
    names_original: "Original",
    names_both: "Beide",
    names_tip_label: "Labels zeigen (sonst den Originalnamen) · N",
    names_tip_original: "Originalnamen zeigen (Gerät / Netzwerk) · N",
    names_tip_both: "Label, darunter der Originalname · N",
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
    shortcuts: "Tasten: / Suche · Pfeile navigieren · Enter TAKE · Esc verwerfen · U Undo · L Sperre · N Namen · 1-9 Ziel",
    dest_label: "Ziel",
    source_label: "Quelle",
    no_match: "Keine Quelle passt zum Filter.",
    label_saved: "Label gespeichert",
    was: "vorher",
    on_air: "Auf Sendung",
    armed_state: "Vorgemerkt",
    mod_dests: "Ziele",
    mod_sources: "Quellen",
    for_dests: "für {d}",
    add_receiver: "Empfänger hinzufügen",
    add_short: "Hinzufügen",
    found_one: "1 neuer Empfänger gefunden",
    found_n: "{n} neue Empfänger gefunden",
    found_sub: "im Netzwerk, noch nicht in der Kreuzschiene",
    found_add: "Hinzufügen",
    found_tip: "{name} wurde im Netzwerk gefunden - zur Kreuzschiene hinzufügen",
    found_kicker: "Neuer Empfänger gefunden",
    loading_flow: "Lade…",
    flow_next: "Weiter",
    flow_submit: "Hinzufügen",
    flow_busy: "Teste Verbindung…",
    flow_scanning: "Durchsuche Netzwerk…",
    flow_close: "Schließen",
    flow_ignore: "Ignorieren",
    flow_ignored: "{name} ignoriert",
    flow_added: "{name} hinzugefügt",
    flow_failed: "Einrichtung fehlgeschlagen",
    flow_gone: "Dieses Gerät wartet nicht mehr (anderswo hinzugefügt oder ignoriert, oder Home Assistant wurde neu gestartet).",
    flow_settings: "Einstellungen",
    flow_settings_tip: "Einstellungen → Geräte & Dienste öffnen",
    flow_settings_needed: "Dieser Schritt geht nur in den Home-Assistant-Einstellungen.",
  },
};
/** Config-flow texts of the integration per language (frontend/get_translations), shared by all cards. */
const FLOW_TEXTS = new Map();

/* ------------------------------------------------------------------ icons (24px, stroke) */
const ICON_PATHS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  signal: '<path d="M4.5 10.5a11 11 0 0 1 15 0"/><path d="M7.8 14a6.3 6.3 0 0 1 8.4 0"/><circle cx="12" cy="18" r="1.4"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
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
  device: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10v4M11 10v4M15.5 12h2"/>',
  power: '<path d="M12 2.5v9"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7Z"/>',
  names: '<path d="M4 7h13"/><path d="M4 12.5h16" opacity=".5"/><path d="M4 17.5h10" opacity=".5"/>',
  preset: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.5"/>',
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

/* ------------------------------------------------------------------ device illustrations
 * One SVG per icon_key in ./devices/<key>.svg next to this file (served by the integration at
 * /av_matrix_static/devices/). Each key is fetched once per page, checked, namespaced (classes get an
 * "avmd-" prefix so they cannot clash with the card's CSS) and cached as a <symbol>; every card copies the
 * symbols it needs into a hidden sprite in its shadow root and draws them with <use>. Colours come from CSS
 * custom properties (--avm-led per status, --avm-dev-* per theme). Unknown key / failed fetch → generic
 * key of the protocol, else no picture. */
const DEVICE_GENERIC = { ndi: "ndi_decoder", dante: "dante_device" };
const DEVICE_ART = new Map(); // key → { state: "loading" | "ok" | "fail", symbol, led }
const DEVICE_LISTENERS = new Set();

/** Base URL of the SVGs: derived from this script's URL (HA loads it as a module → no currentScript). */
const DEVICE_BASE = (() => {
  try {
    let src = document.currentScript && document.currentScript.src;
    if (!src) {
      const el = [...document.querySelectorAll("script[src]")].find((s) => /av-matrix-card\.js/.test(s.src));
      src = el && el.src;
    }
    if (!src) {
      const m = /((?:https?|file):\/\/[^\s'"()]*?av-matrix-card\.js)/.exec(new Error().stack || "");
      src = m && m[1];
    }
    if (src) return new URL("devices/", src).href;
  } catch (_e) {
    /* fall through */
  }
  return "/av_matrix_static/devices/";
})();

/**
 * Strelle Pult-UI typefaces (Atkinson Hyperlegible Next + Mono, SIL OFL 1.1, see fonts/OFL.txt), served by the
 * integration itself (no external font service). @font-face does not work inside a shadow root, so the faces are
 * registered once on the document.
 */
(() => {
  try {
    if (document.getElementById("av-matrix-fonts")) return;
    const base = new URL("../fonts/", DEVICE_BASE).href;
    const st = document.createElement("style");
    st.id = "av-matrix-fonts";
    st.textContent = `@font-face{font-family:"Atkinson Hyperlegible Next";src:url("${base}AtkinsonHyperlegibleNext-latin.woff2") format("woff2");font-weight:400 800;font-style:normal;font-display:swap;unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2190-2193,U+21B5,U+2212,U+2215,U+221E}
@font-face{font-family:"Atkinson Hyperlegible Mono";src:url("${base}AtkinsonHyperlegibleMono-latin.woff2") format("woff2");font-weight:400 700;font-style:normal;font-display:swap;unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2190-2193,U+21B5,U+2212,U+2215,U+221E}`;
    document.head.appendChild(st);
  } catch (_e) {
    /* no document (tests) */
  }
})();

function parseDeviceSvg(key, text) {
  const t = String(text)
    .replace(/^﻿/, "")
    .replace(/^\s*(<\?xml[^>]*\?>\s*)?(<!--[\s\S]*?-->\s*)*/, "");
  if (!/^<svg[\s>]/i.test(t) || /<script/i.test(t) || t.length > 200000) throw new Error("not an svg");
  const doc = new DOMParser().parseFromString(t, "image/svg+xml");
  const svg = doc.documentElement;
  if (!svg || svg.localName !== "svg" || doc.getElementsByTagName("parsererror").length) throw new Error("bad svg");
  for (const el of [svg, ...svg.querySelectorAll("*")]) {
    if (["script", "foreignObject", "iframe", "image"].includes(el.localName)) {
      el.remove();
      continue;
    }
    for (const at of [...el.attributes]) {
      const n = at.name.toLowerCase();
      if (n.startsWith("on")) el.removeAttribute(at.name);
      else if ((n === "href" || n === "xlink:href") && !at.value.trim().startsWith("#")) el.removeAttribute(at.name);
      else if (n === "class")
        el.setAttribute("class", at.value.split(/\s+/).filter(Boolean).map((c) => "avmd-" + c).join(" "));
    }
    if (el.localName === "style") el.textContent = el.textContent.replace(/\.(-?[A-Za-z_][\w-]*)/g, ".avmd-$1");
  }
  // status LED position: the card draws a soft halo there while a destination is connecting
  let led = null;
  const l = svg.querySelector(".avmd-led");
  if (l) {
    const num = (a) => parseFloat(l.getAttribute(a)) || 0;
    if (l.localName === "circle") led = { x: num("cx"), y: num("cy"), r: num("r") };
    else if (l.localName === "ellipse") led = { x: num("cx"), y: num("cy"), r: Math.max(num("rx"), num("ry")) };
    else if (l.localName === "rect")
      led = { x: num("x") + num("width") / 2, y: num("y") + num("height") / 2, r: Math.max(num("width"), num("height")) / 2 };
    if (led && !(led.r > 0)) led = null;
  }
  const NS = "http://www.w3.org/2000/svg";
  const symbol = document.createElementNS(NS, "symbol");
  symbol.setAttribute("id", `avm-dev-${key}`);
  symbol.setAttribute("viewBox", svg.getAttribute("viewBox") || "0 0 96 64");
  for (const child of [...svg.childNodes]) symbol.appendChild(document.importNode(child, true));
  return { symbol, led };
}

/** Cached art of a key, starts the download on first use. null for invalid keys. */
function deviceArt(key) {
  if (!key || typeof key !== "string" || !/^[a-z0-9_]{1,48}$/.test(key)) return null;
  let art = DEVICE_ART.get(key);
  if (!art) {
    art = { state: "loading" };
    DEVICE_ART.set(key, art);
    fetch(`${DEVICE_BASE}${key}.svg`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => Object.assign(art, parseDeviceSvg(key, text), { state: "ok" }))
      .catch(() => {
        art.state = "fail";
      })
      .finally(() => DEVICE_LISTENERS.forEach((fn) => fn()));
  }
  return art;
}

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
const STATUS_ORDER = ["connected", "connecting", "no_source", "source_lost", "error", "offline"];
const NAME_MODES = ["label", "original", "both"];
const NAME_MODE_KEY = "av-matrix-card:name-mode";


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
    this._collapsed = new Set(); // "s:<device>" / "d:<device>" (grouped protocols, e.g. Dante)
    this._expanded = new Set(); // groups the user opened although they start closed (big groups in panel mode)
    this._srcGroup = ""; // device filter of the sources ("" = all)
    this._dstGroup = ""; // device filter of the destinations
    this._lastHtml = "";
    this._width = 0;
    this._nameMode = "both"; // label | original | both
    this._sprited = new Set(); // device art keys already in this card's sprite
    this._onArt = () => {
      this._lastHtml = "";
      this._render();
    };
  }

  _loadNameMode() {
    let stored = null;
    try {
      stored = localStorage.getItem(NAME_MODE_KEY);
    } catch (_e) {
      /* storage unavailable */
    }
    const cfg = this._config && this._config.name_mode;
    this._nameMode = NAME_MODES.includes(stored) ? stored : NAME_MODES.includes(cfg) ? cfg : "both";
  }

  _setNameMode(mode) {
    if (!NAME_MODES.includes(mode)) return;
    this._nameMode = mode;
    try {
      localStorage.setItem(NAME_MODE_KEY, mode);
    } catch (_e) {
      /* storage unavailable */
    }
    this._render();
  }

  _storeKey() {
    return `av-matrix-card:collapsed:${(this._config && this._config.title) || ""}`;
  }

  _saveCollapsed() {
    try {
      localStorage.setItem(this._storeKey(), JSON.stringify({ c: [...this._collapsed], e: [...this._expanded] }));
    } catch (_e) {
      /* storage unavailable */
    }
  }

  _loadCollapsed() {
    try {
      const v = JSON.parse(localStorage.getItem(this._storeKey()) || "{}");
      const strings = (a) => (Array.isArray(a) ? a.filter((x) => typeof x === "string") : []);
      this._collapsed = new Set(strings(v.c));
      this._expanded = new Set(strings(v.e));
    } catch (_e) {
      /* storage unavailable */
    }
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
      theme: "auto",
      ...c,
    };
    if (!["panel", "matrix"].includes(this._config.mode)) this._config.mode = "panel";
    if (!["direct", "preset"].includes(this._config.take_mode)) this._config.take_mode = "direct";
    this._take = this._config.take_mode;
    this._protocol = this._config.protocol || this._protocol;
    this._modeUser = null;
    this._loadCollapsed();
    this._loadNameMode();
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
    if (!this._tick)
      this._tick = setInterval(() => {
        if (this._foundPoll && !(this._tickN = ((this._tickN || 0) + 1) % 4)) this._loadFound(); // every 60 s
        this._render();
      }, 15000);
    DEVICE_LISTENERS.add(this._onArt);
    this._render();
  }

  disconnectedCallback() {
    this._unsubscribe();
    DEVICE_LISTENERS.delete(this._onArt);
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
    return { title: "AV Matrix", mode: "panel", take_mode: "direct", name_mode: "both" };
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
    this._watchFound();
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
    this._unwatchFound();
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
      const p = (out.protocols[key] ||= { title: key === "ndi" ? "NDI®" : key === "dante" ? "Dante®" : key.toUpperCase(), _src: new Map(), destinations: [] });
      const offl = new Set(a.offline_options || []);
      for (const opt of a.options || []) {
        if (opt !== "None" && !p._src.has(opt))
          p._src.set(opt, { id: opt, name: opt, label: null, tags: [], live: !offl.has(opt), host: null, last_seen: null });
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

  _destinations(proto, ignoreGroup = false) {
    const wanted = this._config && Array.isArray(this._config.destinations) ? this._config.destinations : null;
    let out = proto.destinations;
    if (wanted && wanted.length) {
      out = [];
      for (const id of wanted) {
        const d = proto.destinations.find((x) => x.entity_id === id || x.id === id);
        if (d) out.push(d);
      }
    }
    if (this._dstGroup && !ignoreGroup) out = out.filter((d) => d.group === this._dstGroup);
    return out;
  }

  /** Protocols whose sources/destinations belong to devices (Dante) are shown grouped by device. */
  _grouped(proto) {
    return proto.sources.some((s) => s.group) || proto.destinations.some((d) => d.group);
  }

  /** [[group, items]] in order of appearance. */
  _groups(items) {
    const out = new Map();
    for (const it of items) {
      const g = it.group || "";
      if (!out.has(g)) out.set(g, []);
      out.get(g).push(it);
    }
    return [...out.entries()];
  }

  /** Big device groups (> 16 channels) start collapsed in panel mode, everything starts open in the matrix. */
  _isClosed(key, n) {
    if (this._collapsed.has(key)) return true;
    if (this._expanded.has(key)) return false;
    return this._mode() === "panel" && n > 16;
  }

  _toggleGroup(key, n) {
    if (this._isClosed(key, n)) {
      this._collapsed.delete(key);
      this._expanded.add(key);
    } else {
      this._expanded.delete(key);
      this._collapsed.add(key);
    }
    this._saveCollapsed();
  }

  /** Original (device) name of a destination; short = channel only inside a device group. */
  _destOrig(d, short = true) {
    if (short && d.group && d.channel) return d.channel;
    return d.original_name || d.name;
  }

  /** [primary, secondary] name of a destination for the current name mode (secondary only in "both"). */
  _dnames(d, short = true) {
    const orig = this._destOrig(d, short);
    const label = d.label;
    if (!label || this._nameMode === "original") return [orig, ""];
    if (this._nameMode === "label") return [label, ""];
    return label === orig || label === (d.original_name || d.name) ? [label, ""] : [label, orig];
  }

  /** One-line destination name (chips, history, toasts): primary name of the mode, never just a channel. */
  _dTitle(d) {
    return this._dnames(d, false)[0];
  }

  /** Tooltip: label and original name. */
  _dTip(d) {
    const orig = this._destOrig(d, false);
    const model = [d.manufacturer, d.model].filter(Boolean).join(" ");
    return [d.label && d.label !== orig ? `${d.label}\n${orig}` : orig, model].filter(Boolean).join("\n");
  }

  /** Target of a service call: the select entity, or the destination id (entities may be disabled). */
  _tgt(d) {
    return d.entity_id ? { entity_id: d.entity_id } : { destination: [d.id] };
  }

  _sources(proto) {
    const q = this._search.trim().toLowerCase();
    const showOffline = this._config.show_offline !== false && !this._liveOnly;
    const current = new Set(proto.destinations.map((d) => d.current_source));
    return proto.sources.filter((s) => {
      if (!showOffline && !s.live && !current.has(s.id)) return false;
      if (this._tags.size && !(s.tags || []).some((t) => this._tags.has(t))) return false;
      if (this._srcGroup && s.group !== this._srcGroup) return false;
      if (!q) return true;
      return [s.name, s.label, s.original_name, s.id, s.channel, s.group, s.host, ...(s.tags || [])].some(
        (v) => v && String(v).toLowerCase().includes(q)
      );
    });
  }

  _mode() {
    if (this._modeUser) return this._modeUser;
    return this._narrow ? "panel" : this._config.mode;
  }

  _isLight() {
    const forced = this._config && this._config.theme;
    if (forced === "daylight" || forced === "light") return true;
    if (forced === "dark") return false;
    const th = this._hass && this._hass.themes;
    if (th && typeof th.darkMode === "boolean") return !th.darkMode;
    // no theme info: look at the card background
    try {
      const cs = getComputedStyle(this);
      const bg = (cs.getPropertyValue("--ha-card-background") || cs.getPropertyValue("--card-background-color")).trim();
      const m = /^#([0-9a-f]{6})$/i.exec(bg) || /^#([0-9a-f]{3})$/i.exec(bg);
      if (m) {
        const hex = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
        const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5;
      }
      const rgb = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(bg);
      if (rgb) return (0.2126 * rgb[1] + 0.7152 * rgb[2] + 0.0722 * rgb[3]) / 255 > 0.5;
    } catch (_e) {
      /* not rendered yet */
    }
    return false;
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

  /** Original name of a source split for display: "Stream" over "MACHINE" (NDI), channel over device (Dante). */
  _origParts(src, id) {
    if (src && src.group && src.channel) return [src.channel, src.group];
    const name = (src && src.original_name) || (src && src.id) || id;
    const m = /^(.*?)\s*\((.+)\)$/.exec(name);
    if (m) return [m[2], m[1]];
    if (!src) {
      const at = name.lastIndexOf("@");
      return at > 0 ? [name.slice(0, at), name.slice(at + 1)] : [name, ""];
    }
    return [name, src.host || ""];
  }

  /** [primary, secondary] text for a source in the current name mode (label | original | both). */
  _names(src, id) {
    if (!src && !id) return [this._t("off"), ""];
    const orig = this._origParts(src, id);
    const label = src && src.label;
    if (!label || this._nameMode === "original") return orig;
    if (this._nameMode === "label") return [label, ""];
    const full = src.group && src.channel ? src.channel : src.original_name || src.id;
    return label === full ? orig : [label, full];
  }

  /** Tooltip of a source: label, original name, host. */
  _srcTip(src, id) {
    if (!src) return id || this._t("off");
    const orig = src.original_name || src.id;
    return [src.label && src.label !== orig ? src.label : "", orig + (src.host ? ` · ${src.host}` : "")]
      .filter(Boolean)
      .join("\n");
  }

  /* ---------------- device illustrations */
  /** Status → LED colour class of the illustration. */
  _art(key, protoKey, state, cls = "") {
    let art = deviceArt(key);
    if (art && art.state === "fail") {
      const generic = DEVICE_GENERIC[protoKey];
      key = generic && generic !== key ? generic : null;
      art = key ? deviceArt(key) : null;
    } else if (!art) {
      key = DEVICE_GENERIC[protoKey] || null;
      art = key ? deviceArt(key) : null;
    }
    if (!art || art.state === "fail") return "";
    if (art.state !== "ok") return `<span class="dev ${cls} wait" aria-hidden="true"></span>`;
    this._needArt(key, art);
    const halo =
      state === "connecting" && art.led
        ? `<circle class="halo" cx="${art.led.x}" cy="${art.led.y}" r="${Math.max(art.led.r * 2.6, 4)}"/>`
        : "";
    return `<svg class="dev ${cls} s-${esc(state)}" viewBox="${esc(art.symbol.getAttribute("viewBox"))}" aria-hidden="true" focusable="false"><use href="#avm-dev-${key}"/>${halo}</svg>`;
  }

  _needArt(key, art) {
    if (this._sprited.has(key) || !this._sprite) return;
    this._sprited.add(key);
    this._sprite.appendChild(art.symbol.cloneNode(true));
  }

  /** Aggregated status of a group of destinations (device header). */
  _groupState(items) {
    const st = items.map((d) => this._destState(d).status);
    if (st.every((x) => x === "offline")) return "offline";
    for (const s of ["error", "source_lost", "connecting", "connected"]) if (st.includes(s)) return s;
    return "no_source";
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
          ? this._t(blocked[0][0].locked ? "dest_locked" : "dest_offline", { d: this._dTitle(blocked[0][0]) })
          : this._t("dests_locked", { d: blocked.map(([d]) => this._dTitle(d)).join(", ") }),
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
        await this._hass.callService("av_matrix", "route", { ...this._tgt(ok[0][0]), source: src(ok[0][1]) });
      } else {
        await this._hass.callService("av_matrix", "salvo", {
          routes: ok.map(([d, s]) => ({ destination: d.entity_id || d.id, source: src(s) })),
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
    if (this._editMode && sourceId) return this._openLabel("source", sourceId);
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
      this._toast(this._t("dest_locked", { d: locked.map((d) => this._dTitle(d)).join(", ") }), "warn");
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
    for (const d of dests) this._call("av_matrix", d.locked ? "unlock" : "lock", this._tgt(d));
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
      this._call("av_matrix", "undo", this._tgt(d)).then(() => this._render());
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
  /** Label editor (admin) for kind "source" (id = source id) or "destination" (id = destination id). */
  _openLabel(kind, id) {
    if (!this._isAdmin()) return;
    const proto = this._currentProtocol();
    if (!proto) return;
    const dest = kind === "destination";
    const item = dest ? proto.destinations.find((d) => d.id === id) : this._srcById(proto, id);
    if (!item) return;
    const dlg = this.shadowRoot.querySelector("dialog");
    const allTags = dest ? [] : [...new Set(proto.sources.flatMap((s) => s.tags || []))].sort();
    const orig = dest ? this._destOrig(item, false) : item.original_name || item.id;
    const sub = dest ? [item.manufacturer, item.model].filter(Boolean).join(" ") : item.host;
    const art = this._art(item.icon_key, this._protocol, dest ? this._destState(item).status : item.live ? "connected" : "no_source", "dlgart");
    dlg.innerHTML = `
      <form method="dialog" class="dlg-body">
        <div class="dlg-head">
          ${art}
          <div class="dlg-id"><div class="dlg-kicker">${esc(this._t("edit_labels"))} · ${esc(this._t(dest ? "dest_label" : "source_label"))} · ${esc(proto.title)}</div>
          <div class="dlg-title mono">${esc(orig)}</div>
          ${sub ? `<div class="dlg-sub mono">${esc(sub)}</div>` : ""}</div>
          <button type="button" class="ibtn" data-dlg="cancel" aria-label="${esc(this._t("cancel"))}">${icon("x")}</button>
        </div>
        <label class="fld"><span>${esc(this._t("label"))}</span>
          <input name="label" autocomplete="off" value="${esc(item.label || "")}" placeholder="${esc(this._t(dest ? "label_ph_dest" : "label_ph"))}"></label>
        ${dest ? "" : `<label class="fld"><span>${esc(this._t("tags"))}</span>
          <input name="tags" autocomplete="off" value="${esc((item.tags || []).join(", "))}" placeholder="${esc(this._t("tags_ph"))}"></label>`}
        ${
          allTags.length
            ? `<div class="dlg-tags">${allTags.map((t) => `<button type="button" class="chip" data-addtag="${esc(t)}">#${esc(t)}</button>`).join("")}</div>`
            : ""
        }
        <div class="dlg-actions">
          ${item.label || (!dest && (item.tags || []).length) ? `<button type="button" class="btn ghost danger" data-dlg="reset">${esc(this._t("reset"))}</button>` : "<span></span>"}
          <span class="grow"></span>
          <button type="button" class="btn ghost" data-dlg="cancel">${esc(this._t("cancel"))}</button>
          <button type="submit" class="btn primary" data-dlg="save">${esc(this._t("save"))}</button>
        </div>
      </form>`;
    this._dlgTarget = { kind: dest ? "destination" : "source", id: item.id, tags: item.tags || [] };
    if (dlg.open) dlg.close();
    dlg.showModal();
    setTimeout(() => dlg.querySelector('input[name="label"]').focus(), 30);
  }

  async _sendLabel(target, label, tags) {
    const msg =
      target.kind === "destination"
        ? { type: "av_matrix/label", kind: "destination", destination: target.id, label, tags }
        : { type: "av_matrix/label", protocol: this._protocol, source: target.id, label, tags };
    try {
      await this._hass.connection.sendMessagePromise(msg);
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
      const target = this._dlgTarget;
      // destinations: no tag field in the editor - keep the stored tags
      const tags = form.elements.tags
        ? form.elements.tags.value
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean)
        : target.tags;
      dlg.close();
      this._sendLabel(target, label || null, tags.length ? tags : null);
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
        const target = this._dlgTarget;
        this._sendLabel(target, null, target.kind === "destination" && target.tags.length ? target.tags : null);
      }
    });
    // keys typed in the dialog must not reach the card / HA shortcuts
    dlg.addEventListener("keydown", (e) => e.stopPropagation());
  }

  /* ---------------- discovered devices + add-device dialog (admin)
   * Discovered devices are config flows of this integration started by DHCP / zeroconf
   * (WS av_matrix/discovered). The dialog drives any av_matrix config flow over Home Assistant's
   * REST flow API and renders its forms itself (texts from the integration's translations). */
  _canAdd() {
    return this._isAdmin() && !!(this._hass && this._hass.connection);
  }

  _watchFound() {
    if (!this._canAdd() || this._foundUnsub || this._foundOff) return;
    this._loadFound();
    // any config flow change (discovered, finished, ignored) → reload; admin-only HA command
    const unsub = this._hass.connection.subscribeMessage(
      () => {
        clearTimeout(this._foundTimer);
        this._foundTimer = setTimeout(() => this._loadFound(), 400);
      },
      { type: "config_entries/flow/subscribe" }
    );
    this._foundUnsub = unsub;
    unsub.catch(() => {
      if (this._foundUnsub === unsub) this._foundUnsub = null;
      this._foundPoll = true; // fall back to polling with the render tick
    });
  }

  _unwatchFound() {
    if (this._foundUnsub) {
      this._foundUnsub.then((u) => u()).catch(() => {});
      this._foundUnsub = null;
    }
    clearTimeout(this._foundTimer);
  }

  async _loadFound() {
    if (!this._canAdd() || this._foundOff) return;
    try {
      const res = await this._hass.connection.sendMessagePromise({ type: "av_matrix/discovered" });
      this._found = (res && res.flows) || [];
    } catch (err) {
      if (err && err.code === "unknown_command") this._foundOff = true; // older integration
      this._found = [];
    }
    this._render();
  }

  _htmlFound() {
    const found = this._canAdd() ? this._found || [] : [];
    if (!found.length) return "";
    const n = found.length;
    return `
      <div class="found" data-k="found" role="status">
        <div class="found-txt">${icon("signal")}<span><b>${esc(this._t(n === 1 ? "found_one" : "found_n", { n }))}</b>
          <span class="found-sub">${esc(this._t("found_sub"))}</span></span></div>
        <div class="found-list">${found
          .map(
            (f) => `<button type="button" class="found-dev" data-act="found" data-f="${esc(f.flow_id)}" data-k="found-${esc(f.flow_id)}"
              title="${esc(this._t("found_tip", { name: f.name || f.host || "" }))}">
              ${this._art(f.icon_key, "ndi", "no_source", "fart")}
              <span class="fdn"><span class="ell">${esc(f.name || f.host || "?")}</span>
                <span class="fdh mono">${esc([f.host && f.host !== f.name ? f.host : "", (f.source || "").toUpperCase()].filter(Boolean).join(" · "))}</span></span>
              <span class="fadd">${icon("plus")}<span>${esc(this._t("found_add"))}</span></span>
            </button>`
          )
          .join("")}</div>
      </div>`;
  }

  _htmlAddBtn() {
    if (!this._canAdd()) return "";
    const t = this._t("add_receiver");
    return `<button type="button" class="ibtn addbtn" data-act="addflow" title="${esc(t)}" aria-label="${esc(t)}">${icon("plus")}<span>${esc(this._t("add_short"))}</span></button>`;
  }

  async _flowTexts() {
    const lang = (this._hass && this._hass.language) || "en";
    if (FLOW_TEXTS.has(lang)) return FLOW_TEXTS.get(lang);
    let res = {};
    try {
      const r = await this._hass.callWS({ type: "frontend/get_translations", language: lang, category: "config", integration: ["av_matrix"] });
      res = (r && r.resources) || {};
    } catch (_e) {
      res = {};
    }
    FLOW_TEXTS.set(lang, res);
    return res;
  }

  _ftr(key, vars) {
    const res = (this._flow && this._flow.texts) || {};
    let s = res[`component.av_matrix.config.${key}`];
    if (s == null) return "";
    for (const [k, v] of Object.entries(vars || {})) s = s.split(`{${k}}`).join(v ?? "");
    return s;
  }

  /** Open the dialog: flowId = a discovered flow (continue it), null = start "add receiver". */
  async _openFlow(flowId) {
    if (!this._canAdd()) return;
    const found = flowId ? (this._found || []).find((f) => f.flow_id === flowId) : null;
    this._flow = { id: flowId, discovered: !!flowId, found, result: null, busy: true, error: null, values: {}, done: false };
    const dlg = this.shadowRoot.querySelector("dialog.flowdlg");
    this._renderFlow();
    if (!dlg.open) dlg.showModal();
    const flow = this._flow;
    flow.texts = await this._flowTexts();
    try {
      const result = flowId
        ? await this._hass.callApi("GET", `config/config_entries/flow/${encodeURIComponent(flowId)}`)
        : await this._hass.callApi("POST", "config/config_entries/flow", { handler: "av_matrix", show_advanced_options: false });
      if (this._flow !== flow) return;
      this._flowResult(result);
    } catch (err) {
      if (this._flow !== flow) return;
      flow.busy = false;
      flow.error = flowId ? this._t("flow_gone") : `${this._t("flow_failed")}: ${this._errText(err)}`;
      flow.dead = true;
      this._renderFlow();
      if (flowId) this._loadFound();
    }
  }

  _errText(err) {
    if (!err) return "";
    if (typeof err === "string") return err;
    return (err.body && (err.body.message || err.body.error)) || err.message || err.error || String(err);
  }

  _flowResult(result) {
    const flow = this._flow;
    flow.busy = false;
    flow.result = result;
    flow.id = result.flow_id || flow.id;
    flow.error = null;
    if (result.type === "create_entry") {
      flow.done = true;
      this.shadowRoot.querySelector("dialog.flowdlg").close();
      this._toast(this._t("flow_added", { name: result.title || "" }), "ok");
      this._loadFound();
      return;
    }
    if (result.type === "abort") flow.done = true;
    if (result.type === "form" && result.step_id !== (flow.step || null)) flow.values = {};
    flow.step = result.step_id;
    this._renderFlow();
    setTimeout(() => {
      const dlg = this.shadowRoot.querySelector("dialog.flowdlg");
      const first = dlg && dlg.querySelector(".fbody input:not([type=hidden]):not([type=radio]), .fbody select, .fbody .opt input:checked, [data-fmenu]");
      if (first) first.focus();
    }, 30);
  }

  async _flowSend(input) {
    const flow = this._flow;
    if (!flow || !flow.id || flow.busy) return;
    flow.busy = true;
    flow.values = input;
    this._renderFlow();
    try {
      const result = await this._hass.callApi("POST", `config/config_entries/flow/${encodeURIComponent(flow.id)}`, input);
      if (this._flow !== flow) return;
      this._flowResult(result);
    } catch (err) {
      if (this._flow !== flow) return;
      flow.busy = false;
      flow.error = `${this._t("flow_failed")}: ${this._errText(err)}`;
      this._renderFlow();
    }
  }

  _flowField(f, step, errors, values) {
    const sel = f.selector || {};
    const d = f.description || {};
    let value = values[f.name];
    if (value === undefined) value = d.suggested_value !== undefined ? d.suggested_value : f.default;
    const label = this._ftr(`step.${step}.data.${f.name}`) || f.name;
    const help = this._ftr(`step.${step}.data_description.${f.name}`);
    const err = errors[f.name] ? this._ftr(`error.${errors[f.name]}`) || errors[f.name] : "";
    const id = `ff-${f.name}`;
    const req = f.required ? "required" : "";
    const desc = `${help ? `<span class="fhelp" id="${id}-h">${esc(help)}</span>` : ""}${err ? `<span class="ferr" id="${id}-e" role="alert">${icon("warn")}${esc(err)}</span>` : ""}`;
    const aria = `${err ? `aria-invalid="true"` : ""} aria-describedby="${id}-h ${id}-e"`;
    if (sel.select) {
      const opts = (sel.select.options || []).map((o) => (typeof o === "string" ? { value: o, label: o } : o));
      const multiple = !!sel.select.multiple;
      if (sel.select.mode === "list" || multiple) {
        const cur = multiple ? new Set(value || []) : new Set(value != null ? [value] : []);
        return `<fieldset class="fld opts-fld" data-fname="${esc(f.name)}" data-ftype="${multiple ? "multi" : "radio"}"><legend>${esc(label)}</legend>
          <div class="opts">${opts
            .map(
              (o) => `<label class="opt"><input type="${multiple ? "checkbox" : "radio"}" name="${esc(f.name)}" value="${esc(o.value)}" ${cur.has(o.value) ? "checked" : ""} ${!multiple && f.required ? "required" : ""}><span class="optk"></span><span class="optl">${esc(o.label)}</span></label>`
            )
            .join("")}</div>${desc}</fieldset>`;
      }
      return `<label class="fld" data-fname="${esc(f.name)}" data-ftype="text"><span>${esc(label)}</span>
        <select name="${esc(f.name)}" ${req} ${aria}>${f.required ? "" : '<option value=""></option>'}${opts
          .map((o) => `<option value="${esc(o.value)}" ${o.value === value ? "selected" : ""}>${esc(o.label)}</option>`)
          .join("")}</select>${desc}</label>`;
    }
    if (sel.boolean !== undefined || f.type === "boolean") {
      return `<label class="fld chk" data-fname="${esc(f.name)}" data-ftype="bool"><input type="checkbox" name="${esc(f.name)}" ${value ? "checked" : ""}><span>${esc(label)}</span>${desc}</label>`;
    }
    const num = sel.number || (f.type === "integer" || f.type === "float" ? {} : null);
    const pw = sel.text && sel.text.type === "password";
    const type = num ? "number" : pw ? "password" : "text";
    const extra = num ? `inputmode="numeric" ${num.min != null ? `min="${num.min}"` : ""} ${num.max != null ? `max="${num.max}"` : ""} step="${num.step || 1}"` : "";
    return `<label class="fld" data-fname="${esc(f.name)}" data-ftype="${num ? "num" : "text"}"><span>${esc(label)}</span>
      <input name="${esc(f.name)}" type="${type}" value="${esc(value ?? "")}" ${req} ${extra} ${aria} autocomplete="${pw ? "new-password" : "off"}" spellcheck="false" ${type === "text" ? 'autocapitalize="off"' : ""}>${desc}</label>`;
  }

  _flowInput(form) {
    const out = {};
    for (const el of form.querySelectorAll("[data-fname]")) {
      const name = el.dataset.fname;
      const t = el.dataset.ftype;
      if (t === "multi") out[name] = [...el.querySelectorAll("input:checked")].map((i) => i.value);
      else if (t === "radio") {
        const c = el.querySelector("input:checked");
        if (c) out[name] = c.value;
      } else if (t === "bool") out[name] = el.querySelector("input").checked;
      else {
        const v = el.querySelector("input,select").value;
        if (v === "") continue;
        out[name] = t === "num" ? Number(v) : v;
      }
    }
    return out;
  }

  _md(text) {
    return esc(text)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/\n/g, "<br>");
  }

  _renderFlow() {
    const dlg = this.shadowRoot && this.shadowRoot.querySelector("dialog.flowdlg");
    const flow = this._flow;
    if (!dlg || !flow) return;
    const r = flow.result || {};
    const step = r.step_id || "";
    const ph = r.description_placeholders || {};
    const found = flow.found;
    const title =
      (r.type === "abort" ? "" : this._ftr(`step.${step}.title`, ph)) ||
      (found ? found.name || found.host : this._t("add_receiver"));
    const kicker = [this._t(flow.discovered ? "found_kicker" : "add_receiver"), found && found.host && found.host !== title ? found.host : ""]
      .filter(Boolean)
      .join(" · ");
    const art = this._art((found && found.icon_key) || "ndi_decoder", "ndi", flow.busy ? "connecting" : flow.error || (r.errors && r.errors.base) ? "error" : "no_source", "dlgart");
    const errors = r.errors || {};
    let body = "";
    let primary = "";
    if (flow.busy && !r.type) {
      body = `<div class="msg"><span class="spinner"></span><span>${esc(this._t("loading_flow"))}</span></div>`;
    } else if (r.type === "menu") {
      const desc = this._ftr(`step.${step}.description`, ph);
      const opts = Array.isArray(r.menu_options) ? r.menu_options : Object.keys(r.menu_options || {});
      body = `${desc ? `<p class="fdesc">${this._md(desc)}</p>` : ""}<div class="fmenu">${opts
        .map(
          (o) => `<button type="button" class="fmenu-k" data-fmenu="${esc(o)}" ${flow.busy ? "disabled" : ""}>${icon(o === "scan" ? "search" : "device")}<span>${esc(this._ftr(`step.${step}.menu_options.${o}`) || o)}</span>${icon("chevron", "go")}</button>`
        )
        .join("")}</div>`;
    } else if (r.type === "form") {
      const desc = this._ftr(`step.${step}.description`, ph);
      const base = errors.base ? this._ftr(`error.${errors.base}`) || errors.base : "";
      body = `${desc ? `<p class="fdesc">${this._md(desc)}</p>` : ""}
        ${base ? `<div class="fbase" role="alert">${icon("warn")}<span>${esc(base)}</span></div>` : ""}
        <div class="fbody">${(r.data_schema || []).map((f) => this._flowField(f, step, errors, flow.values || {})).join("")}</div>`;
      primary = `<button type="submit" class="btn primary" ${flow.busy ? "disabled" : ""}>${
        flow.busy ? `<span class="spinner sm"></span>` : ""
      }${esc(this._t(flow.busy ? (step === "scan" ? "flow_scanning" : "flow_busy") : ["confirm", "device", "network"].includes(step) ? "flow_submit" : "flow_next"))}</button>`;
    } else if (r.type === "abort") {
      const reason = this._ftr(`abort.${r.reason}`, ph) || r.reason;
      body = `<div class="fbase" role="alert">${icon("warn")}<span>${esc(reason)}</span></div>`;
    } else if (r.type) {
      body = `<div class="fbase" role="alert">${icon("warn")}<span>${esc(this._t("flow_settings_needed"))}</span></div>`;
    }
    if (flow.error) body = `<div class="fbase" role="alert">${icon("warn")}<span>${esc(flow.error)}</span></div>${flow.dead ? "" : body}`;
    const settings = `<button type="button" class="btn ghost" data-fdlg="settings" title="${esc(this._t("flow_settings_tip"))}">${icon("external")}<span>${esc(this._t("flow_settings"))}</span></button>`;
    const ignore =
      flow.discovered && !flow.done && !flow.dead
        ? `<button type="button" class="btn ghost" data-fdlg="ignore" ${flow.busy ? "disabled" : ""}>${esc(this._t("flow_ignore"))}</button>`
        : "";
    dlg.innerHTML = `
      <form method="dialog" class="dlg-body" novalidate>
        <div class="dlg-head">
          ${art}
          <div class="dlg-id"><div class="dlg-kicker">${esc(kicker)}</div>
          <div class="dlg-title">${esc(title)}</div></div>
          <button type="button" class="ibtn" data-fdlg="cancel" aria-label="${esc(this._t("cancel"))}">${icon("x")}</button>
        </div>
        ${body}
        <div class="dlg-actions">
          ${ignore}${settings}
          <span class="grow"></span>
          <button type="button" class="btn ghost" data-fdlg="cancel">${esc(this._t(flow.done || flow.dead ? "flow_close" : "cancel"))}</button>
          ${primary}
        </div>
      </form>`;
  }

  _closeFlow() {
    const flow = this._flow;
    this._flow = null;
    // a flow the user started here is removed again; discovered devices keep waiting
    if (flow && flow.id && !flow.discovered && !flow.done && !flow.dead) {
      this._hass.callApi("DELETE", `config/config_entries/flow/${encodeURIComponent(flow.id)}`).catch(() => {});
    }
  }

  _bindFlowDialog(dlg) {
    dlg.addEventListener("close", () => this._closeFlow());
    dlg.addEventListener("submit", (e) => {
      e.preventDefault();
      const form = e.target;
      if (!form.checkValidity()) {
        form.reportValidity();
        return;
      }
      this._flowSend(this._flowInput(form));
    });
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg) return dlg.close();
      const b = e.target.closest("[data-fdlg],[data-fmenu]");
      if (!b || b.disabled) return;
      if (b.dataset.fmenu) return this._flowSend({ next_step_id: b.dataset.fmenu });
      const act = b.dataset.fdlg;
      if (act === "cancel") dlg.close();
      else if (act === "settings") {
        dlg.close();
        window.history.pushState(null, "", "/config/integrations/dashboard");
        window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
      } else if (act === "ignore") {
        const flow = this._flow;
        const name = (flow.found && (flow.found.name || flow.found.host)) || "";
        flow.busy = true;
        this._renderFlow();
        this._hass
          .callWS({ type: "config_entries/ignore_flow", flow_id: flow.id, title: name })
          .then(() => {
            flow.done = true;
            dlg.close();
            this._toast(this._t("flow_ignored", { name }), "ok");
            this._loadFound();
          })
          .catch((err) => {
            flow.busy = false;
            flow.error = `${this._t("flow_failed")}: ${this._errText(err)}`;
            this._renderFlow();
          });
      }
    });
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
      <ha-card><svg class="sprite" aria-hidden="true" focusable="false"></svg><div class="root" tabindex="-1"></div><div class="toasts" aria-live="polite"></div></ha-card>
      <dialog class="dlg"></dialog><dialog class="dlg flowdlg" aria-label="AV Matrix"></dialog>`;
    this._root = sr.querySelector(".root");
    this._card = sr.querySelector("ha-card");
    this._sprite = sr.querySelector("svg.sprite");
    this._sprited = new Set();
    this._hoverStyle = sr.querySelector("style.hover");
    this._tpl = document.createElement("template");
    this._bind(sr);
    this._bindDialog(sr.querySelector("dialog"));
    this._bindFlowDialog(sr.querySelector("dialog.flowdlg"));
  }

  _render() {
    if (!this._config) return;
    this._ensureShell();
    const cls = `root ${this._narrow ? "narrow" : ""} ${this._width && this._width < 420 ? "xs" : ""} ${
      this._config.compact ? "compact" : ""
    } mode-${this._mode()} take-${this._take} proto-${esc(this._protocol || "")} ${this._isLight() ? "light" : ""}`;
    if (this._root.className !== cls) this._root.className = cls;
    this._card.classList.toggle("amx-light", this._isLight());
    this.toggleAttribute("daylight", this._isLight());
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
      const add = this._snap ? this._htmlAddBtn() : "";
      return `${
        this._config.title || add
          ? `<div class="hdr" data-k="hdr"><div class="ttl">${this._config.title ? `<h2>${esc(this._config.title)}</h2>` : ""}</div><div class="ctrls">${add}</div></div>`
          : ""
      }${this._snap ? this._htmlFound() : ""}${msg}`;
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
      ${this._htmlFound()}
      ${this._editMode ? `<div class="edit-hint" data-k="edithint">${icon("pencil")}<span>${esc(this._t("edit_hint"))}</span></div>` : ""}
      ${mode === "matrix" ? this._htmlMatrix(proto, dests, sources) : this._htmlPanel(proto, dests, sources)}
      ${this._htmlFooter(proto, dests)}
      ${this._historyOpen ? this._htmlHistory(proto) : ""}`;
  }

  _seg(group, items, value, aria = "") {
    return `<div class="seg" role="radiogroup" data-k="seg-${group}"${aria ? ` aria-label="${esc(aria)}"` : ""}>${items
      .map(
        ([v, label, ic, tip]) =>
          `<button type="button" role="radio" class="${v === value ? "on" : ""}" aria-checked="${v === value}" aria-label="${esc(label)}" data-act="${group}" data-v="${esc(v)}" title="${esc(tip || label)}">${ic ? icon(ic) : ""}<span>${esc(label)}</span></button>`
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
            <span class="stat">${this._ledChain(live, proto.sources.length)}<b class="num">${esc(this._t("sources_live", { live, total: proto.sources.length }))}</b></span>
            <span class="stat">${this._ledChain(okDests, dests.length, "lc-dst")}<span class="num">${esc(this._t("destinations", { n: dests.length }))}</span></span>
            ${this._fallback ? `<span class="badge" title="${esc(this._t("basic_mode_tip"))}">${esc(this._t("basic_mode"))}</span>` : ""}
          </div>
        </div>
        <div class="ctrls">
          ${tabs}
          <div class="ctrl2">
          ${this._seg("mode", [["panel", this._t("panel"), "panel"], ["matrix", this._t("matrix"), "matrix"]], this._mode())}
          ${this._seg("takemode", [["direct", this._t("direct"), "bolt"], ["preset", this._t("preset"), "preset"]], this._take)}
          ${
            this._fallback
              ? ""
              : this._width && this._width < 420
                ? `<button type="button" class="ibtn namesbtn" data-act="names" data-v="${NAME_MODES[(NAME_MODES.indexOf(this._nameMode) + 1) % NAME_MODES.length]}" title="${esc(this._t("names_tip_" + this._nameMode))}" aria-label="${esc(this._t("names"))}: ${esc(this._t("names_" + this._nameMode))}">${icon("names")}<span>${esc(this._t("names_" + this._nameMode))}</span></button>`
                : this._seg(
                  "names",
                  NAME_MODES.map((m) => [m, this._t("names_" + m), null, this._t("names_tip_" + m)]),
                  this._nameMode,
                  this._t("names")
                )
          }
          ${
            this._isAdmin()
              ? `<span class="adm">${this._htmlAddBtn()}<button type="button" class="ibtn tgl ${this._editMode ? "on" : ""}" aria-pressed="${this._editMode}" data-act="edit" title="${esc(this._t("edit_labels"))}" aria-label="${esc(this._t("edit_labels"))}">${icon("pencil")}</button></span>`
              : ""
          }
          </div>
        </div>
      </div>
      <div class="filters" data-k="filters">
        <label class="search">${icon("search")}
          <input type="search" data-act="search" placeholder="${esc(this._t("search"))}" value="${esc(this._search)}" aria-label="${esc(this._t("search"))}" autocomplete="off" spellcheck="false">
          <kbd>/</kbd>
        </label>
        ${this._htmlGroupFilters(proto)}
        <div class="chips">
          <button type="button" class="chip live ${this._liveOnly ? "on" : ""}" aria-pressed="${this._liveOnly}" data-act="liveonly" data-k="liveonly"><i class="led connected"></i>${esc(this._t("live_only"))}</button>
          ${tagChips}
        </div>
      </div>`;
  }

  /** LED chain (Pult-UI meter look): one segment per item, scaled down to 16 segments for large systems. */
  _ledChain(on, total, kind = "lc-src") {
    const n = Math.min(total, 16);
    if (!n) return "";
    const lit = total <= 16 ? on : Math.round((on / total) * n);
    let segs = "";
    for (let i = 0; i < n; i++) segs += `<i class="${i < lit ? "on" : ""}"></i>`;
    return `<span class="ledchain ${kind} ${on < total ? "part" : "all"}" aria-hidden="true">${segs}</span>`;
  }

  _htmlGroupFilters(proto) {
    if (!this._grouped(proto)) return "";
    const srcGroups = [...new Set(proto.sources.map((x) => x.group).filter(Boolean))];
    const dstGroups = [...new Set(this._destinations(proto, true).map((x) => x.group).filter(Boolean))];
    if (this._srcGroup && !srcGroups.includes(this._srcGroup)) this._srcGroup = "";
    if (this._dstGroup && !dstGroups.includes(this._dstGroup)) this._dstGroup = "";
    const sel = (act, label, groups, value) =>
      `<label class="gsel ${value ? "on" : ""}" title="${esc(label)}">${icon("device")}<span class="gl">${esc(label)}</span>
        <select data-act="${act}" aria-label="${esc(label)}">
          <option value="" ${value ? "" : "selected"}>${esc(this._t("all_devices"))}</option>
          ${groups.map((g) => `<option value="${esc(g)}" ${g === value ? "selected" : ""}>${esc(g)}</option>`).join("")}
        </select>${icon("chevron", "chev")}</label>`;
    return `<div class="gsels" data-k="gsels">${sel("srcgrp", this._t("from_device"), srcGroups, this._srcGroup)}${sel(
      "dstgrp",
      this._t("to_device"),
      dstGroups,
      this._dstGroup
    )}</div>`;
  }

  /** Collapsible device header (panel tiles and matrix rows/columns). */
  _htmlGroupToggle(kind, group, items, extra = "") {
    const key = `${kind}:${group}`;
    const closed = this._isClosed(key, items.length);
    const live =
      kind === "s"
        ? items.some((x) => x.live)
        : items.some((x) => x.available !== false && x.status !== "offline");
    const label = this._t(closed ? "expand" : "collapse", { g: group });
    const art = items[0]
      ? this._art(items[0].icon_key, this._protocol, kind === "s" ? (live ? "connected" : "no_source") : this._groupState(items), "gart")
      : "";
    const model = items[0] && items[0].model ? `${group} · ${items[0].model}` : group;
    return `<button type="button" class="gtog ${closed ? "closed" : ""}" data-act="grp" data-v="${esc(key)}" data-n="${items.length}" aria-expanded="${!closed}" title="${esc(`${label}\n${model}`)}" aria-label="${esc(label)}">${icon("chevron", "chev")}${art}<i class="led ${live ? "connected" : "offline"}"></i><span class="gname">${esc(group)}</span><span class="gcount">${esc(this._t("group_count", { n: items.length }))}</span>${extra}</button>`;
  }

  _destState(d) {
    const pend = this._pending.get(d.id);
    return {
      pend,
      preset: this._preset.has(d.id) ? this._preset.get(d.id) : undefined,
      status: d.available === false ? "offline" : STATUS_ORDER.includes(d.status) ? d.status : "no_source",
    };
  }

  /** Warning chip: source not sending, or (Dante) the subscription state with its explanation. */
  _htmlSubChip(d, status, warn) {
    const sub = d.subscription;
    if (sub && ["error", "warning", "unresolved", "idle"].includes(sub.state) && status !== "offline") {
      const text = this._t("sub_" + sub.state);
      const tip = [sub.status, sub.detail].filter(Boolean).join(" · ");
      return `<span class="chip warnchip ${sub.state === "error" ? "errchip" : ""}" title="${esc(tip)}">${icon("warn")}${esc(text)}</span>`;
    }
    if (warn) return `<span class="chip warnchip" title="${esc(this._t("not_sending"))}">${icon("warn")}${esc(this._t("not_sending"))}</span>`;
    return "";
  }

  _htmlDestTools(d, compact = false) {
    const disp = d.display;
    const dispOn = disp && (disp.state === "on" || disp.state === "playing" || disp.state === "idle");
    const tools = [];
    tools.push(
      `<button type="button" class="ibtn sm lock ${d.locked ? "on" : ""}" data-act="lock" data-d="${esc(d.id)}" aria-pressed="${d.locked}" title="${esc(this._t(d.locked ? "unlock" : "lock"))}" aria-label="${esc(this._t(d.locked ? "unlock" : "lock"))} · ${esc(this._dTitle(d))}">${icon(d.locked ? "lock" : "unlock")}</button>`
    );
    tools.push(
      `<button type="button" class="ibtn sm" data-act="undo" data-d="${esc(d.id)}" ${d.can_undo && !d.locked ? "" : "disabled"} title="${esc(this._t("undo"))}" aria-label="${esc(this._t("undo"))} · ${esc(this._dTitle(d))}">${icon("undo")}</button>`
    );
    if (disp) {
      const tip = disp.error
        ? `${this._t("display")}: ${disp.error}`
        : dispOn
          ? this._t("display_on", { i: disp.source || disp.configured_input || "" })
          : this._t("display_off");
      tools.push(
        `<button type="button" class="ibtn sm tv ${dispOn ? "on" : ""} ${disp.error ? "bad" : ""}" data-act="tv" data-d="${esc(d.id)}" aria-pressed="${!!dispOn}" title="${esc(tip)}" aria-label="${esc(tip)} · ${esc(this._dTitle(d))}">${icon("tv")}${!compact && dispOn && disp.source ? `<span class="tvin">${esc(disp.source)}</span>` : ""}</button>`
      );
    }
    return tools.join("");
  }

  _htmlPanel(proto, dests, sources) {
    const grouped = this._grouped(proto);
    const groupSize = (list) => {
      const m = new Map();
      for (const x of list) m.set(x.group || "", (m.get(x.group || "") || 0) + 1);
      return m;
    };
    const dSize = groupSize(dests);
    const sSize = groupSize(sources);
    const destKeys = dests.filter((d) => !(grouped && this._isClosed(`d:${d.group || ""}`, dSize.get(d.group || "")))).map((d) => d.id);
    if (!destKeys.includes(this._navKey.d)) this._navKey.d = destKeys.find((id) => this._sel.includes(id)) || destKeys[0];
    const destTile = (d) => {
        const { pend, preset, status } = this._destState(d);
        const sel = this._sel.includes(d.id);
        const [cur, curSub] = this._names(this._srcById(proto, d.current_source), d.current_source);
        const warn = d.current_source && !d.current_source_live && status !== "offline";
        const res = this._res(d.resolution);
        const multi = this._sel.length > 1 && sel;
        const [dn, dorig] = this._dnames(d);
        const art = grouped ? "" : this._art(d.icon_key, this._protocol, status, "dart");
        return `
        <div class="dest st-${status} ${sel ? "sel" : ""} ${d.locked ? "locked" : ""} ${pend ? "pending" : ""} ${preset !== undefined ? "armed" : ""} ${art ? "has-art" : ""}" data-k="d-${esc(d.id)}" data-shake="${esc(d.id)}">
          <button type="button" class="dest-main" data-act="dest" data-d="${esc(d.id)}" data-nav="d" data-key="${esc(d.id)}" tabindex="${d.id === this._navKey.d ? "0" : "-1"}" aria-pressed="${sel}" title="${esc(this._dTip(d))}" aria-label="${esc(this._t("dest_label"))} ${esc(this._dTitle(d))}: ${esc(cur)}">
            <span class="dtop"><i class="led ${status}" title="${esc(this._t("status_" + status))}"></i><span class="dno mono">${String(dests.indexOf(d) + 1).padStart(2, "0")}</span><span class="dres mono">${esc(res || this._t("status_" + status))}</span>${multi ? `<span class="selno">${this._sel.indexOf(d.id) + 1}</span>` : ""}</span>
            <span class="dband"><span class="dname" data-dl="${esc(d.id)}">${esc(dn)}</span></span>
            ${dorig ? `<span class="dorig mono">${esc(dorig)}</span>` : ""}
            <span class="dsrc ${d.current_source ? "" : "none"}">${pend ? `<span class="spinner sm"></span><span class="ell">${esc(this._t("switching"))}</span>` : `<span class="ell">${esc(cur)}</span>`}</span>
            <span class="dsub mono">${esc(pend ? this._srcName(proto, pend.source) : curSub)}</span>
            ${(() => {
              const chip = this._htmlSubChip(d, status, warn);
              return chip ? `<span class="dwarn">${chip}</span>` : "";
            })()}
            <span class="dfoot"><span class="dmeta">
              ${d.locked ? `<span class="chip lockchip">${icon("lock")}${esc(this._t("locked"))}</span>` : ""}
            </span>${art}</span>
            ${preset !== undefined ? `<span class="armline"><b>${esc(this._t("armed_state"))}</b><span class="ell">${esc(this._srcName(proto, preset))}</span></span>` : ""}
          </button>
          <div class="dtools">${this._htmlDestTools(d)}</div>
        </div>`;
    };
    const destHtml = grouped
      ? this._groups(dests)
          .map(([g, items]) => {
            const closed = this._isClosed(`d:${g}`, items.length);
            const armed = items.filter((d) => this._preset.has(d.id)).length;
            return `<div class="ghead" data-k="dg-${esc(g)}">${this._htmlGroupToggle("d", g, items, armed ? `<span class="garm">${armed} PST</span>` : "")}</div>${
              closed ? "" : items.map(destTile).join("")
            }`;
          })
          .join("")
      : dests.map(destTile).join("");

    // sources for the selected destinations
    const selDests = dests.filter((d) => this._sel.includes(d.id));
    const pgm = new Set(selDests.map((d) => d.current_source || ""));
    const pst = new Set(selDests.filter((d) => this._preset.has(d.id)).map((d) => this._preset.get(d.id)));
    const pendSrc = new Set(selDests.filter((d) => this._pending.has(d.id)).map((d) => this._pending.get(d.id).source || ""));
    const usage = new Map();
    for (const d of proto.destinations) usage.set(d.current_source || "", (usage.get(d.current_source || "") || 0) + 1);
    const visibleSources = grouped ? sources.filter((x) => !this._isClosed(`s:${x.group || ""}`, sSize.get(x.group || ""))) : sources;
    const srcKeys = ["", ...visibleSources.map((x) => x.id)];
    if (!srcKeys.includes(this._navKey.s)) this._navKey.s = srcKeys[0];
    const flashKey = (id) => selDests.map((d) => `${d.id}|${id}`)[0] || "";
    const tile = (id, s) => {
      const isPgm = pgm.has(id);
      const isPst = pst.has(id);
      const isPend = pendSrc.has(id);
      const live = id === "" ? true : s.live;
      const [primary, secondary] = id === "" ? [this._t("off"), this._t(grouped ? "off_sub_grouped" : "off_sub")] : this._names(s, id);
      const used = usage.get(id) || 0;
      const tags = id && s.tags && s.tags.length ? s.tags.map((t) => `<span class="tag">#${esc(t)}</span>`).join("") : "";
      const foot = !live
        ? `<span class="offl">${esc(this._t("offline_since", { t: this._ago(s.last_seen) }))}</span>`
        : tags;
      const cls = ["src", id === "" ? "black" : "", id !== "" && !grouped && s.icon_key ? "has-art" : "", isPgm ? "pgm" : "", isPst ? "pst" : "", isPend ? "pend" : "", live ? "" : "dead"]
        .filter(Boolean)
        .join(" ");
      const titleTxt = id === "" ? primary : this._srcTip(s, id);
      const art = id === "" || grouped ? "" : this._art(s.icon_key, this._protocol, live ? "connected" : "no_source", "sart");
      return `
        <button type="button" class="${cls}" data-k="s-${esc(id)}" data-act="src" data-s="${esc(id)}" data-nav="s" data-key="${esc(id)}" data-flash="${esc(flashKey(id))}" tabindex="${id === this._navKey.s ? "0" : "-1"}" aria-pressed="${isPgm}" title="${esc(titleTxt)}" aria-label="${esc(this._t("source_label"))} ${esc(primary)}${live ? "" : " (offline)"}">
          <span class="tally"></span>
          <span class="sname">${esc(primary)}</span>
          <span class="sid mono">${esc(secondary)}</span>
          <span class="sfoot">${isPend || isPgm || isPst ? `<span class="sstate">${esc(this._t(isPend ? "switching" : isPgm ? "on_air" : "armed_state"))}</span>` : ""}<span class="stags">${foot}</span>${used && id !== "" ? `<span class="use" title="${esc(this._t("in_use", { n: used }))}"><i></i>${used}</span>` : ""}${art}</span>
        </button>`;
    };
    const cols = parseInt(this._config.columns, 10);
    const style = cols > 0 && !this._narrow ? ` style="grid-template-columns:repeat(${cols},minmax(0,1fr))"` : "";
    const srcHtml = grouped
      ? [
          tile("", null),
          ...this._groups(sources).map(([g, items]) => {
            const closed = this._isClosed(`s:${g}`, items.length);
            const pgmHere = items.filter((x) => pgm.has(x.id)).length;
            return `<div class="ghead" data-k="sg-${esc(g)}">${this._htmlGroupToggle("s", g, items, pgmHere ? `<span class="gpgm"></span>` : "")}</div>${
              closed ? "" : items.map((x) => tile(x.id, x)).join("")
            }`;
          }),
        ].join("")
      : [tile("", null), ...sources.map((x) => tile(x.id, x))].join("");
    return `
      <section class="panel" data-k="panel">
        <div class="mod mdests">
          <div class="mod-h"><h3>${esc(this._t("mod_dests"))}</h3><span class="mono">${dests.length}</span></div>
          <div class="dests ${grouped ? "grouped" : ""}" role="toolbar" aria-label="${esc(this._t("dest_label"))}" data-shake="__dests">${destHtml}</div>
        </div>
        <div class="mod srcs-wrap">
          <div class="mod-h"><h3>${esc(this._t("mod_sources"))}</h3><span class="ell">${esc(this._t("for_dests", { d: selDests.map((d) => this._dTitle(d)).join(", ") || "–" }))}</span></div>
          <div class="srcs ${grouped ? "grouped" : ""}" role="group" aria-label="${esc(this._t("source_label"))}"${style}>${srcHtml}</div>
          ${sources.length ? "" : `<div class="msg small">${esc(this._t("no_match"))}</div>`}
        </div>
      </section>`;
  }

  _htmlMatrix(proto, dests, sources) {
    const grouped = this._grouped(proto);
    // columns: Off, then sources (grouped protocols: per device, a collapsed device = one summary column)
    const cols = [{ id: "", s: null }];
    const colGroups = []; // [{ g, span, items, closed }]
    if (grouped) {
      for (const [g, items] of this._groups(sources)) {
        const closed = this._isClosed(`s:${g}`, items.length);
        colGroups.push({ g, span: closed ? 1 : items.length, items, closed });
        if (closed) cols.push({ id: null, group: g, items });
        else for (const x of items) cols.push({ id: x.id, s: x, group: g });
      }
    } else {
      for (const x of sources) cols.push({ id: x.id, s: x });
    }
    const keyOf = (r, c) => `${r}:${c}`;
    if (!this._navKey.x || !/^\d+:\d+$/.test(this._navKey.x)) this._navKey.x = "0:0";
    const groupStart = new Set();
    {
      let c = 1;
      for (const cg of colGroups) {
        groupStart.add(c);
        c += cg.span;
      }
    }
    const heads = cols.map((col, c) => {
        const { id, s } = col;
        const gs = groupStart.has(c) ? "gs" : "";
        if (id === null) {
          const used = col.items.some((x) => proto.destinations.some((d) => d.current_source === x.id));
          return `<th scope="col" class="ch sum ${gs} ${used ? "used" : ""}" data-c="${c}" data-k="ch-g-${esc(col.group)}" title="${esc(col.group)}">
            <div class="chw"><span class="chl"><span class="chn">${esc(this._t("group_count", { n: col.items.length }))}</span></span></div></th>`;
        }
        const [primary, secondary] = id === "" ? [this._t("off"), ""] : this._names(s, id);
        const live = id === "" || s.live;
        const used = proto.destinations.some((d) => (d.current_source || "") === id);
        const tip = id === "" ? primary : `${this._srcTip(s, id)}${live ? "" : "\n" + this._t("offline_since", { t: this._ago(s.last_seen) })}`;
        const art = id === "" || grouped ? "" : this._art(s.icon_key, this._protocol, live ? "connected" : "no_source", "cart");
        const sub = secondary && this._nameMode === "both" && s && s.label ? secondary : "";
        return `<th scope="col" class="ch ${gs} ${live ? "" : "dead"} ${used ? "used" : ""} ${id === "" ? "black" : ""}" data-c="${c}" data-k="ch-${esc(id)}" title="${esc(tip)}" ${this._isAdmin() && id ? `data-act="label" data-s="${esc(id)}"` : ""} ${grouped && id === "" ? 'rowspan="2"' : ""}>
          <div class="chw"><span class="chl"><i class="led ${live ? (used ? "pgm" : "connected") : "no_source"}"></i><span class="cht"><span class="chn">${esc(primary)}</span>${sub ? `<span class="chs mono">${esc(sub)}</span>` : ""}</span></span>${art}</div>
        </th>`;
      });
    const groupHead = colGroups
      .map(
        (cg) =>
          `<th scope="colgroup" colspan="${cg.span}" class="cgh ${cg.closed ? "closed" : ""}" data-k="cg-${esc(cg.g)}">${this._htmlGroupToggle("s", cg.g, cg.items)}</th>`
      )
      .join("");
    const ncols = cols.length + 1;
    const corner = `<div class="cornerw"><span class="cs">${esc(this._t("source_label"))} →</span><span class="cd">${esc(this._t("dest_label"))} ↓</span></div>`;
    let r = 0;
    const row = (d) => {
      const rr = r++;
      const { pend, preset, status } = this._destState(d);
      const cur = d.current_source || "";
      const warn = d.current_source && !d.current_source_live && status !== "offline";
      const res = this._res(d.resolution);
      const cells = cols
        .map((col, c) => {
          const k = keyOf(rr, c);
          const gs = groupStart.has(c) ? "gs" : "";
          if (col.id === null) {
            // collapsed device: one summary crosspoint, lit if this row listens to that device
            const hit = col.items.find((x) => x.id === cur);
            const isPst = preset !== undefined && col.items.some((x) => x.id === preset);
            const label = hit ? this._names(hit, hit.id)[0] : col.group;
            return `<td role="gridcell" class="${gs}" data-r="${rr}" data-c="${c}"><button type="button" class="xp sum ${hit ? "pgm" : ""} ${hit && warn ? "lost" : ""} ${isPst ? "pst" : ""}" data-act="grp" data-v="${esc(`s:${col.group}`)}" data-n="${col.items.length}" data-nav="x" data-key="${k}" data-r="${rr}" data-c="${c}" tabindex="${this._navKey.x === k ? "0" : "-1"}" title="${esc(this._t("expand", { g: col.group }))}" aria-label="${esc(label)} → ${esc(this._dTitle(d))}"><i></i>${hit ? `<b class="sumn">${esc(label)}</b>` : ""}</button></td>`;
          }
          const { id, s } = col;
          const on = cur === id;
          const isPst = preset !== undefined && preset === id;
          const isPend = pend && (pend.source || "") === id;
          const live = id === "" || s.live;
          const name = id === "" ? this._t("off") : this._names(s, id)[0];
          const cls = ["xp", on ? "pgm" : "", on && warn ? "lost" : "", isPst ? "pst" : "", isPend ? "pend" : "", live ? "" : "dead"]
            .filter(Boolean)
            .join(" ");
          return `<td role="gridcell" class="${gs}" data-r="${rr}" data-c="${c}"><button type="button" class="${cls}" data-act="xp" data-d="${esc(d.id)}" data-s="${esc(id)}" data-nav="x" data-key="${k}" data-r="${rr}" data-c="${c}" data-flash="${esc(d.id)}|${esc(id)}" tabindex="${this._navKey.x === k ? "0" : "-1"}" aria-pressed="${on}" aria-label="${esc(name)} → ${esc(this._dTitle(d))}" ${d.locked ? 'aria-disabled="true"' : ""}><i></i></button></td>`;
        })
        .join("");
      const sub = d.subscription && ["error", "warning", "unresolved", "idle"].includes(d.subscription.state) && status !== "offline";
      const subTip = sub ? [this._t("sub_" + d.subscription.state), d.subscription.detail].filter(Boolean).join(" · ") : this._t("not_sending");
      const [dn, dorig] = this._dnames(d);
      const art = grouped ? "" : this._art(d.icon_key, this._protocol, status, "rart");
      return `<tr role="row" data-r="${rr}" data-k="r-${esc(d.id)}" class="${d.locked ? "locked" : ""} ${preset !== undefined ? "armed" : ""}" data-shake="${esc(d.id)}">
          <th scope="row" class="rh st-${status}" data-r="${rr}" data-d="${esc(d.id)}">
            <div class="rhw">
              <i class="led ${status}" title="${esc(this._t("status_" + status))}"></i>${art}
              <div class="rht">
                <div class="rhn" title="${esc(this._dTip(d))}" data-dl="${esc(d.id)}" ${this._editMode && this._isAdmin() ? `data-act="dlabel" data-d="${esc(d.id)}"` : ""}><span class="ell">${esc(dn)}</span>${dorig ? `<span class="rho mono">${esc(dorig)}</span>` : ""}</div>
                <div class="rhs ${pend ? "pending" : ""}">${
                  pend
                    ? `<span class="spinner sm"></span>${esc(this._t("switching"))}`
                    : preset !== undefined
                      ? `<span class="pstx"><b>${esc(this._t("armed_state"))}</b>${esc(this._srcName(proto, preset))}</span>`
                      : `<span class="cur">${esc(this._srcName(proto, d.current_source))}</span>${res ? `<span class="chip res mono">${esc(res)}</span>` : ""}${warn || sub ? `<span class="warnico" title="${esc(subTip)}">${icon("warn")}</span>` : ""}`
                }</div>
              </div>
              <div class="rtools">${this._htmlDestTools(d, true)}</div>
            </div>
          </th>
          ${cells}
        </tr>`;
    };
    const rows = grouped
      ? this._groups(dests)
          .map(([g, items]) => {
            const closed = this._isClosed(`d:${g}`, items.length);
            const routed = items.filter((d) => d.current_source).length;
            return `<tr class="rgr ${closed ? "closed" : ""}" data-k="rg-${esc(g)}"><th scope="rowgroup" class="rgh" colspan="${ncols}"><div class="rghw">${this._htmlGroupToggle(
              "d",
              g,
              items,
              `<span class="gsub">${routed}/${items.length}</span>`
            )}</div></th></tr>${closed ? "" : items.map(row).join("")}`;
          })
          .join("")
      : dests.map(row).join("");
    return `
      <section class="mxwrap ${grouped ? "grouped" : ""}" data-k="matrix">
        <div class="mxscroll">
          <table class="mx" role="grid" aria-label="${esc(proto.title)} matrix" aria-rowcount="${r + 1}" aria-colcount="${cols.length + 1}">
            <thead>${
              grouped
                ? `<tr role="row" class="ghr"><th class="corner" rowspan="2">${corner}</th>${heads[0]}${groupHead}</tr><tr role="row" class="chr">${heads.slice(1).join("")}</tr>`
                : `<tr role="row"><th class="corner">${corner}</th>${heads.join("")}</tr>`
            }</thead>
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
          ? `<span class="armchip" data-k="arm-${esc(id)}" title="${esc(this._dTip(d))}"><b>${esc(this._dTitle(d))}</b><span class="arr">←</span>${esc(this._srcName(proto, s))}<button type="button" class="x" data-act="disarm" data-d="${esc(id)}" aria-label="${esc(this._t("clear"))} ${esc(this._dTitle(d))}">${icon("x")}</button></span>`
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
          <span class="hd" title="${esc(d ? this._dTip(d) : e.dest_name || e.dest)}">${esc(d ? this._dTitle(d) : e.dest_name || e.dest)}</span>
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
          this._srcGroup = "";
          this._dstGroup = "";
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
        case "found":
          this._openFlow(el.dataset.f);
          break;
        case "addflow":
          this._openFlow(null);
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
          if (this._editMode && this._isAdmin()) this._openLabel("destination", el.dataset.d);
          else this._selectDest(el.dataset.d, multi);
          break;
        case "dlabel":
          this._openLabel("destination", el.dataset.d);
          break;
        case "names":
          this._setNameMode(el.dataset.v);
          break;
        case "src":
          this._pickSource(el.dataset.s);
          break;
        case "xp": {
          const d = findDest(el.dataset.d);
          if (!d) break;
          if (this._editMode && el.dataset.s) {
            this._openLabel("source", el.dataset.s);
            break;
          }
          if (d.locked) {
            this._toast(this._t("dest_locked", { d: this._dTitle(d) }), "warn");
            this._shake([d.id]);
            break;
          }
          this._crosspoint([d], el.dataset.s);
          break;
        }
        case "label":
          this._openLabel("source", el.dataset.s);
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
        case "grp":
          this._toggleGroup(el.dataset.v, parseInt(el.dataset.n || "0", 10));
          this._render();
          break;
        default:
          break;
      }
    });

    sr.addEventListener("change", (e) => {
      const act = e.target.dataset && e.target.dataset.act;
      if (act === "srcgrp" || act === "dstgrp") {
        if (act === "srcgrp") this._srcGroup = e.target.value;
        else this._dstGroup = e.target.value;
        this._render();
      }
    });

    sr.addEventListener("input", (e) => {
      if (e.target.dataset && e.target.dataset.act === "search") {
        this._search = e.target.value;
        this._render();
      }
    });

    // right click on a source or a destination = edit label (admin)
    sr.addEventListener("contextmenu", (e) => {
      if (!this._isAdmin()) return;
      const el = e.target.closest('[data-act="src"],[data-act="xp"],th.ch');
      const id = el && el.dataset.s;
      if (id) {
        e.preventDefault();
        this._openLabel("source", id);
        return;
      }
      const d = e.target.closest('[data-act="dest"],th.rh');
      if (d && d.dataset.d) {
        e.preventDefault();
        this._openLabel("destination", d.dataset.d);
      }
    });

    // double click on a destination name = edit label (admin)
    sr.addEventListener("dblclick", (e) => {
      const el = e.target.closest("[data-dl]");
      if (el && this._isAdmin()) {
        e.preventDefault();
        this._openLabel("destination", el.dataset.dl);
      }
    });

    // long press: destination name = edit label (admin), destination = add to multi selection,
    // source = edit label (admin)
    sr.addEventListener("pointerdown", (e) => {
      if (!this._root.contains(sr.activeElement)) this._root.focus({ preventScroll: true });
      const nameEl = this._isAdmin() ? e.target.closest("[data-dl]") : null;
      const el = nameEl || e.target.closest('[data-act="dest"],[data-act="src"]');
      clearTimeout(this._lp);
      if (!el || (e.pointerType === "mouse" && e.button !== 0)) return;
      const x = e.clientX;
      const y = e.clientY;
      this._lpStart = { x, y };
      this._lp = setTimeout(() => {
        if (nameEl) {
          this._suppressClick = true;
          this._openLabel("destination", nameEl.dataset.dl);
        } else if (el.dataset.act === "dest") {
          this._selectDest(el.dataset.d, true);
          this._suppressClick = true;
          if (navigator.vibrate) navigator.vibrate(15);
        } else if (el.dataset.s && this._isAdmin()) {
          this._suppressClick = true;
          this._openLabel("source", el.dataset.s);
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
      case "n":
      case "N":
        this._setNameMode(NAME_MODES[(NAME_MODES.indexOf(this._nameMode) + 1) % NAME_MODES.length]);
        handled();
        return;
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
/* ================= Strelle Pult-UI tokens (dark = default, daylight via :host([daylight])) =================
   Signal semantics: red = program / on air, amber = preset / armed / warning, green = ok,
   Strelle blue = selection, focus and the one main action (TAKE) only. */
:host {
  display: block;
  --p-bg: #0a0a0a; --p-surface: #121212; --p-surface-2: #1a1b1e; --p-surface-3: #24262b;
  --p-line: #2c2f35; --p-line-strong: #4f5560; --p-fg: #efedea; --p-muted: #a3a19c;
  --p-accent: #2f6fd0; --p-accent-text: #79a8ec; --p-on-accent: #ffffff;
  --p-live: var(--av-matrix-tally-color, #ff4b42); --p-cue: var(--av-matrix-preset-color, #ffb020);
  --p-ok: #3ddc84; --p-on-signal: #0a0a0a; --p-off: #1f2125;
  --p-cap-hi: #5a5e66; --p-cap-lo: #08090a; --p-shadow: rgba(0,0,0,.55);
  --p-ch: #3fd0d6; --p-on-ch: #0a0a0a;
  --p-font: "Atkinson Hyperlegible Next", "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --amx-mono: "Atkinson Hyperlegible Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --amx-r: 12px; --amx-rm: 18px;
  --amx-hit: 44px; --amx-hit-sm: 40px; --amx-xp: 38px;
  /* aliases used by script-generated styles */
  --amx-tally: var(--p-live); --amx-preset: var(--p-cue); --amx-ok: var(--p-ok); --amx-err: var(--p-live);
  --amx-lost: var(--p-cue); --amx-fg: var(--p-fg); --amx-fg2: var(--p-muted); --amx-accent: var(--p-accent);
  --amx-cross: color-mix(in srgb, var(--p-accent) 13%, var(--p-surface));
  --amx-cross2: color-mix(in srgb, var(--p-accent) 30%, var(--p-surface));
}
@supports (color: oklch(0.5 0.1 250)) {
  :host { --p-accent: oklch(0.5361 0.1495 253.41); --p-accent-text: oklch(0.72 0.12 250); }
}
:host([daylight]) {
  --p-bg: #e9edf2; --p-surface: #ffffff; --p-surface-2: #f3f5f8; --p-surface-3: #e1e6ed;
  --p-line: #c9d0da; --p-line-strong: #7d8693; --p-fg: #0d1117; --p-muted: #4a525e;
  --p-accent-text: #1f5fc4;
  --p-live: var(--av-matrix-tally-color, #e3302a); --p-cue: var(--av-matrix-preset-color, #f0a21a);
  --p-ok: #26b562; --p-off: #d6dbe3; --p-cap-hi: #ffffff; --p-cap-lo: #b9c0ca; --p-shadow: rgba(20,30,50,.18);
  --p-ch: #14a3ab;
}
@supports (color: oklch(0.5 0.1 250)) { :host([daylight]) { --p-accent-text: oklch(0.47 0.15 253); } }
.root.proto-dante { --p-ch: #a87bff; }
:host([daylight]) .root.proto-dante { --p-ch: #7f52e0; --p-on-ch: #ffffff; }
@media (pointer: coarse) { :host { --amx-hit: 56px; --amx-hit-sm: 48px; --amx-xp: 50px; } }

* { box-sizing: border-box; }
ha-card { position: relative; overflow: hidden; background: var(--p-surface); --ha-card-background: var(--p-surface);
  color: var(--p-fg); border-color: var(--p-line); }
.root { outline: none; padding: 14px; display: flex; flex-direction: column; gap: 12px; font-family: var(--p-font);
  font-size: 15px; line-height: 1.35; font-variant-numeric: tabular-nums; color: var(--p-fg); -webkit-font-smoothing: antialiased; }
.root.compact { padding: 10px; gap: 8px; }
.mono { font-family: var(--amx-mono); letter-spacing: 0; font-variant-numeric: tabular-nums; }
.num { font-variant-numeric: tabular-nums; }
.ic { width: 20px; height: 20px; flex: none; fill: none; stroke: currentColor; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round; }
button, input, select { font-family: inherit; }
button { font: inherit; color: inherit; -webkit-tap-highlight-color: transparent; }
button:focus { outline: none; }
button:focus-visible, input:focus-visible, select:focus-visible, .root :focus-visible {
  outline: 3px solid var(--p-accent-text); outline-offset: 2px; }
kbd { font-family: var(--amx-mono); font-size: 13px; font-weight: 500; line-height: 1; padding: 3px 5px; border-radius: 5px;
  border: 1px solid var(--p-line-strong); color: var(--p-muted); background: var(--p-surface); }

/* ---------------- header */
.hdr { display: flex; align-items: center; justify-content: space-between; gap: 10px 16px; flex-wrap: wrap; }
.ttl { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.ttl h2 { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: .005em; line-height: 1.1; color: var(--p-fg);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stats { display: flex; gap: 6px 18px; flex-wrap: wrap; font-size: 14px; color: var(--p-muted); align-items: center; }
.stat { display: inline-flex; align-items: center; gap: 8px; }
.stat b { font-weight: 500; }
.ledchain { display: inline-flex; gap: 2px; padding: 3px; border-radius: 4px; background: var(--p-bg); border: 1px solid var(--p-line); }
.ledchain i { width: 5px; height: 12px; border-radius: 1.5px; background: var(--p-off); }
.ledchain i.on { background: var(--p-ok); box-shadow: 0 0 4px color-mix(in srgb, var(--p-ok) 55%, transparent); }
.ledchain.lc-dst.part i.on { background: var(--p-cue); box-shadow: none; }
:host([daylight]) .ledchain i.on { box-shadow: none; }
.badge { font-size: 13px; font-weight: 700; padding: 2px 8px; border-radius: 4px; background: var(--p-cue); color: var(--p-on-signal); }
.ctrls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ctrl2 { display: contents; }
.tabs, .seg { display: inline-flex; border-radius: var(--amx-r); border: 1px solid var(--p-line-strong); overflow: hidden;
  background: var(--p-surface-3); }
.tab, .seg button { border: 0; border-right: 1px solid var(--p-line-strong); background: none; cursor: pointer;
  min-height: var(--amx-hit); padding: 0 14px; font-size: 15px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
  color: var(--p-fg); display: inline-flex; align-items: center; justify-content: center; gap: 7px; white-space: nowrap;
  transition: background-color .15s, color .15s; }
.tabs > :last-child, .seg button:last-child { border-right: 0; }
.tabs.single .tab { cursor: default; }
.tab:hover:not(.on), .seg button:hover:not(.on) { background: color-mix(in srgb, var(--p-fg) 7%, var(--p-surface-3)); }
.seg button.on { background: var(--p-accent); color: var(--p-on-accent); }
.tab { position: relative; }
.tab.on { background: var(--p-surface); color: var(--p-fg); box-shadow: inset 0 4px 0 var(--p-accent); }
.tabs.single .tab.on { background: none; box-shadow: none; }
.seg button .ic { width: 17px; height: 17px; }
.ibtn { border: 1px solid var(--p-line-strong); background: var(--p-surface-3); cursor: pointer; border-radius: var(--amx-r);
  width: var(--amx-hit); height: var(--amx-hit); display: inline-flex; align-items: center; justify-content: center;
  color: var(--p-fg); transition: background-color .15s, color .15s, border-color .15s; padding: 0; }
.ibtn:hover:not([disabled]) { background: color-mix(in srgb, var(--p-fg) 8%, var(--p-surface-3)); }
.ibtn[disabled] { opacity: .35; cursor: default; }
.ibtn.tgl.on { background: var(--p-accent); border-color: var(--p-accent); color: var(--p-on-accent); }
.namesbtn { width: auto; padding: 0 12px; gap: 6px; font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.namesbtn .ic { width: 17px; height: 17px; }
/* phones: protocol tabs next to the title, icon-only segmented controls, names as one cycling button */
.xs .hdr { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px 8px; align-items: start; }
.xs .ctrls { display: contents; }
.xs .tabs { grid-column: 2; grid-row: 1; }
.xs .tab { padding: 0 10px; font-size: 14px; }
.xs .ctrl2 { grid-column: 1 / -1; display: flex; gap: 6px; align-items: center; }
.xs .ctrl2 .ibtn.tgl { margin-left: auto; }
.xs .seg button { padding: 0 11px; }
.xs .seg button .ic + span { display: none; }
.xs .seg button .ic { width: 19px; height: 19px; }
.xs .search { flex: 1 1 100%; }
.xs .ibtn { flex: none; }
.xs .ibtn.namesbtn { width: auto; }
.xs .stats { gap: 2px 12px; font-size: 14px; }
.xs .ledchain { display: none; }
.narrow .dtools .tvin { display: none; }

/* ---------------- filters */
.filters { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.search { position: relative; display: flex; align-items: center; gap: 8px; flex: 0 1 320px; min-width: 200px;
  height: var(--amx-hit); padding: 0 8px 0 12px; border-radius: var(--amx-r); background: var(--p-bg);
  border: 1px solid var(--p-line-strong); color: var(--p-muted); }
:host([daylight]) .search { background: var(--p-surface); }
.search:focus-within { outline: 3px solid var(--p-accent-text); outline-offset: 2px; }
.search .ic { width: 18px; height: 18px; }
.search input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; color: var(--p-fg); font-size: 16px; height: 100%; }
.search input::placeholder { color: var(--p-muted); }
.search input::-webkit-search-cancel-button { filter: grayscale(1); }
.search input:focus-visible { outline: none; }
.search:focus-within kbd { display: none; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; line-height: 1; padding: 6px 10px;
  border-radius: 8px; border: 1px solid var(--p-line-strong); background: var(--p-surface-3); color: var(--p-fg); white-space: nowrap; }
button.chip { cursor: pointer; min-height: 38px; padding: 0 12px; }
@media (pointer: coarse) { button.chip { min-height: 48px; } }
button.chip:hover:not(.on) { background: color-mix(in srgb, var(--p-fg) 8%, var(--p-surface-3)); }
button.chip.on { background: var(--p-accent); border-color: var(--p-accent); color: var(--p-on-accent); }
.chip .ic { width: 14px; height: 14px; }

/* ---------------- status LEDs: form + colour (circle ok, triangle warning, square error, ring off) */
.led { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: 50%; background: transparent;
  box-shadow: inset 0 0 0 2px var(--p-line-strong); }
.led.connected { background: var(--p-ok); box-shadow: 0 0 6px color-mix(in srgb, var(--p-ok) 65%, transparent); }
.led.connecting, .led.source_lost { width: 12px; height: 11px; border-radius: 0; background: var(--p-cue); box-shadow: none;
  clip-path: polygon(50% 0, 100% 100%, 0 100%); }
.led.connecting { animation: amx-pulse 1.1s ease-in-out infinite; }
.led.connecting.static { animation: none; }
.led.no_source { box-shadow: inset 0 0 0 2px var(--p-muted); }
.led.offline, .led.error { border-radius: 1.5px; background: var(--p-live); box-shadow: none; }
.led.pgm { background: var(--p-live); box-shadow: 0 0 6px var(--p-live); }
:host([daylight]) .led.connected, :host([daylight]) .led.pgm { box-shadow: none; }

.edit-hint { display: flex; align-items: center; gap: 8px; font-size: 14px; padding: 10px 12px; border-radius: var(--amx-r);
  color: var(--p-fg); background: color-mix(in srgb, var(--p-accent) 14%, var(--p-surface));
  border: 1px solid var(--p-accent); }
.edit-hint .ic { width: 18px; height: 18px; color: var(--p-accent-text); }

/* ---------------- modules (signature: blue edge on top while something inside has focus) */
.mod { position: relative; background: var(--p-surface-2); border: 1px solid var(--p-line); border-radius: var(--amx-rm); }
.mod::before { content: ""; position: absolute; left: 0; right: 0; top: 0; height: 3px; background: var(--p-accent);
  border-radius: var(--amx-rm) var(--amx-rm) 0 0; transform: scaleX(0); transform-origin: left;
  transition: transform .35s cubic-bezier(.25, 0, 0, 1); z-index: 1; pointer-events: none; }
.mod:focus-within::before { transform: scaleX(1); }
.mod-h { display: flex; align-items: baseline; gap: 10px; padding: 9px 14px; background: var(--p-surface-3);
  border-bottom: 1px solid var(--p-line); border-radius: var(--amx-rm) var(--amx-rm) 0 0; min-width: 0; }
.mod-h h3 { margin: 0; font-size: 14px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; white-space: nowrap; }
.mod-h > span { font-size: 14px; color: var(--p-muted); min-width: 0; }
.compact .mod-h { padding: 6px 12px; }

/* ---------------- panel: destinations as scribble-strip displays */
.panel { display: flex; flex-direction: column; gap: 12px; }
.dests { display: grid; grid-template-columns: repeat(auto-fill, minmax(196px, 1fr)); gap: 10px; padding: 12px; }
.narrow .dests { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; padding: 8px; }
.dest { position: relative; display: flex; flex-direction: column; border-radius: var(--amx-r); background: var(--p-surface);
  border: 1px solid var(--p-line-strong); min-width: 0; overflow: hidden; transition: box-shadow .15s, border-color .15s; }
.dest::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 5px; background: var(--p-line-strong); z-index: 1; }
.dest.st-connected::before { background: var(--p-ok); }
.dest.st-connecting::before { background: var(--p-cue); animation: amx-pulse 1.1s ease-in-out infinite; }
.dest.st-source_lost::before { background: var(--p-cue); }
.dest.st-offline::before, .dest.st-error::before { background: var(--p-live); }
.dest.sel { border-color: var(--p-accent); box-shadow: 0 0 0 2px var(--p-accent); }
.dest.armed { border-color: var(--p-cue); box-shadow: 0 0 0 2px var(--p-cue); }
.dest.sel.armed { box-shadow: 0 0 0 2px var(--p-accent), 0 0 0 5px var(--p-cue); }
.dest.st-offline .dest-main { opacity: .62; }
.dest-main { display: flex; flex-direction: column; align-items: stretch; gap: 2px; width: 100%; text-align: left;
  border: 0; background: none; cursor: pointer; padding: 13px 12px 10px; min-height: 132px; flex: 1; color: var(--p-fg); }
.dest-main:hover { background: color-mix(in srgb, var(--p-fg) 4%, transparent); }
.compact .dest-main { min-height: 108px; padding: 11px 10px 8px; }
.dtop { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 14px; color: var(--p-muted); }
.dno { font-weight: 600; color: var(--p-fg); }
.dres { margin-left: auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.selno { font-size: 13px; font-weight: 800; min-width: 22px; height: 22px; border-radius: 11px; display: inline-grid;
  place-items: center; background: var(--p-accent); color: var(--p-on-accent); flex: none; }
.dband { display: block; margin: 6px -12px 2px; padding: 4px 12px; background: var(--p-ch); color: var(--p-on-ch); min-width: 0; }
.compact .dband { margin-left: -10px; margin-right: -10px; padding: 3px 10px; }
.dname { display: block; font-size: 19px; font-weight: 700; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dorig { font-size: 14px; color: var(--p-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dsrc { font-size: 18px; font-weight: 700; line-height: 1.25; margin-top: 6px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; display: flex; align-items: center; gap: 8px; }
.compact .dsrc { font-size: 16px; }
.ell { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dsrc.none { color: var(--p-muted); font-weight: 500; }
.dsub { font-size: 14px; color: var(--p-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-height: 18px; }
.dmeta { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; }
.dmeta:empty { display: none; }
.chip.res { padding: 4px 7px; border-radius: 6px; font-size: 14px; font-weight: 500; background: var(--p-bg); border-color: var(--p-line); }
:host([daylight]) .chip.res { background: var(--p-surface-2); }
.chip.lockchip { padding: 4px 8px; border-radius: 6px; font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
  background: var(--p-accent); border-color: var(--p-accent); color: var(--p-on-accent); }
.chip.warnchip { padding: 4px 8px; border-radius: 6px; font-size: 13px; font-weight: 700; color: var(--p-on-signal);
  background: var(--p-cue); border-color: var(--p-cue); }
.chip.warnchip.errchip { background: var(--p-live); border-color: var(--p-live); }
.armline { margin: 8px -12px -10px; padding: 7px 12px; font-size: 15px; font-weight: 700; color: var(--p-on-signal);
  background: var(--p-cue); display: flex; gap: 8px; align-items: baseline; white-space: nowrap; overflow: hidden; }
.armline b { font-size: 13px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; flex: none; }
.dtools { display: flex; gap: 4px; justify-content: flex-end; padding: 4px 6px; border-top: 1px solid var(--p-line);
  background: var(--p-surface-2); }
.dtools .tv { margin-right: auto; }
.ibtn.sm { width: var(--amx-hit-sm); height: var(--amx-hit-sm); border-radius: 10px; background: transparent; border-color: transparent; color: var(--p-muted); }
.ibtn.sm:hover:not([disabled]) { color: var(--p-fg); background: var(--p-surface-3); border-color: var(--p-line-strong); }
.ibtn.sm .ic { width: 19px; height: 19px; }
.ibtn.lock.on { color: var(--p-on-accent); background: var(--p-accent); border-color: var(--p-accent); }
.ibtn.tv { width: auto; min-width: var(--amx-hit-sm); padding: 0 8px; gap: 6px; }
.ibtn.tv.on { color: var(--p-on-signal); background: var(--p-ok); border-color: var(--p-ok); }
.ibtn.tv.bad { color: var(--p-on-signal); background: var(--p-cue); }
.tvin { font-size: 14px; font-weight: 600; font-family: var(--amx-mono); }
.dest.locked .dsrc { color: color-mix(in srgb, var(--p-fg) 75%, transparent); }
.dest.pending .dsrc { color: var(--p-live); }

/* ---------------- panel: sources as illuminated keys */
.srcs { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; padding: 12px; }
.compact .srcs { grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 6px; padding: 8px; }
.narrow .srcs { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 8px; }
.src { position: relative; overflow: hidden; display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  min-height: 84px; padding: 14px 12px 9px; text-align: left; cursor: pointer; border-radius: var(--amx-r);
  border: 1px solid var(--p-line-strong); background: var(--p-surface-3); color: var(--p-fg); touch-action: manipulation;
  transition: background-color .15s, border-color .15s, box-shadow .15s; min-width: 0; }
.compact .src { min-height: 64px; padding: 11px 10px 7px; }
.src:hover { background: color-mix(in srgb, var(--p-fg) 7%, var(--p-surface-3)); }
.src:active { transform: translateY(1px); }
.src .tally { position: absolute; inset: 0 0 auto 0; height: 5px; background: var(--p-line-strong); }
.sname { font-size: 16px; font-weight: 700; line-height: 1.2; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sid { font-size: 14px; color: var(--p-muted); max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sfoot { margin-top: auto; padding-top: 6px; display: flex; gap: 6px; align-items: center; width: 100%; min-height: 20px;
  font-size: 13px; color: var(--p-muted); }
.sstate { font-size: 13px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; white-space: nowrap; color: inherit; }
.tag { font-size: 13px; font-weight: 500; padding: 2px 6px; border-radius: 5px; background: var(--p-surface-2); color: var(--p-muted); white-space: nowrap; }
.use { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; font-family: var(--amx-mono); font-size: 14px; color: var(--p-muted); }
.use i { width: 7px; height: 7px; border-radius: 50%; background: var(--p-live); }
.src.black .sname { color: var(--p-muted); }
.src.black { background: repeating-linear-gradient(135deg, var(--p-surface-3) 0 8px, var(--p-surface-2) 8px 16px); }
.src.dead { border-style: dashed; background: var(--p-surface-2); }
.src.dead .sname, .src.dead .sid { opacity: .5; }
.offl { color: var(--p-muted); font-style: italic; }
/* program: full red key, white edge */
.src.pgm { background: var(--p-live); border-color: var(--p-live); color: var(--p-on-signal);
  box-shadow: 0 0 18px -4px var(--p-live); }
.src.pgm .tally, .src.pst .tally { background: var(--p-fg); }
:host([daylight]) .src.pgm .tally, :host([daylight]) .src.pst .tally { background: var(--p-on-signal); opacity: .75; }
.src.pgm .sid, .src.pgm .sfoot, .src.pgm .offl, .src.pgm .sname, .src.pgm .use,
.src.pst .sid, .src.pst .sfoot, .src.pst .offl, .src.pst .sname, .src.pst .use { color: var(--p-on-signal); opacity: 1; }
.src.pgm .tag, .src.pst .tag { background: rgba(0,0,0,.14); color: var(--p-on-signal); }
.src.pgm .use i, .src.pst .use i { background: var(--p-on-signal); }
/* preset: full amber key */
.src.pst { background: var(--p-cue); border-color: var(--p-cue); color: var(--p-on-signal); box-shadow: 0 0 18px -4px var(--p-cue); }
.src.pst.pgm { background: var(--p-live); border-color: var(--p-live); }
.src.pst.pgm .tally { background: var(--p-cue); height: 9px; opacity: 1; }
.src.pend { animation: amx-pend .8s ease-in-out infinite alternate; }
:host([daylight]) .src.pgm, :host([daylight]) .src.pst { box-shadow: 0 2px 8px -3px var(--p-shadow); }

/* ---------------- matrix */
.mxwrap { border-radius: var(--amx-rm); background: var(--p-surface); border: 1px solid var(--p-line); overflow: hidden; }
.mxscroll { overflow: auto; max-height: var(--av-matrix-max-height, 70vh); overscroll-behavior: contain; scrollbar-width: thin; }
.mx { border-collapse: separate; border-spacing: 0; min-width: 100%; }
.mx th, .mx td { padding: 0; }
.mx thead th { position: sticky; top: 0; z-index: 2; background: var(--p-surface-2); border-bottom: 1px solid var(--p-line-strong); vertical-align: bottom; }
.mx th.corner { left: 0; z-index: 4; text-align: left; border-right: 1px solid var(--p-line-strong); }
.cornerw { display: flex; flex-direction: column; justify-content: flex-end; gap: 4px; height: 142px; padding: 10px 12px;
  font-size: 13px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--p-muted); }
.cornerw .cs { align-self: flex-end; }
.ch { cursor: default; min-width: calc(var(--amx-xp) + 8px); }
.ch[data-act] { cursor: context-menu; }
.chw { height: 142px; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 6px; padding: 8px 0 10px; }
.chl { writing-mode: vertical-rl; transform: rotate(180deg); display: flex; align-items: center; gap: 7px; max-height: 136px;
  white-space: nowrap; overflow: hidden; }
.cht { display: flex; flex-direction: column; gap: 1px; overflow: hidden; min-height: 0; }
.chn { font-size: 14px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; }
.chs { font-size: 13px; color: var(--p-muted); overflow: hidden; text-overflow: ellipsis; }
.chl .led { width: 9px; height: 9px; }
.ch.dead .chn, .ch.dead .chs { opacity: .5; font-style: italic; }
.ch.black .chn { color: var(--p-muted); }
.mx th.rh { position: sticky; left: 0; z-index: 1; background: var(--p-surface-2); text-align: left;
  border-right: 1px solid var(--p-line-strong); font-weight: 400; box-shadow: inset 5px 0 0 var(--p-line-strong); }
.mx th.rh.st-connected { box-shadow: inset 5px 0 0 var(--p-ok); }
.mx th.rh.st-connecting, .mx th.rh.st-source_lost { box-shadow: inset 5px 0 0 var(--p-cue); }
.mx th.rh.st-offline, .mx th.rh.st-error { box-shadow: inset 5px 0 0 var(--p-live); }
tr.armed th.rh { background: color-mix(in srgb, var(--p-cue) 16%, var(--p-surface-2)); }
.rhw { display: flex; align-items: center; gap: 10px; padding: 6px 6px 6px 16px; min-width: 300px; max-width: 380px; }
.narrow .rhw { min-width: 190px; max-width: 230px; }
.rht { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.rhn { display: flex; align-items: baseline; gap: 7px; min-width: 0; font-size: 16px; font-weight: 700; white-space: nowrap; overflow: hidden; }
.rhn .ell { flex: 0 1 auto; }
.rho { font-size: 14px; font-weight: 400; color: var(--p-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 0 1 auto; }
.rhn[data-act] { cursor: text; text-decoration: underline dotted var(--p-accent-text); text-underline-offset: 3px; }
.rhs { display: flex; align-items: center; gap: 6px; font-size: 14px; color: var(--p-muted); min-width: 0; white-space: nowrap; }
.rhs .cur { overflow: hidden; text-overflow: ellipsis; }
.rhs.pending { color: var(--p-live); font-weight: 700; }
.rhs .chip.res { padding: 2px 6px; }
.pstx { display: inline-flex; gap: 6px; align-items: baseline; padding: 1px 8px; border-radius: 5px; background: var(--p-cue);
  color: var(--p-on-signal); font-weight: 700; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.pstx b { font-size: 12px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
.warnico { color: var(--p-cue); display: inline-flex; }
.warnico .ic { width: 16px; height: 16px; }
.rtools { display: flex; gap: 0; }
.rtools .tvin { display: none; }
.rtools .ibtn.sm { width: 34px; height: 34px; }
@media (pointer: coarse) { .rtools .ibtn.sm { width: 44px; height: 44px; } }
.rtools .ibtn.tv { padding: 0; }
.rtools .ibtn.tv.on, .rtools .ibtn.tv.bad { background: transparent; border-color: transparent; }
.rtools .ibtn.tv.on { color: var(--p-ok); }
.rtools .ibtn.tv.bad { color: var(--p-cue); }
.mx tbody tr + tr > * { border-top: 1px solid var(--p-line); }
.mx tbody td + td, .mx thead th.ch + th.ch { border-left: 1px solid var(--p-line); }
.mx td { text-align: center; background: var(--p-surface); }
/* crosspoint: dimmed key, fully lit when routed */
.xp { width: var(--amx-xp); height: var(--amx-xp); margin: 3px; border: 0; padding: 0; background: none; cursor: pointer;
  border-radius: 9px; display: inline-grid; place-items: center; position: relative; }
.xp i { width: 18px; height: 18px; border-radius: 5px; box-shadow: inset 0 0 0 2px var(--p-line-strong); background: transparent; }
.xp:hover i { box-shadow: inset 0 0 0 2px var(--p-muted); background: var(--p-surface-3); }
.xp.dead i { box-shadow: none; border: 2px dashed var(--p-line-strong); }
.xp.pgm i { width: calc(var(--amx-xp) - 10px); height: calc(var(--amx-xp) - 10px); border-radius: 7px; border: 0;
  background: var(--p-live); box-shadow: inset 0 3px 0 rgba(255,255,255,.75), 0 0 12px -2px var(--p-live); }
.xp.pgm.lost i { background: repeating-linear-gradient(135deg, var(--p-live) 0 4px, color-mix(in srgb, var(--p-live) 35%, var(--p-surface)) 4px 8px);
  box-shadow: inset 0 0 0 2px var(--p-live); }
.xp.pst i { width: calc(var(--amx-xp) - 10px); height: calc(var(--amx-xp) - 10px); border-radius: 7px; border: 0;
  background: var(--p-cue); box-shadow: inset 0 3px 0 rgba(255,255,255,.75), 0 0 12px -2px var(--p-cue); }
.xp.pgm.pst i { background: var(--p-live); box-shadow: inset 0 0 0 4px var(--p-cue); }
:host([daylight]) .xp.pgm i, :host([daylight]) .xp.pst i { box-shadow: inset 0 3px 0 rgba(255,255,255,.6); }
.xp.pend i { animation: amx-pend .8s ease-in-out infinite alternate; box-shadow: inset 0 0 0 2px var(--p-live); }
.xp[aria-disabled="true"] { cursor: not-allowed; }
.xp[aria-disabled="true"] i { opacity: .5; }
.flash { animation: amx-flash .55s ease-out; }
.xp.flash i { animation: amx-pop .3s ease-out; }

/* ---------------- footer / take bar */
.ftr { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px; border-radius: var(--amx-rm);
  border: 1px solid var(--p-line); background: var(--p-surface-2); position: sticky; bottom: 8px; z-index: 5;
  box-shadow: 0 8px 20px -12px var(--p-shadow); }
.fl, .fr { display: flex; gap: 6px; align-items: center; }
.armbar { flex: 1; min-width: 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 14px; }
.armlbl { font-weight: 800; color: var(--p-fg); margin-right: 4px; font-size: 13px; letter-spacing: .07em; text-transform: uppercase;
  display: inline-flex; align-items: center; gap: 7px; }
.armlbl::before { content: ""; width: 10px; height: 10px; border-radius: 2px; background: var(--p-cue); }
.armlbl.dim { color: var(--p-muted); text-transform: none; letter-spacing: 0; font-weight: 400; font-size: 14px; }
.armlbl.dim::before { display: none; }
.armchip { display: inline-flex; align-items: center; gap: 6px; padding: 0 4px 0 10px; min-height: 36px; border-radius: 8px; font-size: 14px;
  background: var(--p-cue); color: var(--p-on-signal); font-weight: 500; }
.armchip b { font-weight: 800; }
.armchip .x { border: 0; background: none; cursor: pointer; width: 30px; height: 30px; display: inline-grid; place-items: center;
  border-radius: 6px; color: var(--p-on-signal); }
.armchip .x:hover { background: rgba(0,0,0,.14); }
.armchip .x .ic { width: 15px; height: 15px; }
.kbdhint { display: inline-flex; align-items: center; gap: 8px; color: var(--p-muted); font-size: 13px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.kbdhint .ic { width: 18px; height: 18px; }
.narrow .kbdhint, .xs .fl .btn span { display: none; }
@media (pointer: coarse) { .kbdhint { display: none; } }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 7px; cursor: pointer; min-height: var(--amx-hit);
  padding: 0 14px; border-radius: var(--amx-r); font-size: 15px; font-weight: 700; border: 1px solid var(--p-line-strong);
  background: var(--p-surface-3); color: var(--p-fg); transition: background-color .15s, border-color .15s, opacity .15s; }
.btn:hover:not([disabled]) { background: color-mix(in srgb, var(--p-fg) 8%, var(--p-surface-3)); }
.btn[disabled] { opacity: .4; cursor: default; }
.btn.ghost { background: transparent; border-color: transparent; color: var(--p-fg); font-weight: 600; }
.btn.ghost:hover:not([disabled]) { background: var(--p-surface-3); border-color: var(--p-line-strong); }
.btn .ic { width: 18px; height: 18px; }
.btn .cnt { font-family: var(--amx-mono); font-size: 14px; font-weight: 600; padding: 1px 7px; border-radius: 99px; background: var(--p-surface-3); }
.btn .chev { transition: transform .15s; width: 16px; height: 16px; }
.btn.hist.on { background: var(--p-accent); border-color: var(--p-accent); color: var(--p-on-accent); }
.btn.hist.on .cnt { background: rgba(255,255,255,.2); }
.btn.hist.on .chev { transform: rotate(180deg); }
.btn kbd { margin-left: 2px; }
.btn.clear { min-width: 110px; min-height: 56px; }
.btn.take { min-width: 156px; min-height: 56px; font-size: 18px; font-weight: 800; letter-spacing: .12em; border-radius: 999px;
  color: var(--p-muted); background: var(--p-surface-3); padding: 0 24px; }
.btn.take kbd { color: inherit; border-color: currentColor; background: transparent; opacity: .7; }
.btn.take.hot { color: var(--p-on-accent); background: var(--p-accent); border-color: var(--p-accent);
  box-shadow: 0 0 18px -3px var(--p-accent); }
.btn.take.hot:hover { background: color-mix(in srgb, var(--p-accent) 88%, #fff); }
.narrow .ftr.preset .armbar { order: 3; flex-basis: 100%; }
.narrow .ftr.preset .fr { margin-left: auto; }
.xs .ftr.preset .fr { flex: 1; }
.xs .ftr.preset .fr .btn { flex: 1; min-width: 0; }
.narrow .btn kbd { display: none; }

/* ---------------- history */
.history { border-radius: var(--amx-rm); border: 1px solid var(--p-line); background: var(--p-surface-2); max-height: 280px; overflow: auto; }
.history ol { list-style: none; margin: 0; padding: 4px 0; }
.history li { display: grid; grid-template-columns: 86px minmax(110px, 190px) minmax(140px, 1.2fr) minmax(120px, 1fr) minmax(120px, auto);
  gap: 10px; align-items: center; padding: 8px 14px; font-size: 14px; }
.history li + li { border-top: 1px solid var(--p-line); }
.history li.empty { display: block; color: var(--p-muted); }
.history li:first-child:not(.empty) { animation: amx-in .15s ease-out; }
.ht { color: var(--p-muted); font-size: 14px; }
.hd { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hs { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hs .arr { color: var(--p-live); margin-right: 6px; font-weight: 700; }
.hp { color: var(--p-muted); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hp .was { margin-right: 5px; }
.hu { color: var(--p-muted); display: flex; gap: 6px; align-items: center; justify-content: flex-end; white-space: nowrap; }
.narrow .history li { grid-template-columns: 76px 1fr 1fr; }
.narrow .history .hp, .narrow .history .hu { display: none; }

/* ---------------- messages, toasts, spinner */
.msg { display: flex; align-items: center; gap: 10px; padding: 12px 4px; color: var(--p-muted); }
.msg.small { padding: 12px 14px; font-size: 14px; }
.msg.err { color: var(--p-fg); }
.msg.err .ic { color: var(--p-live); }
.spinner { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--p-line-strong); border-top-color: var(--p-live);
  animation: amx-spin .8s linear infinite; flex: none; display: inline-block; }
.spinner.sm { width: 13px; height: 13px; }
.toasts { position: absolute; left: 50%; bottom: 84px; transform: translateX(-50%); display: flex; flex-direction: column;
  gap: 6px; align-items: center; z-index: 10; pointer-events: none; width: max-content; max-width: calc(100% - 32px); }
.toast { display: flex; gap: 8px; align-items: center; padding: 10px 14px; border-radius: var(--amx-r); font-size: 15px; font-weight: 500;
  color: var(--p-fg); background: var(--p-surface-3); border: 1px solid var(--p-line-strong); border-top: 4px solid var(--p-line-strong);
  box-shadow: 0 10px 30px -10px var(--p-shadow); animation: amx-in .15s ease-out; transition: opacity .3s, transform .3s; }
.toast .ic { width: 18px; height: 18px; }
.toast.err { border-top-color: var(--p-live); }
.toast.err .ic { color: var(--p-live); }
.toast.warn { border-top-color: var(--p-cue); }
.toast.warn .ic { color: var(--p-cue); }
.toast.ok { border-top-color: var(--p-ok); }
.toast.out { opacity: 0; transform: translateY(6px); }
.shake { animation: amx-shake .4s ease-in-out; }

/* ---------------- dialog (label editor) */
dialog { border: 1px solid var(--p-line-strong); border-radius: var(--amx-rm); padding: 0; width: min(460px, calc(100vw - 32px));
  color: var(--p-fg); background: var(--p-surface-2); box-shadow: 0 30px 80px -20px var(--p-shadow); font-family: var(--p-font); font-size: 15px; }
dialog::before { content: ""; display: block; height: 4px; background: var(--p-accent); }
dialog::backdrop { background: rgba(0,0,0,.5); }
.dlg-body { display: flex; flex-direction: column; gap: 14px; padding: 18px; }
.dlg-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.dlg-kicker { font-size: 13px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--p-muted); }
.dlg-title { font-size: 18px; font-weight: 700; margin-top: 4px; word-break: break-all; }
.dlg-sub { font-size: 14px; color: var(--p-muted); margin-top: 2px; font-family: var(--amx-mono); }
.fld { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 500; letter-spacing: .07em; text-transform: uppercase; color: var(--p-muted); }
.fld input { height: 56px; border-radius: var(--amx-r); border: 1px solid var(--p-line-strong); background: var(--p-surface); color: var(--p-fg);
  padding: 0 14px; font-size: 17px; font-weight: 500; letter-spacing: 0; text-transform: none; outline: none; }
.fld input:focus { outline: 3px solid var(--p-accent-text); outline-offset: 2px; }
.dlg-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.dlg-actions { display: flex; gap: 8px; align-items: center; }
.dlg-actions .grow { flex: 1; }
.btn.primary { background: var(--p-accent); border-color: var(--p-accent); color: var(--p-on-accent); }
.btn.primary:hover:not([disabled]) { background: color-mix(in srgb, var(--p-accent) 88%, #fff); }
.btn.danger { color: var(--p-live); }
.dlg-head .dlgart { width: 72px; margin-top: 2px; }
.dlg-id { flex: 1; min-width: 0; }

/* ---------------- discovered receivers + add dialog (admin) */
.addbtn { width: auto; padding: 0 14px 0 11px; gap: 6px; font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.addbtn .ic { width: 18px; height: 18px; }
.adm { display: contents; }
/* phones: add + edit on their own row, right-aligned, so the console controls keep their 44/56 px keys */
.xs .ctrl2 { flex-wrap: wrap; }
.xs .ctrl2 .seg { flex: none; }
.xs .adm { display: flex; gap: 6px; margin-left: auto; }
.xs .ctrl2 .adm .ibtn.tgl { margin-left: 0; }
.found { display: flex; align-items: center; gap: 10px 16px; flex-wrap: wrap; padding: 10px 12px 10px 14px; border-radius: var(--amx-r);
  background: color-mix(in srgb, var(--p-accent) 13%, var(--p-surface-2)); border: 1px solid color-mix(in srgb, var(--p-accent) 55%, var(--p-line-strong));
  border-left: 5px solid var(--p-accent); animation: amx-in .2s ease-out; }
.found-txt { display: flex; align-items: center; gap: 10px; flex: 1 1 260px; min-width: 0; color: var(--p-fg); font-size: 16px; line-height: 1.25; }
.found-txt > .ic { width: 26px; height: 26px; flex: none; color: var(--p-accent-text); }
.found-txt b { font-weight: 800; }
.found-sub { display: block; font-size: 14px; color: var(--p-muted); }
.found-list { display: flex; gap: 8px; flex-wrap: wrap; }
.found-dev { display: inline-flex; align-items: center; gap: 10px; min-height: var(--amx-hit); padding: 4px 6px 4px 8px; cursor: pointer;
  border-radius: var(--amx-r); border: 1px solid var(--p-line-strong); background: var(--p-surface); color: var(--p-fg); text-align: left;
  max-width: 100%; transition: background-color .15s, border-color .15s; }
.found-dev:hover { border-color: var(--p-accent); }
.found-dev:focus-visible { outline: 3px solid var(--p-accent-text); outline-offset: 2px; }
.found-dev .fart { width: 44px; flex: none; }
.fdn { display: flex; flex-direction: column; min-width: 0; font-size: 15px; font-weight: 700; }
.fdh { font-size: 13px; font-weight: 500; color: var(--p-muted); font-family: var(--amx-mono); white-space: nowrap; }
.fadd { display: inline-flex; align-items: center; gap: 5px; margin-left: 4px; padding: 0 12px 0 9px; min-height: 36px; border-radius: 8px;
  background: var(--p-accent); color: var(--p-on-accent); font-size: 14px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; white-space: nowrap; }
.fadd .ic { width: 16px; height: 16px; }
.narrow .found-list, .narrow .found-dev { width: 100%; }
.narrow .found-dev .fdn { flex: 1; }
dialog.flowdlg { width: min(540px, calc(100vw - 32px)); max-height: calc(100vh - 48px); }
.flowdlg .dlg-title { word-break: normal; font-size: 20px; }
.fdesc { margin: 0; font-size: 15px; line-height: 1.45; color: var(--p-muted); }
.fdesc b { color: var(--p-fg); font-weight: 700; }
.fbody { display: flex; flex-direction: column; gap: 14px; }
.fbase { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: var(--amx-r); font-size: 15px; font-weight: 600;
  background: color-mix(in srgb, var(--p-live) 12%, var(--p-surface)); border: 1px solid color-mix(in srgb, var(--p-live) 50%, var(--p-line-strong)); }
.fbase .ic { width: 20px; height: 20px; flex: none; color: var(--p-live); }
.fld select { height: 56px; border-radius: var(--amx-r); border: 1px solid var(--p-line-strong); background: var(--p-surface); color: var(--p-fg);
  padding: 0 12px; font-size: 17px; font-weight: 500; text-transform: none; letter-spacing: 0; }
.fld input[aria-invalid="true"] { border-color: var(--p-live); box-shadow: inset 0 0 0 1px var(--p-live); }
.fhelp { font-size: 13px; letter-spacing: 0; text-transform: none; color: var(--p-muted); font-weight: 400; line-height: 1.35; }
.ferr { display: inline-flex; gap: 6px; align-items: center; font-size: 14px; font-weight: 600; letter-spacing: 0; text-transform: none; color: var(--p-live); }
.ferr .ic { width: 15px; height: 15px; }
.fld.chk { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 10px; text-transform: none; letter-spacing: 0; font-size: 16px; color: var(--p-fg); }
.fld.chk input { width: 22px; height: 22px; accent-color: var(--p-accent); }
.fld.chk .fhelp, .fld.chk .ferr { flex-basis: 100%; }
fieldset.fld { border: 0; margin: 0; padding: 0; min-width: 0; }
fieldset.fld legend { padding: 0; margin-bottom: 6px; }
.opts { display: flex; flex-direction: column; gap: 6px; max-height: 300px; overflow: auto; }
.opt { position: relative; display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 6px 12px; cursor: pointer; border-radius: var(--amx-r);
  border: 1px solid var(--p-line-strong); background: var(--p-surface); color: var(--p-fg); font-size: 16px; font-weight: 600; letter-spacing: 0; text-transform: none; }
.opt input { position: absolute; opacity: 0; pointer-events: none; }
.optk { width: 18px; height: 18px; flex: none; border-radius: 50%; box-shadow: inset 0 0 0 2px var(--p-line-strong); }
.opt input[type=checkbox] + .optk { border-radius: 4px; }
.opt:has(input:checked) { border-color: var(--p-accent); box-shadow: inset 4px 0 0 var(--p-accent); }
.opt input:checked + .optk { background: var(--p-accent); box-shadow: inset 0 0 0 4px var(--p-surface), 0 0 0 2px var(--p-accent); }
.opt:has(input:focus-visible) { outline: 3px solid var(--p-accent-text); outline-offset: 2px; }
.fmenu { display: flex; flex-direction: column; gap: 8px; }
.fmenu-k { display: flex; align-items: center; gap: 12px; min-height: 60px; padding: 0 14px; cursor: pointer; border-radius: var(--amx-r);
  border: 1px solid var(--p-line-strong); background: var(--p-surface); color: var(--p-fg); font-size: 16px; font-weight: 700; text-align: left; }
.fmenu-k:hover:not([disabled]) { border-color: var(--p-accent); }
.fmenu-k:focus-visible { outline: 3px solid var(--p-accent-text); outline-offset: 2px; }
.fmenu-k .ic { width: 22px; height: 22px; flex: none; color: var(--p-accent-text); }
.fmenu-k span { flex: 1; }
.fmenu-k .go { transform: rotate(-90deg); color: var(--p-muted); width: 18px; height: 18px; }
.flowdlg .dlg-actions { flex-wrap: wrap; }
.flowdlg .btn .ic { width: 16px; height: 16px; }

/* ---------------- grouped protocols (Dante®): device filters, collapsible device groups */
.gsels { display: flex; gap: 6px; flex-wrap: wrap; }
.gsel { position: relative; display: inline-flex; align-items: center; gap: 6px; height: var(--amx-hit); padding: 0 10px 0 12px;
  border-radius: var(--amx-r); background: var(--p-surface-3); border: 1px solid var(--p-line-strong); color: var(--p-muted); font-size: 13px;
  font-weight: 500; letter-spacing: .05em; text-transform: uppercase; }
.gsel.on { color: var(--p-on-accent); border-color: var(--p-accent); background: var(--p-accent); }
.gsel.on select { color: var(--p-on-accent); }
.gsel .ic { width: 17px; height: 17px; flex: none; }
.gsel .gl { white-space: nowrap; }
.gsel select { appearance: none; -webkit-appearance: none; border: 0; outline: 0; background: none; color: var(--p-fg); font-size: 15px;
  font-weight: 700; letter-spacing: 0; text-transform: none; padding: 0 20px 0 2px; margin-right: -18px; max-width: 200px; cursor: pointer;
  text-overflow: ellipsis; height: 100%; }
.gsel select option { color: initial; }
.gsel .chev { width: 15px; height: 15px; pointer-events: none; }
.gsel:focus-within { outline: 3px solid var(--p-accent-text); outline-offset: 2px; }
.narrow .gsels { width: 100%; }
.narrow .gsel { flex: 1 1 0; min-width: 0; }
.narrow .gsel .ic:first-child { display: none; }
.narrow .gsel select { max-width: none; flex: 1; min-width: 0; }
.gtog { display: inline-flex; align-items: center; gap: 8px; border: 0; background: none; color: var(--p-fg); cursor: pointer;
  padding: 4px 10px 4px 6px; border-radius: 10px; min-height: 40px; max-width: 100%; text-align: left; }
@media (pointer: coarse) { .gtog { min-height: 48px; } }
.gtog:hover { background: color-mix(in srgb, var(--p-fg) 7%, transparent); }
.gtog .chev { width: 17px; height: 17px; flex: none; transition: transform .15s; color: var(--p-muted); }
.gtog.closed .chev { transform: rotate(-90deg); }
.gtog .led { width: 9px; height: 9px; }
.gtog .gname { font-size: 14px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.gtog .gcount, .gtog .gsub { font-family: var(--amx-mono); font-size: 14px; color: var(--p-muted); white-space: nowrap; }
.gtog .gsub { padding: 1px 7px; border-radius: 99px; background: var(--p-surface); border: 1px solid var(--p-line); }
.gtog .garm { font-size: 12px; font-weight: 800; letter-spacing: .06em; padding: 2px 7px; border-radius: 5px; background: var(--p-cue); color: var(--p-on-signal); }
.gtog .gpgm { width: 10px; height: 10px; border-radius: 50%; background: var(--p-live); box-shadow: 0 0 6px var(--p-live); }
.dests.grouped > .ghead, .srcs.grouped > .ghead { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px;
  margin-top: 4px; border-bottom: 1px solid var(--p-line); padding-bottom: 2px; }
.dests.grouped > .ghead:first-child, .srcs.grouped > .src.black + .ghead { margin-top: 0; }
.srcs.grouped > .src.black { grid-column: 1 / -1; max-width: 240px; }
.mx thead tr.ghr > th { height: 46px; }
.mx thead tr.ghr > th.cgh { vertical-align: middle; text-align: left; padding: 0 2px; border-bottom: 1px solid var(--p-line);
  border-left: 1px solid var(--p-line-strong); }
.mx thead tr.ghr > th.cgh .gtog { position: sticky; left: 290px; }
.narrow .mx thead tr.ghr > th.cgh .gtog { left: 200px; }
.mx thead tr.chr > th { top: 47px; }
.mxwrap.grouped .chw { height: 124px; }
.mxwrap.grouped .chl { max-height: 108px; }
.mxwrap.grouped .cornerw { height: 171px; }
.mx th.ch.gs, .mx td.gs { border-left: 1px solid var(--p-line-strong) !important; }
.mx th.ch.sum .chn { font-family: var(--amx-mono); font-size: 14px; font-weight: 500; color: var(--p-muted); }
.mx th.ch.sum, .mx td.gs:has(> .xp.sum) { background: repeating-linear-gradient(135deg, var(--p-surface) 0 6px, var(--p-surface-2) 6px 12px); }
.xp.sum { width: auto; min-width: var(--amx-xp); padding: 0 8px; gap: 6px; display: inline-flex; align-items: center; }
.xp.sum i { box-shadow: none; border: 2px dotted var(--p-line-strong); }
.xp.sum .sumn { font-size: 14px; font-weight: 700; color: var(--p-fg); white-space: nowrap; max-width: 110px; overflow: hidden; text-overflow: ellipsis; }
.xp.sum.pgm i { width: 18px; height: 18px; border: 0; }
.mx tbody tr.rgr > th { text-align: left; padding: 0; background: var(--p-surface-3); border-top: 1px solid var(--p-line-strong);
  border-bottom: 1px solid var(--p-line); }
.mx tbody tr.rgr + tr > * { border-top: 0; }
.rghw { position: sticky; left: 0; display: inline-flex; align-items: center; padding: 3px 8px; }
.dests.grouped { grid-template-columns: repeat(auto-fill, minmax(172px, 1fr)); gap: 8px; }
.narrow .dests.grouped { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.dests.grouped .dest { flex-direction: row; align-items: stretch; }
.dests.grouped .dest-main { min-height: 0; padding: 10px 8px 8px 10px; gap: 1px; flex: 1; min-width: 0; }
.dests.grouped .dtop { font-size: 13px; }
.dests.grouped .dband { margin: 4px -8px 1px -10px; padding: 3px 8px 3px 10px; }
.dests.grouped .dname { font-size: 16px; }
.dests.grouped .dsrc { font-size: 15px; margin-top: 3px; }
.dests.grouped .dsub { font-size: 14px; min-height: 18px; }
.dests.grouped .dmeta:not(:has(.lockchip)) { display: none; }
.dests.grouped .dwarn { margin-top: 4px; }
.dests.grouped .armline { margin: 6px -8px -8px -10px; padding: 5px 10px; font-size: 14px; }
.dests.grouped .dtools { flex-direction: column; justify-content: flex-start; padding: 6px 3px 3px; border-top: 0;
  border-left: 1px solid var(--p-line); gap: 2px; }
.dests.grouped .dtools .ibtn.sm { width: 34px; height: 34px; }
@media (pointer: coarse) { .dests.grouped .dtools .ibtn.sm { width: 44px; height: 44px; } }

/* ---------------- device illustrations (SVG sprite + <use>, colours via custom properties) */
.sprite { position: absolute; width: 0; height: 0; overflow: hidden; pointer-events: none; }
ha-card.amx-light { --avm-dev-body: #474e58; --avm-dev-top: #5c636d; --avm-dev-side: #2c3138; --avm-dev-line: #9aa3ad;
  --avm-dev-metal: #c9d0d7; --avm-dev-screen: #161a20; }
.dev { display: block; flex: none; overflow: visible; aspect-ratio: 3 / 2; height: auto; pointer-events: none; }
span.dev.wait { visibility: hidden; }
.dev.s-connected { --avm-led: var(--p-ok); }
.dev.s-connecting { --avm-led: var(--p-cue); }
.dev.s-no_source { --avm-led: #8a8f96; }
.dev.s-source_lost { --avm-led: var(--p-cue); }
.dev.s-error, .dev.s-offline { --avm-led: var(--p-live); }
.dev .halo { fill: var(--avm-led); opacity: 0; animation: amx-halo 1.1s ease-in-out infinite; }
@keyframes amx-halo { 0%, 100% { opacity: 0; } 50% { opacity: .55; } }
.dfoot { display: flex; align-items: flex-end; gap: 8px; margin-top: auto; padding-top: 6px; min-width: 0; }
.dfoot .dmeta { flex: 1; min-width: 0; }
.dart { width: 66px; margin: -6px -4px -4px auto; }
.dwarn { display: flex; margin-top: 6px; min-width: 0; }
.dwarn .chip { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.dmeta .chip { max-width: 100%; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.compact .dart { width: 50px; }
.narrow .dart { width: 52px; }
.xs .dart { width: 44px; }
.dest.st-offline .dart, .dest.st-no_source .dart { opacity: .75; }
.sart { width: 30px; margin: -6px -3px -3px auto; }
.use + .sart { margin-left: 2px; }
.stags { display: flex; gap: 6px; align-items: center; flex: 0 1 auto; min-width: 0; overflow: hidden; white-space: nowrap; }
.stags .offl { overflow: hidden; text-overflow: ellipsis; }
.src.dead .sart { opacity: .4; }
.compact .sart { width: 24px; }
.src.pgm .sstate + .stags .tag, .src.pst .sstate + .stags .tag { display: none; }
.rart { width: 32px; }
.narrow .rart { width: 26px; }
.mxwrap:not(.grouped) .chw { height: 176px; }
.mxwrap:not(.grouped) .cornerw { height: 176px; }
.chl { max-height: 140px; }
.cart { width: 26px; }
.mxwrap.grouped .chl { max-height: 108px; }
.gart { width: 34px; margin: -3px 0; }
.mx .gart { width: 30px; }
.dname[data-dl] { cursor: inherit; }
.mode-panel .edit-hint ~ .panel .dest-main .dname { text-decoration: underline dotted; text-underline-offset: 3px; }
.xs .rhw { min-width: 156px; max-width: 184px; gap: 7px; padding-left: 12px; }
.xs .rart, .xs .rho, .xs .rhs .chip.res, .xs .rtools [data-act="undo"] { display: none; }
.xs .mxwrap:not(.grouped) .chw, .xs .mxwrap:not(.grouped) .cornerw { height: 150px; }
.xs .chl { max-height: 120px; }
.xs .mod-h > span { display: none; }

/* ---------------- motion: state changes only */
@keyframes amx-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
@keyframes amx-pend { from { box-shadow: 0 0 0 0 color-mix(in srgb, var(--p-live) 0%, transparent); }
  to { box-shadow: 0 0 0 3px color-mix(in srgb, var(--p-live) 60%, transparent); } }
@keyframes amx-flash { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--p-live) 70%, transparent); } 100% { box-shadow: 0 0 0 12px transparent; } }
@keyframes amx-pop { 0% { transform: scale(.5); } 100% { transform: scale(1); } }
@keyframes amx-spin { to { transform: rotate(360deg); } }
@keyframes amx-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@keyframes amx-shake { 0%, 100% { transform: none; } 20%, 60% { transform: translateX(-5px); } 40%, 80% { transform: translateX(5px); } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 1ms !important; animation-iteration-count: 1 !important; transition: none !important; }
  .led.connecting, .dest.st-connecting::before { animation: none !important; }
  .dev .halo { animation: none !important; opacity: .35; }
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
        name: "name_mode",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "both", label: de ? "Beide (Label, darunter Originalname)" : "Both (label, original name underneath)" },
              { value: "label", label: "Label" },
              { value: "original", label: de ? "Originalname" : "Original name" },
            ],
          },
        },
      },
      {
        name: "theme",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "auto", label: de ? "Automatisch (nach Home-Assistant-Theme)" : "Automatic (follows the Home Assistant theme)" },
              { value: "dark", label: de ? "Dunkel (Regie, Saal, Abend)" : "Dark (control room, hall, evening)" },
              { value: "daylight", label: de ? "Tageslicht (Open Air, Bühne, Büro)" : "Daylight (open air, stage, office)" },
            ],
          },
        },
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
      name_mode: de ? "Namen (Start, im Browser umschaltbar)" : "Names (initial, switchable in the browser)",
      show_offline: de ? "Offline-Quellen zeigen" : "Show offline sources",
      compact: de ? "Kompakt" : "Compact",
      theme: de ? "Darstellung" : "Theme",
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
      name_mode: "both",
      theme: "auto",
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
