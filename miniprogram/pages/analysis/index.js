import * as echarts from "../../components/ec-canvas/echarts";
const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { syncTabBar } = require("../../utils/tabbar");
const {
  bgBarWidthPct,
  childLevelForPath,
  isSkuListLevel,
  segmentFromRow,
  buildBreadcrumbCrumbs,
  pathAfterBreadcrumbTap,
  LEVEL_GRAND,
} = require("../../utils/analyticsUI");

const PIE_COLORS = [
  "#C92539",
  "#D83D4F",
  "#E86B7A",
  "#B01E2F",
  "#F0A0A8",
  "#8B1538",
  "#E04856",
  "#A89A9E",
];

function pad2(n) {
  return String(n).padStart(2, "0");
}

function buildMonthOptions() {
  const out = [];
  const d = new Date();
  for (let i = 0; i < 12; i++) {
    const t = new Date(d.getFullYear(), d.getMonth() - i, 1);
    const ym = `${t.getFullYear()}-${pad2(t.getMonth() + 1)}`;
    out.push({ ym, label: `${t.getFullYear()}年${t.getMonth() + 1}月` });
  }
  return out;
}

function monthBounds(ym) {
  const [y, m] = ym.split("-").map(Number);
  const start = `${y}-${pad2(m)}-01`;
  const last = new Date(y, m, 0).getDate();
  const end = `${y}-${pad2(m)}-${pad2(last)}`;
  return { start, end };
}

function prevYm(ym) {
  const [y, m] = ym.split("-").map(Number);
  const t = new Date(y, m - 1, 1);
  t.setMonth(t.getMonth() - 1);
  return `${t.getFullYear()}-${pad2(t.getMonth() + 1)}`;
}

