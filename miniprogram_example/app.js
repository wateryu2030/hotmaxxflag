// 好特卖看板小程序调试：与后端 htma 同域 HTTPS
App({
  globalData: {
    baseUrl: "https://htma.greatagain.com.cn",
    token: "",
  },
  onLaunch() {
    try {
      const t = wx.getStorageSync("htma_token");
      if (t) this.globalData.token = t;
    } catch (e) {}
  },
  setToken(t) {
    this.globalData.token = t || "";
    try {
      if (t) wx.setStorageSync("htma_token", t);
      else wx.removeStorageSync("htma_token");
    } catch (e) {}
  },
});
