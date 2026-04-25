# -*- coding: utf-8 -*-
"""供销社「红背篓」渠道选品：按品类筛选 + 批次效期 + 导出数据行构造。"""
from datetime import date, datetime
from decimal import Decimal


def _d(v, default=None):
    if v is None:
        return default
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _expiry_tag(earliest_expiry):
    """earliest_expiry: date or None"""
    if earliest_expiry is None:
        return "未知"
    if isinstance(earliest_expiry, datetime):
        earliest_expiry = earliest_expiry.date()
    today = date.today()
    if earliest_expiry < today:
        return "已过期"
    days = (earliest_expiry - today).days
    if days <= 30:
        return "临期(≤30天)"
    if days < 90:
        return "不足3个月"
    return "正常(≥3个月)"


def _ref_price(row):
    for k in ("sale_price", "avg_price", "unit_price", "master_retail_price", "master_delivery_price"):
        v = row.get(k)
        if v is not None and _d(v, 0) > 0:
            return _d(v, 0)
    return None


def _price_advantage_pct(ref_price, rival_min):
    if ref_price is None or rival_min is None:
        return None
    r = _d(rival_min, 0)
    if r <= 0:
        return None
    return round((r - ref_price) / r * 100, 2)


# 加价率下限：10%（业务规则）；留空未填时默认 15%
MARKUP_RATIO_MIN = 0.1
MARKUP_RATIO_DEFAULT = 0.15


def parse_markup_ratio(raw):
    """
    加价率 r：供货价 = 我方参考价 × (1 + r)。
    - 填小数：0.15 表示加价 15%；
    - 填大于 1 的数字：15 视为 15%（即 r=0.15）。
    - **不得低于 10%**（即 r < 0.1 不允许）；未填写时默认按 **15%**。
    无效输入抛出 ValueError。
    """
    if raw is None or not str(raw).strip():
        return MARKUP_RATIO_DEFAULT
    s = str(raw).strip().replace("%", "")
    try:
        x = float(s)
    except (TypeError, ValueError):
        raise ValueError("加价率须为数字，例如 0.1 表示 10%，或 15 表示 15%。")
    if x > 1:
        result = x / 100.0
    else:
        result = x
    if result < MARKUP_RATIO_MIN:
        raise ValueError("加价率不得低于 10%%，请至少填写 0.1、10（表示 10%%）或更高。")
    return result


def supply_price(ref_price, markup_ratio):
    """ref_price 为 float 或 None；markup_ratio 为小数加价率。"""
    if ref_price is None:
        return None
    r = float(markup_ratio or 0)
    return round(float(ref_price) * (1.0 + r), 2)


# 对外导出（CSV/PDF）仅含下列列；数据库与查询仍保留全字段
EXPORT_SIMPLE_COLUMNS = [
    ("product_name", "品名"),
    ("spec", "规格"),
    ("unit", "单位"),
    ("brand_name", "品牌"),
    ("category_mid", "中类"),
    ("category_small", "小类"),
    ("stock_qty", "库存数量"),
    ("sale_qty_30d", "近30天销量"),
    ("supply_price", "供货价"),
]


def rows_to_simple_export(rows, markup_ratio_raw):
    """
    rows: 已由 enrich_catalog_row 处理过的 dict 列表。
    返回 (简化行列表, 生效加价率)；parse 失败抛出 ValueError。
    """
    r = parse_markup_ratio(markup_ratio_raw)
    out = []
    for row in rows:
        ref = row.get("ref_price")
        sup = supply_price(ref, r)
        out.append(
            {
                "sku_code": row.get("sku_code") or "",
                "category_large": row.get("category_large") or "",
                "category_large_code": row.get("category_large_code") or "",
                "product_name": row.get("product_name") or "",
                "spec": row.get("spec") or "",
                "unit": row.get("unit") or "",
                "brand_name": row.get("brand_name") or "",
                "category_mid": row.get("category_mid") or "",
                "category_small": row.get("category_small") or "",
                "stock_qty": row.get("stock_qty"),
                "sale_qty_30d": row.get("sale_qty_30d"),
                "supply_price": sup,
            }
        )
    return out, r


