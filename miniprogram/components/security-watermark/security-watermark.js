const { buildSecurityWatermarkText } = require("../../utils/watermarkText");

Component({
  data: {
    text: "",
    rows: [
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    ],
  },
  lifetimes: {
    attached() {
      this._sync();
    },
  },
  pageLifetimes: {
    show() {
      this._sync();
    },
  },
  methods: {
    _sync() {
      const text = buildSecurityWatermarkText();
      if (text === this.data.text) return;
      this.setData({ text });
    },
  },
});
