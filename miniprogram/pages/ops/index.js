const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");

const { syncTabBar } = require("../../utils/tabbar");
const { bgBarWidthPct, buildCategoriesDrillUrlFromLargeRow } = require("../../utils/analyticsUI");

Page({
  data: {
    labor: null,
    inv: null,
    quad: null,
    quadHeat: [],
    invExpanded: false,
    invDisplayItems: [],
  },
  onShow() {
    syncTabBar();
    if (!requireToken()) return;
    this.load();
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },
  load() {
    this.setData({ invExpanded: false });
    const e = new Date();
    const s = new Date();
    s.setDate(s.getDate() - 29);
    const qs =
      "start_date=" +
      s.toISOString().slice(0, 10) +
      "&end_date=" +
      e.toISOString().slice(0, 10);
    return Promise.all([
      request("/api/mobile/labor_summary?" + qs, "GET", {}),
      request("/api/mobile/inventory_summary", "GET", {}),
      request("/api/mobile/four_quadrant_simple?" + qs, "GET", {}),
    ])
      .then(([a, b, c]) => {
        const qd = c.data || null;
        this.setData(
          {
            labor: a.data || null,
            inv: b.data || null,
            quad: qd,
            quadHeat: this._decorateQuadHeat(qd),
          },
          () => this._syncInvList()
        );
      })
      .catch((e) => {
        wx.showToast({ title: (e && e.message) || "失败", icon: "none" });
      });
  },
  _decorateQuadHeat(quad) {
    if (!quad) return [];
    const list = [...(quad.low_margin_high_labor || [])].sort(
      (a, b) => (Number(a.margin_pct) || 0) - (Number(b.margin_pct) || 0)
    );
    if (!list.length) return [];
    const margins = list.map((x) => Number(x.margin_pct) || 0);
    const minM = Math.min.apply(null, margins);
    const maxM = Math.max.apply(null, margins) || 1;
    return list.map((p, i) => {
      const m = Number(p.margin_pct) || 0;
      const t = maxM > minM ? (m - minM) / (maxM - minM) : 0.5;
      const a = 0.14 + 0.52 * (1 - t);
      return {
        ...p,
        _k: (p.category || "c") + i,
        _heatStyle: "background: rgba(201, 37, 57, " + a.toFixed(3) + ");",
        _bgPct: bgBarWidthPct((1 - t) * 100),
      };
    });
  },
  onQuadHeatCell(e) {
    this._openQuadDrill(e);
  },
  onQuadListDrill(e) {
    this._openQuadDrill(e);
  },
  _openQuadDrill(e) {
    const i = Number(e.currentTarget.dataset.i);
    const it = (this.data.quadHeat || [])[i];
    if (!it) return;
    const url = buildCategoriesDrillUrlFromLargeRow(it);
    if (url) {
      wx.navigateTo({ url });
      return;
    }
    const h = (this.data.quad && this.data.quad.hint) || "";
    wx.showModal({
      title: it.category || "经营",
      content:
        "未解析到大类编码或名称，无法下钻。\n毛利率 " +
        (it.margin_pct != null ? it.margin_pct : "—") +
        "%\n人力强度 " +
        (it.labor_intensity != null ? it.labor_intensity : "—") +
        (h ? "\n\n" + h : ""),
      showCancel: false,
    });
  },
  _syncInvList() {
    const inv = this.data.inv;
    const rows = (inv && inv.low_stock_items) || [];
    const qs = rows.map((r) => Number(r.stock_qty) || 0);
    const maxQ = qs.length ? Math.max.apply(null, qs.concat(1)) : 1;
    const lim = this.data.invExpanded ? rows.length : Math.min(5, rows.length);
    const slice = rows.slice(0, lim);
    const invDisplayItems = slice.map((r) => {
      const q = Number(r.stock_qty) || 0;
      return {
        ...r,
        _k: r.sku_code || String(q),
        _bgPct: bgBarWidthPct((q / maxQ) * 100),
      };
    });
    this.setData({ invDisplayItems });
  },
  toggleInv() {
    this.setData({ invExpanded: !this.data.invExpanded }, () => this._syncInvList());
  },
  goAlerts() {
    wx.navigateTo({ url: "/pages/alerts/index" });
  },
  goLaborWeb() {
    wx.navigateTo({ url: "/pages/labor/web" });
  },
});
