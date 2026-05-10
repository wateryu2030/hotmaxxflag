Component({
  data: {
    selected: 0,
    list: [
      { pagePath: "/pages/home/index", text: "总览", key: "home" },
      { pagePath: "/pages/analysis/index", text: "品类", key: "cat" },
      { pagePath: "/pages/insight/index", text: "趋势", key: "trend" },
      { pagePath: "/pages/ops/index", text: "经营", key: "ops" },
      { pagePath: "/pages/profile/index", text: "我的", key: "me" },
    ],
  },
  methods: {
    switchTab(e) {
      const i = Number(e.currentTarget.dataset.i);
      const url = this.data.list[i].pagePath;
      wx.switchTab({ url });
    },
  },
});
