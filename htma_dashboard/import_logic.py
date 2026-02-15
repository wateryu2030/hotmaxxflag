# -*- coding: utf-8 -*-
"""Excel 导入逻辑：完整导入所有合规数据到 MySQL"""
import os
import re
from datetime import datetime

import pandas as pd
import pymysql

STORE_ID = "沈阳超级仓"


def _safe_decimal(v, default=0):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_str(v, max_len=128):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()[:max_len] or None
    return s if s else None


def _parse_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    # Excel 序列日期 (1900-01-01 起算)
    if isinstance(v, (int, float)) and not pd.isna(v) and v > 1000:
        try:
            from datetime import timedelta
            d = datetime(1899, 12, 30) + timedelta(days=int(float(v)))
            return d.date().isoformat()
        except Exception:
            pass
    s = str(v).strip()
    # YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # YYYYMMDD
    m = re.search(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # YYYY年M月D日
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _extract_report_date(df_or_path):
    """从表头前几行或文件名提取报告日期。df_or_path 可为 DataFrame 或文件路径"""
    if isinstance(df_or_path, str):
        m = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", df_or_path)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return None
    df = df_or_path
    for r in range(min(15, df.shape[0])):
        row = df.iloc[r]
        for c in range(min(20, len(row))):
            v = row.iloc[c]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            s = str(v).strip()
            m = re.search(r"日期\s*[：:]\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _row_val(row, idx, default=None, as_decimal=False):
    if idx >= len(row):
        return _safe_decimal(default, 0) if as_decimal else default
    v = row.iloc[idx]
    if as_decimal:
        return _safe_decimal(v, default or 0)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return default
    # 货号等：数字型如 12345.0 转为 "12345"
    if isinstance(v, (int, float)) and float(v) == int(float(v)):
        return str(int(float(v)))
    return s[:128] if s else default


def _trim_leading_junk_rows(df, keywords=("货号", "销售金额", "商品编码", "销售日期", "销售数量", "商品名称", "订单日期", "实时库存", "库存", "大类名称", "类别名称", "求和项")):
    """删除前导无用行（标题、空行、合并表头占位行），保留含关键字的表头及之后数据"""
    if df.shape[0] == 0:
        return df
    df = df.dropna(how="all", axis=0).reset_index(drop=True)
    if df.shape[0] == 0:
        return df
    for r in range(min(25, df.shape[0])):
        row = df.iloc[r]
        for c in range(min(50, len(row))):
            v = str(row.iloc[c]).strip() if c < len(row) else ""
            if any(k in v for k in keywords):
                return df.iloc[r:].reset_index(drop=True)
    return df


def _header_row_forward_fill(row):
    """合并单元格：空单元格沿用前一格的值，便于表头检测"""
    out = []
    last = ""
    for c in range(len(row)):
        v = row.iloc[c]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            s = ""
        else:
            s = str(v).strip()
        if s and s.lower() != "nan":
            last = s
        out.append(last if last else "")
    return out


def _detect_header_row(df, keywords=("货号", "商品", "编码", "品号", "商品编码", "商品名称")):
    """返回数据起始行索引（表头下一行）"""
    if df.shape[0] == 0:
        return 0
    ncol = min(df.shape[1], 25)
    for r in range(min(15, df.shape[0])):
        row = df.iloc[r]
        # 合并单元格：空值沿用前一列
        filled = _header_row_forward_fill(row)
        for c in range(min(ncol, len(filled))):
            v = filled[c]
            if any(k in v for k in keywords):
                return r + 1  # 数据从下一行开始
    return 1


def _find_col_by_header(df, header_row_idx, keywords):
    """在 header 行中查找包含任一 keyword 的列索引，返回第一个匹配的列"""
    if header_row_idx >= df.shape[0]:
        return None
    row = df.iloc[header_row_idx]
    for c in range(min(len(row), 60)):
        v = str(row.iloc[c]).strip() if c < len(row) else ""
        if any(kw in v for kw in keywords):
            return c
    return None


def _detect_sale_cols(df, start_row, ncol, is_summary=False):
    """
    根据表头字面含义检测销售表列索引。严格按列名匹配，避免误绑。
    支持多种 Excel 格式：
    - 销售金额：仅匹配「销售金额」（不匹配「金额小计」「退货金额」等）
    - 成本：匹配「成本金额」「销售成本」「参考金额」「参考进价金额」（不匹配「成本单价」）
    - 日期：匹配「销售日期」「订单日期」「日期」
    - 货号：匹配「商品编码」「货号」「SKU」等
    """
    if is_summary:
        default = {"sku": 2, "date": 27, "amount": 31, "cost": 41, "qty": 30, "category": 9}
    else:
        default = {"sku": 2, "date": 26, "amount": 29, "cost": 38, "qty": 28, "category": 9}
    if start_row >= df.shape[0] or ncol < 3:
        return default
    # 优先从表头行(start_row-1)往前扫，再往后；合并单元格用 forward-fill 补全
    scan_order = [start_row - 1] + list(range(start_row - 2, -1, -1)) + list(range(start_row, min(start_row + 3, df.shape[0])))
    for h_idx in scan_order:
        if h_idx < 0 or h_idx >= df.shape[0]:
            continue
        row = df.iloc[h_idx]
        filled = _header_row_forward_fill(row)
        cols = {}
        for c in range(min(len(filled), 60)):
            v = filled[c]
            if not v:
                continue
            if any(k in v for k in ("货号", "商品编码", "SKU", "品号", "商品号")):
                cols["sku"] = c
            elif any(k in v for k in ("销售日期", "订单日期", "业务日期", "日期")):
                cols["date"] = c
            # 金额小计=销售-退货+赠送，为行净额，优先于销售金额（退货行销售金额常为0）
            elif "金额小计" in v and "占比" not in v:
                cols["amount"] = c
            # 严格按字面：仅「销售金额」（含「求和项:销售金额」等透视表列名）
            elif "销售金额" in v and "amount" not in cols:
                cols["amount"] = c
            # 按字面：成本总额列（成本金额/销售成本/参考金额/参考进价金额），排除「成本单价」
            elif ("成本金额" in v or "销售成本" in v or "参考金额" in v or "参考进价金额" in v) and "成本单价" not in v:
                cols["cost"] = c
            # 销售汇总表：进销差价金额 = 毛利，优先使用可避免计算误差
            elif "进销差价金额" in v:
                cols["margin"] = c
            elif "销售数量" in v or ("数量小计" in v and "占比" not in v):
                cols["qty"] = c
            elif any(k in v for k in ("类别名称", "品类")):
                cols["category"] = c
            elif "大类编码" in v or v.strip() == "大类编":
                cols["category_large_code"] = c
            elif "大类名称" in v:
                cols["category_large"] = c
            elif "中类编码" in v or v.strip() == "中类编":
                cols["category_mid_code"] = c
            elif "中类名称" in v:
                cols["category_mid"] = c
            elif "小类编码" in v or v.strip() == "小类编":
                cols["category_small_code"] = c
            elif "小类名称" in v:
                cols["category_small"] = c
            elif "经营方式" in v:
                cols["biz_mode"] = c
        if cols.get("sku") is not None and (cols.get("amount") is not None or cols.get("date") is not None):
            for k, v in default.items():
                if k not in cols:
                    cols[k] = v
            # 大类/中类/小类 编码与名称默认列索引（销售日报：大类10/11, 中类12/13, 小类14/15）
            if cols.get("category_large_code") is None and ncol > 10:
                cols["category_large_code"] = 10
            if cols.get("category_large") is None and ncol > 11:
                cols["category_large"] = 11
            if cols.get("category_mid_code") is None and ncol > 12:
                cols["category_mid_code"] = 12
            if cols.get("category_mid") is None and ncol > 13:
                cols["category_mid"] = 13
            if cols.get("category_small_code") is None and ncol > 14:
                cols["category_small_code"] = 14
            if cols.get("category_small") is None and ncol > 15:
                cols["category_small"] = 15
            if cols.get("biz_mode") is None and ncol > 16:
                cols["biz_mode"] = 16
            return cols
    return default


# 销售日报表 39列：完整列映射 (excel_col_idx, db_column, as_decimal)
# 仓库编码0,仓库名称1,货号2,品名3,国际条码4,简称5,单位6,规格7,类别编码8,类别名称9,大类10,大类名称11,中类12,中类名称13,小类14,小类名称15,
# 经营方式16,供应商17,供应商名称18,品牌19,品牌名称20,课组21,课组名称22,库位23,库位名称24,联营扣率25,销售日期26,售价27,销售数量28,销售金额29,
# 退货数量30,退货金额31,赠送数量32,赠送金额33,数量小计34,金额小计35,退货价36,参考进价37,参考金额38
SALE_DAILY_FULL = [
    (0, "warehouse_code", False), (1, "warehouse_name", False), (2, "sku_code", False), (3, "product_name", False),
    (4, "barcode", False), (5, "short_name", False), (6, "unit", False), (7, "spec", False),
    (8, "category_code", False), (9, "category", False), (10, "category_large_code", False), (11, "category_large", False),
    (12, "category_mid_code", False), (13, "category_mid", False), (14, "category_small_code", False), (15, "category_small", False),
    (16, "biz_mode", False), (17, "supplier_code", False), (18, "supplier_name", False), (19, "brand_code", False), (20, "brand_name", False),
    (21, "category_group_code", False), (22, "category_group_name", False), (23, "location_code", False), (24, "location_name", False),
    (25, "joint_rate", True), (26, "data_date", False), (27, "sale_price", True), (28, "sale_qty", True), (29, "sale_amount", True),
    (30, "return_qty", True), (31, "return_amount", True), (32, "gift_qty", True), (33, "gift_amount", True),
    (34, "qty_total", True), (35, "amount_total", True), (36, "return_price", True), (38, "cost_amount", True),
]
SALE_DAILY_COLS = {c[1]: c[0] for c in SALE_DAILY_FULL}

# 销售汇总表 54列：0-25同日报, 26联营扣率, 27销售日期, 28平均售价, 29售价, 30销售数量, 31销售金额, 32退货数量, 33退货金额, 34赠送数量, 35赠送金额,
# 36数量小计, 37数量小计占比, 38金额小计, 39金额小计占比, 40退货价, 41参考进价金额, 42进销差价金额, 43当前库存
SALE_SUMMARY_FULL = [
    (0, "warehouse_code", False), (1, "warehouse_name", False), (2, "sku_code", False), (3, "product_name", False),
    (4, "barcode", False), (5, "short_name", False), (6, "unit", False), (7, "spec", False),
    (8, "category_code", False), (9, "category", False), (10, "category_large_code", False), (11, "category_large", False),
    (12, "category_mid_code", False), (13, "category_mid", False), (14, "category_small_code", False), (15, "category_small", False),
    (16, "supplier_code", False), (17, "supplier_name", False), (18, "supplier_main_code", False), (19, "supplier_main_name", False),
    (20, "brand_code", False), (21, "brand_name", False), (22, "category_group_code", False), (23, "category_group_name", False),
    (24, "location_code", False), (25, "location_name", False), (26, "joint_rate", True), (27, "data_date", False),
    (28, "avg_sale_price", True), (29, "sale_price", True), (30, "sale_qty", True), (31, "sale_amount", True),
    (32, "return_qty", True), (33, "return_amount", True), (34, "gift_qty", True), (35, "gift_amount", True),
    (36, "qty_total", True), (37, "qty_ratio", True), (38, "amount_total", True), (39, "amount_ratio", True),
    (40, "return_price", True), (41, "cost_amount", True), (42, "margin_amount", True), (43, "current_stock", True),
]
SALE_SUMMARY_COLS = {c[1]: c[0] for c in SALE_SUMMARY_FULL}

def _read_excel_safe(path):
    """读取 Excel，兼容 .xls / .xlsx"""
    ext = os.path.splitext(path)[1].lower()
    last_err = None
    for engine in (["openpyxl"] if ext == ".xlsx" else [None, "xlrd"]):
        try:
            return pd.read_excel(path, header=None, engine=engine)
        except Exception as e:
            last_err = e
    raise last_err or RuntimeError("无法读取 Excel")


def preview_sale_excel(excel_path, is_summary=False):
    """预览销售 Excel 结构，用于调试。返回检测到的列、首行数据、可能的问题"""
    try:
        df = _read_excel_safe(excel_path)
        raw_rows, raw_cols = df.shape[0], df.shape[1]
        df_trimmed = _trim_leading_junk_rows(df, ("货号", "销售金额", "商品编码", "销售日期", "销售数量", "品号", "商品号", "商品名称", "订单日期", "销售汇总"))
        if df_trimmed.shape[0] == 0:
            return {"ok": False, "error": "trim后无数据", "raw_rows": raw_rows, "raw_cols": raw_cols}
        start_row = _detect_header_row(df_trimmed)
        cols = _detect_sale_cols(df_trimmed, start_row, df_trimmed.shape[1], is_summary=is_summary)
        data_rows = df_trimmed.iloc[start_row:]
        sample = []
        for i, (_, row) in enumerate(data_rows.head(3).iterrows()):
            dt = _parse_date(_row_val(row, cols["date"]))
            sku = _row_val(row, cols["sku"])
            amt = _row_val(row, cols["amount"], as_decimal=True)
            cost = _row_val(row, cols["cost"], as_decimal=True)
            sample.append({"row": i, "sku": sku, "date": dt, "amount": amt, "cost": cost})
        issues = []
        if not sample or all(not s["sku"] for s in sample):
            issues.append("货号列为空或未识别")
        if not sample or all(not s["date"] for s in sample):
            issues.append("日期列为空或格式不支持")
        return {
            "ok": True,
            "raw_rows": raw_rows, "raw_cols": raw_cols,
            "trimmed_rows": len(df_trimmed), "header_row": start_row - 1, "data_rows": len(data_rows),
            "cols": cols,
            "sample": sample,
            "issues": issues,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# 实时库存表：支持两种格式
# 格式一(旧24列)：仓库编码0,仓库名称1,类别2,类别名称3,货号4,国际条码5,商品名称6,规格7,单位8,商品状态9,分店经营10,实时库存11,库存箱数12,库存金额(零售价)13,...
# 格式二(库存查询_默认)：仓库0,仓库名称1,货号2,品类3,大类编码4,大类名称5,中类编码6,中类名称7,小类编码8,小类名称9,规格10,库位名称11,品牌12,单位13,品号14,库存数量15,平均价16,库存总金额17,账龄18,上次变动日期19,平均入库价20,SKU商品状态21,条码22
STOCK_FULL = [
    (0, "warehouse_code", False), (1, "warehouse_name", False), (2, "category", False), (3, "category_name", False),
    (4, "sku_code", False), (5, "barcode", False), (6, "product_name", False), (7, "spec", False), (8, "unit", False),
    (9, "product_status", False), (10, "branch_manage", False), (11, "stock_qty", True), (12, "stock_boxes", True),
    (13, "stock_amount", True), (13, "stock_amount_retail", True), (14, "sale_price", True), (15, "short_name", False),
    (16, "brand_code", False), (17, "brand_name", False), (18, "supplier_code", False), (19, "supplier_name", False),
    (20, "location_code", False), (21, "location_name", False), (22, "contact", False), (23, "biz_mode", False),
]
# 库存查询_默认格式补充映射 (excel_col_idx, db_column, as_decimal)，表头检测会覆盖索引
STOCK_V2_EXTRA = [
    (4, "category_large_code", False), (5, "category_large", False), (6, "category_mid_code", False), (7, "category_mid", False),
    (8, "category_small_code", False), (9, "category_small", False), (16, "avg_price", True), (18, "aging", True),
    (19, "last_change_date", False), (20, "avg_inbound_price", True), (14, "product_code", False),
]
STOCK_COLS = {"sku_code": 4, "category": 2, "stock_qty": 11, "stock_amount": 13}
# 新表 t_htma_stock (05_create_stock_table_v2) 支持的列，导入时过滤
STOCK_NEW_COLS = {
    "warehouse_code", "warehouse_name", "category", "category_name", "category_large_code", "category_large",
    "category_mid_code", "category_mid", "category_small_code", "category_small", "spec", "location_name",
    "brand_name", "unit", "product_code", "avg_price", "aging", "last_change_date", "avg_inbound_price",
    "product_status", "barcode", "product_name",
}


def import_sale_daily(excel_path, conn):
    """销售日报表：支持表头检测，销售收入=销售金额，成本=成本金额/参考金额/销售成本。"""
    df = _read_excel_safe(excel_path)
    df = _trim_leading_junk_rows(df, ("货号", "销售金额", "商品编码", "销售日期", "销售数量", "品号", "商品号", "商品名称", "订单日期", "销售汇总"))
    if df.shape[0] <= 1:
        return 0, "行数不足"
    ncol = df.shape[1]
    start_row = _detect_header_row(df)
    cols = _detect_sale_cols(df, start_row, ncol, is_summary=False)
    # 销售日报至少需要: 货号, 日期, 销售金额, 参考金额
    if cols.get("amount") is not None and ncol <= cols["amount"]:
        return 0, f"列数不足(需>={cols['amount']+1}, 实际{ncol})"
    if cols.get("cost") is not None and ncol <= cols["cost"]:
        return 0, f"列数不足(需>={cols['cost']+1}, 实际{ncol})"
    data_rows = df.iloc[start_row:]
    cur = conn.cursor()
    inserted = 0
    skipped_no_sku = 0
    skipped_no_date = 0
    skipped_err = 0
    first_err = None
    for _, row in data_rows.iterrows():
        dt = _parse_date(_row_val(row, cols["date"]))
        sku = _row_val(row, cols["sku"])
        if not sku:
            skipped_no_sku += 1
            continue
        if not dt:
            skipped_no_date += 1
            continue
        sale_amount = _row_val(row, cols["amount"], as_decimal=True)
        cost = _row_val(row, cols["cost"], as_decimal=True)
        gross = sale_amount - cost
        if sale_amount == 0 and cost > 0:
            gross = 0
        try:
            _import_sale_full(row, dt, sku, sale_amount, cost, gross, cur, cols, SALE_DAILY_FULL, source_sheet="sale_daily")
            inserted += 1
        except Exception as e:
            skipped_err += 1
            if first_err is None:
                first_err = str(e)
            pass  # 跳过该行
    conn.commit()
    diag = None
    if inserted == 0:
        parts = [f"总行{len(data_rows)}"]
        if skipped_no_sku:
            parts.append(f"无货号{skipped_no_sku}")
        if skipped_no_date:
            parts.append(f"无日期{skipped_no_date}")
        if skipped_err:
            parts.append(f"导入失败{skipped_err}行")
        if first_err:
            parts.append(f"异常:{first_err[:100]}")
        diag = "销售日报: " + ", ".join(parts)
    return inserted, diag


def _import_sale_full(row, dt, sku, sale_amount, cost, gross, cur, cols, full_map, source_sheet="sale_daily"):
    """完整导入：将 Excel 行按 full_map 映射写入 t_htma_sale 所有字段"""
    qty_idx = cols.get("qty", 28 if source_sheet == "sale_daily" else 30)
    extra_cols, extra_vals = [], []
    for excel_col, db_col, as_dec in full_map:
        if db_col in ("data_date", "sku_code", "sale_amount", "cost_amount", "sale_qty"):
            continue
        idx = cols.get(db_col, excel_col)
        if idx >= len(row):
            continue
        v = _row_val(row, idx, as_decimal=as_dec) if as_dec else _row_val(row, idx)
        extra_cols.append(db_col)
        extra_vals.append(v)
    all_cols = ["data_date", "sku_code", "store_id"] + extra_cols + ["sale_qty", "sale_amount", "sale_cost", "gross_profit", "source_sheet"]
    all_vals = [dt, sku, STORE_ID] + extra_vals + [_row_val(row, qty_idx, as_decimal=True), sale_amount, cost, gross, source_sheet]
    placeholders = ", ".join(["%s"] * len(all_vals))
    col_str = ", ".join(all_cols)
    # 同一(date,sku)多行（如销售+退货）需累加，不能覆盖
    update_parts = [
        "sale_qty=sale_qty+VALUES(sale_qty)",
        "sale_amount=sale_amount+VALUES(sale_amount)",
        "sale_cost=sale_cost+VALUES(sale_cost)",
        "gross_profit=gross_profit+VALUES(gross_profit)",
    ]
    for c in extra_cols:
        update_parts.append(f"{c}=COALESCE(VALUES({c}),{c})")
    update_parts.append("source_sheet=VALUES(source_sheet)")
    update_str = ", ".join(update_parts)
    try:
        cur.execute(f"""
            INSERT INTO t_htma_sale ({col_str})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {update_str}
        """, tuple(all_vals))
    except Exception as e:
        if "Unknown column" in str(e):
            cur.execute("""
                INSERT INTO t_htma_sale (data_date, sku_code, category, sale_qty, sale_amount, sale_cost, gross_profit, store_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE sale_qty=VALUES(sale_qty), sale_amount=VALUES(sale_amount), sale_cost=VALUES(sale_cost), gross_profit=VALUES(gross_profit)
            """, (dt, sku, _row_val(row, cols.get("category", 9)), _row_val(row, qty_idx, as_decimal=True), sale_amount, cost, gross, STORE_ID))
        else:
            raise


def import_sale_summary(excel_path, conn):
    """销售汇总表：支持表头检测，销售收入=销售金额，成本=成本金额/参考进价金额/销售成本。"""
    df = _read_excel_safe(excel_path)
    df = _trim_leading_junk_rows(df, ("货号", "销售金额", "商品编码", "销售日期", "销售数量", "品号", "商品号", "商品名称", "订单日期", "销售汇总"))
    if df.shape[0] <= 1:
        return 0, "行数不足"
    ncol = df.shape[1]
    start_row = _detect_header_row(df)
    cols = _detect_sale_cols(df, start_row, ncol, is_summary=True)
    if cols.get("amount") is not None and ncol <= cols["amount"]:
        return 0, f"列数不足(需>={cols['amount']+1}, 实际{ncol})"
    if cols.get("cost") is not None and ncol <= cols["cost"]:
        return 0, f"列数不足(需>={cols['cost']+1}, 实际{ncol})"
    data_rows = df.iloc[start_row:]
    cur = conn.cursor()
    inserted = 0
    skipped_no_sku = 0
    skipped_no_date = 0
    skipped_err = 0
    first_err = None
    for _, row in data_rows.iterrows():
        dt = _parse_date(_row_val(row, cols["date"]))
        sku = _row_val(row, cols["sku"])
        if not sku:
            skipped_no_sku += 1
            continue
        if not dt:
            skipped_no_date += 1
            continue
        sale_amount = _row_val(row, cols["amount"], as_decimal=True)
        cost = _row_val(row, cols["cost"], as_decimal=True)
        # 销售汇总表：若有「进销差价金额」列，直接用作毛利（与系统报表一致）
        if cols.get("margin") is not None:
            gross = _row_val(row, cols["margin"], as_decimal=True)
            cost = sale_amount - gross if sale_amount and gross is not None else cost
        else:
            gross = sale_amount - cost
        if sale_amount == 0 and cost > 0:
            gross = 0
        try:
            _import_sale_full(row, dt, sku, sale_amount, cost, gross, cur, cols, SALE_SUMMARY_FULL, source_sheet="sale_summary")
            inserted += 1
        except Exception as e:
            skipped_err += 1
            if first_err is None:
                first_err = str(e)
            pass
    conn.commit()
    diag = None
    if inserted == 0:
        parts = [f"总行{len(data_rows)}"]
        if skipped_no_sku:
            parts.append(f"无货号{skipped_no_sku}")
        if skipped_no_date:
            parts.append(f"无日期{skipped_no_date}")
        if skipped_err:
            parts.append(f"导入失败{skipped_err}行")
        if first_err:
            parts.append(f"异常:{first_err[:100]}")
        diag = "销售汇总: " + ", ".join(parts)
    return inserted, diag


def _detect_stock_cols(df, start_row, ncol):
    """检测库存表列：货号、实时库存、库存金额及全部 24 列"""
    default = {c[1]: c[0] for c in (STOCK_FULL + STOCK_V2_EXTRA) if c[1] in ("sku_code", "category", "stock_qty", "stock_amount")}
    default["sku"] = default.get("sku_code", 4)
    default.setdefault("category", 3)
    default.setdefault("stock_qty", 15)
    default.setdefault("stock_amount", 17)
    if start_row >= df.shape[0] or ncol < 5:
        return default
    for h_idx in [start_row - 1, 0, 1]:
        if h_idx < 0 or h_idx >= df.shape[0]:
            continue
        row = df.iloc[h_idx]
        filled = _header_row_forward_fill(row)
        cols = {}
        for c in range(min(len(filled), 40)):
            v = filled[c]
            if not v:
                continue
            if any(k in v for k in ("货号", "商品编码", "品号", "SKU")):
                cols["sku"] = cols["sku_code"] = c
            elif any(k in v for k in ("类别", "品类")) and "名称" not in v:
                cols["category"] = c
            elif "类别名称" in v or ("类别" in v and "名称" in v):
                cols["category_name"] = c
            elif "库存总金额" in v:
                cols["stock_amount"] = c
            elif any(k in v for k in ("库存金额", "零售价")):
                cols["stock_amount_retail"] = c
                if "stock_amount" not in cols:
                    cols["stock_amount"] = c
            elif any(k in v for k in ("实时库存", "库存数量")) or ("库存" in v and "金额" not in v):
                cols["stock_qty"] = c
            elif "仓库编码" in v:
                cols["warehouse_code"] = c
            elif "仓库名称" in v:
                cols["warehouse_name"] = c
            elif "国际条码" in v or "条码" in v:
                cols["barcode"] = c
            elif "商品名称" in v:
                cols["product_name"] = c
            elif "规格" in v:
                cols["spec"] = c
            elif "单位" in v:
                cols["unit"] = c
            elif "商品状态" in v:
                cols["product_status"] = c
            elif "分店经营" in v:
                cols["branch_manage"] = c
            elif "库存箱数" in v:
                cols["stock_boxes"] = c
            elif "售价" in v:
                cols["sale_price"] = c
            elif "商品简称" in v:
                cols["short_name"] = c
            elif "品牌编码" in v:
                cols["brand_code"] = c
            elif "品牌名称" in v:
                cols["brand_name"] = c
            elif "供应商编码" in v or ("供应商" in v and "主" not in v):
                cols["supplier_code"] = c
            elif "主供应商" in v:
                cols["supplier_name"] = c
            elif "库位" in v and "名称" not in v:
                cols["location_code"] = c
            elif "库位名称" in v:
                cols["location_name"] = c
            elif "联系方式" in v:
                cols["contact"] = c
            elif "经营方式" in v:
                cols["biz_mode"] = c
            elif "大类编码" in v or v == "大类编":
                cols["category_large_code"] = c
            elif "大类名称" in v:
                cols["category_large"] = c
            elif "中类编码" in v or v == "中类编":
                cols["category_mid_code"] = c
            elif "中类名称" in v:
                cols["category_mid"] = c
            elif "小类编码" in v or v == "小类编":
                cols["category_small_code"] = c
            elif "小类名称" in v:
                cols["category_small"] = c
            elif "平均价" in v:
                cols["avg_price"] = c
            elif "账龄" in v:
                cols["aging"] = c
            elif "上次变动日期" in v:
                cols["last_change_date"] = c
            elif "平均入库价" in v:
                cols["avg_inbound_price"] = c
            elif "品号" in v:
                cols["product_code"] = c
            elif "品牌" in v and "编码" not in v:
                cols["brand_name"] = c
        if cols.get("sku") is not None:
            for excel_col, db_col, _ in STOCK_FULL + STOCK_V2_EXTRA:
                if db_col not in cols:
                    cols[db_col] = excel_col
            return cols
    return default


def _parse_datetime(v):
    """解析日期时间，支持 YYYY-MM-DD HH:MM:SS、Excel 序列等"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    s = str(v).strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s+(\d{1,2})[:.](\d{1,2})[:.]?(\d{0,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d} {int(m.group(4)):02d}:{int(m.group(5)):02d}:{int(m.group(6) or 0):02d}"
    d = _parse_date(v)
    return (d + " 00:00:00") if d else None


def _import_stock_full(row, data_date, cur, cols, full_map):
    """完整导入：将 Excel 行按 full_map 映射写入 t_htma_stock 所有字段"""
    sku = _row_val(row, cols.get("sku", cols.get("sku_code", 2)))
    if not sku:
        return False
    qty = _row_val(row, cols.get("stock_qty", 15), as_decimal=True)
    amount = _row_val(row, cols.get("stock_amount", 17), as_decimal=True)
    extra_cols, extra_vals = [], []
    for excel_col, db_col, as_dec in full_map:
        if db_col in ("sku_code", "stock_qty", "stock_amount"):
            continue
        if db_col not in STOCK_NEW_COLS:
            continue
        idx = cols.get(db_col, excel_col)
        if idx >= len(row):
            continue
        if db_col == "last_change_date":
            v = _parse_datetime(row.iloc[idx]) if idx < len(row) else None
        else:
            v = _row_val(row, idx, as_decimal=as_dec) if as_dec else _row_val(row, idx)
        extra_cols.append(db_col)
        extra_vals.append(v)
    all_cols = ["data_date", "sku_code", "store_id"] + extra_cols + ["stock_qty", "stock_amount"]
    all_vals = [data_date, sku, STORE_ID] + extra_vals + [qty, amount]
    placeholders = ", ".join(["%s"] * len(all_vals))
    col_str = ", ".join(all_cols)
    update_parts = ["stock_qty=VALUES(stock_qty)", "stock_amount=VALUES(stock_amount)"]
    for c in extra_cols:
        update_parts.append(f"{c}=COALESCE(VALUES({c}),{c})")
    update_str = ", ".join(update_parts)
    try:
        cur.execute(f"""
            INSERT INTO t_htma_stock ({col_str})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {update_str}
        """, tuple(all_vals))
        return True
    except Exception as e:
        if "Unknown column" in str(e):
            cur.execute("""
                INSERT INTO t_htma_stock (data_date, sku_code, category, stock_qty, stock_amount, store_id)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE stock_qty=VALUES(stock_qty), stock_amount=VALUES(stock_amount)
            """, (data_date, sku, _row_val(row, cols.get("category", 2)), qty, amount, STORE_ID))
            return True
        raise


def import_stock(excel_path, conn):
    """实时库存表：支持表头检测，完整导入所有 24 列。"""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(excel_path))
    data_date = m.group(0) if m else datetime.now().strftime("%Y-%m-%d")
    df = _read_excel_safe(excel_path)
    df = _trim_leading_junk_rows(df, ("货号", "实时库存", "库存", "商品名称", "库存金额", "库存数量", "库存总金额"))
    if df.shape[0] <= 1 or df.shape[1] < 5:
        return 0
    start_row = _detect_header_row(df)
    cols = _detect_stock_cols(df, start_row, df.shape[1])
    data_rows = df.iloc[start_row:]
    cur = conn.cursor()
    inserted = 0
    for _, row in data_rows.iterrows():
        if _import_stock_full(row, data_date, cur, cols, STOCK_FULL + STOCK_V2_EXTRA):
            inserted += 1
    conn.commit()
    return inserted


def _detect_category_cols(df):
    """检测品类附表列：大类编、大类名称、中类编、中类名称、小类编、小类名称"""
    default = {"category_large_code": 0, "category_large": 1, "category_mid_code": 2, "category_mid": 3, "category_small_code": 4, "category_small": 5}
    if df.shape[0] < 2 or df.shape[1] < 4:
        return default, 1
    header_row = 0
    for h_idx in range(min(8, df.shape[0])):
        row = df.iloc[h_idx]
        filled = _header_row_forward_fill(row)
        cols = {}
        for c in range(min(len(filled), 12)):
            v = str(filled[c]).strip()
            if not v:
                continue
            if "大类编码" in v or v == "大类编":
                cols["category_large_code"] = c
            elif "大类名称" in v:
                cols["category_large"] = c
            elif "中类编码" in v or v == "中类编":
                cols["category_mid_code"] = c
            elif "中类名称" in v:
                cols["category_mid"] = c
            elif "小类编码" in v or v == "小类编":
                cols["category_small_code"] = c
            elif "小类名称" in v:
                cols["category_small"] = c
        if len(cols) >= 2:
            for k, v in default.items():
                if k not in cols:
                    cols[k] = v
            return cols, h_idx + 1
    return default, 1


def import_category(excel_path, conn):
    """导入品类主数据表（附表结构：大类编、大类名称、中类编、中类名称、小类编、小类名称）。
    支持合并单元格：空单元格沿用上一行同列值。"""
    df = _read_excel_safe(excel_path)
    df = df.dropna(how="all", axis=0).reset_index(drop=True)
    if df.shape[0] < 2:
        return 0
    cols, start_row = _detect_category_cols(df)
    data_rows = df.iloc[start_row:]
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE t_htma_category")
    last_large_code, last_large, last_mid_code, last_mid = "", "", "", ""
    inserted = 0
    for _, row in data_rows.iterrows():
        lc = _row_val(row, cols.get("category_large_code", 0)) or last_large_code
        ln = _row_val(row, cols.get("category_large", 1)) or last_large
        mc = _row_val(row, cols.get("category_mid_code", 2)) or last_mid_code
        mn = _row_val(row, cols.get("category_mid", 3)) or last_mid
        sc = _row_val(row, cols.get("category_small_code", 4)) or ""
        sn = _row_val(row, cols.get("category_small", 5)) or ""
        if lc:
            last_large_code, last_large = lc, ln
        if mc:
            last_mid_code, last_mid = mc, mn
        if not lc and not ln and not mc and not mn and not sc and not sn:
            continue
        lc = str(lc).strip()[:16] if lc else ""
        ln = str(ln).strip()[:64] if ln else "未分类"
        mc = str(mc).strip()[:16] if mc else ""
        mn = str(mn).strip()[:64] if mn else ""
        sc = str(sc).strip()[:16] if sc else ""
        sn = str(sn).strip()[:64] if sn else ""
        try:
            cur.execute("""
                INSERT INTO t_htma_category (category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE category_large=VALUES(category_large), category_mid=VALUES(category_mid), category_small=VALUES(category_small)
            """, (lc, ln, mc, mn, sc, sn))
            inserted += 1
        except Exception:
            pass
    conn.commit()
    return inserted


def _detect_profit_cols(df, start_row, ncol):
    """检测毛利汇总表列：大类名称、类别名称、销售金额、参考进价金额"""
    default = {"category_large": 0, "category": 1, "total_sale": 2, "cost": 4}
    if start_row >= df.shape[0] or ncol < 3:
        return default
    for h_idx in [start_row - 1, 0, 1]:
        if h_idx < 0 or h_idx >= df.shape[0]:
            continue
        row = df.iloc[h_idx]
        filled = _header_row_forward_fill(row)
        cols = {}
        for c in range(min(len(filled), 15)):
            v = filled[c]
            if not v:
                continue
            if "大类名称" in v:
                cols["category_large"] = c
            elif any(k in v for k in ("类别名称", "品类")):
                cols["category"] = c
            elif "销售金额" in v:
                cols["total_sale"] = c
            elif "销售数量" in v:
                cols["sale_qty"] = c
            elif "参考进价金额" in v or "参考金额" in v:
                cols["cost"] = c
        if cols.get("total_sale") is not None and cols.get("cost") is not None:
            for k, v in default.items():
                if k not in cols:
                    cols[k] = v
            return cols
    return default


def import_profit(excel_path, conn):
    """导入毛利汇总 Excel 到 t_htma_profit。
    格式：大类名称、类别名称、求和项:销售金额、求和项:参考进价金额。
    毛利=销售金额-参考进价金额。过滤前4行，日期从文件名或表头提取。"""
    df = _read_excel_safe(excel_path)
    df = _trim_leading_junk_rows(df, ("大类名称", "类别名称", "销售金额", "参考进价", "求和项"))
    if df.shape[0] <= 1:
        return 0, "行数不足"
    ncol = df.shape[1]
    start_row = _detect_header_row(df)
    start_row = max(start_row, 4)
    cols = _detect_profit_cols(df, start_row, ncol)
    data_date = _extract_report_date(excel_path) or _extract_report_date(df) or datetime.now().strftime("%Y-%m-%d")
    data_rows = df.iloc[start_row:]
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    last_large = ""
    for _, row in data_rows.iterrows():
        large = _row_val(row, cols.get("category_large", 0)) or last_large
        if large:
            last_large = large
        cat = _row_val(row, cols.get("category", 1))
        total_sale = _row_val(row, cols.get("total_sale", 2), as_decimal=True)
        cost = _row_val(row, cols.get("cost", 4), as_decimal=True)
        if not cat and not large:
            continue
        if total_sale == 0 and cost == 0:
            continue
        if (str(cat or "").strip() == "总计" or str(large or "").strip() == "总计"):
            continue
        category = (cat or large or "未分类").strip()[:64]
        total_profit = total_sale - cost
        profit_rate = total_profit / total_sale if total_sale and total_sale > 0 else 0
        profit_rate = max(-1, min(1, profit_rate))
        try:
            cur.execute("""
                INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id, category_large)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE total_sale=VALUES(total_sale), total_profit=VALUES(total_profit), profit_rate=VALUES(profit_rate), category_large=COALESCE(VALUES(category_large),category_large)
            """, (data_date, category, total_sale, total_profit, profit_rate, STORE_ID, last_large[:64] if last_large else None))
            inserted += 1
        except Exception as e:
            if "Unknown column" in str(e) and "category_large" in str(e):
                cur.execute("""
                    INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE total_sale=VALUES(total_sale), total_profit=VALUES(total_profit), profit_rate=VALUES(profit_rate)
                """, (data_date, category, total_sale, total_profit, profit_rate, STORE_ID))
                inserted += 1
            else:
                skipped += 1
    conn.commit()
    diag = None
    if inserted == 0 and skipped > 0:
        diag = f"毛利表: 总行{len(data_rows)}, 跳过{skipped}行"
    return inserted, diag


def refresh_category_from_sale(conn):
    """从销售表透视大类/中类/小类，写入品类主数据表 t_htma_category，作为查询基础数据"""
    cur = conn.cursor()
    try:
        cur.execute("SELECT category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small, category FROM t_htma_sale LIMIT 1")
    except Exception:
        return 0
    cur.execute("TRUNCATE TABLE t_htma_category")
    cur.execute("""
        INSERT INTO t_htma_category (category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
        SELECT
            COALESCE(NULLIF(TRIM(lc), ''), '0'),
            COALESCE(NULLIF(TRIM(ln), ''), '未分类'),
            COALESCE(TRIM(mc), ''),
            COALESCE(NULLIF(TRIM(mn), ''), ''),
            COALESCE(TRIM(sc), ''),
            COALESCE(NULLIF(TRIM(sn), ''), '')
        FROM (
            SELECT
                COALESCE(category_large_code, '') AS lc,
                MAX(COALESCE(category_large, '')) AS ln,
                COALESCE(category_mid_code, '') AS mc,
                MAX(COALESCE(category_mid, '')) AS mn,
                COALESCE(category_small_code, '') AS sc,
                MAX(COALESCE(NULLIF(TRIM(category_small), ''), NULLIF(TRIM(category), ''), '')) AS sn
            FROM t_htma_sale
            WHERE (COALESCE(TRIM(category_large_code), '') != '' OR COALESCE(TRIM(category_large), '') != '')
               OR (COALESCE(TRIM(category_mid_code), '') != '' OR COALESCE(TRIM(category_mid), '') != '')
               OR (COALESCE(TRIM(category_small_code), '') != '' OR COALESCE(TRIM(category_small), '') != '' OR COALESCE(TRIM(category), '') != '')
            GROUP BY COALESCE(category_large_code, ''), COALESCE(category_mid_code, ''), COALESCE(category_small_code, '')
        ) t
        WHERE (TRIM(lc) != '' OR TRIM(ln) != '') OR (TRIM(mc) != '' OR TRIM(mn) != '') OR (TRIM(sc) != '' OR TRIM(sn) != '')
        ON DUPLICATE KEY UPDATE category_large=VALUES(category_large), category_mid=VALUES(category_mid), category_small=VALUES(category_small)
    """)
    conn.commit()
    return cur.rowcount


def refresh_profit(conn):
    """按日期+品类汇总销售表，写入毛利表（含分类层级字段）"""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
            category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
        SELECT data_date, COALESCE(category, '未分类'),
               SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
               LEAST(1, GREATEST(-1, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
               store_id,
               MAX(category_code), MAX(category_large_code), MAX(category_large),
               MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
        FROM t_htma_sale
        GROUP BY data_date, category, store_id
        ON DUPLICATE KEY UPDATE total_sale=VALUES(total_sale), total_profit=VALUES(total_profit), profit_rate=VALUES(profit_rate),
            category_code=VALUES(category_code), category_large_code=VALUES(category_large_code), category_large=VALUES(category_large),
            category_mid_code=VALUES(category_mid_code), category_mid=VALUES(category_mid),
            category_small_code=VALUES(category_small_code), category_small=VALUES(category_small)
    """)
    conn.commit()
    return cur.rowcount