def enrich_catalog_row(row, share_ratio=0.3):
    """row: dict from SQL; adds expiry_tag, ref_price, price_advantage_pct, share_qty_suggested"""
    earliest = row.get("earliest_expiry")
    if earliest and hasattr(earliest, "date"):
        earliest = earliest.date() if hasattr(earliest, "date") else earliest
    row["expiry_tag"] = _expiry_tag(earliest)
    ref = _ref_price(row)
    row["ref_price"] = ref
    rival = row.get("min_rival_price")
    row["price_advantage_pct"] = _price_advantage_pct(ref, rival)
    sq = _d(row.get("stock_qty"), 0) or 0
    ratio = max(0.0, min(1.0, float(share_ratio or 0.3)))
    row["share_qty_suggested"] = int(sq * ratio) if sq > 0 else 0
    return row


def build_catalog_sql(store_id, category_large_code, category_mid_code, category_small_code, min_stock, exclude_expired, has_price_compare, has_batch_table):
    """Returns (sql, params_list). 无比价表/批次表时用 CAST NULL，避免无效 JOIN。"""
    conds = ["ls.stock_qty > %s"]
    params = [min_stock]

    def _add_cat(field_code, field_name, val):
        if not val:
            return
        conds.append(
            "(COALESCE(TRIM(ls.{0}), '') = %s OR COALESCE(TRIM(ls.{1}), '') = %s)".format(field_code, field_name)
        )
        params.extend([val, val])

    _add_cat("category_large_code", "category_large", category_large_code)
    _add_cat("category_mid_code", "category_mid", category_mid_code)
    _add_cat("category_small_code", "category_small", category_small_code)

    if has_batch_table and exclude_expired:
        conds.append("(eb.earliest_expiry IS NULL OR eb.earliest_expiry >= CURDATE())")

    if has_batch_table:
        batch_cols = "eb.earliest_expiry,\n      eb.batch_qty_sum,"
        join_batch = """
    LEFT JOIN (
      SELECT sku_code, MIN(expiry_date) AS earliest_expiry, SUM(qty) AS batch_qty_sum
      FROM t_htma_sku_batch
      WHERE store_id = %s
      GROUP BY sku_code
    ) eb ON eb.sku_code = ls.sku_code
        """
    else:
        batch_cols = "CAST(NULL AS DATE) AS earliest_expiry,\n      CAST(NULL AS DECIMAL(14,4)) AS batch_qty_sum,"
        join_batch = ""

    if has_price_compare:
        rival_col = "rpc.min_rival_price"
        join_price = """
    LEFT JOIN (
      SELECT sku_code, MIN(price) AS min_rival_price
      FROM t_price_compare
      GROUP BY sku_code
    ) rpc ON rpc.sku_code = ls.sku_code
        """
    else:
        rival_col = "CAST(NULL AS DECIMAL(12,2)) AS min_rival_price"
        join_price = ""

    sql = """
    SELECT
      ls.sku_code,
      ls.barcode,
      ls.product_name,
      ls.spec,
      ls.unit,
      ls.brand_name,
      ls.category_large_code,
      ls.category_large,
      ls.category_mid_code,
      ls.category_mid,
      ls.category_small_code,
      ls.category_small,
      ls.stock_qty,
      ls.stock_amount,
      ls.sale_price,
      ls.avg_price,
      p.unit_price AS unit_price,
      p.sale_qty AS sale_qty_30d,
      p.sale_amount AS sale_amount_30d,
      pm.shelf_life AS shelf_life_days,
      pm.retail_price AS master_retail_price,
      pm.delivery_price AS master_delivery_price,
      """ + batch_cols + """
      """ + rival_col + """
    FROM t_htma_stock ls
    INNER JOIN (
      SELECT sku_code, MAX(data_date) AS md
      FROM t_htma_stock
      WHERE store_id = %s
      GROUP BY sku_code
    ) z ON z.sku_code = ls.sku_code AND z.md = ls.data_date AND ls.store_id = %s
    LEFT JOIN t_htma_products p ON p.store_id = ls.store_id AND p.sku_code = ls.sku_code
    LEFT JOIN t_htma_product_master pm ON pm.sku_code = ls.sku_code AND pm.store_id = %s
    """ + join_batch + join_price + """
    WHERE """ + " AND ".join(conds) + """
    ORDER BY ls.category_large_code, ls.category_mid_code, ls.category_small_code, ls.sku_code
    """

    full_params = [store_id, store_id, store_id]
    if has_batch_table:
        full_params.append(store_id)
    full_params.extend(params)

    return sql, full_params


