const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { syncTabBar } = require("../../utils/tabbar");
const { bgBarWidthPct } = require("../../utils/analyticsUI");

const CYCLES = [
  { id: "today", label: "今日" },
  { id: "this_week", label: "本周" },
  { id: "this_month", label: "本月" },
  { id: "last_30_days", label: "近30天" },
  { id: "custom", label: "自定义" },
];

/** 服务端在导入后会清缓存；此处不再长时间跳过 onShow，避免切回首页仍显示旧 KPI */
const CACHE_MS = 0;

Page({
  _lastLoadKey: "",
  _lastLoadAt: 0,
  _loadSeq: 0,
  _aiTick: null,
  data: {
    loading: true,
    kpiCycle: "last_30_days",
    cycleLabel: "近30天",
    cycleIndex: 3,
    cycleLabels: CYCLES,
    customRange: { start: "", end: "" },
    ov: null,
    asOf: "",
    tickerItems: [],
    aiReport: "",
    aiReportFull: "",
    aiReportDate: "",
    aiTyping: false,
    statsLagNote: "",
    sigCard: { loaded: false, rows: [], slope: null, slopeCls: "", metaLine: "" },
  },
  onUnload() {
    this._clearAiTick();
  },
  _clearAiTick() {
    if (this._aiTick) {
      clearInterval(this._aiTick);
      this._aiTick = null;
    }
  },
  _startAiTypewriter(full) {
    this._clearAiTick();
    const text = String(full || "").trim();
    if (!text) {
      this.setData({ aiReport: "", aiReportFull: "", aiTyping: false });
      return;
    }
    this.setData({ aiReportFull: text, aiReport: "", aiTyping: true });
    let i = 0;
    const step = 2;
    const self = this;
    this._aiTick = setInterval(() => {
      i += step;
      if (i >= text.length) {
        self.setData({ aiReport: text, aiTyping: false });
        self._clearAiTick();
        return;
      }
      self.setData({ aiReport: text.slice(0, i) });
    }, 42);
  },
  onShow() {
    syncTabBar();
    if (!requireToken()) return;
    const c = this.data.kpiCycle;
    const { start, end } = this.data.customRange || {};
    if (c === "custom" && (!start || !end)) {
      return;
    }
    const key = `${c}|${start || ""}|${end || ""}`;
    const now = Date.now();
    if (
      key === this._lastLoadKey &&
      now - this._lastLoadAt < CACHE_MS &&
      this.data.ov
    ) {
      return;
    }
    this.load();
  },
  onPullDownRefresh() {
    this._lastLoadAt = 0;
    this._lastLoadKey = "";
    this.load().finally(() => wx.stopPullDownRefresh());
  },
  onPickCycle(e) {
    const i = Number(e.detail.value);
    const cyc = CYCLES[i] || CYCLES[3];
    const isCustom = cyc.id === "custom";
    this.setData(
      { kpiCycle: cyc.id, cycleLabel: cyc.label, cycleIndex: i },
      () => {
        if (isCustom) {
          this.setData({ loading: false });
          wx.showToast({
            title: "请选择开始与结束日期后点「应用」",
            icon: "none",
            duration: 2200,
          });
          return;
        }
        this.load();
      }
    );
  },
  onPickCycleCap(e) {
    const i = Number(e.currentTarget.dataset.i);
    if (Number.isNaN(i)) return;
    const cyc = CYCLES[i] || CYCLES[3];
    const isCustom = cyc.id === "custom";
    this.setData(
      { kpiCycle: cyc.id, cycleLabel: cyc.label, cycleIndex: i },
      () => {
        if (isCustom) {
          this.setData({ loading: false });
          wx.showToast({
            title: "请选择开始与结束日期后点「应用」",
            icon: "none",
            duration: 2200,
          });
          return;
        }
        this.load();
      }
    );
  },
  onStart(e) {
    this.setData({ "customRange.start": e.detail.value });
  },
  onEnd(e) {
    this.setData({ "customRange.end": e.detail.value });
  },
  goCats() {
    wx.switchTab({ url: "/pages/analysis/index" });
  },
  goInsight() {
    wx.switchTab({ url: "/pages/insight/index" });
  },
  goAttribution() {
    const app = getApp();
    if (app && app.globalData) app.globalData.analysisOpenTabIndex = 4;
    wx.switchTab({ url: "/pages/analysis/index" });
  },
  /** 与日期行「应用」绑定：先固定为自定义周期再拉数，避免 setData 异步导致仍按近30天请求 */
  applyCustom() {
    const { start, end } = this.data.customRange || {};
    if (!start || !end) {
      wx.showToast({
        title: "请同时选择开始与结束日期",
        icon: "none",
      });
      return;
    }
    const ci = CYCLES.findIndex((x) => x.id === "custom");
    this.setData(
      {
        kpiCycle: "custom",
        cycleLabel: "自定义",
        cycleIndex: ci >= 0 ? ci : 4,
      },
      () => this.load()
    );
  },
  load() {
    const c = this.data.kpiCycle;
    if (c === "custom") {
      const s = this.data.customRange.start;
      const e = this.data.customRange.end;
      if (!s || !e) {
        this.setData({ loading: false });
        wx.showToast({
          title: "请同时选择开始与结束日期",
          icon: "none",
        });
        return Promise.resolve();
      }
    }
    const seq = ++this._loadSeq;
    this.setData({ loading: true });
    let q = "kpi_cycle=" + encodeURIComponent(c);
    if (c === "custom") {
      const s = this.data.customRange.start;
      const e = this.data.customRange.end;
      q += "&start_date=" + s + "&end_date=" + e;
    }
    return Promise.all([
      request("/api/mobile/overview?" + q, "GET", {}),
      request("/api/mobile/alerts/list?days=30", "GET", {}).catch(() => ({
        data: { items: [] },
      })),
      request("/api/mobile/ai_daily/latest", "GET", {}).catch(() => ({
        data: { content: "", report_date: "" },
      })),
      request("/api/mobile/insights_signals?days=40", "GET", {}).catch(() => null),
    ])
      .then(([j, ja, jl, js]) => {
        if (seq !== this._loadSeq) return;
        const d = j.data || {};
        const wk = d.weekday_compare || [];
        const maxS = wk.length ? Math.max.apply(null, wk.map((x) => x.sales || 0)) : 0;
        d.weekday_compare = wk.map((x) => {
          const p = maxS > 0 ? Math.round((x.sales / maxS) * 100) : 0;
          return { ...x, _pct: p, _bgPct: bgBarWidthPct(p) };
        });
        d._saleWan = d.total_sales != null ? (d.total_sales / 10000).toFixed(1) : "—";
        d._profWan = d.total_profit != null ? (d.total_profit / 10000).toFixed(1) : "—";
        d._invWan =
          d.inventory_total != null ? (d.inventory_total / 10000).toFixed(1) : "—";
        const rawA = (ja.data && ja.data.items) || [];
        const aiBody = jl.data || {};
        const aiContent = (aiBody.content || "").trim();
        const aiDate = (aiBody.report_date || "").trim();
        this._startAiTypewriter(aiContent);
        const tickerItems = rawA.slice(0, 10).map((it, idx) => {
          const t = (it && it.title) || "";
          const det = (it && it.detail) ? String(it.detail) : "";
          return {
            _k: "tk" + idx,
            line:
              t + (det ? " · " + (det.length > 40 ? det.slice(0, 40) + "…" : det) : ""),
          };
        });
        const lag = d.stats_lag || {};
        const lagNote = (lag && lag.note) || "";
        let sigCard = { loaded: false, rows: [], slope: null, slopeCls: "", metaLine: "" };
        if (js && Number(js.code) === 0 && js.data && typeof js.data === "object") {
          const sig = js.data;
          const low = (sig.margin_zscore_low || []).slice(0, 5);
          const zs = low.map((x) => Math.abs(Number(x.zscore_margin) || 0));
          const maxZ = zs.length ? Math.max.apply(null, zs) : 2.5;
          const zDenom = Math.max(maxZ, 2.5);
          sigCard = {
            loaded: true,
            rows: low.map((x, i) => ({
              _k: "sig" + i,
              category_large: x.category_large || "",
              zscore_margin: x.zscore_margin,
              latest_margin_pct: x.latest_margin_pct,
              _bgPct: bgBarWidthPct(
                Math.min(100, (Math.abs(Number(x.zscore_margin) || 0) / zDenom) * 100)
              ),
            })),
            slope: sig.sales_ma7_slope_pct != null ? sig.sales_ma7_slope_pct : null,
            slopeCls:
              sig.sales_ma7_slope_pct == null
                ? ""
                : Number(sig.sales_ma7_slope_pct) >= 0
                  ? "tr-up"
                  : "tr-down",
            metaLine:
              sig.daily_points_used != null
                ? "窗口内 " +
                  sig.daily_points_used +
                  " 个有销日 · " +
                  (sig.categories_tracked || 0) +
                  " 个大类序列"
                : "",
          };
        }
        this.setData({
          ov: d,
          asOf: d.stats_as_of || "",
          statsLagNote: lagNote,
          loading: false,
          tickerItems,
          aiReportDate: aiDate,
          sigCard,
        });
        const c2 = this.data.kpiCycle;
        const r2 = this.data.customRange || {};
        this._lastLoadKey = `${c2}|${r2.start || ""}|${r2.end || ""}`;
        this._lastLoadAt = Date.now();
      })
      .catch((err) => {
        if (seq !== this._loadSeq) return;
        this.setData({
          loading: false,
          ov: null,
          asOf: "",
          statsLagNote: "",
          sigCard: {
            loaded: false,
            rows: [],
            slope: null,
            slopeCls: "",
            metaLine: "",
          },
        });
        if (err && err.silent) return;
        wx.showToast({
          title: (err && err.message) || "加载失败",
          icon: "none",
        });
      });
  },
});
