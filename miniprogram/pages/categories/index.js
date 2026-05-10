const { request } = require("../../utils/request");
const { requireToken } = require("../../utils/auth");
const {
  bgBarWidthPct,
  childLevelForPath,
  isSkuListLevel,
  segmentFromRow,
  buildBreadcrumbCrumbs,
  pathAfterBreadcrumbTap,
  LEVEL_GRAND,
} = require("../../utils/analyticsUI");

function ymd(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return y + "-" + m + "-" + day;
}

function decorateRows(items) {
  const arr = [...(items || [])].sort(
    (a, b) => (Number(b.sale_amount) || 0) - (Number(a.sale_amount) || 0)
  );
  const maxS = arr.length ? Math.max(...arr.map((x) => Number(x.sale_amount) || 0), 0.01) : 1;
  return arr.map((it, idx) => ({
    ...it,
    _rank: idx + 1,
    _bgPct: bgBarWidthPct(((Number(it.sale_amount) || 0) / maxS) * 100),
    _wk:
      String(it.sku_code || "") +
      "|" +
      String(it.category_mid_code || "") +
      "|" +
      String(it.category_large_code || "") +
      "|" +
      String(it.category_small_code || it.category_small || "") +
      "|" +
      idx,
  }));
}

Page({
  data: {
    drillPath: [],
    breadcrumb: [],
    items: [],
    loading: true,
    drillLoading: false,
    listEmpty: false,
    emptyHint: "",
    highlight: "",
    listTitle: "品类概览",
  },
  onLoad(q) {
    const hi = (q && q.highlight_large) || "";
    let seed = [];
    if (q && (q.bootstrap || q.large_code)) {
      const lc = (q.large_code || q.category_large_code || "").trim();
      if (lc) {
        let ln = "";
        const raw = (q.large_name || q.category_large || "").trim();
        try {
          ln = raw ? decodeURIComponent(raw) : "";
        } catch (e) {
          ln = raw;
        }
        seed = [{ level: LEVEL_GRAND, code: lc, name: ln || lc }];
      }
    }
    this.setData({ highlight: hi, drillPath: seed });
  },
  onShow() {
    if (!requireToken()) return;
    this.loadList();
  },
  onPullDownRefresh() {
    this.loadList().finally(() => wx.stopPullDownRefresh());
  },
  onBreadcrumbTap(e) {
    const tapIndex = Number(e.currentTarget.dataset.i);
    const next = pathAfterBreadcrumbTap(this.data.drillPath, tapIndex);
    this.setData({ drillPath: next }, () => this.loadList());
  },
  onRowTap(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    const row = (this.data.items || [])[idx];
    if (!row) return;
    const path = this.data.drillPath || [];
    if (isSkuListLevel(path)) {
      const title = row.name || row.sku_code || "SKU";
      const lines = [
        "SKU：" + (row.sku_code || "—"),
        "销额：" + (row.sale_amount != null ? row.sale_amount : "—"),
        "毛利：" + (row.gross_profit != null ? row.gross_profit : "—"),
        "毛利率：" + (row.margin_pct != null ? row.margin_pct + "%" : "—"),
        "销量：" + (row.sale_qty != null ? row.sale_qty : "—"),
      ];
      wx.showModal({
        title,
        content: lines.join("\n"),
        showCancel: false,
      });
      return;
    }
    const child = childLevelForPath(path);
    const seg = segmentFromRow(child, row);
    if (!seg.code && child !== LEVEL_GRAND) {
      wx.showToast({ title: "缺少下级编码", icon: "none" });
      return;
    }
    if (!seg.code) {
      wx.showToast({ title: "无法下钻", icon: "none" });
      return;
    }
    this.setData({ drillPath: path.concat([seg]) }, () => this.loadList());
  },
  loadList() {
    const path = this.data.drillPath || [];
    const e = new Date();
    const s = new Date();
    s.setDate(s.getDate() - 29);
    const dq = "start_date=" + ymd(s) + "&end_date=" + ymd(e);
    this.setData({
      drillLoading: true,
      listEmpty: false,
      emptyHint: "",
      breadcrumb: buildBreadcrumbCrumbs(path),
    });
    const n = path.length;
    let p;
    if (n === 0) {
      this.setData({ listTitle: "大类" });
      p = request("/api/mobile/category_large?" + dq, "GET", {});
    } else if (n === 1) {
      this.setData({ listTitle: "中类" });
      p = request(
        "/api/mobile/category_mid?category_large_code=" +
          encodeURIComponent(path[0].code) +
          "&" +
          dq,
        "GET",
        {}
      );
    } else if (n === 2) {
      this.setData({ listTitle: "小类" });
      p = request(
        "/api/mobile/category_small?category_large_code=" +
          encodeURIComponent(path[0].code) +
          "&category_mid_code=" +
          encodeURIComponent(path[1].code) +
          "&" +
          dq,
        "GET",
        {}
      );
    } else if (n === 3) {
      this.setData({ listTitle: "SKU" });
      p = request(
        "/api/mobile/category_skus?category_large_code=" +
          encodeURIComponent(path[0].code) +
          "&category_mid_code=" +
          encodeURIComponent(path[1].code) +
          "&category_small_code=" +
          encodeURIComponent(path[2].code) +
          "&" +
          dq,
        "GET",
        {}
      );
    } else {
      this.setData({
        items: [],
        loading: false,
        drillLoading: false,
        listEmpty: true,
        emptyHint: "层级过深",
      });
      return Promise.resolve();
    }
    return p
      .then((j) => {
        const d = j.data || {};
        const raw = d.items || [];
        const decorated = decorateRows(raw);
        const note = (d.note || "").trim();
        this.setData({
          items: decorated,
          loading: false,
          drillLoading: false,
          listEmpty: !decorated.length,
          emptyHint: note || (n === 2 ? "暂无小类数据（可能销售表无小类字段）" : "暂无下级分类"),
        });
      })
      .catch((err) => {
        this.setData({
          loading: false,
          drillLoading: false,
          items: [],
          listEmpty: true,
          emptyHint: (err && err.message) || "加载失败",
        });
        if (err && err.silent) return;
        wx.showToast({
          title: (err && err.message) || "失败",
          icon: "none",
          duration: 3500,
        });
      });
  },
});
