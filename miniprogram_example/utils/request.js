function _getApp() {
  try {
    return getApp();
  } catch (e) {
    return null;
  }
}

/**
 * @param {string} path
 * @param {string} method
 * @param {object} data
 * @param {{ skipAuth?: boolean }} options
 */
function request(path, method, data, options) {
  options = options || {};
  const a = _getApp();
  const base = (a && a.globalData && a.globalData.baseUrl) || "";
  const token =
    options.skipAuth || !a || !a.globalData
      ? ""
      : a.globalData.token || "";
  const url = (base.replace(/\/$/, "") || "") + path;
  return new Promise((resolve, reject) => {
    if (!url.startsWith("http")) {
      reject(new Error("未配置 baseUrl（utils/request 需在 App 已注册后取 getApp）"));
      return;
    }
    wx.request({
      url,
      method: method || "GET",
      data: data || {},
      timeout: 60000,
      dataType: "json",
      header: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      success(res) {
        const sc = res.statusCode || 0;
        const body = res.data;
        if (sc === 401) {
          try {
            const g = _getApp();
            g && g.setToken && g.setToken("");
          } catch (e) {}
          reject(new Error((body && body.message) || "401 请先登录"));
          return;
        }
        if (sc >= 400) {
          const msg =
            (body && (body.message || body.errmsg || body.error)) ||
            "HTTP " + sc;
          reject(new Error(typeof msg === "string" ? msg : JSON.stringify(msg)));
          return;
        }
        resolve(body);
      },
      fail(err) {
        let msg = (err && (err.errMsg || err.message)) || "网络请求失败";
        if (/timeout|timed out/i.test(String(msg))) {
          msg += "（可检查 baseUrl、本机服务与合法域名/不校验）";
        }
        reject(new Error(msg));
      },
    });
  });
}

module.exports = { request };
