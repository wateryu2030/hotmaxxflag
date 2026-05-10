const { request } = require("../../utils/request");

Page({
  goEntry() {
    wx.reLaunch({ url: "/pages/entry/index" });
  },
  doLogin() {
    wx.showLoading({ title: "登录中" });
    wx.login({
      success: (lr) => {
        if (!lr.code) {
          wx.hideLoading();
          wx.showToast({ title: "无 code", icon: "none" });
          return;
        }
        request(
          "/api/wechat/login",
          "POST",
          { code: lr.code },
          { skipAuth: true }
        )
          .then((b) => {
            const token = b.token;
            if (!token) {
              throw new Error("登录响应无 token");
            }
            const app = getApp();
            if (app && app.setToken) app.setToken(token);
            else {
              wx.setStorageSync("token", token);
              if (app) app.globalData.token = token;
            }
            if (b.user && app) app.globalData.userInfo = b.user;
            wx.hideLoading();
            wx.reLaunch({ url: "/pages/home/index" });
          })
          .catch((e) => {
            wx.hideLoading();
            wx.showToast({ title: (e && e.message) || "登录失败", icon: "none" });
          });
      },
      fail: () => {
        wx.hideLoading();
        wx.showToast({ title: "wx.login 失败", icon: "none" });
      },
    });
  },
  getPhone(e) {
    if (!e.detail || !e.detail.code) {
      wx.showToast({ title: "未取到 code", icon: "none" });
      return;
    }
    request("/api/wechat/bind_phone", "POST", { code: e.detail.code })
      .then(() => wx.showToast({ title: "已绑定" }))
      .catch((err) => wx.showToast({ title: (err && err.message) || "失败", icon: "none" }));
  },
});
