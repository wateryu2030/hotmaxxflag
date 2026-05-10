const { request, clearAuth } = require("./utils/request");
const { errText } = require("./utils/errMsg");

function _wmRandHex(len) {
  const hex = "0123456789abcdef";
  let s = "";
  for (let i = 0; i < len; i++) s += hex[Math.floor(Math.random() * 16)];
  return s;
}

App({
  globalData: {
    baseUrl: "https://htma.greatagain.com.cn",
    requestTimeout: 45000,
    token: "",
    userInfo: null,
    subscribeTmplIds: [],
    /** 冷启动一次，用于水印截屏溯源 */
    wmSessionKey: "",
    /** switchTab 无法带参：预警跳转品类分析前写入，analysis 页 onShow 消费 */
    analysisTabBootstrap: null,
    /** 首页「查看归因」：打开品类分析指定 Tab（0-4，4=销售额环比归因） */
    analysisOpenTabIndex: null,
  },
  onUnhandledRejection(ev) {
    const r = ev && ev.reason;
    if (r == null) return;
    const line =
      r instanceof Error
        ? errText(r.message, "Error")
        : errText(r, "rejected");
    console.warn("[未处理的 Promise]", line);
  },
  onLaunch() {
    if (!wx.__htmaToastPatched) {
      wx.__htmaToastPatched = true;
      const __toast = wx.showToast.bind(wx);
      wx.showToast = function (opts) {
        if (!opts || typeof opts !== "object") return __toast(opts);
        const t0 = opts.title;
        if (t0 !== undefined && t0 !== null && t0 !== "") {
          let t = t0;
          if (typeof t !== "string") t = errText(t, "请稍后重试");
          else if (String(t).trim() === "[object Object]")
            t = "接口返回异常，请稍后重试";
          return __toast({ ...opts, title: t });
        }
        return __toast(opts);
      };
    }
    this.globalData.wmSessionKey = _wmRandHex(10);
    this._loadSubscribeTmplIds();
    const t = wx.getStorageSync("token");
    this.globalData.token = t || "";
    if (t) {
      wx.reLaunch({ url: "/pages/home/index" });
      setTimeout(() => this._refreshUser(), 2000);
    }
  },
  setToken(t) {
    this.globalData.token = t || "";
    if (t) wx.setStorageSync("token", t);
    else wx.removeStorageSync("token");
  },
  _loadSubscribeTmplIds() {
    const base = (this.globalData && this.globalData.baseUrl) || "";
    if (!base) return;
    wx.request({
      url: `${base.replace(/\/$/, "")}/api/wechat/subscribe_config`,
      method: "GET",
      success: (res) => {
        const body = res.data || {};
        const ids = body.template_ids;
        if (res.statusCode === 200 && Array.isArray(ids) && ids.length) {
          this.globalData.subscribeTmplIds = ids;
        }
      },
    });
  },
  _refreshUser() {
    if (!this.globalData.token) return;
    request("/api/wechat/me", "GET", {})
      .then((body) => {
        if (body && (body.user || (body.data && body.data.user))) {
          this.globalData.userInfo = body.user || body.data.user;
        }
      })
      .catch(() => {});
  },
  checkSession() {
    if (!this.globalData.token) {
      clearAuth();
      return;
    }
    request("/api/wechat/me", "GET", {}, { showErr: false })
      .then(() => {})
      .catch(() => {
        clearAuth();
      });
  },
});
