/**
 * Water Heater Optimizer info page — 热水器优化器信息页
 * (water-heater-optimizer-page).
 *
 * Zero-build vanilla Web Component served from static/, mounted by the
 * FumihaHub shell as a page module. Read-only: data comes from
 * GET /api/water_heater_optimizer/info via hass.fetchWithAuth; the page
 * invents no mutation endpoints.
 *
 * No hub tokens.css link (Stockroom/WHA shape), so :host{display:block}
 * is declared here per the hub registry display contract.
 *
 * All server-provided strings are rendered through textContent (el()).
 */

const API_INFO = "/api/water_heater_optimizer/info";
const POLL_MS = 30000;

const ROWS = [
  ["last_avg_temp", "24h 均值进水温度"],
  ["target_temp", "目标淋浴温度"],
  ["hot_water_ratio", "热水比例"],
  ["min_temp", "推荐下限"],
  ["max_temp", "推荐上限"],
  ["applied_temp", "最近下发"],
];

const STYLE = `
  :host { display: block; height: 100%; overflow-y: auto; }
  .wrap {
    font: 14px/1.6 var(--paper-font-body1_-_font-family, sans-serif);
    color: var(--primary-text-color, #212121);
    padding: 16px;
    max-width: 720px;
    margin: 0 auto;
    box-sizing: border-box;
  }
  .card {
    background: var(--card-background-color, #fff);
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 16px;
    box-shadow: var(--shadow-2dp, 0 2px 2px rgba(0,0,0,.14));
  }
  .head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .rec {
    font-size: 34px; font-weight: 600;
    color: var(--primary-text-color, #212121);
  }
  .rec small { font-size: 14px; font-weight: 400; }
  .badge {
    font-size: 12px; padding: 2px 10px; border-radius: 10px;
    background: var(--primary-color, #03a9f4); color: #fff;
  }
  .badge.off { background: var(--disabled-text-color, #9e9e9e); }
  .row {
    display: flex; justify-content: space-between; gap: 12px;
    padding: 3px 0; border-top: 1px solid var(--divider-color, #e0e0e0);
  }
  .row:first-of-type { border-top: none; }
  .row .k { color: var(--secondary-text-color, #727272); }
  .row .v { font-variant-numeric: tabular-nums; }
  .hint { font-size: 12px; color: var(--secondary-text-color, #727272); }
  .err { color: var(--error-color, #db4437); white-space: pre-wrap; }
`;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fmt(value, unit) {
  if (value === null || value === undefined) return "—";
  return value + (unit || "");
}

class WaterHeaterOptimizerPage extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._timer = null;
    this._seq = 0;
    this._root = this.attachShadow({ mode: "open" });
  }

  set hass(value) {
    const first = this._hass === null;
    this._hass = value;
    // The shell injects hass after mount; react immediately so the first
    // fetch does not wait out the poll interval (Stockroom lesson).
    if (first && this.isConnected) this._refresh();
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._renderShell();
    if (this._hass) this._refresh();
    this._timer = setInterval(() => this._refresh(), POLL_MS);
  }

  disconnectedCallback() {
    // Kill in-flight fetches: a stale response must not render into a
    // detached DOM after the hub unmounted this page.
    this._seq += 1;
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _renderShell() {
    const style = document.createElement("style");
    style.textContent = STYLE;
    this._root.replaceChildren(style, el("div", "wrap"));
  }

  async _fetch() {
    if (!this._hass) throw new Error("hass 未就绪");
    const response = await this._hass.fetchWithAuth(API_INFO);
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) {
      throw new Error(`HTTP ${response.status}`);
    }
    return payload;
  }

  async _refresh() {
    const seq = ++this._seq;
    try {
      const payload = await this._fetch();
      if (seq !== this._seq) return;
      this._render(payload.entries || []);
    } catch (err) {
      if (seq !== this._seq) return;
      const wrap = this._root.querySelector(".wrap");
      if (wrap) {
        wrap.replaceChildren(
          el("div", "err", "信息页加载失败：" + (err && err.message ? err.message : err))
        );
      }
    }
  }

  _render(entries) {
    const wrap = this._root.querySelector(".wrap");
    if (!wrap) return;
    wrap.replaceChildren();
    if (!entries.length) {
      wrap.append(el("div", "hint", "没有已配置的热水器优化器条目。"));
      return;
    }
    for (const entry of entries) {
      wrap.append(this._renderEntry(entry));
    }
  }

  _renderEntry(entry) {
    const card = el("div", "card");
    const head = el("div", "head");
    head.append(el("div", "rec", fmt(entry.recommended_temp, "") + "°C"));
    const badge = el(
      "span",
      "badge" + (entry.auto_adjust ? "" : " off"),
      entry.auto_adjust ? "自动调节 开" : "自动调节 关"
    );
    head.append(badge);
    card.append(head);

    for (const [key, label] of ROWS) {
      const row = el("div", "row");
      row.append(el("span", "k", label));
      row.append(el("span", "v", this._fmtField(key, entry[key])));
      card.append(row);
    }

    // shortcut: 设备页跳转未实现(无 more-info 事件形态实证), 实体以文本呈现;
    // 升级时机=某现役面板出现 hass-more-info 用例并实证事件形态后随批清偿
    const heaterRow = el("div", "row");
    heaterRow.append(el("span", "k", "热水器"));
    heaterRow.append(el("span", "v", fmt(entry.water_heater)));
    card.append(heaterRow);
    const avgRow = el("div", "row");
    avgRow.append(el("span", "k", "均值源实体"));
    avgRow.append(el("span", "v", fmt(entry.inlet_temp_sensor)));
    card.append(avgRow);
    return card;
  }

  _fmtField(key, value) {
    if (value === null || value === undefined) return "—";
    if (key === "hot_water_ratio") return String(value);
    if (key === "last_avg_temp") return value + "°C";
    if (key === "target_temp" || key === "min_temp" || key === "max_temp") {
      return value + "°C";
    }
    if (key === "applied_temp") return value + "°C";
    return String(value);
  }
}

customElements.define("water-heater-optimizer-page", WaterHeaterOptimizerPage);
