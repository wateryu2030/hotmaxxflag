/**
 * 全站数据分析：行背景条宽度（0–100 量纲）
 */
function bgBarWidthPct(pct0to100) {
  const pct = Number(pct0to100) || 0;
  return Math.min(100, Math.max(4, pct * 0.92 + 4));
}

/** 层级常量（与后端钻取顺序一致） */
const LEVEL_GRAND = "grand";
const LEVEL_MIDDLE = "middle";
const LEVEL_SMALL = "small";
const LEVEL_SKU = "sku";
/** 规格明细：当前由 SKU 行 Modal 承担；若后续有规格维度接口，在品类页 `loadList` 增加 path.length===4 分支即可 */
const LEVEL_SPEC = "spec";

/** 面包屑根文案 */
const BREADCRUMB_ROOT_LABEL = "全部";

/**
 * 根据 path 长度得到「当前列表」所展示的子级类型（path 为已选祖先链）
 * [] -> 大类列表；[L] -> 中类；[L,M] -> 小类；[L,M,S] -> SKU
 */
function childLevelForPath(path) {
  const n = (path || []).length;
  if (n <= 0) return LEVEL_GRAND;
  if (n === 1) return LEVEL_MIDDLE;
  if (n === 2) return LEVEL_SMALL;
  if (n === 3) return LEVEL_SKU;
  return LEVEL_SPEC;
}

/** 是否已到达 SKU 列表（再点行应弹详情而非下钻） */
function isSkuListLevel(path) {
  return childLevelForPath(path) === LEVEL_SKU;
}

/**
 * 从当前行构造 path 新尾段（不含 SKU 行；SKU 在页内单独处理）
 * @param {string} childLevel
 * @param {object} row API 行
 */
function segmentFromRow(childLevel, row) {
  if (childLevel === LEVEL_GRAND) {
    return {
      level: LEVEL_GRAND,
      code: row.category_large_code || "",
      name: row.category_large || row.category_large_code || "—",
    };
  }
  if (childLevel === LEVEL_MIDDLE) {
    return {
      level: LEVEL_MIDDLE,
      code: row.category_mid_code || "",
      name: row.category_mid || row.category_mid_code || "—",
    };
  }
  if (childLevel === LEVEL_SMALL) {
    return {
      level: LEVEL_SMALL,
      code: row.category_small_code || row.category_small || "",
      name: row.category_small || row.category_small_code || "—",
    };
  }
  return { level: LEVEL_SKU, code: "", name: "" };
}

/**
 * 生成面包屑片段（用于 WXML）：{ label, tapIndex }
 * tapIndex 0 表示回根；k>0 表示截断到 path.slice(0, k)
 */
function buildBreadcrumbCrumbs(path) {
  const crumbs = [{ label: BREADCRUMB_ROOT_LABEL, tapIndex: 0 }];
  (path || []).forEach((seg, i) => {
    crumbs.push({
      label: seg.name || seg.code || "—",
      tapIndex: i + 1,
    });
  });
  return crumbs;
}

/** 截断 path 到指定面包屑 tapIndex（与 buildBreadcrumbCrumbs 一致） */
function pathAfterBreadcrumbTap(path, tapIndex) {
  const p = path || [];
  const k = Number(tapIndex) || 0;
  if (k <= 0) return [];
  return p.slice(0, k);
}

/**
 * 人力四象限 / 经营类目行：销售侧聚合键存于 `category_large_code`（可能为正式编码，也可能与展示名相同）；
 * 展示名在 `category` 或 `category_large`。
 * @param {object} row
 * @returns {{ large_code: string, large_name: string } | null}
 */
function resolveLargeCategoryDrillKeys(row) {
  if (!row || typeof row !== "object") return null;
  const codeRaw = String(
    row.category_large_code || row.large_code || row.code || ""
  ).trim();
  const nameRaw = String(
    row.category_large || row.category || row.name || ""
  ).trim();
  const large_code = codeRaw || nameRaw;
  const large_name = nameRaw || codeRaw;
  if (!large_code) return null;
  return { large_code, large_name: large_name || large_code };
}

/** 打开「品类概览」统一下钻并定位到大类（中类列表） */
function buildCategoriesDrillUrlFromLargeRow(row) {
  const r = resolveLargeCategoryDrillKeys(row);
  if (!r) return "";
  return (
    "/pages/categories/index?bootstrap=1&large_code=" +
    encodeURIComponent(r.large_code) +
    "&large_name=" +
    encodeURIComponent(r.large_name)
  );
}

module.exports = {
  bgBarWidthPct,
  LEVEL_GRAND,
  LEVEL_MIDDLE,
  LEVEL_SMALL,
  LEVEL_SKU,
  LEVEL_SPEC,
  BREADCRUMB_ROOT_LABEL,
  childLevelForPath,
  isSkuListLevel,
  segmentFromRow,
  buildBreadcrumbCrumbs,
  pathAfterBreadcrumbTap,
  resolveLargeCategoryDrillKeys,
  buildCategoriesDrillUrlFromLargeRow,
};
