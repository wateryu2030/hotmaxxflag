const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { bgBarWidthPct } = require("../../utils/analyticsUI");

Page({
  data: { t: null },
  onShow() {
    if (!requireToken()) return;
    request("/api/mobile/tax_summary", "GET", {})
      .then((j) => {
        const t = j.data || null;
        if (t) {
          const r = Number(t.avg_tax_rate_pct);
          t._rateBar = Number.isFinite(r) ? Math.min(100, Math.max(0, r)) : 0;
          t._bgPct = bgBarWidthPct(t._rateBar);
        }
        this.setData({ t });
      })
      .catch(() => {});
  },
});
