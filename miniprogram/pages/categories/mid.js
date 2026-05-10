Page({
  onLoad(q) {
    const code =
      (q && q.large_code) || (q && q.category_large_code) || (q && q.categoryLargeCode) || "";
    if (!code) return;
    let name = "";
    const raw = (q && q.large_name) || (q && q.category_large) || "";
    try {
      name = raw ? decodeURIComponent(raw) : "";
    } catch (e) {
      name = raw || "";
    }
    let u =
      "/pages/categories/index?bootstrap=1&large_code=" + encodeURIComponent(code);
    if (name) u += "&large_name=" + encodeURIComponent(name);
    wx.redirectTo({ url: u });
  },
});