def table_exists(cur, table_name):
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def query_catalog_rows(conn, store_id, category_large_code="", category_mid_code="", category_small_code="", min_stock=0.01, share_ratio=0.3, exclude_expired=True):
    with conn.cursor() as cur:
        has_pc = table_exists(cur, "t_price_compare")
        has_batch = table_exists(cur, "t_htma_sku_batch")
        sql, params = build_catalog_sql(
            store_id,
            category_large_code.strip() or None,
            category_mid_code.strip() or None,
            category_small_code.strip() or None,
            min_stock,
            exclude_expired,
            has_pc,
            has_batch,
        )
        cur.execute(sql, params)
        rows = cur.fetchall()
    out = []
    for r in rows:
        row = dict(r)
        enrich_catalog_row(row, share_ratio=share_ratio)
        out.append(row)
    return out


def build_selection_logic_meta(
    conn,
    store_id,
    category_large_code="",
    category_mid_code="",
    category_small_code="",
    min_stock=0.01,
    share_ratio=0.3,
    exclude_expired=True,
):
    """
    与 query_catalog_rows / build_catalog_sql 一致的「选品逻辑」说明，供前端展示。
    不拉全表，仅探测表是否存在 + 最新库存日期。
    """
    with conn.cursor() as cur:
        has_pc = table_exists(cur, "t_price_compare")
        has_batch = table_exists(cur, "t_htma_sku_batch")
        cur.execute("SELECT MAX(data_date) AS md FROM t_htma_stock WHERE store_id = %s", (store_id,))
        rmd = cur.fetchone() or {}
        md = rmd.get("md")
        latest = md.isoformat() if md and hasattr(md, "isoformat") else (str(md) if md else None)

    ratio_clamped = max(0.0, min(1.0, float(share_ratio or 0.3)))

    rules = [
        {
            "id": "stock_snapshot",
            "title": "库存快照",
            "detail": "每个 SKU 取「本门店」在库存表 t_htma_stock 中 **data_date 最大** 的一行作为当前库存；门店 ID 与看板一致。",
        },
        {
            "id": "stock_floor",
            "title": "库存门槛",
            "detail": "仅包含 **库存数量 > min_stock** 的 SKU（默认 min_stock=0.01，可通过接口参数调整）。",
        },
        {
            "id": "category_filter",
            "title": "品类筛选",
            "detail": "大类 / 中类 / 小类可选；每级若填写，则要求库存行上 **编码或名称** 与所选值一致（OR 匹配，兼容仅有编码或仅有名称）。未选的级别不参与过滤。",
        },
        {
            "id": "batch_expiry",
            "title": "批次与最早到期",
            "detail": "若已建表 t_htma_sku_batch：按 SKU 汇总 **MIN(expiry_date)** 为最早到期日，**SUM(qty)** 为批次表合计件数。若无批次记录，最早到期为空，效期标签为「未知」。",
        },
        {
            "id": "exclude_expired_rule",
            "title": "排除已过期",
            "detail": "仅在 **已存在批次表** 且您勾选「排除已过期」时生效：去掉「最早到期日 < 今天」的 SKU。**无批次数据的 SKU**（最早到期为空）**仍会保留**，避免误伤。",
            "active": bool(has_batch and exclude_expired),
        },
        {
            "id": "expiry_tag_rule",
            "title": "效期标签（行上展示）",
            "detail": "无最早到期 → **未知**；已过期 → **已过期**；距今天数 ≤30 → **临期(≤30天)**；<90 天 → **不足3个月**；≥90 天 → **正常(≥3个月)**。",
        },
        {
            "id": "share_cap",
            "title": "共享额度建议",
            "detail": "对每条 SKU：**⌊库存数量 × 共享比例⌋**，比例限制在 0～1（当前 {:.0%}）。仅为建议值，不锁库、不扣减线下库存。".format(ratio_clamped),
        },
        {
            "id": "ref_price",
            "title": "我方参考价",
            "detail": "按顺序取第一个大于 0 的：**门店售价** → **库存均价** → **商品表单价(t_htma_products)** → **档案零售价** → **档案配送价(t_htma_product_master)**。",
        },
        {
            "id": "price_advantage",
            "title": "价格优势%",
            "detail": "若存在表 t_price_compare 且该 SKU 有竞品最低价：**(竞品最低价 − 我方参考价) / 竞品最低价 × 100**。缺表或缺价则为空。",
            "active": bool(has_pc),
        },
        {
            "id": "joins",
            "title": "关联数据",
            "detail": "LEFT JOIN t_htma_products：近 30 天销量/销售额等同步字段；LEFT JOIN t_htma_product_master：保质期天数、档案价（**同 store_id**）。",
        },
        {
            "id": "export_supply",
            "title": "导出供货价与简化列",
            "detail": "CSV/PDF 仅含：**序号**、品名、规格、单位、品牌、中类、小类、库存数量、近30天销量、**供货价**（不含大类列）。供货价 = 我方参考价 × (1 + 加价率)。**加价率不得低于 10%%**（至少填 0.1 或 10）；未填默认 **15%%**。可填 0.15、15 等。库内仍保留全量字段备查。",
        },
    ]

    column_glossary = [
        {"field": "sku_code", "label": "货号", "hint": "库存行主键之一"},
        {"field": "stock_qty", "label": "库存数量", "hint": "最新快照日期的在库数量"},
        {"field": "earliest_expiry", "label": "最早到期日", "hint": "来自批次表 MIN(expiry_date)；无批次为空"},
        {"field": "batch_qty_sum", "label": "批次表合计件数", "hint": "批次表 SUM(qty)，可与实物核对"},
        {"field": "expiry_tag", "label": "效期标签", "hint": "按最早到期日相对今天计算，见上方规则"},
        {"field": "share_qty_suggested", "label": "共享额度建议", "hint": "⌊库存×共享比例⌋"},
        {"field": "ref_price", "label": "我方参考价", "hint": "多字段优先级取价，见规则"},
        {"field": "min_rival_price", "label": "竞品最低价", "hint": "t_price_compare 全平台 MIN(price)"},
        {"field": "price_advantage_pct", "label": "价格优势%", "hint": "相对竞品低价，价低则数值偏大"},
        {"field": "sale_qty_30d", "label": "近30天销量", "hint": "来自 t_htma_products 同步字段"},
        {"field": "shelf_life_days", "label": "档案保质期天", "hint": "商品档案字段，非剩余保质期"},
        {"field": "supply_price", "label": "供货价", "hint": "导出用：参考价×(1+加价率)；无参考价则为空"},
    ]

    applied_filters = {
        "store_id": store_id,
        "category_large_code": category_large_code or None,
        "category_mid_code": category_mid_code or None,
        "category_small_code": category_small_code or None,
        "min_stock": min_stock,
        "share_ratio": ratio_clamped,
        "exclude_expired": bool(exclude_expired),
    }

    return {
        "store_id": store_id,
        "latest_stock_date": latest,
        "has_batch_table": has_batch,
        "has_price_compare_table": has_pc,
        "rules": rules,
        "column_glossary": column_glossary,
        "applied_filters": applied_filters,
        "markup_ratio_default": MARKUP_RATIO_DEFAULT,
        "markup_ratio_min": MARKUP_RATIO_MIN,
        "export_note": "导出 CSV/PDF 仅含：序号、品名、规格、单位、品牌、中类、小类、库存数量、近30天销量、供货价（供货价=我方参考价×(1+加价率)；未填加价率按 15%%）。完整字段仍在库内可查。",
    }


EXPORT_COLUMNS = [
    ("sku_code", "货号"),
    ("barcode", "条码"),
    ("product_name", "品名"),
    ("spec", "规格"),
    ("unit", "单位"),
    ("brand_name", "品牌"),
    ("category_large_code", "大类编码"),
    ("category_large", "大类"),
    ("category_mid_code", "中类编码"),
    ("category_mid", "中类"),
    ("category_small_code", "小类编码"),
    ("category_small", "小类"),
    ("stock_qty", "库存数量"),
    ("stock_amount", "库存金额"),
    ("sale_price", "门店售价"),
    ("avg_price", "库存均价"),
    ("unit_price", "商品表单价"),
    ("sale_qty_30d", "近30天销量"),
    ("sale_amount_30d", "近30天销售额"),
    ("shelf_life_days", "档案保质期天"),
    ("earliest_expiry", "最早到期日"),
    ("batch_qty_sum", "批次表合计件数"),
    ("expiry_tag", "效期标签"),
    ("min_rival_price", "竞品最低价"),
    ("ref_price", "我方参考价"),
    ("price_advantage_pct", "价格优势%"),
    ("share_qty_suggested", "共享额度建议"),
]
