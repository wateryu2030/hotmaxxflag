Page({
  data: { src: "", boardUrl: "" },
  onLoad() {
    const app = getApp();
    const base = (
      (app && app.globalData && app.globalData.baseUrl) ||
      ""
    ).replace(/\/$/, "");
    const boardUrl = /^https:\/\//i.test(base) ? `${base}/login?from=miniprogram` : "";
    this.setData({ src: boardUrl, boardUrl });
  },
  copyBoardUrl() {
    const u = this.data.boardUrl || this.data.src;
    if (!u) {
      wx.showToast({ title: "请先配置 baseUrl", icon: "none" });
      return;
    }
    wx.setClipboardData({
      data: u,
      success: () => wx.showToast({ title: "已复制登录页链接" }),
    });
  },
});
