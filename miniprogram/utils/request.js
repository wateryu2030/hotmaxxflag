/**
 * 禁止在模块顶层 getApp()：app.js 里 require 本文件时 App() 尚未执行，会导致 baseUrl 为空、请求异常或长时间无响应。
 */
const { errText } = require("./errMsg");

function _getApp() {
  try {
    return getApp();
  } catch (e) {
    return null;
  }
}

function clearAuth() {
  const app = _getApp();
  try {
    if (app && app.setToken) app.setToken("");
    else {
      wx.removeStorageSync("token");
      if (app) app.globalData.token = "";
    }
  } catch (e) {}
  wx.reLaunch({ url: "/pages/entry/index" });
}

/**
 * @param {string} path
 * @param {string} method
 * @param {object} data
 * @param {{ skipAuth?: boolean, showErr?: boolean }} options
 */
function request(path, method, data, options) {
  options = options || {};
  const app = _getApp();
  const base =
    (app && app.globalData && app.globalData.baseUrl) || "";
  const timeoutMs =
    (app && app.globalData && app.globalData.requestTimeout) || 60000;
  const token = options.skipAuth
    ? ""
    : (app && app.globalData && app.globalData.token) ||
      wx.getStorageSync("token") ||
      "";
  const url = (String(base).replace(/\/$/, "") || "") + path;
  return new Promise((resolve, reject) => {
    if (!/^https?:\/\//i.test(url)) {
      reject(
        new Error(
          "请配置 baseUrl：app.js 中 globalData.baseUrl，如 https://htma.greatagain.com.cn 或本机调试用你的局域网/隧道 HTTPS"
        )
      );
      return;
    }
    wx.request({
      url,
      method: method || "GET",
      data: data || {},
      timeout: timeoutMs,
      dataType: "json",
      header: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      success(res) {
        const sc = res.statusCode || 0;
        const body = res.data;
        if (sc === 401) {
          if (options.showErr === false) {
            clearAuth();
            const e = new Error("LOGIN");
            e.silent = true;
            reject(e);
            return;
          }
          clearAuth();
          const e1 = new Error(
            errText(body && (body.message || body.msg), "请先登录")
          );
          e1.silent = true;
          reject(e1);
          return;
        }
        if (sc === 404) {
          const e2 = new Error(
            "接口 404：多为服务端未部署含 /api/mobile 的看板，请在服务器上更新代码并重启 gunicorn/uwsgi/进程"
          );
          e2.silent = false;
          reject(e2);
          return;
        }
        if (sc >= 400) {
          const raw =
            (body && (body.message || body.msg || body.error)) || "HTTP " + sc;
          reject(new Error(errText(raw, "HTTP " + sc)));
          return;
        }
        if (body && body.code !== undefined) {
          if (Number(body.code) !== 0) {
            reject(
              new Error(
                errText(
                  body.msg != null && body.msg !== ""
                    ? body.msg
                    : body.message,
                  "业务错误 " + body.code
                )
              )
            );
            return;
          }
          resolve({ ...body, data: body.data });
          return;
        }
        if (body && body.success === false) {
          reject(
            new Error(
              errText(
                body.message != null && body.message !== ""
                  ? body.message
                  : body.msg,
                "失败"
              )
            )
          );
          return;
        }
        resolve(body);
      },
      fail(err) {
        const raw = err && (err.errMsg != null ? err.errMsg : err.message);
        let msg = errText(raw, "网络请求失败");
        if (/timeout|timed out/i.test(String(msg))) {
          msg =
            "请求超时。请检查：① 本机/服务器已启动 ② 域名在工具里已勾选不校验 或 已配合法域名 ③ baseUrl 可改为当前可访问的 HTTPS";
        }
        reject(new Error(msg));
      },
    });
  });
}

module.exports = { request, clearAuth };
