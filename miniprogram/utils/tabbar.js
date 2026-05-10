/** 与 app.json tabBar.list 顺序一致 */
const ROUTE_TAB_INDEX = {
  "pages/home/index": 0,
  "pages/analysis/index": 1,
  "pages/insight/index": 2,
  "pages/ops/index": 3,
  "pages/profile/index": 4,
};

function syncTabBar() {
  try {
    const pages = getCurrentPages();
    const cur = pages[pages.length - 1];
    if (!cur || !cur.route) return;
    const idx = ROUTE_TAB_INDEX[cur.route];
    if (idx === undefined) return;
    if (typeof cur.getTabBar === "function") {
      const bar = cur.getTabBar();
      if (bar) bar.setData({ selected: idx });
    }
  } catch (_) {}
}

module.exports = { syncTabBar };
