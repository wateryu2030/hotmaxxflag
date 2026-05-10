const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { bgBarWidthPct } = require("../../utils/analyticsUI");

Page({
  data: { items: [], note: "" },
  onShow() {
    if (!requireToken()) return;
    request("/api/mobile/selection", "GET", {})
      .then((j) => {
        const raw = (j.data && j.data.items) || [];
        const maxM = raw.reduce((m, x) => Math.max(m, Number(x.margin_pct) || 0), 0);
        const items = raw.map((x) => {
          const pct = Number(x.margin_pct);
          const p = Number.isFinite(pct) ? pct : 0;
          const _marginBar = Math.min(100, Math.max(0, p));
          const _relBar = maxM > 0 ? Math.min(100, Math.round((p / maxM) * 100)) : 0;
          return {
            ...x,
            _marginBar,
            _relBar,
            _bgPct: bgBarWidthPct((_marginBar + _relBar) / 2),
          };
        });
        this.setData({
          items,
          note: (j.data && j.data.note) || "",
        });
      })
      .catch(() => {});
  },
});
