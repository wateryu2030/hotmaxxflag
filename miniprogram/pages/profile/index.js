const { request, clearAuth } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const { syncTabBar } = require("../../utils/tabbar");

Page({
  data: { user: null },
  onShow() {
    syncTabBar();
    if (!requireToken()) return;
    this.load();
  },
  load() {
    return request("/api/wechat/me", "GET", {})
      .then((b) => {
        const u = b.user || (b.data && b.data.user);
        let initial = "经";
        if (u) {
          if (u.role) initial = String(u.role).charAt(0);
          else if (u.phone) initial = String(u.phone).charAt(0);
          else if (u.id != null) initial = String(u.id).charAt(0);
        }
        this.setData({ user: u ? { ...u, _initial: initial } : null });
        const app = getApp();
        if (app) app.globalData.userInfo = u;
      })
      .catch(() => {});
  },
  goSku() {
    wx.navigateTo({ url: "/pages/tools/sku" });
  },
  goTax() {
    wx.navigateTo({ url: "/pages/tools/tax" });
  },
  goSel() {
    wx.navigateTo({ url: "/pages/tools/selection" });
  },
  goAi() {
    wx.navigateTo({ url: "/pages/tools/ai" });
  },
  goReport() {
    wx.navigateTo({ url: "/pages/tools/report" });
  },
  bindPhone() {
    wx.showModal({
      content: "在登录页可授权手机号，或在公众平台开通「getPhoneNumber」后使用。",
      showCancel: false,
    });
  },
  bindFeishu() {
    wx.showModal({
      title: "绑定飞书",
      editable: true,
      placeholderText: "ou_xxx 或 open_id",
      success: (res) => {
        if (!res.confirm || !res.content) return;
        request("/api/wechat/bind_feishu", "POST", { feishu_open_id: res.content })
          .then(() => {
            wx.showToast({ title: "已更新" });
            this.load();
          })
          .catch((e) => wx.showToast({ title: (e && e.message) || "失败", icon: "none" }));
      },
    });
  },
  goLogin() {
    wx.reLaunch({ url: "/pages/entry/index" });
  },
  logout() {
    const app = getApp();
    if (app && app.setToken) app.setToken("");
    clearAuth();
  },
});
