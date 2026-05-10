import * as echarts from "../../components/ec-canvas/echarts";
const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { syncTabBar } = require("../../utils/tabbar");
const { bgBarWidthPct } = require("../../utils/analyticsUI");

const GR = ["day", "week", "month"];
const GRL = ["按日", "按周", "按月"];
const MT = ["sales", "profit", "margin"];
const MTL = ["销售额", "毛利", "毛利率%"];

const MAX_POINTS = 120;

function sampleSeries(dates, vals, max) {
  if (dates.length <= max) return { dates, vals };
  const step = Math.ceil(dates.length / max);
  const d2 = [];
  const v2 = [];
  for (let i = 0; i < dates.length; i += step) {
    d2.push(dates[i]);
    v2.push(vals[i]);
  }
  return { dates: d2, vals: v2 };
}

function decorateTableRows(pairs) {
  const tableRows = pairs.slice().reverse();
  const nums = tableRows.map((r) => Number(r.v)).filter((x) => Number.isFinite(x));
  const maxAbs = nums.length ? Math.max.apply(null, nums.map((x) => Math.abs(x))) : 0;
  const ma = maxAbs > 0 ? maxAbs : 1;
  const byVal = tableRows
    .map((r) => r)
    .slice()
    .sort((a, b) => Number(b.v) - Number(a.v));
  const rankByKey = {};
  byVal.forEach((r, ord) => {
    rankByKey[r._k] = ord + 1;
  });
  return tableRows.map((r) => {
    const t = Number(r.v);
    const tv = Number.isFinite(t) ? t : 0;
    return {
      ...r,
      _bgPct: bgBarWidthPct((Math.abs(tv) / ma) * 100),
      _rank: rankByKey[r._k] || 0,
    };
  });
}

function fmtComparePct(n) {
  if (n == null || Number.isNaN(n)) return "";
  const s = (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
  return s;
}

Page({
  data: {
    ec: { lazyLoad: true },
    loading: true,
    gi: 0,
    mi: 0,
    gLabels: GRL,
    mLabels: MTL,
    rows: [],
    tableRows: [],
    stat: { min: "—", max: "—" },
    compareMom: null,
    compareSpan: null,
    compareMomStr: "",
    compareSpanStr: "",
  },
  onReady() {
    this._pageReady = true;
    if (this._pendingChart) {
      this._pendingChart = false;
      wx.nextTick(() => this._syncLineChart());
    }
  },
  onShow() {
    syncTabBar();
    if (!requireToken()) return;
    this.load();
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },
  setTabG(e) {
    const i = Number(e.currentTarget.dataset.i) || 0;
    this.setData({ gi: i }, () => this.load());
  },
  setTabM(e) {
    const i = Number(e.currentTarget.dataset.i) || 0;
    this.setData({ mi: i }, () => this.load());
  },
  load() {
    this.setData({ loading: true });
    const d0 = new Date();
    d0.setDate(d0.getDate() - 29);
    const s = d0.toISOString().slice(0, 10);
    const e = new Date().toISOString().slice(0, 10);
    const g = GR[this.data.gi];
    const m = MT[this.data.mi];
    return request(
      "/api/mobile/trend_advanced?granularity=" +
        g +
        "&metric=" +
        m +
        "&start_date=" +
        s +
        "&end_date=" +
        e,
      "GET",
      {}
    )
      .then((j) => {
        const d = j.data || {};
        const vals = d.values || [];
        const dates = d.dates || [];
        const pairs = dates.map((dt, i) => ({ dt, v: vals[i], _k: dt + "-" + i }));
        const tableRows = decorateTableRows(pairs);
        const nnum = vals
          .map((x) => Number(x))
          .filter((x) => Number.isFinite(x));
        const min = nnum.length ? Math.min.apply(null, nnum) : null;
        const max = nnum.length ? Math.max.apply(null, nnum) : null;
        let compareMom = null;
        let compareSpan = null;
        if (nnum.length >= 2) {
          const last = nnum[nnum.length - 1];
          const prev = nnum[nnum.length - 2];
          if (Number.isFinite(prev) && Math.abs(prev) > 1e-9) {
            compareMom = ((last - prev) / Math.abs(prev)) * 100;
          }
        }
        if (nnum.length >= 2) {
          const first = nnum[0];
          const last = nnum[nnum.length - 1];
          if (Number.isFinite(first) && Math.abs(first) > 1e-9) {
            compareSpan = ((last - first) / Math.abs(first)) * 100;
          }
        }
        this.setData(
          {
            rows: pairs,
            tableRows,
            stat: {
              min: min != null ? String(min) : "—",
              max: max != null ? String(max) : "—",
            },
            compareMom,
            compareSpan,
            compareMomStr: compareMom != null ? fmtComparePct(compareMom) : "",
            compareSpanStr: compareSpan != null ? fmtComparePct(compareSpan) : "",
            loading: false,
          },
          () => {
            if (this._pageReady) wx.nextTick(() => this._syncLineChart());
            else this._pendingChart = true;
          }
        );
      })
      .catch((err) => {
        this.setData({ loading: false });
        wx.showToast({ title: (err && err.message) || "失败", icon: "none" });
      });
  },
  _syncLineChart() {
    if (!this.ecComp) {
      this.ecComp = this.selectComponent("#insight-line");
    }
    if (!this.ecComp) return;
    let dates = this.data.rows.map((r) => r.dt);
    let vals = this.data.rows.map((r) => r.v);
    const sampled = sampleSeries(dates, vals, MAX_POINTS);
    dates = sampled.dates;
    vals = sampled.vals;
    const name = this.data.mLabels[this.data.mi];
    if (!this._lineInited) {
      this._lineInited = true;
      this.ecComp.init((canvas, width, height, dpr) => {
        const chart = echarts.init(canvas, null, {
          width,
          height,
          devicePixelRatio: dpr,
        });
        canvas.setChart(chart);
        this._lineChart = chart;
        this._applyLineOption(chart, dates, vals, name);
        return chart;
      });
    } else if (this._lineChart) {
      this._applyLineOption(this._lineChart, dates, vals, name);
    }
  },
  _applyLineOption(chart, dates, vals, name) {
    let areaColor = { color: "rgba(201, 37, 57, 0.16)" };
    try {
      if (echarts.graphic && echarts.graphic.LinearGradient) {
        areaColor = {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(201, 37, 57, 0.22)" },
            { offset: 1, color: "rgba(201, 37, 57, 0.02)" },
          ]),
        };
      }
    } catch (err) {
      /* 使用实色 */
    }
    chart.setOption(
      {
        tooltip: { trigger: "axis" },
        grid: {
          left: 52,
          right: 16,
          top: 32,
          bottom: dates.length > 14 ? 72 : 40,
        },
        xAxis: {
          type: "category",
          data: dates,
          axisLabel: { rotate: dates.length > 12 ? 35 : 0, fontSize: 10 },
        },
        yAxis: { type: "value", scale: true, splitLine: { lineStyle: { type: "dashed" } } },
        series: [
          {
            name,
            type: "line",
            smooth: true,
            data: vals,
            showSymbol: false,
            lineStyle: { color: "#c92539", width: 2 },
            itemStyle: { color: "#c92539" },
            areaStyle: areaColor,
            emphasis: {
              focus: "series",
              lineStyle: { width: 3, color: "#c92539" },
              itemStyle: {
                color: "#c92539",
                borderColor: "#ffffff",
                borderWidth: 2,
                shadowBlur: 8,
                shadowColor: "rgba(201, 37, 57, 0.45)",
              },
            },
          },
        ],
      },
      { notMerge: true }
    );
  },
});
