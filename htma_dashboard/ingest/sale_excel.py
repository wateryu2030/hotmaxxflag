# -*- coding: utf-8 -*-
"""销售日报 / 库存 Excel 读取、解析、校验与写入 — 分组B"""
import os
import re
from datetime import datetime, timedelta

import pandas as pd
import pymysql

from ingest.helpers import (
    _safe_decimal, _safe_str, _parse_date, _parse_datetime,
    _extract_report_date, _is_summary_like, _is_sale_summary_row,
    _row_val_raw, _row_val, _trim_leading_junk_rows,
    _header_row_forward_fill, _detect_header_row, _find_col_by_header,
    _read_excel_safe,
)
from core.db import get_conn

STORE_ID = "沈阳超级仓"
SALE_SUMMARY_ROW_KEYWORDS = frozenset({"总计", "合计", "小计", "求和项", "汇总", "合计行", "总计行", "小计行", "货号", "汇总数据"})
SUMMARY_SUBSTRINGS = ("合计", "总计", "小计", "汇总", "求和项", "合计行", "总计行", "小计行", "汇总数据")

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
            # 退货/赠送：按表头识别，确保导入时能正确带入
            elif "退货数量" in v or (v.strip() and "退货" in v and "数量" in v):
                cols["return_qty"] = c
            elif "退货金额" in v or (v.strip() and "退货" in v and "金额" in v):
                cols["return_amount"] = c
            elif "赠送数量" in v or (v.strip() and "赠送" in v and "数量" in v):
                cols["gift_qty"] = c
            elif "赠送金额" in v or (v.strip() and "赠送" in v and "金额" in v):
                cols["gift_amount"] = c
            elif "数量小计占比" in v or ("数量" in v and "占比" in v):
                cols["qty_ratio"] = c
            elif "金额小计占比" in v or ("金额" in v and "占比" in v and "小计" in v):
                cols["amount_ratio"] = c
            elif "进销差价金额" in v or "进销差价" in v:
                cols["margin_amount"] = c
            elif "当前库存" in v:
                cols["current_stock"] = c
            elif "性别" in v:
                cols["gender"] = c
            elif "上下装" in v:
                cols["top_bottom"] = c
            elif "风格" in v:
                cols["style"] = c
            elif "事业部" in v:
                cols["division"] = c
            elif "色系" in v:
                cols["color_system"] = c
            elif "色深" in v:
                cols["color_depth"] = c
            elif "标准码" in v:
                cols["standard_code"] = c
            elif "原条码" in v:
                cols["original_barcode"] = c
            elif "厚度" in v:
                cols["thickness"] = c
            elif "长度" in v:
                cols["length"] = c
        if cols.get("sku") is not None and (cols.get("amount") is not None or cols.get("date") is not None):
            for k, v in default.items():
                if k not in cols:
                    cols[k] = v
            # 退货/赠送默认列索引（未检测到表头时按标准顺序：日报 30/31/32/33，汇总 32/33/34/35）
            if cols.get("return_qty") is None and ncol > (33 if is_summary else 31):
                cols["return_qty"] = 32 if is_summary else 30
            if cols.get("return_amount") is None and ncol > (33 if is_summary else 31):
                cols["return_amount"] = 33 if is_summary else 31
            if cols.get("gift_qty") is None and ncol > (35 if is_summary else 33):
                cols["gift_qty"] = 34 if is_summary else 32
            if cols.get("gift_amount") is None and ncol > (35 if is_summary else 33):
                cols["gift_amount"] = 35 if is_summary else 33
            if is_summary:
                if cols.get("qty_ratio") is None and ncol > 37:
                    cols["qty_ratio"] = 37
                if cols.get("amount_ratio") is None and ncol > 39:
                    cols["amount_ratio"] = 39
                if cols.get("margin_amount") is None and ncol > 42:
                    cols["margin_amount"] = 42
                if cols.get("current_stock") is None and ncol > 43:
                    cols["current_stock"] = 43
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
# -1 表示“按表头识别或填空”，保证该列始终参与 INSERT，无数据时写 NULL/0
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
    (-1, "qty_ratio", True), (-1, "amount_ratio", True), (-1, "margin_amount", True), (-1, "current_stock", True),
    (-1, "gender", False), (-1, "top_bottom", False), (-1, "style", False), (-1, "division", False),
    (-1, "color_system", False), (-1, "color_depth", False), (-1, "standard_code", False), (-1, "original_barcode", False),
    (-1, "thickness", False), (-1, "length", False),
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
    (-1, "gender", False), (-1, "top_bottom", False), (-1, "style", False), (-1, "division", False),
    (-1, "color_system", False), (-1, "color_depth", False), (-1, "standard_code", False), (-1, "original_barcode", False),
    (-1, "thickness", False), (-1, "length", False),
]
SALE_SUMMARY_COLS = {c[1]: c[0] for c in SALE_SUMMARY_FULL}

