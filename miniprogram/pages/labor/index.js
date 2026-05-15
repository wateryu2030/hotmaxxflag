const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");

Page({
  data: {
    months: [],
    monthIdx: 0,
    currentMonth: "",
    loading: false,
    error: "",
    summary: null,
    persons: [],
    displayList: [],
    byTypeArr: [],
    trends: [],
    trendRows: [],
  },

  onShow() {
    if (!requireToken()) return;
    this._loadAll(true);
  },
  onPullDownRefresh() {
    this._loadAll(false).finally(() => wx.stopPullDownRefresh());
  },

  onMonthChange(e) {
    const idx = parseInt(e.detail.value, 10);
    this.setData({ monthIdx: idx, currentMonth: this.data.months[idx] || "" });
    this._loadMonth(this.data.months[idx] || "");
  },

  _buildTrendRows(trs) {
    const t = (trs || []).slice(-6);
    let maxC = 0;
    t.forEach((row) => {
      const c = Number(row.total_cost) || 0;
      if (c > maxC) maxC = c;
    });
    if (!maxC) maxC = 1;
    return t.map((row) => ({
      month: row.month,
      headcount: row.headcount,
      total_cost: row.total_cost,
      _costPct: Math.round(((Number(row.total_cost) || 0) / maxC) * 100),
    }));
  },

  _applyDetailPayload(d) {
    const months = (d.trends || []).map((t) => t.month);
    const month = d.month || (months.length ? months[months.length - 1] : "");
    const idx = months.indexOf(month);
    this.setData({
      months,
      monthIdx: idx >= 0 ? idx : Math.max(0, months.length - 1),
      currentMonth: month,
      trends: d.trends || [],
      trendRows: this._buildTrendRows(d.trends),
      summary: d.summary || null,
      persons: d.persons || [],
      byTypeArr: this._buildTypeArr(d),
      loading: false,
    });
    this._renderList();
  },

  _loadAll(showLoading) {
    if (showLoading) this.setData({ loading: true, error: "" });
    const p = request("/api/mobile/labor_detail", "GET", {})
      .then((j) => {
        this._applyDetailPayload(j.data || {});
      })
      .catch((e) => {
        if (e && e.silent) return;
        this.setData({
          loading: false,
          error: (e && e.message) || "加载失败",
        });
      });
    return p;
  },

  _loadMonth(month) {
    if (!month) return;
    this.setData({ loading: true, error: "" });
    request("/api/mobile/labor_detail?month=" + encodeURIComponent(month), "GET", {})
      .then((j) => {
        const d = j.data || {};
        this.setData({
          summary: d.summary || null,
          persons: d.persons || [],
          byTypeArr: this._buildTypeArr(d),
          trends: d.trends && d.trends.length ? d.trends : this.data.trends,
          trendRows: this._buildTrendRows(d.trends && d.trends.length ? d.trends : this.data.trends),
          loading: false,
        });
        this._renderList();
      })
      .catch((e) => {
        if (e && e.silent) return;
        this.setData({
          loading: false,
          error: (e && e.message) || "加载失败",
        });
      });
  },

  _buildTypeArr(d) {
    const byType = d.byType || d.by_type || {};
    const total = d.summary ? d.summary.total_cost || 1 : 1;
    const meta = {
      fulltime: "组员",
      leader: "组长",
      management: "管理岗",
      cleaner: "保洁",
      parttime: "兼职",
      hourly: "小时工",
    };
    const colors = {
      fulltime: "#3498db",
      leader: "#f39c12",
      management: "#9b59b6",
      cleaner: "#1abc9c",
      parttime: "#e74c3c",
      hourly: "#95a5a6",
    };
    return Object.keys(byType).map((k) => ({
      name: k,
      label: meta[k] || k,
      cnt: byType[k].count || 0,
      cost: byType[k].cost || 0,
      pct: Math.round(((byType[k].cost || 0) / total) * 100),
      color: colors[k] || "#667eea",
    }));
  },

  _renderList() {
    const ps = (this.data.persons || []).slice();
    ps.sort((a, b) => (b.total_cost || 0) - (a.total_cost || 0));
    const displayList = ps.map((p) => {
      const tl = (p.type_label || "").trim();
      const typeLabelClass =
        tl === "经营岗" ? "direct" : tl === "通用岗" ? "shared" : "management";
      return Object.assign({}, p, { typeLabelClass });
    });
    this.setData({ displayList });
  },
});