function fmtYuan(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function decorateDrillRows(items) {
  const arr = [...(items || [])].sort(
    (a, b) => (Number(b.sale_amount) || 0) - (Number(a.sale_amount) || 0)
  );
  const maxS = arr.length ? Math.max(...arr.map((x) => Number(x.sale_amount) || 0), 0.01) : 1;
  return arr.map((it, idx) => ({
    ...it,
    _rank: idx + 1,
    _bgPct: bgBarWidthPct(((Number(it.sale_amount) || 0) / maxS) * 100),
    _wk:
      String(it.sku_code || "") +
      "|" +
      String(it.category_mid_code || "") +
      "|" +
      String(it.category_large_code || "") +
      "|" +
      String(it.category_small_code || it.category_small || "") +
      "|" +
      idx,
  }));
}

Page({
  data: {
    tab: 0,
    ecPie: { lazyLoad: true },
    ecBar: { lazyLoad: true },
    share: [],
    matrix: [],
    contrib: [],
    loading: true,
    monthOptions: [],
    monthLabels: [],
    monthIndex: 0,
    legendColors: PIE_COLORS,
    pieSelection: { mode: "total" },
    drillPath: [],
    drillBreadcrumb: [],
    drillItems: [],
    drillLoading: false,
    drillEmpty: false,
    drillEmptyHint: "",
    drillListTitle: "大类",
    attrLoading: false,
    attrError: "",
    attrRangeNote: "",
    attrSummary: null,
    attrRows: [],
  },
  onReady() {
    this._pageReady = true;
    if (this._pendingCharts) {
      this._pendingCharts = false;
      wx.nextTick(() => {
        this._syncChartsForTab();
        if (this.data.tab === 3 && !this.data.loading) this._loadDrillList();
        if (this.data.tab === 4 && !this.data.loading) this._loadAttribution();
      });
    }
  },
  onLoad() {
    const opts = buildMonthOptions();
    this.setData({
      monthOptions: opts,
      monthLabels: opts.map((o) => o.label),
    });
  },
  onShow() {
    syncTabBar();
    if (!requireToken()) return;
    const app = getApp();
    let pendingTab = null;
    if (app && app.globalData && app.globalData.analysisOpenTabIndex != null && app.globalData.analysisOpenTabIndex !== "") {
      const ti = Number(app.globalData.analysisOpenTabIndex);
      app.globalData.analysisOpenTabIndex = null;
      if (!Number.isNaN(ti) && ti >= 0 && ti <= 4) pendingTab = ti;
    }
    const boot = app && app.globalData && app.globalData.analysisTabBootstrap;
    if (boot && boot.large_code) {
      app.globalData.analysisTabBootstrap = null;
      this._pendingAnalysisBootstrap = { large_code: boot.large_code, large_name: boot.large_name || "" };
    }
    const runLoad = () => {
      const p = this.loadAll();
      const done = () => {
        const b = this._pendingAnalysisBootstrap;
        if (b && b.large_code) {
          this._pendingAnalysisBootstrap = null;
          wx.nextTick(() => this._openDrillTabAtLarge(b.large_code, b.large_name || ""));
        }
      };
      if (p && typeof p.then === "function") {
        p.then(done).catch(() => {});
      } else {
        done();
      }
    };
    if (pendingTab != null) {
      const prev = this.data.tab;
      if (prev === 0 && pendingTab !== 0) this._disposePie();
      if (prev === 2 && pendingTab !== 2) this._disposeBar();
      this.setData({ tab: pendingTab }, runLoad);
      return;
    }
    runLoad();
  },
  onPullDownRefresh() {
    this.loadAll().finally(() => wx.stopPullDownRefresh());
  },
  onMonthChange(e) {
    const i = Number(e.detail.value) || 0;
    this.setData({ monthIndex: i, pieSelection: { mode: "total" } }, () => this.loadAll());
  },
  _disposePie() {
    try {
      if (this._pieChart) this._pieChart.dispose();
    } catch (err) {}
    this._pieChart = null;
    this._pieInited = false;
    this.pieComp = null;
    this._pieEventsBound = false;
  },
  _disposeBar() {
    try {
      if (this._barChart) this._barChart.dispose();
    } catch (err) {}
    this._barChart = null;
    this._barInited = false;
    this.barComp = null;
  },
  setTab(e) {
    const t = Number(e.currentTarget.dataset.i) || 0;
    const prev = this.data.tab;
    if (prev === 0 && t !== 0) this._disposePie();
    if (prev === 2 && t !== 2) this._disposeBar();
    const resetDrill = prev !== 3 && t === 3;
    this.setData(
      {
        tab: t,
        ...(resetDrill ? { drillPath: [] } : {}),
      },
      () => {
        wx.nextTick(() => {
          this._syncChartsForTab();
          if (t === 3 && !this.data.loading) this._loadDrillList();
          if (t === 4 && !this.data.loading) this._loadAttribution();
        });
      }
    );
  },
  resetPieSelection() {
    this.setData({ pieSelection: { mode: "total" } }, () => {
      this._ensurePie();
      if (this._pieChart) {
        this._pieChart.dispatchAction({ type: "downplay", seriesIndex: 0 });
      }
    });
  },
  /** 长按图例：仅高亮饼图对应扇区（不离开本 Tab） */
  onLegendHighlightPie(e) {
    const i = Number(e.currentTarget.dataset.i);
    if (Number.isNaN(i)) return;
    this._suppressLegendTapUntil = Date.now() + 520;
    try {
      wx.vibrateShort({ fail() {} });
    } catch (err) {}
    this._setPieSelection(i);
  },
  /** 轻点图例：进入下钻（长按后的松手会误触 tap，用时间窗忽略） */
  onLegendOpenDrill(e) {
    if (Date.now() < (this._suppressLegendTapUntil || 0)) return;
    const c = (e.currentTarget.dataset.code || "").trim();
    const n = (e.currentTarget.dataset.name || "").trim();
    if (!c) return;
    this._openDrillTabAtLarge(c, n);
  },
  /** 饼图选中某一扇区后，一键进入该类下钻 */
  onDrillFromPieSelection() {
    const sel = this.data.pieSelection || {};
    if (sel.mode !== "slice" || sel.index == null) return;
    const it = (this.data.share || [])[sel.index];
    if (!it) return;
    this._openDrillTabAtLarge(it.category_large_code, it.category_large);
  },
  /** 热力 / 贡献列表：按大类下钻 */
  onMatrixRowDrill(e) {
    const c = (e.currentTarget.dataset.code || "").trim();
    const n = (e.currentTarget.dataset.name || "").trim();
    if (!c) return;
    this._openDrillTabAtLarge(c, n);
  },
  onContribRowDrill(e) {
    const c = (e.currentTarget.dataset.code || "").trim();
    const n = (e.currentTarget.dataset.name || "").trim();
    if (!c) return;
    this._openDrillTabAtLarge(c, n);
  },
  /**
   * 切到「下钻」Tab 并定位到大类（中类列表），与当前月份数据范围一致。
   */
  _openDrillTabAtLarge(code, name) {
    let c = String(code || "").trim();
    const n = String(name || "").trim();
    if (!c && n) c = n;
    if (!c) {
      wx.showToast({ title: "缺少大类信息", icon: "none" });
      return;
    }
    const seg = { level: LEVEL_GRAND, code: c, name: n || c };
    try {
      wx.vibrateShort({ fail() {} });
    } catch (err) {}
    const prev = this.data.tab;
    if (prev === 0) this._disposePie();
    if (prev === 2) this._disposeBar();
    this.setData(
      {
        tab: 3,
        drillPath: [seg],
        pieSelection: { mode: "total" },
      },
      () => {
        wx.nextTick(() => {
          this._syncChartsForTab();
          if (!this.data.loading) this._loadDrillList();
        });
      }
    );
  },
  _setPieSelection(dataIndex) {
    const it = (this.data.share || [])[dataIndex];
    if (!it) return;
    this.setData(
      {
        pieSelection: {
          mode: "slice",
          index: dataIndex,
          name: it.category_large,
          value: it.sales_amount,
          pct: it.percentage,
        },
      },
      () => {
        this._ensurePie();
        if (this._pieChart) {
          this._pieChart.dispatchAction({ type: "downplay", seriesIndex: 0 });
          this._pieChart.dispatchAction({
            type: "highlight",
            seriesIndex: 0,
            dataIndex,
          });
        }
      }
    );
  },
  /** 占比列表行：本页下钻到中类，与所选月份一致 */
  onShareRowDrill(e) {
    const c = (e.currentTarget.dataset.code || "").trim();
    const n = (e.currentTarget.dataset.name || "").trim();
    this._openDrillTabAtLarge(c, n);
  },
  goTrend() {
    wx.switchTab({ url: "/pages/insight/index" });
  },
  goList() {
    wx.navigateTo({ url: "/pages/categories/index" });
  },
  _drillDateQuery() {
    const opt =
      (this.data.monthOptions || [])[this.data.monthIndex] || (buildMonthOptions()[0] || { ym: "" });
    const ym = opt.ym;
    if (!ym) return "";
    const { start, end } = monthBounds(ym);
    return "start_date=" + start + "&end_date=" + end;
  },
  _decorateAttrRows(items) {
    const arr = items || [];
    let mx = 0;
    arr.forEach((r) => {
      const v = Math.abs(Number(r.share_of_total_delta_pct) || 0);
      if (v > mx) mx = v;
    });
    if (mx < 0.01) mx = 1;
    return arr.map((r, i) => {
      const sh = Math.abs(Number(r.share_of_total_delta_pct) || 0);
      const d = Number(r.delta) || 0;
      const sign = d >= 0 ? "+" : "";
      return {
        ...r,
        _k: (r.category_large_code || "") + "-" + i,
        _bgPct: bgBarWidthPct((sh / mx) * 100),
        _deltaUp: d > 0.01,
        _deltaDown: d < -0.01,
        _deltaDisplay: sign + String(r.delta != null ? r.delta : ""),
      };
    });
  },
  _loadAttribution() {
    if (this.data.tab !== 4) return;
    const dq = this._drillDateQuery();
    if (!dq) {
      this.setData({
        attrLoading: false,
        attrError: "请先选择月份",
        attrRangeNote: "",
        attrSummary: null,
        attrRows: [],
      });
      return;
    }
    this.setData({ attrLoading: true, attrError: "" });
    const primary = "/api/mobile/analysis/attribution?" + dq;
    const alias = "/api/mobile/attribution?" + dq;
    const mirror = "/api/wechat/mini/analysis/attribution?" + dq;
    const fetchAttr = (path) => request(path, "GET", {});
    return fetchAttr(primary)
      .catch((err) => {
        const m = (err && err.message) ? String(err.message) : "";
        if (m.indexOf("404") >= 0) return fetchAttr(alias);
        throw err;
      })
      .catch((err) => {
        const m = (err && err.message) ? String(err.message) : "";
        if (m.indexOf("404") >= 0) return fetchAttr(mirror);
        throw err;
      })
      .then((j) => {
        const d = j.data || {};
        const cur = (d.range && d.range.current) || {};
        const prev = (d.range && d.range.previous) || {};
        const note =
          cur.start_date && cur.end_date
            ? `本期 ${cur.start_date}～${cur.end_date} · 对比上期 ${prev.start_date || ""}～${prev.end_date || ""}`
            : "";
        this.setData({
          attrLoading: false,
          attrError: "",
          attrRangeNote: note,
          attrSummary: {
            prev_total: d.prev_total,
            cur_total: d.cur_total,
            delta_total: d.delta_total,
            delta_pct_prev: d.delta_pct_prev,
          },
          attrRows: this._decorateAttrRows(d.by_category || []),
        });
      })
      .catch((err) => {
        this.setData({
          attrLoading: false,
          attrError: (err && err.message) || "加载失败",
          attrRangeNote: "",
          attrSummary: null,
          attrRows: [],
        });
      });
  },
  onDrillBreadcrumbTap(e) {
    const tapIndex = Number(e.currentTarget.dataset.i);
    const next = pathAfterBreadcrumbTap(this.data.drillPath, tapIndex);
    this.setData({ drillPath: next }, () => this._loadDrillList());
  },
  onDrillRowTap(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    const row = (this.data.drillItems || [])[idx];
    if (!row) return;
    const path = this.data.drillPath || [];
    if (isSkuListLevel(path)) {
      const title = row.name || row.sku_code || "SKU";
      wx.showModal({
        title,
        content: [
          "SKU：" + (row.sku_code || "—"),
          "销额：" + (row.sale_amount != null ? row.sale_amount : "—"),
          "毛利：" + (row.gross_profit != null ? row.gross_profit : "—"),
          "毛利率：" + (row.margin_pct != null ? row.margin_pct + "%" : "—"),
          "销量：" + (row.sale_qty != null ? row.sale_qty : "—"),
        ].join("\n"),
        showCancel: false,
      });
      return;
    }
    const child = childLevelForPath(path);
    const seg = segmentFromRow(child, row);
    if (!seg.code && child !== LEVEL_GRAND) {
      wx.showToast({ title: "缺少下级编码", icon: "none" });
      return;
    }
    if (!seg.code) {
      wx.showToast({ title: "无法下钻", icon: "none" });
      return;
    }
    this.setData({ drillPath: path.concat([seg]) }, () => this._loadDrillList());
  },
  _loadDrillList() {
    if (this.data.tab !== 3) return;
    const dq = this._drillDateQuery();
    if (!dq) {
      this.setData({
        drillItems: [],
        drillEmpty: true,
        drillEmptyHint: "请先选择月份",
        drillBreadcrumb: buildBreadcrumbCrumbs([]),
        drillLoading: false,
      });
      return;
    }
    const path = this.data.drillPath || [];
    const n = path.length;
    let title = "大类";
    if (n === 1) title = "中类";
    else if (n === 2) title = "小类";
    else if (n === 3) title = "SKU";
    this.setData({
      drillLoading: true,
      drillEmpty: false,
      drillEmptyHint: "",
      drillListTitle: title,
      drillBreadcrumb: buildBreadcrumbCrumbs(path),
    });
    let p;
    if (n === 0) {
      p = request("/api/mobile/category_large?" + dq, "GET", {});
    } else if (n === 1) {
      p = request(
        "/api/mobile/category_mid?category_large_code=" +
          encodeURIComponent(path[0].code) +
          "&" +
          dq,
        "GET",
        {}
      );
    } else if (n === 2) {
      p = request(
        "/api/mobile/category_small?category_large_code=" +
          encodeURIComponent(path[0].code) +
          "&category_mid_code=" +
          encodeURIComponent(path[1].code) +
          "&" +
          dq,
        "GET",
        {}
      );
    } else if (n === 3) {
      p = request(
        "/api/mobile/category_skus?category_large_code=" +
          encodeURIComponent(path[0].code) +
          "&category_mid_code=" +
          encodeURIComponent(path[1].code) +
          "&category_small_code=" +
          encodeURIComponent(path[2].code) +
          "&" +
          dq,
        "GET",
        {}
      );
    } else {
      this.setData({
        drillItems: [],
        drillLoading: false,
        drillEmpty: true,
        drillEmptyHint: "层级过深",
      });
      return;
    }
    return p
      .then((j) => {
        const d = j.data || {};
        const raw = d.items || [];
        const note = (d.note || "").trim();
        this.setData({
          drillItems: decorateDrillRows(raw),
          drillLoading: false,
          drillEmpty: !raw.length,
          drillEmptyHint:
            note || (n === 2 ? "暂无小类（可能销售表无小类字段）" : "暂无下级分类"),
        });
      })
      .catch((err) => {
        this.setData({
          drillItems: [],
          drillLoading: false,
          drillEmpty: true,
          drillEmptyHint: (err && err.message) || "加载失败",
        });
        wx.showToast({ title: (err && err.message) || "失败", icon: "none" });
      });
  },
  _syncChartsForTab() {
    const t = this.data.tab;
    if (t === 0) this._ensurePie();
    if (t === 2) this._ensureBar();
  },
  _bindPieEvents() {
    if (!this._pieChart || this._pieEventsBound) return;
    this._pieEventsBound = true;
    this._pieChart.on("click", (params) => {
      if (params.dataIndex == null) return;
      this._setPieSelection(params.dataIndex);
    });
  },
  _ensurePie() {
    const share = this.data.share || [];
    if (!share.length) {
      this._disposePie();
      return;
    }
    if (!this.pieComp) this.pieComp = this.selectComponent("#analysis-pie");
    if (!this.pieComp) return;
    const data = share.map((s) => ({
      name: (s.category_large || s.category_large_code || "").slice(0, 12),
      value: Number(s.sales_amount) || 0,
    }));
    const total = data.reduce((a, b) => a + b.value, 0);
    if (!this._pieInited) {
      this._pieInited = true;
      this.pieComp.init((canvas, width, height, dpr) => {
        const chart = echarts.init(canvas, null, {
          width,
          height,
          devicePixelRatio: dpr,
        });
        canvas.setChart(chart);
        this._pieChart = chart;
        this._applyPie(chart, data, total);
        this._bindPieEvents();
        return chart;
      });
    } else if (this._pieChart) {
      this._applyPie(this._pieChart, data, total);
      this._bindPieEvents();
    }
  },
  _applyPie(chart, data, total) {
    const sel = this.data.pieSelection || { mode: "total" };
    const colors = PIE_COLORS;
    const seriesData = data.map((d, i) => ({
      ...d,
      itemStyle: {
        color: colors[i % colors.length],
        borderRadius: 6,
        borderColor: "#ffffff",
        borderWidth: 2,
      },
    }));
    let titleText = "总销售额";
    let subText = "¥" + fmtYuan(total);
    if (sel.mode === "slice" && sel.name) {
      titleText = sel.name.slice(0, 14);
      subText = "¥" + fmtYuan(sel.value) + " · " + (sel.pct != null ? sel.pct : 0) + "%";
    }
    chart.setOption(
      {
        color: colors,
        title: {
          text: titleText,
          subtext: subText,
          left: "center",
          top: "36%",
          textAlign: "center",
          textStyle: {
            color: "#8c8c8c",
            fontSize: 11,
            fontWeight: "normal",
          },
          subtextStyle: {
            color: "#c92539",
            fontSize: 15,
            fontWeight: "bold",
          },
        },
        tooltip: {
          trigger: "item",
          confine: true,
          formatter: "{b}: ¥{c} ({d}%)",
        },
        series: [
          {
            type: "pie",
            radius: ["48%", "74%"],
            center: ["50%", "42%"],
            clockwise: true,
            minAngle: 2,
            avoidLabelOverlap: true,
            label: { show: false },
            labelLine: { show: false },
            emphasis: {
              scale: true,
              scaleSize: 4,
            },
            data: seriesData,
          },
        ],
      },
      { notMerge: true }
    );
    setTimeout(() => {
      if (!chart) return;
      chart.dispatchAction({ type: "downplay", seriesIndex: 0 });
      if (sel.mode === "slice" && sel.index != null) {
        chart.dispatchAction({
          type: "highlight",
          seriesIndex: 0,
          dataIndex: sel.index,
        });
      }
    }, 80);
  },
  _ensureBar() {
    const contrib = this.data.contrib || [];
    if (!this.barComp) this.barComp = this.selectComponent("#analysis-bar");
    if (!this.barComp) return;
    const names = contrib.map((c) =>
      String(c.large_category || c.category_large_code || "").slice(0, 10)
    );
    const sdat = contrib.map((c) => Math.round(Number(c.sales_share || 0) * 10000) / 100);
    const pdat = contrib.map((c) => Math.round(Number(c.profit_share || 0) * 10000) / 100);
    if (!this._barInited) {
      this._barInited = true;
      this.barComp.init((canvas, width, height, dpr) => {
        const chart = echarts.init(canvas, null, {
          width,
          height,
          devicePixelRatio: dpr,
        });
        canvas.setChart(chart);
        this._barChart = chart;
        this._applyBar(chart, names, sdat, pdat);
        return chart;
      });
    } else if (this._barChart) {
      this._applyBar(this._barChart, names, sdat, pdat);
    }
  },
  _applyBar(chart, names, sdat, pdat) {
    chart.setOption(
      {
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        legend: { data: ["销售占比%", "毛利占比%"], top: 0, textStyle: { fontSize: 10 } },
        grid: { left: 12, right: 16, top: 36, bottom: 8, containLabel: true },
        xAxis: { type: "value", max: 100, axisLabel: { fontSize: 10 } },
        yAxis: { type: "category", data: names, axisLabel: { fontSize: 10 } },
        series: [
          { name: "销售占比%", type: "bar", data: sdat, itemStyle: { color: "#c92539" } },
          { name: "毛利占比%", type: "bar", data: pdat, itemStyle: { color: "#52c41a" } },
        ],
      },
      { notMerge: true }
    );
  },
  _decorateMatrix(matrix) {
    return (matrix || []).map((r, i) => {
      const m = Number(r.margin_pct) || 0;
      return {
        ...r,
        _k: (r.month || "") + "-" + (r.category_large_code || i),
        _bgPct: bgBarWidthPct(m),
      };
    });
  },
  _decorateContrib(items) {
    return (items || []).map((c) => {
      const s = Number(c.sales_share) || 0;
      const p = Number(c.profit_share) || 0;
      const compositePct = ((s + p) / 2) * 100;
      return { ...c, _bgPct: bgBarWidthPct(compositePct) };
    });
  },
  _decorateShare(items, prevItems) {
    const prevMap = {};
    (prevItems || []).forEach((p) => {
      const k = p.category_large_code || p.category_large;
      if (k) prevMap[k] = Number(p.percentage);
    });
    return (items || []).map((it) => {
      const key = it.category_large_code || it.category_large;
      const prevP = prevMap[key];
      const pct = Number(it.percentage) || 0;
      let _hasMom = false;
      let _momUp = false;
      let _momDown = false;
      let _momStr = "";
      if (prevP != null && !Number.isNaN(prevP)) {
        const delta = Math.round((pct - prevP) * 100) / 100;
        _hasMom = true;
        if (delta > 0.02) _momUp = true;
        else if (delta < -0.02) _momDown = true;
        _momStr = (delta >= 0 ? "+" : "") + delta + "pp";
      }
      return {
        ...it,
        _bgPct: bgBarWidthPct(pct),
        _hasMom,
        _momUp,
        _momDown,
        _momStr,
      };
    });
  },
  loadAll() {
    this.setData({ loading: true });
    const opt = (this.data.monthOptions || [])[this.data.monthIndex] || (buildMonthOptions()[0] || { ym: "" });
    const ym = opt.ym;
    if (!ym) {
      this.setData({ loading: false });
      return Promise.resolve();
    }
    const { start, end } = monthBounds(ym);
    const pYm = prevYm(ym);
    const { start: ps, end: pe } = monthBounds(pYm);
    const q = "kpi_cycle=custom&start_date=" + start + "&end_date=" + end;
    const pq = "kpi_cycle=custom&start_date=" + ps + "&end_date=" + pe;
    const p1 = request("/api/mobile/category_share?" + q, "GET", {});
    const p2 = request(
      "/api/mobile/heatmap?year_month_start=" + encodeURIComponent(ym) + "&year_month_end=" + encodeURIComponent(ym),
      "GET",
      {}
    );
    const p3 = request("/api/mobile/contribution?" + q, "GET", {});
    const p4 = request("/api/mobile/category_share?" + pq, "GET", {}).catch(() => ({
      data: { items: [] },
    }));
    return Promise.all([p1, p2, p3, p4])
      .then(([a, b, c, d]) => {
        const curItems = (a.data && a.data.items) || [];
        const prevItems = (d.data && d.data.items) || [];
        const share = this._decorateShare(curItems, prevItems);
        const mx = (b.data && b.data.matrix) || [];
        this.setData(
          {
            share,
            matrix: this._decorateMatrix(mx),
            contrib: this._decorateContrib((c.data && c.data.items) || []),
            loading: false,
            pieSelection: { mode: "total" },
            ...(this.data.tab === 3 ? { drillPath: [] } : {}),
          },
          () => {
            this._pieEventsBound = false;
            if (this._pageReady) {
              wx.nextTick(() => {
                this._syncChartsForTab();
                if (this.data.tab === 3) this._loadDrillList();
                if (this.data.tab === 4) this._loadAttribution();
              });
            } else this._pendingCharts = true;
          }
        );
      })
      .catch((e) => {
        this.setData({ loading: false });
        wx.showToast({ title: (e && e.message) || "失败", icon: "none" });
      });
  },
});
