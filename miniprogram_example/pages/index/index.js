const { wechatLogin } = require("../../utils/login.js");
const { request } = require("../../utils/request.js");

Page({
  data: {
    baseUrl: "",
    hasToken: false,
    log: "",
    autoRunning: false,
  },
  onLoad() {
    const app = getApp();
    const baseUrl = (app.globalData && app.globalData.baseUrl) || "";
    this.setData({
      baseUrl,
      hasToken: !!(app.globalData && app.globalData.token),
    });
    // 进入页自动：换 token → 拉 dashboard（与手动按钮同逻辑）
    this.scheduleAutoPipeline();
  },
  onShow() {
    const app = getApp();
    this.setData({ hasToken: !!(app.globalData && app.globalData.token) });
  },
  onPullDownRefresh() {
    this.scheduleAutoPipeline(true);
  },
  scheduleAutoPipeline(fromPull) {
    if (fromPull) wx.stopPullDownRefresh();
    // 等首屏渲染后再跑，避免 IDE 偶发首帧未就绪
    setTimeout(() => this.runAutoPipeline(fromPull), 200);
  },
  _append(msg) {
    const prev = this.data.log || "";
    this.setData({ log: prev + msg + "\n" });
  },
  /** 自动流水线：静默清掉可能干扰换码的旧 token，再 login → dashboard */
  runAutoPipeline(fromPull) {
    if (this.data.autoRunning) return;
    this.setData({ autoRunning: true });
    const app = getApp();
    try {
      app.setToken("");
    } catch (e) {}
    this.setData({
      hasToken: false,
      log: (fromPull ? "【下拉刷新】" : "【自动】") + "清除本地旧 token → wx.login …\n",
    });
    wechatLogin()
      .then((j) => {
        this._append(
          "换 token 成功，user.id=" + (j.user && j.user.id) + "，拉取 dashboard …\n"
        );
        this.setData({ hasToken: true });
        return request("/api/mobile/dashboard", "GET");
      })
      .then((j) => {
        this._append(JSON.stringify(j, null, 2).slice(0, 5000));
      })
      .catch((e) => {
        this._append(
          "失败: " + (e && e.message ? e.message : String(e)) + "\n"
        );
        this._append(
          "若仍 INVALID_TOKEN：微信开发者工具右上角退出账号后重新扫码登录；或检查公众平台 AppSecret 与服务器 .env 是否一致。"
        );
      })
      .finally(() => {
        this.setData({ autoRunning: false, hasToken: !!getApp().globalData.token });
      });
  },
  onLogin() {
    this.setData({ log: "" });
    this._append("手动：wx.login …\n");
    wechatLogin()
      .then((j) => {
        this._append("登录成功 user.id=" + (j.user && j.user.id));
        this.setData({ hasToken: true });
      })
      .catch((e) => {
        this._append("失败: " + (e && e.message ? e.message : String(e)));
      });
  },
  onDash() {
    this._append("手动：GET /api/mobile/dashboard …\n");
    request("/api/mobile/dashboard", "GET")
      .then((j) => {
        this._append(JSON.stringify(j, null, 2).slice(0, 4000));
      })
      .catch((e) => {
        this._append("失败: " + (e && e.message ? e.message : String(e)));
      });
  },
});
