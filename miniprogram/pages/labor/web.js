Page({
  data: { src: "" },
  onLoad(q) {
    const u = (q && q.u) ? decodeURIComponent(q.u) : "";
    this.setData({ src: u });
  },
});
