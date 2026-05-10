Page({
  goWechat() {
    wx.navigateTo({ url: "/pages/profile/login" });
  },
  goFeishu() {
    wx.navigateTo({ url: "/pages/profile/feishu-web" });
  },
});
