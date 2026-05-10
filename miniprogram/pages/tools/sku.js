const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { bgBarWidthPct } = require("../../utils/analyticsUI");

Page({
  data: { kw: "", items: [] },
  onShow() {
    if (!requireToken()) return;
  },
  onIn(e) {
    this.setData({ kw: e.detail.value });
  },
  search() {
    const k = (this.data.kw || "").trim();
    if (!k) return;
    request("/api/mobile/sku_search?keyword=" + encodeURIComponent(k), "GET", {})
      .then((j) => {
        const raw = (j.data && j.data.items) || [];
        const maxSa = raw.reduce((m, x) => Math.max(m, Number(x.sale_amount) || 0), 0);
        const items = raw.map((x) => {
          const sa = Number(x.sale_amount) || 0;
          const m = parseFloat(x.margin_pct);
          const _saleBar = maxSa > 0 ? Math.min(100, Math.round((sa / maxSa) * 100)) : 0;
          const _marginBar = Math.min(100, Math.max(0, Number.isFinite(m) ? m : 0));
          return {
            ...x,
            _saleBar,
            _marginBar,
            _bgPct: bgBarWidthPct((_saleBar + _marginBar) / 2),
          };
        });
        this.setData({ items });
      })
      .catch((e) => wx.showToast({ title: (e && e.message) || "失败", icon: "none" }));
  },
});