def _read_excel_safe(path):
    """读取 Excel，兼容 .xls（需 xlrd>=2.0.1）/ .xlsx（openpyxl）"""
    ext = os.path.splitext(path)[1].lower()
    last_err = None
    # .xls 优先用 xlrd，否则 pandas 会报错提示安装 xlrd
    engines = (["openpyxl"] if ext == ".xlsx" else ["xlrd", None])
    for engine in engines:
        try:
            return pd.read_excel(path, header=None, engine=engine)
        except Exception as e:
            last_err = e
    raise last_err or RuntimeError("无法读取 Excel（.xls 需安装 xlrd: pip install xlrd>=2.0.1）")


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
        # 退货/赠送列是否识别（经营分析依赖）
        return_cols_ok = all(k in cols for k in ("return_qty", "return_amount", "gift_qty", "gift_amount"))
        if not return_cols_ok:
            issues.append("未识别到退货/赠送列（需表头含「退货数量」「退货金额」「赠送数量」「赠送金额」），经营分析中退货/赠送将为 0")
        return {
            "ok": True,
            "raw_rows": raw_rows, "raw_cols": raw_cols,
            "trimmed_rows": len(df_trimmed), "header_row": start_row - 1, "data_rows": len(data_rows),
            "cols": cols,
            "sample": sample,
            "issues": issues,
            "return_gift_cols_detected": return_cols_ok,
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


def import_sale_daily(excel_path, conn, overwrite_on_duplicate=True):
    """销售日报表：支持表头检测。仅写入 t_htma_sale（增量/覆盖），不触碰库存/人力/品类/商品档案。默认同(日期,货号)覆盖不累加，避免重复导入同一日报导致翻倍。"""
    from clean.sale_profit_sync import ensure_sale_table_columns, backfill_sale_category_and_supplier
    ensure_sale_table_columns(conn)
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
    skipped_summary = 0
    skipped_err = 0
    first_err = None
    col_list = None
    buf = []
    qty_idx = cols.get("qty", 28)

    def flush_sale_batch():
        nonlocal inserted, skipped_err, first_err, col_list
        if not buf:
            return
        try:
            _batch_insert_sale(cur, col_list, buf, overwrite_on_duplicate)
            inserted += len(buf)
        except Exception as e:
            col_str = ", ".join(col_list)
            one_ph = ", ".join(["%s"] * len(col_list))
            if overwrite_on_duplicate:
                update_parts = ["sale_qty=VALUES(sale_qty)", "sale_amount=VALUES(sale_amount)", "sale_cost=VALUES(sale_cost)", "gross_profit=VALUES(gross_profit)"]
            else:
                update_parts = ["sale_qty=sale_qty+VALUES(sale_qty)", "sale_amount=sale_amount+VALUES(sale_amount)", "sale_cost=sale_cost+VALUES(sale_cost)", "gross_profit=gross_profit+VALUES(gross_profit)"]
            for c in col_list:
                if c not in ("data_date", "sku_code", "store_id", "sale_qty", "sale_amount", "sale_cost", "gross_profit", "source_sheet"):
                    update_parts.append(f"{c}=VALUES({c})")
            update_parts.append("source_sheet=VALUES(source_sheet)")
            update_str = ", ".join(update_parts)
            sql_one = f"INSERT INTO t_htma_sale ({col_str}) VALUES ({one_ph}) ON DUPLICATE KEY UPDATE {update_str}"
            for v in buf:
                try:
                    cur.execute(sql_one, tuple(v))
                    inserted += 1
                except Exception as e2:
                    skipped_err += 1
                    if first_err is None:
                        first_err = str(e2)
        buf.clear()

    # 按 (日期, 货号) 去重合并后再写入，避免重复数据上传（用 itertuples 替代 iterrows 提升遍历效率）
    agg_sale = {}  # (dt, sku) -> (qty_sum, amount_sum, cost_sum, gross_sum, row)
    for row in data_rows.itertuples(index=False, name=None):
        row = tuple(row)
        if _is_sale_summary_row(row, cols):
            skipped_summary += 1
            continue
        dt = _parse_date(_row_val(row, cols["date"]))
        sku_raw = _row_val(row, cols["sku"])
        sku = (str(sku_raw or "").strip())[:64]
        # 无货号或货号为表头/合计等：一律视为「无商品、仅合计」行，不导入，避免重复计算
        if not sku or sku in SALE_SUMMARY_ROW_KEYWORDS or _is_summary_like(sku):
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
        qty = _row_val(row, qty_idx, as_decimal=True) or 0
        key = (dt, sku)
        if key not in agg_sale:
            agg_sale[key] = [0, 0, 0, 0, row]
        agg_sale[key][0] += qty
        agg_sale[key][1] += sale_amount
        agg_sale[key][2] += cost
        agg_sale[key][3] += gross

    for (dt, sku), (qty_sum, amount_sum, cost_sum, gross_sum, row) in agg_sale.items():
        try:
            all_cols, all_vals = _build_sale_row_vals(row, dt, sku, amount_sum, cost_sum, gross_sum, cols, SALE_DAILY_FULL, source_sheet="sale_daily", qty_override=qty_sum)
            if col_list is None:
                col_list = all_cols
            buf.append(all_vals)
            if len(buf) >= _IMPORT_BATCH_SIZE:
                flush_sale_batch()
        except Exception as e:
            skipped_err += 1
            if first_err is None:
                first_err = str(e)
    flush_sale_batch()
    conn.commit()
    backfill_sale_category_and_supplier(conn, STORE_ID)
    diag = None
    if inserted == 0 or skipped_summary > 0:
        parts = [f"总行{len(data_rows)}", f"去重后{len(agg_sale)}条", f"导入{inserted}条"]
        if skipped_summary:
            parts.append(f"跳过汇总行{skipped_summary}条")
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


# 批量写入每批行数，减少数据库往返，避免长时间导入超时（如 Cloudflare 524）；适当增大可提升导入速度
_IMPORT_BATCH_SIZE = 2500


def _build_sale_row_vals(row, dt, sku, sale_amount, cost, gross, cols, full_map, source_sheet="sale_daily", qty_override=None):
    """构建单行销售数据 (all_cols, all_vals)。所有 full_map 列均参与写入，缺列或空值用 0/NULL 保证数据完整。"""
    qty_idx = cols.get("qty", 28 if source_sheet == "sale_daily" else 30)
    qty_val = qty_override if qty_override is not None else _row_val(row, qty_idx, as_decimal=True)
    extra_cols, extra_vals = [], []
    row_len = len(row)
    for excel_col, db_col, as_dec in full_map:
        if db_col in ("data_date", "sku_code", "sale_amount", "sale_qty"):
            continue
        idx = cols.get(db_col, excel_col if isinstance(excel_col, int) and excel_col >= 0 else -1)
        if idx is None or idx < 0 or idx >= row_len:
            v = (0 if as_dec else None)
        else:
            v = _row_val(row, idx, as_decimal=as_dec) if as_dec else _row_val(row, idx)
        extra_cols.append(db_col)
        extra_vals.append(v)
    all_cols = ["data_date", "sku_code", "store_id"] + extra_cols + ["sale_qty", "sale_amount", "sale_cost", "gross_profit", "source_sheet"]
    all_vals = [dt, sku, STORE_ID] + extra_vals + [qty_val, sale_amount, cost, gross, source_sheet]
    return all_cols, all_vals


def _batch_insert_sale(cur, all_cols, vals_list, overwrite_on_duplicate=False):
    """批量 INSERT 销售表。overwrite_on_duplicate=True 时同键覆盖不累加，避免日报+汇总同传时销售额翻倍。"""
    if not vals_list:
        return
    n = len(vals_list)
    placeholders = ", ".join(["(" + ", ".join(["%s"] * len(all_cols)) + ")" for _ in range(n)])
    col_str = ", ".join(all_cols)
    if overwrite_on_duplicate:
        update_parts = [
            "sale_qty=VALUES(sale_qty)", "sale_amount=VALUES(sale_amount)",
            "sale_cost=VALUES(sale_cost)", "gross_profit=VALUES(gross_profit)",
        ]
    else:
        update_parts = [
            "sale_qty=sale_qty+VALUES(sale_qty)", "sale_amount=sale_amount+VALUES(sale_amount)",
            "sale_cost=sale_cost+VALUES(sale_cost)", "gross_profit=gross_profit+VALUES(gross_profit)",
        ]
    extra_cols = [c for c in all_cols if c not in ("data_date", "sku_code", "store_id", "sale_qty", "sale_amount", "sale_cost", "gross_profit", "source_sheet")]
    for c in extra_cols:
        update_parts.append(f"{c}=VALUES({c})")
    update_parts.append("source_sheet=VALUES(source_sheet)")
    update_str = ", ".join(update_parts)
    flat = []
    for v in vals_list:
        flat.extend(v)
    cur.execute(f"""
        INSERT INTO t_htma_sale ({col_str})
        VALUES {placeholders}
        ON DUPLICATE KEY UPDATE {update_str}
    """, flat)


def _import_sale_full(row, dt, sku, sale_amount, cost, gross, cur, cols, full_map, source_sheet="sale_daily"):
    """完整导入：将 Excel 行按 full_map 映射写入 t_htma_sale 所有字段（单行，供 fallback 或小数据量使用）。"""
    all_cols, all_vals = _build_sale_row_vals(row, dt, sku, sale_amount, cost, gross, cols, full_map, source_sheet)
    placeholders = ", ".join(["%s"] * len(all_vals))
    col_str = ", ".join(all_cols)
    update_parts = [
        "sale_qty=sale_qty+VALUES(sale_qty)",
        "sale_amount=sale_amount+VALUES(sale_amount)",
        "sale_cost=sale_cost+VALUES(sale_cost)",
        "gross_profit=gross_profit+VALUES(gross_profit)",
    ]
    extra_cols = [c for c in all_cols if c not in ("data_date", "sku_code", "store_id", "sale_qty", "sale_amount", "sale_cost", "gross_profit", "source_sheet")]
    for c in extra_cols:
        update_parts.append(f"{c}=VALUES({c})")
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
            qty_idx = cols.get("qty", 28 if source_sheet == "sale_daily" else 30)
            cur.execute("""
                INSERT INTO t_htma_sale (data_date, sku_code, category, sale_qty, sale_amount, sale_cost, gross_profit, store_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE sale_qty=VALUES(sale_qty), sale_amount=VALUES(sale_amount), sale_cost=VALUES(sale_cost), gross_profit=VALUES(gross_profit)
            """, (dt, sku, _row_val(row, cols.get("category", 9)), _row_val(row, qty_idx, as_decimal=True), sale_amount, cost, gross, STORE_ID))
        else:
            raise


def import_sale_summary(excel_path, conn, overwrite_on_duplicate=True):
    """销售汇总表：支持表头检测。仅写入 t_htma_sale。默认 overwrite_on_duplicate=True：同(日期,货号)覆盖不累加，避免与日报重复导入或单独导入时在已有数据上累加导致翻倍（如 3 月 7 日重复）。"""
    from clean.sale_profit_sync import ensure_sale_table_columns, backfill_sale_category_and_supplier
    ensure_sale_table_columns(conn)
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
    skipped_summary = 0
    skipped_err = 0
    first_err = None
    col_list = None
    buf = []
    qty_idx = cols.get("qty", 30)

    def flush_sale_batch():
        nonlocal inserted, skipped_err, first_err, col_list
        if not buf:
            return
        try:
            _batch_insert_sale(cur, col_list, buf, overwrite_on_duplicate)
            inserted += len(buf)
        except Exception as e:
            col_str = ", ".join(col_list)
            one_ph = ", ".join(["%s"] * len(col_list))
            if overwrite_on_duplicate:
                update_parts = ["sale_qty=VALUES(sale_qty)", "sale_amount=VALUES(sale_amount)", "sale_cost=VALUES(sale_cost)", "gross_profit=VALUES(gross_profit)"]
            else:
                update_parts = ["sale_qty=sale_qty+VALUES(sale_qty)", "sale_amount=sale_amount+VALUES(sale_amount)", "sale_cost=sale_cost+VALUES(sale_cost)", "gross_profit=gross_profit+VALUES(gross_profit)"]
            for c in col_list:
                if c not in ("data_date", "sku_code", "store_id", "sale_qty", "sale_amount", "sale_cost", "gross_profit", "source_sheet"):
                    update_parts.append(f"{c}=VALUES({c})")
            update_parts.append("source_sheet=VALUES(source_sheet)")
            update_str = ", ".join(update_parts)
            sql_one = f"INSERT INTO t_htma_sale ({col_str}) VALUES ({one_ph}) ON DUPLICATE KEY UPDATE {update_str}"
            for v in buf:
                try:
                    cur.execute(sql_one, tuple(v))
                    inserted += 1
                except Exception as e2:
                    skipped_err += 1
                    if first_err is None:
                        first_err = str(e2)
        buf.clear()

    # 按 (日期, 货号) 去重合并后再写入，避免重复数据上传（用 itertuples 替代 iterrows 提升遍历效率）
    agg_sale = {}  # (dt, sku) -> (qty_sum, amount_sum, cost_sum, gross_sum, row)
    for row in data_rows.itertuples(index=False, name=None):
        row = tuple(row)
        if _is_sale_summary_row(row, cols):
            skipped_summary += 1
            continue
        dt = _parse_date(_row_val(row, cols["date"]))
        sku_raw = _row_val(row, cols["sku"])
        sku = (str(sku_raw or "").strip())[:64]
        # 无货号或货号为表头/合计等：一律视为「无商品、仅合计」行，不导入，避免重复计算
        if not sku or sku in SALE_SUMMARY_ROW_KEYWORDS or _is_summary_like(sku):
            skipped_no_sku += 1
            continue
        if not dt:
            skipped_no_date += 1
            continue
        sale_amount = _row_val(row, cols["amount"], as_decimal=True)
        cost = _row_val(row, cols["cost"], as_decimal=True)
        if cols.get("margin") is not None:
            gross = _row_val(row, cols["margin"], as_decimal=True)
            cost = sale_amount - gross if sale_amount and gross is not None else cost
        else:
            gross = sale_amount - cost
        if sale_amount == 0 and cost > 0:
            gross = 0
        qty = _row_val(row, qty_idx, as_decimal=True) or 0
        key = (dt, sku)
        if key not in agg_sale:
            agg_sale[key] = [0, 0, 0, 0, row]
        agg_sale[key][0] += qty
        agg_sale[key][1] += sale_amount
        agg_sale[key][2] += cost
        agg_sale[key][3] += gross

    for (dt, sku), (qty_sum, amount_sum, cost_sum, gross_sum, row) in agg_sale.items():
        try:
            all_cols, all_vals = _build_sale_row_vals(row, dt, sku, amount_sum, cost_sum, gross_sum, cols, SALE_SUMMARY_FULL, source_sheet="sale_summary", qty_override=qty_sum)
            if col_list is None:
                col_list = all_cols
            buf.append(all_vals)
            if len(buf) >= _IMPORT_BATCH_SIZE:
                flush_sale_batch()
        except Exception as e:
            skipped_err += 1
            if first_err is None:
                first_err = str(e)
    flush_sale_batch()
    conn.commit()
    backfill_sale_category_and_supplier(conn, STORE_ID)
    parts = [f"总行{len(data_rows)}", f"去重后{len(agg_sale)}条", f"导入{inserted}条"]
    if skipped_summary:
        parts.append(f"跳过汇总行{skipped_summary}条")
    if skipped_no_sku:
        parts.append(f"无货号{skipped_no_sku}")
    if skipped_no_date:
        parts.append(f"无日期{skipped_no_date}")
    if skipped_err:
        parts.append(f"导入失败{skipped_err}行")
    if first_err:
        parts.append(f"异常:{first_err[:100]}")
    diag = ", ".join(parts)
    return inserted, diag


def _detect_stock_cols(df, start_row, ncol):
    """检测库存表列：货号、实时库存、库存金额及全部 24 列。格式二(库存查询_默认)货号=2、品类=3、库存数量=15、库存总金额=17；
    30+列格式(仓库/仓库名称/货号/…/库存数量/零售价/库存售价金额)：数量=24、金额=26，避免误用15/17导致金额偏小。"""
    # 格式一默认：货号4 类别3 实时库存11 库存金额13；格式二默认：货号2 品类3 库存数量15 库存总金额17
    default = {"sku_code": 4, "category": 3, "stock_qty": 11, "stock_amount": 13}
    default["sku"] = default["sku_code"]
    # 列数>=18 时可能是格式二，先按格式二默认，表头检测会覆盖
    if ncol >= 18:
        default["stock_qty"] = 15
        default["stock_amount"] = 17
        default["sku"] = default["sku_code"] = 2
        default["category"] = 3
    # 30+列「库存查询」格式：货号2, 库存数量24, 零售价25, 库存售价金额26；若用15/17会读成供应商/经营方式导致金额严重偏小
    if ncol >= 26:
        default["stock_qty"] = 24
        default["stock_amount"] = 26
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
            elif "品名" in v:
                cols["product_name"] = c
            elif any(k in v for k in ("类别", "品类")) and "名称" not in v:
                cols["category"] = c
            elif "类别名称" in v or ("类别" in v and "名称" in v):
                cols["category_name"] = c
            elif "库存总金额" in v or "库存售价金额" in v:
                cols["stock_amount"] = c
                if "售价" in v or "零售" in v:
                    cols["stock_amount_retail"] = c
            elif any(k in v for k in ("库存金额", "零售价")):
                cols["stock_amount_retail"] = c
                if "stock_amount" not in cols:
                    cols["stock_amount"] = c
            elif any(k in v for k in ("实时库存", "库存数量")) or ("库存" in v and "金额" not in v and "价" not in v):
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
            elif "售价" in v or "零售价" in v:
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
            elif "上次变动日期" in v or "库存最近变动日期" in v or "最近变动" in v:
                cols["last_change_date"] = c
            elif "平均入库价" in v or "最后入库价格" in v:
                cols["avg_inbound_price"] = c
            elif "品号" in v:
                cols["product_code"] = c
            elif "品牌" in v and "编码" not in v:
                cols["brand_name"] = c
        if cols.get("sku") is not None:
            # 二次扫描：30+列时在 20~35 列显式找「库存数量」「库存售价金额」，避免表头合并单元格漏识别导致用错列
            if ncol >= 24:
                for c in range(20, min(ncol, 35)):
                    v = filled[c] if c < len(filled) else None
                    if not v:
                        continue
                    v = str(v).strip()
                    if "库存" in v and "数量" in v and "金额" not in v:
                        cols["stock_qty"] = c
                    if ("库存" in v and "售价" in v) or ("库存" in v and "金额" in v) or "库存总金额" in v:
                        cols["stock_amount"] = c
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


def _build_stock_row_vals(row, data_date, qty, amount, cols, full_map):
    """构建单行库存数据。所有 full_map 中且在 STOCK_NEW_COLS 的列均参与写入，缺列或空值用 0/NULL。"""
    sku = _row_val(row, cols.get("sku", cols.get("sku_code", 2)))
    if not sku:
        return None, None
    extra_cols, extra_vals = [], []
    row_len = len(row)
    for excel_col, db_col, as_dec in full_map:
        if db_col in ("sku_code", "stock_qty", "stock_amount"):
            continue
        if db_col not in STOCK_NEW_COLS:
            continue
        idx = cols.get(db_col, excel_col if isinstance(excel_col, int) and excel_col >= 0 else -1)
        if idx is None or idx < 0 or idx >= row_len:
            v = (0 if as_dec else None)
        elif db_col == "last_change_date":
            v = _parse_datetime(_row_val_raw(row, idx)) if idx < row_len else None
        else:
            v = _row_val(row, idx, as_decimal=as_dec) if as_dec else _row_val(row, idx)
        extra_cols.append(db_col)
        extra_vals.append(v)
    all_cols = ["data_date", "sku_code", "store_id"] + extra_cols + ["stock_qty", "stock_amount"]
    all_vals = [data_date, sku, STORE_ID] + extra_vals + [qty, amount]
    return all_cols, all_vals


def _batch_insert_stock(cur, all_cols, vals_list):
    """批量 INSERT 库存表。vals_list 每项为一行 all_vals。"""
    if not vals_list:
        return
    n = len(vals_list)
    placeholders = ", ".join(["(" + ", ".join(["%s"] * len(all_cols)) + ")" for _ in range(n)])
    col_str = ", ".join(all_cols)
    update_parts = ["stock_qty=VALUES(stock_qty)", "stock_amount=VALUES(stock_amount)"]
    extra_cols = [c for c in all_cols if c not in ("data_date", "sku_code", "store_id", "stock_qty", "stock_amount")]
    for c in extra_cols:
        update_parts.append(f"{c}=VALUES({c})")
    update_str = ", ".join(update_parts)
    flat = []
    for v in vals_list:
        flat.extend(v)
    cur.execute(f"""
        INSERT INTO t_htma_stock ({col_str})
        VALUES {placeholders}
        ON DUPLICATE KEY UPDATE {update_str}
    """, flat)


def _import_stock_full(row, data_date, cur, cols, full_map):
    """完整导入：将 Excel 行按 full_map 映射写入 t_htma_stock 所有字段。同一 (date, sku) 应由调用方先聚合。"""
    qty = _row_val(row, cols.get("stock_qty", 15), as_decimal=True)
    amount = _row_val(row, cols.get("stock_amount", 17), as_decimal=True)
    if (amount is None or amount == 0) and qty:
        avg_price = _row_val(row, cols.get("avg_price", 16), as_decimal=True)
        if avg_price:
            amount = avg_price * qty
    all_cols, all_vals = _build_stock_row_vals(row, data_date, qty, amount, cols, full_map)
    if all_cols is None:
        return False
    placeholders = ", ".join(["%s"] * len(all_vals))
    col_str = ", ".join(all_cols)
    update_parts = ["stock_qty=VALUES(stock_qty)", "stock_amount=VALUES(stock_amount)"]
    extra_cols = [c for c in all_cols if c not in ("data_date", "sku_code", "store_id", "stock_qty", "stock_amount")]
    for c in extra_cols:
        update_parts.append(f"{c}=VALUES({c})")
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
            sku = all_vals[all_cols.index("sku_code")]
            cur.execute("""
                INSERT INTO t_htma_stock (data_date, sku_code, category, stock_qty, stock_amount, store_id)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE stock_qty=VALUES(stock_qty), stock_amount=VALUES(stock_amount)
            """, (data_date, sku, _row_val(row, cols.get("category", 3)), qty, amount, STORE_ID))
            return True
        raise


def import_stock(excel_path, conn):
    """实时库存表：支持表头检测，完整导入。仅写入 t_htma_stock（按日期+货号覆盖），不触碰销售/人力/品类/商品档案。同一货号多行（多仓库/库位）会按货号汇总数量与金额后再写入，避免统计偏小。"""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(excel_path))
    data_date = m.group(0) if m else datetime.now().strftime("%Y-%m-%d")
    df = _read_excel_safe(excel_path)
    df = _trim_leading_junk_rows(df, ("货号", "实时库存", "库存", "商品名称", "库存金额", "库存数量", "库存总金额", "库存售价金额"))
    if df.shape[0] <= 1 or df.shape[1] < 5:
        return 0, "行数或列数不足"
    start_row = _detect_header_row(df)
    cols = _detect_stock_cols(df, start_row, df.shape[1])
    data_rows = df.iloc[start_row:]
    ncol = df.shape[1]
    sku_idx = cols.get("sku_code", cols.get("sku", 2))
    fallback_qty = 24 if ncol >= 26 else 15
    fallback_amt = 26 if ncol >= 26 else 17
    qty_idx = cols.get("stock_qty", fallback_qty)
    amt_idx = cols.get("stock_amount", fallback_amt)
    # 按货号聚合：同一货号多行（多仓库/库位）数量、金额相加，避免唯一键 (data_date, sku_code) 只保留最后一行导致统计偏小（用 itertuples 替代 iterrows，按 sku 只保留首行索引，写库时再取行，减少拷贝与遍历）
    agg = {}  # sku -> (qty_sum, amount_sum, first_row_index)
    for i, row in enumerate(data_rows.itertuples(index=False, name=None)):
        row = tuple(row)
        sku = _row_val(row, sku_idx)
        if not sku:
            continue
        if _is_summary_like(sku):
            continue
        cat = _row_val(row, cols.get("category", 3))
        pn = _row_val(row, cols.get("product_name", 6))
        if _is_summary_like(cat or "") or _is_summary_like(pn or ""):
            continue
        qty = _row_val(row, qty_idx, as_decimal=True) or 0
        amount = _row_val(row, amt_idx, as_decimal=True) or 0
        if amount == 0 and qty:
            ap = _row_val(row, cols.get("avg_price", 16), as_decimal=True)
            if ap:
                amount = ap * qty
        if sku not in agg:
            agg[sku] = [0, 0, i]
        agg[sku][0] += qty
        agg[sku][1] += amount
    cur = conn.cursor()
    inserted = 0
    col_list = None
    buf = []
    # STOCK_V2_EXTRA 仅适用于「库存查询」类宽表（≥26 列含大类/中类/小类）；24 列「实时库存」与 STOCK_FULL 列位一致，若误合并会把第 6 列商品名称写入 category_mid_code 导致超长报错
    full_map = STOCK_FULL + (STOCK_V2_EXTRA if ncol >= 26 else [])

    def flush_stock_batch():
        nonlocal inserted, col_list
        if not buf:
            return
        try:
            _batch_insert_stock(cur, col_list, buf)
            inserted += len(buf)
        except Exception:
            for (first_row, qty_sum, amt_sum) in buf_rows:
                if _import_stock_full(first_row, data_date, cur, cols, full_map):
                    inserted += 1
        buf.clear()
        buf_rows.clear()

    buf_rows = []  # 与 buf 一一对应，用于 fallback 时调用 _import_stock_full(first_row,...)

    for sku, (qty_sum, amt_sum, first_i) in agg.items():
        if _is_summary_like(sku):
            continue
        first_row = data_rows.iloc[first_i].copy()
        if qty_idx < len(first_row):
            first_row.iloc[qty_idx] = qty_sum
        if amt_idx < len(first_row):
            first_row.iloc[amt_idx] = amt_sum
        all_cols, all_vals = _build_stock_row_vals(first_row, data_date, qty_sum, amt_sum, cols, full_map)
        if all_cols is None:
            continue
        if col_list is None:
            col_list = all_cols
        buf.append(all_vals)
        buf_rows.append((first_row, qty_sum, amt_sum))
        if len(buf) >= _IMPORT_BATCH_SIZE:
            flush_stock_batch()
    flush_stock_batch()
    conn.commit()
    total_qty = sum(a[0] for a in agg.values())
    total_amt = sum(a[1] for a in agg.values())
    diag = f"库存: 导入{inserted}条, 合计数量{total_qty:,.0f}件, 合计金额{total_amt:,.2f}元"
    return inserted, diag