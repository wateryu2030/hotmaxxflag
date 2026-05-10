# -*- coding: utf-8 -*-
"""品类附表 / 税率负担 / 毛利汇总 Excel 读取、解析、写入 — Phase 2 批次 3"""
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


def _detect_tax_burden_cols(df):
    """检测税率负担表列：编码、名称、毛利率(0-1)、前台显示、微小店状态、税收分类编码、税率"""
    default = {"code": 0, "name": 1, "gross_margin": 2, "front_display": 3, "minishop_status": 4, "tax_class_code": 5, "tax_rate": 6}
    if df.shape[0] < 2 or df.shape[1] < 4:
        return default, 1
    for h_idx in range(min(8, df.shape[0])):
        row = df.iloc[h_idx]
        filled = _header_row_forward_fill(row)
        cols = {}
        for c in range(min(len(filled), 15)):
            v = str(filled[c]).strip()
            if not v:
                continue
            if v == "编码" or "编码" in v and "分类" not in v and "税收" not in v:
                cols["code"] = c
            elif v == "名称" or "名称" in v:
                cols["name"] = c
            elif "毛利率" in v or "毛利" in v:
                cols["gross_margin"] = c
            elif "前台显示" in v:
                cols["front_display"] = c
            elif "微小店" in v:
                cols["minishop_status"] = c
            elif "税收分类编码" in v:
                cols["tax_class_code"] = c
            elif v == "税率" or "税率" in v:
                cols["tax_rate"] = c
        if len(cols) >= 2:
            for k, v in default.items():
                if k not in cols:
                    cols[k] = v
            return cols, h_idx + 1
    return default, 1


def import_tax_burden(excel_path, conn):
    """导入税率负担表 Excel 到 t_htma_tax_burden。按编码：已存在则覆盖，不存在则新增。"""
    df = _read_excel_safe(excel_path)
    df = _trim_leading_junk_rows(df, ("编码", "名称", "毛利率", "税率", "税收分类", "前台显示", "微小店"))
    df = df.dropna(how="all", axis=0).reset_index(drop=True)
    if df.shape[0] < 2:
        return 0
    cols, start_row = _detect_tax_burden_cols(df)
    data_rows = df.iloc[start_row:]
    cur = conn.cursor()
    inserted = 0
    for _, row in data_rows.iterrows():
        code = _row_val(row, cols.get("code", 0))
        name = _row_val(row, cols.get("name", 1))
        if not code or not str(code).strip():
            continue
        code = str(code).strip()[:32]
        name = (str(name).strip() or "未命名")[:128]
        gross_margin = _safe_decimal(_row_val(row, cols.get("gross_margin", 2)), 0)
        front_display = _row_val(row, cols.get("front_display", 3)) or "是"
        front_display = str(front_display).strip()[:8] or "是"
        minishop_status = _safe_str(_row_val(row, cols.get("minishop_status", 4)), 32)
        tax_class_code = _safe_str(_row_val(row, cols.get("tax_class_code", 5)), 32)
        tax_rate = _safe_decimal(_row_val(row, cols.get("tax_rate", 6)), 0)
        try:
            cur.execute("""
                INSERT INTO t_htma_tax_burden (code, name, gross_margin, front_display, minishop_status, tax_class_code, tax_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    gross_margin = VALUES(gross_margin),
                    front_display = VALUES(front_display),
                    minishop_status = VALUES(minishop_status),
                    tax_class_code = VALUES(tax_class_code),
                    tax_rate = VALUES(tax_rate)
            """, (code, name, gross_margin, front_display, minishop_status, tax_class_code, tax_rate))
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
    # 按 (日期, 品类) 去重合并后再写入，避免重复数据
    agg_profit = {}  # category -> (total_sale_sum, total_profit_sum, category_large)
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
        cat_s = (str(cat or "").strip())[:32]
        large_s = (str(large or "").strip())[:32]
        if cat_s in SALE_SUMMARY_ROW_KEYWORDS or large_s in SALE_SUMMARY_ROW_KEYWORDS:
            continue
        if _is_summary_like(cat_s) or _is_summary_like(large_s):
            continue
        category = (cat or large or "未分类").strip()[:64]
        total_profit = total_sale - cost
        if category not in agg_profit:
            agg_profit[category] = [0, 0, last_large[:64] if last_large else None]
        agg_profit[category][0] += total_sale
        agg_profit[category][1] += total_profit

    for category, (sale_sum, profit_sum, large_val) in agg_profit.items():
        profit_rate = profit_sum / sale_sum if sale_sum and sale_sum > 0 else 0
        profit_rate = max(-1, min(1, profit_rate))
        try:
            cur.execute("""
                INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id, category_large)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE total_sale=VALUES(total_sale), total_profit=VALUES(total_profit), profit_rate=VALUES(profit_rate), category_large=COALESCE(VALUES(category_large),category_large)
            """, (data_date, category, sale_sum, profit_sum, profit_rate, STORE_ID, large_val))
            inserted += 1
        except Exception as e:
            if "Unknown column" in str(e) and "category_large" in str(e):
                cur.execute("""
                    INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE total_sale=VALUES(total_sale), total_profit=VALUES(total_profit), profit_rate=VALUES(profit_rate)
                """, (data_date, category, sale_sum, profit_sum, profit_rate, STORE_ID))
                inserted += 1
            else:
                skipped += 1
    conn.commit()
    diag = None
    if inserted == 0 and skipped > 0:
        diag = f"毛利表: 总行{len(data_rows)}, 跳过{skipped}行"
    return inserted, diag
