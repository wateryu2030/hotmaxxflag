/** 未登录则进登录页，返回 false */
function requireToken() {
  if (!wx.getStorageSync("token")) {
    wx.reLaunch({ url: "/pages/entry/index" });
    return false;
  }
  return true;
}

module.exports = { requireToken };
