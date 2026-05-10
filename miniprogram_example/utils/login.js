const { request } = require("./request.js");

/**
 * wx.login → POST /api/wechat/login（不带旧 Authorization，避免 INVALID_TOKEN / 会话冲突）
 */
function wechatLogin() {
  const app = getApp();
  return new Promise((resolve, reject) => {
    wx.login({
      success: async (lr) => {
        if (!lr.code) {
          reject(new Error("wx.login 无 code"));
          return;
        }
        try {
          const j = await request(
            "/api/wechat/login",
            "POST",
            { code: lr.code },
            { skipAuth: true }
          );
          if (!j || !j.success || !j.token) {
            reject(new Error((j && j.message) || "登录失败"));
            return;
          }
          app.setToken(j.token);
          resolve(j);
        } catch (e) {
          reject(e);
        }
      },
      fail: (e) =>
        reject(new Error((e && e.errMsg) || "wx.login 失败")),
    });
  });
}

module.exports = { wechatLogin };
