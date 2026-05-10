const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { bgBarWidthPct } = require("../../utils/analyticsUI");

function stripForItem(it) {
  const lv = (it && it.level) || "";
  if (lv === "critical") return "danger";
  if (lv === "warning") return "warn";
  const icon = (it && it.icon) || "";
  const typ = (it && it.type) || "";
  if (icon === "error" || typ === "negative_sku" || lv === "critical") return "danger";
  if (icon === "warning" || typ === "low_margin_category" || lv === "warning") return "warn";
  return "info";
}

function decorateItems(raw) {
  return (raw || []).map((it) => ({
    ...it,
    _strip: stripForItem(it),
  }));
}

function stripToPct(strip) {
  if (strip === "danger") return 96;
  if (strip === "warn") return 62;
  return 36;
}

Page({
  data: {
    loading: true,
    items: [],
    displayList: [],
    expandAll: false,
    showExpandBtn: false,
  },
  onShow() {
    if (!requireToken()) return;
    this.load();
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },
  load() {
    this.setData({ loading: true });
    return request("/api/mobile/alerts/list?days=30", "GET", {})
      .then((j) => {
        const items = decorateItems((j.data || {}).items || []);
        this.setData({ loading: false, items }, () => this._recomputeDisplay());
      })
      .catch((e) => {
        this.setData({ loading: false });
        if (e && e.silent) return;
        wx.showToast({ title: (e && e.message) || "失败", icon: "none" });
      });
  },
  _recomputeDisplay() {
    const { items, expandAll } = this.data;
    const abnormal = items.filter((i) => i._strip === "danger" || i._strip === "warn");
    const COLLAPSE_ABNORMAL_MAX = 5;
    let displayList;
    if (expandAll) {
      displayList = items;
    } else if (abnormal.length) {
      displayList = abnormal.slice(0, COLLAPSE_ABNORMAL_MAX);
    } else {
      displayList = items.slice(0, 3);
    }
    const moreAbnormal = !expandAll && abnormal.length > COLLAPSE_ABNORMAL_MAX;
    const hasHiddenInfo = !expandAll && items.some((i) => i._strip === "info");
    const moreNeutral = !expandAll && items.length > 3 && !abnormal.length;
    const showExpandBtn =
      expandAll ||
      moreAbnormal ||
      (hasHiddenInfo && abnormal.length > 0) ||
      (!expandAll && items.length > displayList.length) ||
      moreNeutral;
    const enriched = displayList.map((it, i) => ({
      ...it,
      _k: "al_" + i + "_" + (it.title || "").slice(0, 24) + "_" + (it.id || 0),
      _idx: i,
      _bgPct: bgBarWidthPct(stripToPct(it._strip)),
    }));
    this.setData({ displayList: enriched, showExpandBtn });
  },
  toggleExpand() {
    const expandAll = !this.data.expandAll;
    this.setData({ expandAll }, () => this._recomputeDisplay());
  },
  onAck(e) {
    const id = Number(e.currentTarget.dataset.id);
    if (!id) return;
    request("/api/mobile/alerts/ack", "POST", { id })
      .then(() => {
        wx.showToast({ title: "已处理", icon: "success" });
        this.load();
      })
      .catch((err) => {
        wx.showToast({ title: (err && err.message) || "失败", icon: "none" });
      });
  },
  onTapItem(e) {
    const u = (e.currentTarget.dataset.link || "").trim();
    if (u.indexOf("htma://analysis?") === 0) {
      const qs = u.slice("htma://analysis?".length);
      const params = {};
      qs.split("&").forEach((pair) => {
        const idx = pair.indexOf("=");
        if (idx < 0) return;
        const k = decodeURIComponent(pair.slice(0, idx));
        const v = decodeURIComponent(pair.slice(idx + 1) || "");
        params[k] = v;
      });
      const lc = (params.large_code || "").trim();
      if (!lc) return;
      const app = getApp();
      if (app && app.globalData) {
        app.globalData.analysisTabBootstrap = {
          large_code: lc,
          large_name: (params.large_name || "").trim(),
        };
      }
      wx.switchTab({ url: "/pages/analysis/index" });
      return;
    }
    if (u && u.indexOf("pages/") === 0) {
      wx.navigateTo({ url: (u.indexOf("/") === 0 ? u : "/" + u) });
    }
  },
  subscribe() {
    const app = getApp();
    const ids = (app.globalData && app.globalData.subscribeTmplIds) || [];
    if (!ids.length) {
      wx.showModal({
        content:
          "未获取到订阅模板 ID。请在服务器 .env 中配置 WECHAT_SUBSCRIBE_TEMPLATE_ID（公众平台已审核的模板，可多个用英文逗号分隔），保存后重启看板，再重进本页。",
        showCancel: false,
      });
      return;
    }
    wx.requestSubscribeMessage({
      tmplIds: ids,
      success: (res) => {
        for (const tid of ids) {
          if ((res || {})[tid] === "accept" || (res || {})[tid] === "acceptWithAlert") {
            request("/api/wechat/subscribe", "POST", { template_id: tid, is_active: true })
              .then(() => wx.showToast({ title: "已登记" }))
              .catch((e) => wx.showToast({ title: (e && e.message) || "失败", icon: "none" }));
            return;
          }
        }
        wx.showToast({ title: "未接受订阅", icon: "none" });
      },
    });
  },
});
