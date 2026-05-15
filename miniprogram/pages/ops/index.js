import * as echarts from "../../components/ec-canvas/echarts";
const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { syncTabBar } = require("../../utils/tabbar");
const { bgBarWidthPct, buildCategoriesDrillUrlFromLargeRow } = require("../../utils/analyticsUI");

function fmtNum(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "0";
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + "亿";
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(1) + "万";
  const abs = Math.abs(n);
  const frac = abs < 100 && abs % 1 !== 0;
  return frac ? n.toFixed(2) : String(Math.round(n));
}

function fmtMom(v) {
  if (v == null || Number.isNaN(Number(v))) return "";
  const n = Number(v);
  return (n >= 0 ? "+" : "") + n.toFixed(1) + "% 环比";
}

function momClass(v) {
  if (v == null || Number.isNaN(Number(v))) return "";
  return Number(v) >= 0 ? "ops-chip--up" : "ops-chip--down";
}

Page({
  data: {
    ec: { lazyLoad: true },
    loading: true,
    labor: null,
    laborDash: null,
    laborRangeLabel: "",
    laborTrends: [],
    chartTab: 0,
    inv: null,
    invSummary: null,
    quad: null,
    quadHeat: [],
    riskCats: [],
    invExpanded: false,
    invDisplayItems: [],
    invCollapsed: true,
    quadExpanded: true,
  },

  onReady() {
    this._pageReady = true;
    if (this._pendingChart) {
      this._pendingChart = false;
      wx.nextTick(() => this._syncTrendChart());
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

  load() {
    if (this._trendChart) {
      try {
        this._trendChart.dispose();
      } catch (e) {}
      this._trendChart = null;
    }
    this._trendInited = false;
    this.ecComp = null;

    this.setData({ loading: true, invExpanded: false, invCollapsed: true });
    const e = new Date();
    const s = new Date();
    s.setDate(s.getDate() - 29);
    const sStr = s.toISOString().slice(0, 10);
    const eStr = e.toISOString().slice(0, 10);
    const qs = "start_date=" + sStr + "&end_date=" + eStr;
    return Promise.all([
      request("/api/mobile/labor_summary?" + qs, "GET", {}),
      request("/api/mobile/inventory_summary", "GET", {}),
      request("/api/mobile/four_quadrant_simple?" + qs, "GET", {}),
      request("/api/mobile/labor_detail", "GET", {}).catch(() => ({ data: {} })),
    ])
      .then(([a, b, c, d]) => {
        const labor = a.data || null;
        const inv = b.data || null;
        const qd = c.data || null;
        const detail = d.data || {};
        const trends = (detail.trends || []).slice(-14);
        const laborDash = this._buildLaborDash(labor);
        const riskCats = this._buildRiskCats(labor);
        const invSummary = inv
          ? {
              totalStr: fmtNum(inv.inventory_total),
              lowCnt: (inv.low_stock_items || []).length,
            }
          : null;
        this.setData(
          {
            loading: false,
            labor,
            laborDash,
            laborRangeLabel: sStr + " ~ " + eStr,
            laborTrends: trends,
            inv,
            invSummary,
            quad: qd,
            quadHeat: this._decorateQuadHeat(qd),
            riskCats,
            chartTab: 0,
          },
          () => {
            this._syncInvList();
            if (this._pageReady) wx.nextTick(() => this._syncTrendChart());
            else this._pendingChart = true;
          }
        );
      })
      .catch((err) => {
        this.setData({ loading: false });
        wx.showToast({ title: (err && err.message) || "失败", icon: "none" });
      });
  },

  _buildLaborDash(labor) {
    if (!labor) return null;
    const lc = labor.labor_cost_link_ratio;
    const sl = labor.sales_link_ratio;
    const spc = labor.sales_per_capita_link_ratio;
    const lts = labor.labor_cost_to_sales_ratio;
    return {
      cost: fmtNum(labor.total_labor_cost),
      costMom: fmtMom(lc),
      costMomClass: momClass(lc),
      sales: fmtNum(labor.total_sales),
      salesMom: fmtMom(sl),
      salesMomClass: momClass(sl),
      profit: fmtNum(labor.total_gross_profit),
      spc: fmtNum(labor.sales_per_capita),
      spcMom: fmtMom(spc),
      spcMomClass: momClass(spc),
      laborToSale:
        lts != null && Number.isFinite(Number(lts))
          ? (Number(lts) * 100).toFixed(2) + "%"
          : "—",
    };
  },

  _buildRiskCats(labor) {
    const list = (labor && labor.low_margin_high_labor_categories) || [];
    const slice = list.slice(0, 8);
    if (!slice.length) return [];
    const intens = slice.map((x) => Number(x.labor_intensity) || 0);
    const maxI = Math.max.apply(null, intens.concat([1e-9]));
    return slice.map((x, i) => ({
      ...x,
      _k: (x.category || "c") + "-" + i,
      _barPct: bgBarWidthPct(((Number(x.labor_intensity) || 0) / maxI) * 100),
    }));
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

  setChartTab(e) {
    const i = Number(e.currentTarget.dataset.i) || 0;
    this.setData({ chartTab: i }, () => this._syncTrendChart());
  },

  toggleInvCollapse() {
    this.setData({ invCollapsed: !this.data.invCollapsed });
  },

  toggleQuad() {
    this.setData({ quadExpanded: !this.data.quadExpanded });
  },

  _syncTrendChart() {
    const trends = this.data.laborTrends || [];
    if (!trends.length) {
      if (this._trendChart) {
        try {
          this._trendChart.dispose();
        } catch (e) {}
        this._trendChart = null;
        this._trendInited = false;
      }
      this.ecComp = null;
      return;
    }
    let tries = 0;
    const run = () => {
      if (!this.ecComp) this.ecComp = this.selectComponent("#ops-trend");
      if (!this.ecComp) {
        tries += 1;
        if (tries < 12) setTimeout(run, 60);
        return;
      }
      if (!this._trendInited) {
        this._trendInited = true;
        this.ecComp.init((canvas, width, height, dpr) => {
          const chart = echarts.init(canvas, null, {
            width,
            height,
            devicePixelRatio: dpr,
          });
          canvas.setChart(chart);
          this._trendChart = chart;
          this._applyTrendOption(chart);
          return chart;
        });
      } else if (this._trendChart) {
        this._applyTrendOption(this._trendChart);
      }
    };
    run();
  },

  _applyTrendOption(chart) {
    const trends = this.data.laborTrends || [];
    const tab = this.data.chartTab || 0;
    const xData = trends.map((t) => {
      const m = t.month || "";
      const p = m.split("-");
      if (p.length >= 2) return p[0].slice(2) + "/" + p[1];
      return m;
    });
    let series = [];
    const yAxis = [{ type: "value", splitLine: { lineStyle: { type: "dashed" } } }];
    let barColor = "#c92539";
    try {
      if (echarts.graphic && echarts.graphic.LinearGradient) {
        barColor = new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: "#e85a6d" },
          { offset: 1, color: "#c92539" },
        ]);
      }
    } catch (err) {
      barColor = "#c92539";
    }
    if (tab === 0) {
      series = [
        {
          name: "人力成本",
          type: "bar",
          data: trends.map((t) => Number(t.total_cost) || 0),
          barMaxWidth: 28,
          itemStyle: {
            color: barColor,
            borderRadius: [6, 6, 0, 0],
          },
        },
      ];
    } else if (tab === 1) {
      series = [
        {
          name: "人效(销/人)",
          type: "line",
          smooth: true,
          showSymbol: true,
          symbolSize: 6,
          data: trends.map((t) => Number(t.sale_per_capita) || 0),
          lineStyle: { width: 2.5, color: "#c92539" },
          itemStyle: { color: "#c92539" },
          areaStyle: { color: "rgba(201, 37, 57, 0.12)" },
        },
      ];
    } else {
      series = [
        {
          name: "人工/销售额",
          type: "line",
          smooth: true,
          showSymbol: true,
          symbolSize: 6,
          data: trends.map((t) => Number(t.labor_sale_ratio) || 0),
          lineStyle: { width: 2.5, color: "#722ed1" },
          itemStyle: { color: "#722ed1" },
          areaStyle: { color: "rgba(114, 46, 209, 0.1)" },
        },
      ];
    }
    chart.setOption(
      {
        color: ["#c92539"],
        tooltip: {
          trigger: "axis",
          confine: true,
          formatter: (items) => {
            if (!items || !items.length) return "";
            const ax = items[0].axisValueLabel || "";
            const lines = [ax];
            items.forEach((it) => {
              let v = it.data;
              if (tab === 2) v = (Number(v) || 0).toFixed(2) + "%";
              else if (tab === 0) v = fmtNum(v);
              else v = (Number(v) || 0).toFixed(2);
              lines.push(it.marker + (it.seriesName || "") + " " + v);
            });
            return lines.join("\n");
          },
        },
        grid: { left: 8, right: 12, top: 36, bottom: 8, containLabel: true },
        xAxis: {
          type: "category",
          data: xData,
          axisLabel: { fontSize: 10, color: "#6b7280" },
          axisLine: { lineStyle: { color: "#e5e7eb" } },
        },
        yAxis,
        series,
      },
      { notMerge: true }
    );
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

  onRiskCatTap(e) {
    const i = Number(e.currentTarget.dataset.i);
    const it = (this.data.riskCats || [])[i];
    if (!it) return;
    const url = buildCategoriesDrillUrlFromLargeRow(it);
    if (url) wx.navigateTo({ url });
    else {
      wx.showModal({
        title: it.category || "类目",
        content:
          "毛利率 " +
          (it.margin_pct != null ? it.margin_pct : "—") +
          "% · 人力强度 " +
          (it.labor_intensity != null ? it.labor_intensity : "—"),
        showCancel: false,
      });
    }
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
  goLaborDetail() {
    wx.navigateTo({ url: "/pages/labor/index" });
  },
});
