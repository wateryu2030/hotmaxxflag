const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");

Page({
  data: { summary: null },
  onShow() {
    if (!requireToken()) return;
    this.loadSummary();
  },
  onPullDownRefresh() {
    this.loadSummary().finally(() => wx.stopPullDownRefresh());
  },
  loadSummary() {
    const s = new Date();
    s.setDate(s.getDate() - 29);
    const e = new Date();
    const fmt = (d) =>
      d.getFullYear() +
      "-" +
      String(d.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(d.getDate()).padStart(2, "0");
    return request(
      "/api/mobile/labor_summary?start_date=" + fmt(s) + "&end_date=" + fmt(e),
      "GET",
      {}
    )
      .then((j) => {
        const s = j.data || null;
        if (s && Array.isArray(s.low_margin_high_labor_categories)) {
          const arr = s.low_margin_high_labor_categories;
          const labs = arr.map((x) => {
            const v = parseFloat(x.labor_intensity);
            return Number.isFinite(v) ? v : 0;
          });
          const maxL = Math.max(...labs, 1e-9);
          s.low_margin_high_labor_categories = arr.map((x, i) => {
            const m = parseFloat(x.margin_pct);
            const lab = labs[i];
            return {
              ...x,
              _k: String(x.category_large_code || x.category || i) + "_" + String(i),
              _marginBar: Math.min(100, Math.max(0, Number.isFinite(m) ? m : 0)),
              _laborBar: Math.min(100, (lab / maxL) * 100),
            };
          });
        }
        this.setData({ summary: s });
      })
      .catch((e) => {
        if (e && e.silent) return;
        wx.showToast({ title: (e && e.message) || "失败", icon: "none" });
      });
  },
  openWeb() {
    const app = getApp();
    const base = (app.globalData && app.globalData.baseUrl) || "";
    const token = (app.globalData && app.globalData.token) || wx.getStorageSync("token") || "";
    const u =
      base.replace(/\/$/, "") +
      "/static/labor_analysis.html" +
      "?_ts=" +
      Date.now() +
      "#t=" +
      encodeURIComponent(token);
    wx.navigateTo({
      url: "/pages/labor/web?u=" + encodeURIComponent(u),
    });
  },
});
