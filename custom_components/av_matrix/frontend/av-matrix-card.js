/*
 * AV Matrix card - a plain, working crosspoint grid for the av_matrix integration.
 * Rows = destinations, columns = sources, one tab per protocol. Click = route.
 * Data comes from the WebSocket subscription "av_matrix/subscribe" (docs/frontend-api.md).
 * Served by the integration itself; no build step, no manual resource needed.
 */
const CARD_VERSION = "0.1.0";

class AvMatrixCard extends HTMLElement {
  setConfig(config) {
    this._config = { title: "AV Matrix", show_offline_sources: true, ...(config || {}) };
    this._protocol = this._config.protocol || null;
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || !this._unsub) this._subscribe();
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((u) => u()).catch(() => {});
      this._unsub = null;
    }
  }

  _subscribe() {
    if (!this._hass || !this._hass.connection || this._unsub) return;
    this._unsub = this._hass.connection.subscribeMessage(
      (state) => {
        this._state = state;
        this._error = null;
        this._render();
      },
      { type: "av_matrix/subscribe" }
    );
    this._unsub.catch((err) => {
      this._unsub = null;
      this._error = (err && err.message) || "AV Matrix integration not loaded";
      this._render();
    });
  }

  getCardSize() {
    const p = this._currentProtocol();
    return 2 + (p ? p.destinations.length : 2);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  static getStubConfig() {
    return { title: "AV Matrix" };
  }

  _currentProtocol() {
    const protos = (this._state && this._state.protocols) || {};
    const keys = Object.keys(protos);
    if (!keys.length) return null;
    if (!this._protocol || !protos[this._protocol]) this._protocol = keys[0];
    return protos[this._protocol];
  }

  async _route(dest, sourceId) {
    if (dest.locked) return;
    this._busy = `${dest.id}`;
    this._render();
    try {
      await this._hass.callService("av_matrix", "route", {
        entity_id: dest.entity_id,
        source: sourceId === null ? "None" : sourceId,
      });
    } catch (err) {
      this._error = (err && err.message) || String(err);
    }
    this._busy = null;
    this._render();
  }

  _esc(text) {
    return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const protos = (this._state && this._state.protocols) || {};
    const proto = this._currentProtocol();
    const keys = Object.keys(protos);
    let body;
    if (this._error && !proto) {
      body = `<div class="msg">${this._esc(this._error)}</div>`;
    } else if (!this._state) {
      body = `<div class="msg">Loading…</div>`;
    } else if (!proto) {
      body = `<div class="msg">No devices yet. Add one under Settings → Devices &amp; services → AV Matrix.</div>`;
    } else {
      const sources = proto.sources.filter((s) => this._config.show_offline_sources || s.live);
      const head = sources
        .map((s) => `<th class="src ${s.live ? "" : "dead"}" title="${this._esc(s.id)}${s.host ? " · " + this._esc(s.host) : ""}"><span>${this._esc(s.name)}</span></th>`)
        .join("");
      const rows = proto.destinations
        .map((d) => {
          const cells = sources
            .map((s) => {
              const on = d.current_source === s.id;
              return `<td><button class="x ${on ? "on" : ""} ${on && !s.live ? "lost" : ""}" data-d="${this._esc(d.id)}" data-s="${this._esc(s.id)}" ${d.locked ? "disabled" : ""} aria-label="${this._esc(s.name)} → ${this._esc(d.name)}"></button></td>`;
            })
            .join("");
          const off = `<td><button class="x none ${d.current_source === null ? "on" : ""}" data-d="${this._esc(d.id)}" data-s="" ${d.locked ? "disabled" : ""} aria-label="None → ${this._esc(d.name)}"></button></td>`;
          return `<tr><th class="dst"><span class="dot ${this._esc(d.status)}" title="${this._esc(d.status)}"></span>${this._esc(d.name)}${d.locked ? ' <ha-icon icon="mdi:lock"></ha-icon>' : ""}<div class="sub">${this._esc(d.resolution || d.status.replace("_", " "))}</div></th>${off}${cells}</tr>`;
        })
        .join("");
      body = `<div class="scroll"><table><thead><tr><th></th><th class="src"><span>None</span></th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
      if (this._error) body += `<div class="msg err">${this._esc(this._error)}</div>`;
    }
    const tabs =
      keys.length > 1
        ? `<div class="tabs">${keys.map((k) => `<button class="tab ${k === this._protocol ? "act" : ""}" data-p="${this._esc(k)}">${this._esc(protos[k].title)}</button>`).join("")}</div>`
        : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 12px 0 8px; }
        .title { padding: 0 16px 8px; font-size: var(--ha-card-header-font-size, 20px); color: var(--ha-card-header-color, var(--primary-text-color)); }
        .tabs { display: flex; gap: 4px; padding: 0 16px 8px; }
        .tab { border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color); border-radius: 12px; padding: 2px 10px; cursor: pointer; }
        .tab.act { background: var(--primary-color); color: var(--text-primary-color); border-color: var(--primary-color); }
        .scroll { overflow-x: auto; padding: 0 16px; -webkit-overflow-scrolling: touch; }
        table { border-collapse: collapse; }
        th, td { padding: 2px; text-align: center; }
        th.dst { text-align: left; white-space: nowrap; padding-right: 10px; font-weight: 500; color: var(--primary-text-color); position: sticky; left: 0; background: var(--ha-card-background, var(--card-background-color)); z-index: 1; }
        th.dst ha-icon { --mdc-icon-size: 14px; color: var(--secondary-text-color); }
        .sub { font-size: 11px; font-weight: 400; color: var(--secondary-text-color); padding-left: 14px; }
        th.src { vertical-align: bottom; height: 110px; width: 34px; }
        th.src span { display: inline-block; writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; max-height: 108px; overflow: hidden; text-overflow: ellipsis; font-weight: 400; font-size: 12px; color: var(--primary-text-color); }
        th.src.dead span { color: var(--disabled-text-color, var(--secondary-text-color)); font-style: italic; }
        .x { width: 30px; height: 30px; border-radius: 6px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); cursor: pointer; padding: 0; }
        .x:hover:not([disabled]) { border-color: var(--primary-color); }
        .x.on { background: var(--primary-color); border-color: var(--primary-color); }
        .x.on.lost { background: var(--warning-color, #ffa600); border-color: var(--warning-color, #ffa600); }
        .x.none.on { background: var(--secondary-text-color); }
        .x[disabled] { cursor: not-allowed; opacity: .5; }
        .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: var(--disabled-text-color, #999); }
        .dot.connected { background: var(--success-color, #43a047); }
        .dot.connecting { background: var(--warning-color, #ffa600); }
        .dot.source_lost, .dot.offline { background: var(--error-color, #db4437); }
        .msg { padding: 8px 16px; color: var(--secondary-text-color); }
        .msg.err { color: var(--error-color, #db4437); }
      </style>
      <ha-card>
        ${this._config && this._config.title ? `<div class="title">${this._esc(this._config.title)}</div>` : ""}
        ${tabs}
        ${body}
      </ha-card>`;
    this.shadowRoot.querySelectorAll("button.tab").forEach((b) =>
      b.addEventListener("click", () => {
        this._protocol = b.dataset.p;
        this._render();
      })
    );
    this.shadowRoot.querySelectorAll("button.x").forEach((b) =>
      b.addEventListener("click", () => {
        const p = this._currentProtocol();
        const dest = p && p.destinations.find((d) => d.id === b.dataset.d);
        if (dest) this._route(dest, b.dataset.s === "" ? null : b.dataset.s);
      })
    );
  }
}

if (!customElements.get("av-matrix-card")) {
  customElements.define("av-matrix-card", AvMatrixCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "av-matrix-card",
    name: "AV Matrix",
    description: "Crosspoint matrix for the AV Matrix integration (NDI® decoders and more).",
    preview: false,
    documentationURL: "https://github.com/strelle/ha-av-matrix",
  });
  console.info(`%c AV-MATRIX-CARD %c ${CARD_VERSION} `, "background:#03a9f4;color:#fff", "");
}
