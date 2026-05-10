const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");

Page({
  data: { msg: "" },
  onShow() {
    if (!requireToken()) return;
  },
  gen() {
    request("/api/mobile/generate_report", "POST", {})
      .then((j) => {
        const d = j.data || {};
        this.setData({
          msg: (d.message || "") + " " + (d.url || ""),
        });
        if (d.url) {
          wx.setClipboardData({ data: d.url });
        }
      })
      .catch((e) => wx.showToast({ title: (e && e.message) || "失败", icon: "none" }));
  },
});
