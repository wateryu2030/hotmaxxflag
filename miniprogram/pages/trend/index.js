const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { bgBarWidthPct } = require("../../utils/analyticsUI");

const LIST_TAIL = 20;

function buildSeriesRows(dates, values) {
  const ds = dates || [];
  const vs = (values || []).map((x) => Number(x));
  const n = Math.min(ds.length, vs.length);
  if (!n) return [];
  const tail = Math.max(0, n - LIST_TAIL);
  const sliceD = ds.slice(tail);
  const sliceV = vs.slice(tail);
  const mx = Math.max(...sliceV.map((x) => (Number.isFinite(x) ? Math.abs(x) : 0)), 1e-9);
  const rows = sliceD.map((dt, i) => {
    const v = sliceV[i];
    const num = Number.isFinite(v) ? v : 0;
    return {
      dt,
      v,
      _rk: String(dt) + "_" + String(i),
      _bgPct: bgBarWidthPct((Math.abs(num) / mx) * 100),
    };
  });
  const rev = rows.slice().reverse();
  const sortedByVal = rev.slice().sort((a, b) => Number(b.v) - Number(a.v));
  const rankByRk = {};
  sortedByVal.forEach((r, ord) => {
    rankByRk[r._rk] = ord + 1;
  });
  return rev.map((r) => ({ ...r, _rank: rankByRk[r._rk] || 0 }));
}

Page({
  data: {
    metric: "sale",
    days: 30,
    dates: [],
    values: [],
    seriesRows: [],
    labels: { sale: "销售额", profit: "毛利", margin: "毛利率(%)" },
  },
  onReady() {
    this._draw = this._draw.bind(this);
  },
  onShow() {
    if (!requireToken()) return;
    this.load();
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },
  setMetric(e) {
    const m = e.currentTarget.dataset.m || "sale";
    this.setData({ metric: m }, () => this.load());
  },
  setDays(e) {
    const d = Number(e.currentTarget.dataset.d) || 30;
    this.setData({ days: d }, () => this.load());
  },
  load() {
    return request(
      "/api/mobile/trend?metric=" + this.data.metric + "&days=" + this.data.days,
      "GET",
      {}
    )
      .then((j) => {
        const d = j.data || {};
        const dates = d.dates || [];
        const values = d.values || [];
        this.setData({
          dates,
          values,
          seriesRows: buildSeriesRows(dates, values),
        });
        this._draw();
      })
      .catch((e) => {
        if (e && e.silent) return;
        wx.showToast({ title: (e && e.message) || "失败", icon: "none" });
      });
  },
  _draw() {
    const vals = (this.data.values || []).map((x) => Number(x));
    const w = 340;
    const h = 180;
    const pad = 20;
    const ctx = wx.createCanvasContext("trendLine", this);
    ctx.clearRect(0, 0, w + 40, h + 40);
    ctx.setStrokeStyle("#e8eaed");
    ctx.setLineWidth(1);
    ctx.beginPath();
    ctx.moveTo(pad, pad);
    ctx.lineTo(pad, h - pad);
    ctx.lineTo(w - pad, h - pad);
    ctx.stroke();
    if (!vals.length) {
      ctx.draw();
      return;
    }
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    const n = vals.length;
    const step = (w - 2 * pad) / Math.max(1, n - 1);
    const points = [];
    for (let i = 0; i < n; i++) {
      const vx = pad + i * step;
      const vy = h - pad - ((vals[i] - min) / range) * (h - 2 * pad);
      points.push([vx, vy]);
    }
    const grd = ctx.createLinearGradient(0, pad, 0, h - pad);
    grd.addColorStop(0, "rgba(201, 37, 57, 0.22)");
    grd.addColorStop(1, "rgba(201, 37, 57, 0.02)");
    ctx.beginPath();
    ctx.moveTo(points[0][0], h - pad);
    points.forEach((p) => ctx.lineTo(p[0], p[1]));
    ctx.lineTo(points[n - 1][0], h - pad);
    ctx.closePath();
    ctx.setFillStyle(grd);
    ctx.fill();
    ctx.setStrokeStyle("#c92539");
    ctx.setLineWidth(2);
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const vx = points[i][0];
      const vy = points[i][1];
      if (i === 0) ctx.moveTo(vx, vy);
      else ctx.lineTo(vx, vy);
    }
    ctx.stroke();
    ctx.draw();
  },
});
