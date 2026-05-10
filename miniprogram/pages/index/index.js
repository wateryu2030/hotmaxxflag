const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");

function decorateTop(top) {
  const list = top || [];
  const maxSa = list.reduce((m, x) => Math.max(m, Number(x.sale_amount) || 0), 0);
  return list.map((x) => ({
    ...x,
    _barPct: maxSa > 0 ? Math.min(100, Math.round(((Number(x.sale_amount) || 0) / maxSa) * 100)) : 0,
  }));
}

Page({
  data: {
    days: 30,
    loading: true,
    kpi: null,
    top: [],
    negSku: 0,
    alerts: [],
    range: null,
  },
  onShow() {
    if (!requireToken()) return;
    this.load();
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },
  onDays(e) {
    const d = Number(e.currentTarget.dataset.d) || 30;
    this.setData({ days: d });
    this.load();
  },
  goAlerts() {
    wx.navigateTo({ url: "/pages/alerts/index" });
  },
  goCats() {
    wx.navigateTo({ url: "/pages/categories/index" });
  },
  goTrend() {
    wx.navigateTo({ url: "/pages/trend/index" });
  },
  goProfile() {
    wx.navigateTo({ url: "/pages/profile/index" });
  },
  load() {
    this.setData({ loading: true });
    return request("/api/mobile/dashboard?days=" + this.data.days, "GET", {})
      .then((j) => {
        const d = j.data || {};
        const prev = d.alerts_preview || (d.data && d.data.alerts_preview) || [];
        const rawTop = d.top_categories || [];
        this.setData({
          kpi: d.kpi || null,
          top: decorateTop(rawTop),
          negSku: d.negative_margin_sku_count || 0,
          alerts: Array.isArray(prev) ? prev : [],
          range: d.range || null,
          loading: false,
        });
      })
      .catch((err) => {
        this.setData({ loading: false });
        if (err && err.silent) {
          return;
        }
        wx.showToast({
          title: (err && err.message) || "加载失败",
          icon: "none",
          duration: 3500,
        });
      });
  },
});
