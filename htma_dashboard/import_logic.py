# -*- coding: utf-8 -*-
"""Excel 导入逻辑：完整导入所有合规数据到 MySQL"""
import os
import re
from datetime import datetime

import pandas as pd
import pymysql

STORE_ID = "沈阳超级仓"


def _safe_decimal(v, default=0):
    """数值解析，支持千分位逗号（如 18,000.00）。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
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


# 销售/毛利/库存 Excel 中视为「汇总行」的货号或品类，导入时跳过，避免重复计入（含「汇总数据」等导出统计行）
SALE_SUMMARY_ROW_KEYWORDS = frozenset({"总计", "合计", "小计", "求和项", "汇总", "合计行", "总计行", "小计行", "货号", "汇总数据"})
# 任一字段「包含」以下词即视为汇总行（导出的统计结果，非明细）
SUMMARY_SUBSTRINGS = ("合计", "总计", "小计", "汇总", "求和项", "合计行", "总计行", "小计行", "汇总数据")


def _is_summary_like(s):
    """字符串是否包含汇总类关键词（合计/总计/小计等），用于严格过滤导出中的统计行"""
    if not s or not str(s).strip():
        return False
    t = str(s).strip()
    for k in SUMMARY_SUBSTRINGS:
        if k in t:
            return True
    return False


def _is_sale_summary_row(row, cols):
    """判断是否为汇总行（总计/合计/小计/汇总数据等），这类行不应作为明细导入，否则会重复计算"""
    sku = _row_val(row, cols.get("sku", cols.get("sku_code", 2)))
    cat = _row_val(row, cols.get("category", 9))
    pn = _row_val(row, cols.get("product_name", 3))
    sku_s = (str(sku or "").strip())[:64]
    cat_s = (str(cat or "").strip())[:64]
    pn_s = (str(pn or "").strip())[:128]
    if sku_s and sku_s in SALE_SUMMARY_ROW_KEYWORDS:
        return True
    if cat_s and cat_s in SALE_SUMMARY_ROW_KEYWORDS:
        return True
    if _is_summary_like(sku_s) or _is_summary_like(cat_s):
        return True
    if _is_summary_like(pn_s):
        return True
    # 部分导出在货号列写「求和项:销售金额」等
    if sku_s and ("求和项" in sku_s or "总计" in sku_s or "合计" in sku_s):
        return True
    # 货号为 0/000000 且品类或品名含合计/小计/汇总：多为导出中的「合计行」，跳过
    if sku_s and sku_s.replace("0", "") == "" and len(sku_s) <= 10:
        if _is_summary_like(cat_s) or _is_summary_like(pn_s):
            return True
    return False


def _row_val_raw(row, idx):
    """取行中某列原始值，支持 Series 或 tuple/list（itertuples 等），用于日期时间等需原始类型的场景。"""
    if idx is None or idx < 0:
        return None
    if isinstance(row, (tuple, list)):
        return row[idx] if idx < len(row) else None
    if hasattr(row, "iloc"):
        return row.iloc[idx] if idx < len(row) else None
    return None


def _row_val(row, idx, default=None, as_decimal=False):
    if idx is None or idx < 0 or idx >= len(row):
        return _safe_decimal(default, 0) if as_decimal else default
    if isinstance(row, (tuple, list)):
        v = row[idx] if idx < len(row) else None
    else:
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



# ── Phase 2 批次 2b：销售/库存导入已迁至 ingest/sale_excel.py ──
from ingest.sale_excel import (
    _detect_sale_cols, preview_sale_excel, import_sale_daily,
    _build_sale_row_vals, _batch_insert_sale, _import_sale_full,
    import_sale_summary, _detect_stock_cols, import_stock,
    _build_stock_row_vals, _batch_insert_stock, _import_stock_full,
    SALE_DAILY_FULL, SALE_DAILY_COLS, SALE_SUMMARY_FULL, SALE_SUMMARY_COLS,
    STOCK_FULL, STOCK_V2_EXTRA, STOCK_COLS, STOCK_NEW_COLS,
)
from ingest.helpers import _read_excel_safe

# ── Phase 批次 5：人力/商品档案导入已迁出 ──
from ingest.labor import (
    import_labor_cost, import_labor_cost_from_image,
)
from ingest.product_master import (
    import_product_master, _flush_product_master_batch,
    _ensure_product_master_distribution_mode,
)
from clean.labor_analysis import (
    refresh_labor_cost_analysis,
)



# ── Phase 2 批次 3：品类/税务/利润导入已迁至 ingest/category_tax_profit.py ──
from ingest.category_tax_profit import (
    _detect_category_cols, import_category,
    _detect_tax_burden_cols, import_tax_burden,
    _detect_profit_cols, import_profit,
)



# ── Phase 3：清洗/同步函数已迁至 clean/sale_profit_sync.py ──
from clean.sale_profit_sync import (
    refresh_category_from_sale,
    SALE_TABLE_EXTRA_COLUMNS,
    ensure_sale_table_columns,
    backfill_sale_category_and_supplier,
    sync_products_table,
    sync_category_table,
    refresh_profit,
)


# ---------- 人力成本导入（组长表 + 全职表，附图格式）----------






