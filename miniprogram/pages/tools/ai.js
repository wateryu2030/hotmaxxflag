const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");

Page({
  data: { text: "" },
  onShow() {
    if (!requireToken()) return;
    this.refresh();
  },
  refresh() {
    request("/api/mobile/ai_advice", "GET", {})
      .then((j) => this.setData({ text: (j.data && j.data.text) || "" }))
      .catch(() => {});
  },
});
