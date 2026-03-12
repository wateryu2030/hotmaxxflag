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


def import_sale_daily(excel_path, conn, overwrite_on_duplicate=False):
    """销售日报表：支持表头检测。仅写入 t_htma_sale（增量/覆盖），不触碰库存/人力/品类/商品档案。overwrite_on_duplicate=True 时同(日期,货号)覆盖不累加（与汇总同传时防翻倍）。"""
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
    full_map = STOCK_FULL + STOCK_V2_EXTRA

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


def refresh_category_from_sale(conn):
    """从销售表透视大类/中类/小类，写入品类主数据表 t_htma_category。仅操作 t_htma_category，不触碰销售/库存/人力/商品档案表。"""
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


# t_htma_sale 表需有的大类/中类/小类/供应商/品牌等列（与 run_add_columns 一致，用于导入前确保列存在）
SALE_TABLE_EXTRA_COLUMNS = [
    ("category_large_code", "VARCHAR(32) DEFAULT NULL COMMENT '大类编码'"),
    ("category_large", "VARCHAR(64) DEFAULT NULL COMMENT '大类名称'"),
    ("category_mid_code", "VARCHAR(32) DEFAULT NULL COMMENT '中类编码'"),
    ("category_mid", "VARCHAR(64) DEFAULT NULL COMMENT '中类名称'"),
    ("category_small_code", "VARCHAR(32) DEFAULT NULL COMMENT '小类编码'"),
    ("category_small", "VARCHAR(64) DEFAULT NULL COMMENT '小类名称'"),
    ("supplier_code", "VARCHAR(64) DEFAULT NULL COMMENT '供应商编码'"),
    ("supplier_name", "VARCHAR(128) DEFAULT NULL COMMENT '供应商名称'"),
    ("supplier_main_code", "VARCHAR(64) DEFAULT NULL COMMENT '主供应商编码'"),
    ("supplier_main_name", "VARCHAR(128) DEFAULT NULL COMMENT '主供应商名称'"),
    ("brand_code", "VARCHAR(32) DEFAULT NULL COMMENT '品牌编码'"),
    ("brand_name", "VARCHAR(64) DEFAULT NULL COMMENT '品牌名称'"),
]


def ensure_sale_table_columns(conn):
    """确保 t_htma_sale 存在大类/中类/小类/供应商/品牌等列；缺则 ADD COLUMN，已存在则跳过（便于未跑过 run_add_columns 的环境）。"""
    cur = conn.cursor()
    for col, defn in SALE_TABLE_EXTRA_COLUMNS:
        try:
            cur.execute(f"ALTER TABLE t_htma_sale ADD COLUMN {col} {defn}")
            conn.commit()
        except pymysql.err.OperationalError as e:
            if "Duplicate column" in str(e):
                pass
            else:
                raise
    cur.close()


def backfill_sale_category_and_supplier(conn, store_id: str = None):
    """
    透视回填：对 t_htma_sale 中大类/中类/小类/供应商/品牌为空的记录，
    1) 从 t_htma_product_master 按 sku_code+store_id 回填 brand_name、supplier_name；
    2) 若有 category（类别名称）但无大类/中类/小类，则用 category 回填 category_small/category_mid/category_large；
    3) 再调用 refresh_category_from_sale 更新 t_htma_category。
    """
    store_id = store_id or STORE_ID
    cur = conn.cursor()
    try:
        # 1) 从商品档案回填品牌、供应商（仅当 sale 中为空时）
        cur.execute("""
            UPDATE t_htma_sale s
            INNER JOIN t_htma_product_master p ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            SET
                s.brand_name = COALESCE(NULLIF(TRIM(s.brand_name), ''), p.brand_name),
                s.supplier_name = COALESCE(NULLIF(TRIM(s.supplier_name), ''), p.supplier_name)
            WHERE s.store_id = %s
              AND (COALESCE(TRIM(s.brand_name), '') = '' OR COALESCE(TRIM(s.supplier_name), '') = '')
        """, (store_id,))
        conn.commit()
        # 2) 用 category 回填大类/中类/小类（仅当三者均为空且 category 有值时）
        cur.execute("""
            UPDATE t_htma_sale
            SET
                category_large = COALESCE(NULLIF(TRIM(category_large), ''), category),
                category_mid = COALESCE(NULLIF(TRIM(category_mid), ''), category),
                category_small = COALESCE(NULLIF(TRIM(category_small), ''), category)
            WHERE store_id = %s
              AND COALESCE(TRIM(category_large), '') = ''
              AND COALESCE(TRIM(category_mid), '') = ''
              AND COALESCE(TRIM(category_small), '') = ''
              AND COALESCE(TRIM(category), '') != ''
        """, (store_id,))
        conn.commit()
        # 3) 刷新品类主数据表
        refresh_category_from_sale(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def sync_products_table(conn, store_id: str = "沈阳超级仓", days: int = 90) -> int:
    """
    从 t_htma_sale + t_htma_stock 同步商品主表 t_htma_products。
    唯一性：store_id+sku_code；有条码必录（供比价）；粒度与比价分析配合。
    若表不存在则先创建，避免新环境报错。
    """
    cur = conn.cursor()
    create_sql = """
        CREATE TABLE IF NOT EXISTS t_htma_products (
          id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
          store_id        VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
          sku_code        VARCHAR(64)     NOT NULL COMMENT 'SKU编码',
          product_name    VARCHAR(128)    DEFAULT NULL,
          raw_name        VARCHAR(128)    DEFAULT NULL,
          spec            VARCHAR(64)     DEFAULT NULL,
          barcode         VARCHAR(64)     DEFAULT NULL,
          brand_name      VARCHAR(64)     DEFAULT NULL,
          category        VARCHAR(64)     DEFAULT NULL,
          category_large  VARCHAR(64)     DEFAULT NULL,
          category_mid    VARCHAR(64)     DEFAULT NULL,
          category_small  VARCHAR(64)     DEFAULT NULL,
          category_large_code VARCHAR(32) DEFAULT NULL,
          category_mid_code   VARCHAR(32) DEFAULT NULL,
          category_small_code VARCHAR(32) DEFAULT NULL,
          unit_price      DECIMAL(12,2)   DEFAULT NULL,
          sale_qty        DECIMAL(12,2)   DEFAULT 0,
          sale_amount     DECIMAL(14,2)   DEFAULT 0,
          gross_profit    DECIMAL(14,2)   DEFAULT 0,
          sync_at         DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uk_store_sku (store_id, sku_code),
          KEY idx_barcode (barcode),
          KEY idx_cat_large (category_large),
          KEY idx_cat_mid (category_mid),
          KEY idx_cat_small (category_small)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品主表'
    """
    cur.execute(create_sql)
    conn.commit()
    insert_sql = """
        INSERT INTO t_htma_products
        (store_id, sku_code, product_name, raw_name, spec, barcode, brand_name,
         category, category_large, category_mid, category_small,
         category_large_code, category_mid_code, category_small_code,
         unit_price, sale_qty, sale_amount, gross_profit, sync_at)
        SELECT %s, s.sku_code,
               COALESCE(st.product_name, s.product_name, s.sku_code),
               COALESCE(st.product_name, s.product_name, s.sku_code),
               MAX(COALESCE(st.spec, s.spec)),
               NULLIF(TRIM(MAX(COALESCE(st.barcode, s.barcode))), ''),
               MAX(COALESCE(st.brand_name, s.brand_name)),
               MAX(s.category), MAX(s.category_large), MAX(s.category_mid), MAX(s.category_small),
               MAX(s.category_large_code), MAX(s.category_mid_code), MAX(s.category_small_code),
               SUM(s.sale_amount)/NULLIF(SUM(s.sale_qty),0),
               COALESCE(SUM(s.sale_qty),0), COALESCE(SUM(s.sale_amount),0), COALESCE(SUM(s.gross_profit),0),
               NOW()
        FROM t_htma_sale s
        LEFT JOIN t_htma_stock st ON st.sku_code = s.sku_code AND st.store_id = s.store_id
            AND st.data_date = (SELECT MAX(t.data_date) FROM t_htma_stock t WHERE t.store_id = %s)
        WHERE s.store_id = %s AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY s.sku_code, st.product_name, s.product_name, s.category, s.category_large, s.category_mid, s.category_small
        ON DUPLICATE KEY UPDATE
            product_name=VALUES(product_name), raw_name=VALUES(raw_name),
            spec=VALUES(spec), barcode=COALESCE(VALUES(barcode), barcode),
            brand_name=VALUES(brand_name),
            category=VALUES(category), category_large=VALUES(category_large),
            category_mid=VALUES(category_mid), category_small=VALUES(category_small),
            category_large_code=VALUES(category_large_code), category_mid_code=VALUES(category_mid_code),
            category_small_code=VALUES(category_small_code),
            unit_price=VALUES(unit_price), sale_qty=VALUES(sale_qty),
            sale_amount=VALUES(sale_amount), gross_profit=VALUES(gross_profit),
            sync_at=NOW()
    """
    try:
        cur.execute(insert_sql, (store_id, store_id, store_id, days))
    except Exception as e:
        err_code = e.args[0] if getattr(e, "args", None) and len(e.args) > 0 else None
        if err_code == 1146:  # Table doesn't exist
            cur.execute(create_sql)
            conn.commit()
            cur.execute(insert_sql, (store_id, store_id, store_id, days))
        else:
            raise
    conn.commit()
    cnt = cur.rowcount
    cur.close()
    return cnt


def sync_category_table(conn, store_id: str = "沈阳超级仓", days: int = 30) -> int:
    """
    从 t_htma_profit 汇总同步品类毛利表 t_htma_category_profit。
    品类维度：总销售额、总毛利、毛利率、SKU数、销售笔数、周期。
    若表不存在则先创建，确保导入后自动化更新品类表。
    """
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS t_htma_category_profit (
          id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
          store_id            VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
          category            VARCHAR(64)     NOT NULL COMMENT '品类/小类',
          category_large_code VARCHAR(32)     DEFAULT NULL,
          category_large      VARCHAR(64)     DEFAULT NULL,
          category_mid_code   VARCHAR(32)     DEFAULT NULL,
          category_mid        VARCHAR(64)     DEFAULT NULL,
          category_small_code VARCHAR(32)     DEFAULT NULL,
          category_small      VARCHAR(64)     DEFAULT NULL,
          total_sale          DECIMAL(14,2)   NOT NULL DEFAULT 0,
          total_profit        DECIMAL(14,2)   NOT NULL DEFAULT 0,
          profit_rate         DECIMAL(6,4)    DEFAULT NULL,
          sku_count           INT             DEFAULT 0,
          sale_count          INT             DEFAULT 0,
          period_start        DATE            DEFAULT NULL,
          period_end          DATE            DEFAULT NULL,
          sync_at             DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uk_store_cat (store_id, category),
          KEY idx_cat_large (category_large),
          KEY idx_cat_mid (category_mid)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='品类毛利汇总'
    """)
    cur.execute("""
        INSERT INTO t_htma_category_profit
        (store_id, category, category_large, category_mid, category_small,
         category_large_code, category_mid_code, category_small_code,
         total_sale, total_profit, profit_rate, sku_count, sale_count,
         period_start, period_end, sync_at)
        SELECT store_id, category,
               MAX(category_large), MAX(category_mid), MAX(category_small),
               MAX(category_large_code), MAX(category_mid_code), MAX(category_small_code),
               SUM(total_sale), SUM(total_profit),
               CASE WHEN SUM(total_sale) > 0 THEN SUM(total_profit)/SUM(total_sale) ELSE NULL END,
               0,
               COUNT(*),
               MIN(data_date), MAX(data_date),
               NOW()
        FROM t_htma_profit
        WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY store_id, category
        ON DUPLICATE KEY UPDATE
            category_large=VALUES(category_large), category_mid=VALUES(category_mid), category_small=VALUES(category_small),
            category_large_code=VALUES(category_large_code), category_mid_code=VALUES(category_mid_code),
            category_small_code=VALUES(category_small_code),
            total_sale=VALUES(total_sale), total_profit=VALUES(total_profit), profit_rate=VALUES(profit_rate),
            sku_count=VALUES(sku_count), sale_count=VALUES(sale_count),
            period_start=VALUES(period_start), period_end=VALUES(period_end),
            sync_at=NOW()
    """, (store_id, days))
    conn.commit()
    cnt = cur.rowcount
    cur.close()
    return cnt


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


# ---------- 人力成本导入（组长表 + 全职表，附图格式）----------

def _normalize_header(h):
    """表头规范化：去掉 求和项:、换行、括号说明、合并空格等，便于匹配（如「姓  名」→「姓名」）"""
    if h is None or (isinstance(h, float) and pd.isna(h)):
        return ""
    s = str(h).replace("\n", " ").replace("\r", " ").strip()
    if s.startswith("求和项:"):
        s = s[4:].strip()
    if "(" in s:
        s = s.split("(")[0].strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_position_name(s, max_len=64):
    """清洗岗位/属性名：去首尾空白、合并连续空格、截断长度，便于归类与展示。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip()
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t)
    return t[:max_len] if len(t) > max_len else t


def _normalize_person_name(s, max_len=64):
    """清洗姓名：去空白、合并空格；若为纯数字或序号则返回空，便于用行号区分而不误存为姓名。"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip()
    if not t:
        return ""
    try:
        float(t)
        return ""
    except (TypeError, ValueError):
        pass
    if t.isdigit() or (len(t) <= 4 and t.replace(".", "").isdigit()):
        return ""
    t = re.sub(r"\s+", " ", t)
    return t[:max_len] if len(t) > max_len else t


def _supplier_from_sheet(sheet_name, max_len=64):
    """从 sheet 名推断供应商，与汇总表口径一致：斗米/中锐/快聘/保洁。"""
    if not sheet_name:
        return "斗米"[:max_len]
    s = str(sheet_name).strip()
    if "保洁" in s:
        return "保洁"[:max_len]
    if "中锐" in s:
        return "中锐"[:max_len]
    if "快聘" in s:
        return "快聘"[:max_len]
    return "斗米"[:max_len]


def import_labor_cost(excel_path, report_month, conn, store_id=None):
    """
    导入人力成本 Excel：支持单 sheet 或多 sheet，自动识别类型并归类。
    用工类型与汇总表一致：管理组→leader(组长)、全职→fulltime(组员)、保洁全职→cleaner、兼职→parttime、小时工→hourly；
    成本以「开票金额/总成本」为准；供应商(斗米/中锐/快聘/保洁)从列或 sheet 名解析。
    组长/组员 sheet：全部到人导入（姓名为空或汇总行跳过）；兼职/小时工/保洁：到人且每人有人名。
    report_month 如 2026-01。返回 (counts_dict, diagnostics)。
    仅操作 t_htma_labor_cost（先按 report_month 删除该月再写入），不触碰销售/库存/品类/商品档案表。
    """
    store_id = store_id or STORE_ID
    counts = {"leader": 0, "fulltime": 0, "parttime": 0, "hourly": 0, "cleaner": 0, "management": 0}
    diagnostics = []
    n_to_person_with_real_name = [0]
    n_to_person_total = [0]
    # 唯一键 (report_month, position_type, position_name, person_name, supplier_name, store_id)。
    # 同键重复时不再合并：第一人用本名，第2次用 姓名1，第3次用 姓名2，确保人数与汇总一致。
    _seen_keys = {}  # report_month -> dict: key -> 已出现次数 (0=首条用本名, 1=第2条用名+1, 2=第3条用名+2...)
    duplicates = []  # 仅记录“因重复而加了后缀”的人员，用于日志提示

    def _dup_key(ptype, pos_name, person_name, supplier_name):
        pn = (person_name or "").strip()[:64]
        sup = (supplier_name or "").strip()[:64]
        key = (ptype, (pos_name or "").strip()[:64], pn, sup)
        return key

    def _person_name_with_suffix(report_month, ptype, pos_name, person_name, supplier_name):
        """若该键已出现过，返回 姓名+后缀（姓名1、姓名2…），否则返回原姓名；并更新计数。"""
        key = _dup_key(ptype, pos_name, person_name, supplier_name)
        if report_month not in _seen_keys:
            _seen_keys[report_month] = {}
        count = _seen_keys[report_month].get(key, -1) + 1
        _seen_keys[report_month][key] = count
        if count == 0:
            return (person_name or "").strip() or ""
        suffix = str(count)  # 第2条 -> 1, 第3条 -> 2
        base = (person_name or "").strip() or "-"
        if base.startswith("#"):
            return base + suffix  # #1 -> #11, #12
        duplicates.append({
            "report_month": report_month,
            "position_type": ptype,
            "person_name": base,
            "position_name": (pos_name or "").strip() or "-",
            "supplier_name": (supplier_name or "").strip() or "-",
            "suffix": suffix,
        })
        return base + suffix  # 高伟 -> 高伟1, 高伟2

    # 导入前删除该月数据，避免旧逻辑（person_name 空）与新逻辑（到人）并存造成重复，避免旧逻辑（person_name 空）与新逻辑（到人）并存造成重复
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM t_htma_labor_cost WHERE report_month = %s", (report_month,))
        conn.commit()
    except Exception as e:
        diagnostics.append("清理该月数据时: " + str(e))

    def _safe_num(v, default=0):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        try:
            if isinstance(v, str):
                v = v.replace(",", "").strip()
            return float(v)
        except (TypeError, ValueError):
            return default

    def _is_skip_position(name):
        if name is None or (isinstance(name, float) and pd.isna(name)):
            return True
        if not str(name).strip():
            return True
        t = str(name).strip().lower()
        if t in ("nan", "none", "#n/a", "-"):
            return True
        for k in ("合计", "总计", "小计", "汇总", "求和项"):
            if k in t:
                return True
        return False

    def _is_skip_person_row(name_val):
        """姓名为空或为汇总关键字（合计、小计等）时视为汇总行，跳过该行，避免重复计算。"""
        if name_val is None or (isinstance(name_val, float) and pd.isna(name_val)):
            return True
        t = str(name_val).strip()
        if not t:
            return True
        t_lower = t.lower()
        if t_lower in ("nan", "none", "#n/a", "-"):
            return True
        for k in ("合计", "总计", "小计", "汇总", "求和项"):
            if k in t_lower:
                return True
        if t.isdigit() or (len(t) <= 6 and t.replace(".", "", 1).replace("-", "", 1).isdigit()):
            return True
        return False

    def _is_header_or_invalid_row(pos_val, row, pos_col, num_cols):
        """表头行或无效行：岗位列为「岗位」字样、纯序号、空；仅保留有效数据行"""
        if pos_val is None:
            return True
        t = str(pos_val).strip()
        if not t:
            return True
        if "岗位" == t or "求和项:岗位" in t or t.replace(" ", "") == "岗位" or t == "职务":
            return True
        if t.isdigit() and len(t) <= 5:
            return True
        if num_cols:
            has_num = any(_safe_num(row.get(c)) != 0 for c in num_cols if c is not None)
            if not has_num and len(t) < 3:
                return True
        return False

    try:
        xl = pd.ExcelFile(excel_path)
        sheets = xl.sheet_names
    except Exception as e:
        diagnostics.append(str(e))
        return counts, diagnostics, []

    for sheet_name in sheets:
        # 跳过汇总表 sheet（合计/跟发票或发薪对应）：仅人数与总成本，无到人明细，避免重复计入
        _sn = (sheet_name or "").strip()
        if "合计" in _sn and ("发票" in _sn or "发薪" in _sn or "对应" in _sn):
            continue
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
        if df.shape[0] == 0:
            continue
        # 按 sheet 名称优先判定类型：组长/管理组、组员/全职、兼职、小时工、保洁、管理岗（全面识别各 sheet）
        sheet_name_lower = _sn.lower()
        preferred_leader = "组长" in sheet_name_lower or "管理组" in sheet_name_lower
        preferred_fulltime = "组员" in sheet_name_lower or ("全职" in sheet_name_lower and "保洁" not in sheet_name_lower)

        header_row = 0
        for r in range(min(12, df.shape[0])):
            row = df.iloc[r]
            for c in range(min(50, len(row))):
                v = str(row.iloc[c]).strip() if c < len(row) else ""
                if any(k in v for k in (
                    "岗位", "职务", "合计薪资", "总工时", "本月合计薪资", "费用总额",
                    "费用合计", "属性", "开票金额", "总成本",
                )):
                    header_row = r
                    break
            else:
                continue
            break
        df_header = pd.read_excel(excel_path, sheet_name=sheet_name, header=header_row)
        df_header = df_header.dropna(how="all", axis=0).dropna(how="all", axis=1)
        col_map = {}
        for col in df_header.columns:
            n = _normalize_header(col)
            if n:
                col_map[col] = n

        # 岗位列：组长表可能用「职务」，组员表用「岗位」；先确定 pos_col 再对合并单元格做向前填充
        pos_col = None
        for c in df_header.columns:
            nm = col_map.get(c) or _normalize_header(str(c))
            if "岗位" in nm:
                pos_col = c
                break
        if not pos_col and (preferred_leader or not preferred_fulltime):
            for c in df_header.columns:
                nm = col_map.get(c) or _normalize_header(str(c))
                if "职务" in nm:
                    pos_col = c
                    break
        if not pos_col and ("兼职" in sheet_name_lower or "小时工" in sheet_name_lower):
            for c in df_header.columns:
                nm = col_map.get(c) or _normalize_header(str(c))
                if "属性" in nm:
                    pos_col = c
                    break
        if not pos_col:
            for c in df_header.columns:
                nm = col_map.get(c) or _normalize_header(str(c))
                if "姓名" in nm or "人员" in nm or "名字" in nm:
                    pos_col = c
                    break
        has_any_cost_col = any(
            (col_map.get(c) or "").find("费用") >= 0 or (col_map.get(c) or "").find("开票") >= 0 or (col_map.get(c) or "").find("总成本") >= 0
            for c in df_header.columns
        )
        if not pos_col and has_any_cost_col:
            first_col = df_header.columns[0] if len(df_header.columns) else None
            if first_col is not None:
                pos_col = first_col
        if not pos_col:
            continue

        # 岗位/职务列合并单元格：向前填充，避免同一岗位多行只显示首行、其余为 NaN
        if pos_col in df_header.columns:
            df_header[pos_col] = df_header[pos_col].ffill()

        has_total_cost = any("费用总额" in (col_map.get(c) or "") or "人力成本" in (col_map.get(c) or "") or "开票金额" in (col_map.get(c) or "") or "总成本" in (col_map.get(c) or "") for c in df_header.columns)
        has_fee_total = any("费用合计" in (col_map.get(c) or "") for c in df_header.columns)
        has_luxury_bonus = any("奢品奖金" in (col_map.get(c) or "") for c in df_header.columns)
        has_work_hours = any("总工时" in (col_map.get(c) or "") or "12月" in (col_map.get(c) or "") or "当月总工时" in (col_map.get(c) or "") or "本月总工时" in (col_map.get(c) or "") for c in df_header.columns)
        has_base_salary = any("基本工资" in (col_map.get(c) or "") for c in df_header.columns)

        def _col(name, fallbacks=None):
            for c in df_header.columns:
                n = col_map.get(c) or _normalize_header(str(c))
                if n == name or (fallbacks and any(f in n for f in fallbacks)):
                    return c
                if name == "姓名" and n.replace(" ", "").replace("\u3000", "") == "姓名":
                    return c
            return None

        def _total_cost_col():
            """优先取开票金额/总成本（与汇总表口径一致），再取费用总额、公司实际成本。"""
            col = _col("开票金额", ["开票金额/总成本", "总成本", "开票金额"])
            if col is not None:
                return col
            col = _col("费用总额", ["费用总额", "人力成本总额", "含服务费"])
            if col is not None:
                return col
            return _col("公司实际成本")

        supplier_col = _col("供应商")
        default_supplier = _supplier_from_sheet(sheet_name)

        def _row_supplier(row):
            v = row.get(supplier_col) if supplier_col is not None else None
            v = _normalize_position_name(v) if v is not None else ""
            return (v or default_supplier)[:64]

        # 组长表：按 sheet 名或列特征；明确为兼职/小时工 sheet 时不做组长表
        is_leader_table = (has_total_cost or has_luxury_bonus) and not has_work_hours
        if preferred_leader:
            is_leader_table = True
        if preferred_fulltime or "兼职" in sheet_name_lower or "小时工" in sheet_name_lower:
            is_leader_table = False
        is_fulltime_table = has_work_hours and has_base_salary
        if preferred_fulltime:
            is_fulltime_table = True
        if preferred_leader:
            is_fulltime_table = False
        # 兼职/小时工：有「费用合计」或「开票金额/总成本」即视为成本列，与汇总表口径一致
        has_cost_for_ph = has_fee_total or has_total_cost
        is_parttime_table = "兼职" in sheet_name_lower and has_cost_for_ph and pos_col is not None
        is_hourly_table = "小时工" in sheet_name_lower and has_cost_for_ph and pos_col is not None
        is_cleaner_table = "保洁" in sheet_name_lower
        is_management_table = ("管理岗" in sheet_name_lower or "宝赞" in sheet_name_lower) and (has_total_cost or has_fee_total)

        if is_cleaner_table or is_management_table:
            ptype = "cleaner" if "保洁" in sheet_name_lower else "management"
            total_cost_col = _total_cost_col()
            if total_cost_col is None and is_cleaner_table:
                # 保洁表可能无「开票金额/总成本」列，尝试：公司实际成本、应发、实发、本月应发、人力成本
                total_cost_col = _col("公司实际成本") or _col("应发") or _col("实发") or _col("本月应发") or _col("人力成本") or _col("应发工资")
            company_cost_col_other = _col("公司实际成本")
            person_col_other = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            first_col_other = df_header.columns[0] if len(df_header.columns) else None
            # 保洁表无单一费用列时，用 基本工资+绩效+岗位补贴+饭补 合计
            base_sal_col = _col("基本工资")
            perf_col = _col("绩效")
            allow_col = _col("岗位补贴")
            meal_col = _col("饭补")
            cur = conn.cursor()
            if person_col_other is not None:
                # 到人：每行一条，姓名为空或汇总行跳过
                for i, (_, row) in enumerate(df_header.iterrows()):
                    pos = row.get(pos_col)
                    if _is_skip_position(pos) or _is_skip_person_row(row.get(person_col_other)):
                        continue
                    pos_name = _normalize_position_name(pos)
                    if not pos_name:
                        continue
                    person_name = _normalize_person_name(row.get(person_col_other)) or ""
                    if not person_name and first_col_other is not None:
                        first_val = row.get(first_col_other)
                        person_name = _normalize_person_name(first_val) or ("#%d" % (i + 1))
                    cost_val = _safe_num(row.get(total_cost_col)) if total_cost_col else _safe_num(row.get(company_cost_col_other))
                    if not cost_val and company_cost_col_other:
                        cost_val = _safe_num(row.get(company_cost_col_other))
                    if not cost_val and is_cleaner_table and (base_sal_col is not None or perf_col is not None):
                        cost_val = _safe_num(row.get(base_sal_col)) + _safe_num(row.get(perf_col)) + _safe_num(row.get(allow_col)) + _safe_num(row.get(meal_col))
                    sup = _row_supplier(row)
                    person_name = _person_name_with_suffix(report_month, ptype, pos_name, person_name, sup)
                    cur.execute("""
                        INSERT INTO t_htma_labor_cost
                        (report_month, position_type, position_name, person_name, company_cost, total_cost, supplier_name, store_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                    """, (report_month, ptype, pos_name, person_name or "", cost_val, cost_val, sup, store_id))
                    counts[ptype] += 1
                    n_to_person_total[0] += 1
                    if person_name and not str(person_name).strip().startswith("#"):
                        n_to_person_with_real_name[0] += 1
            else:
                # 无姓名列：按岗位汇总
                agg_other = {}
                for _, row in df_header.iterrows():
                    pos = row.get(pos_col)
                    if _is_skip_position(pos):
                        continue
                    pos_name = _normalize_position_name(pos)
                    if not pos_name:
                        continue
                    cost_val = _safe_num(row.get(total_cost_col)) if total_cost_col else _safe_num(row.get(company_cost_col_other))
                    if not cost_val and company_cost_col_other:
                        cost_val = _safe_num(row.get(company_cost_col_other))
                    if pos_name not in agg_other:
                        agg_other[pos_name] = 0
                    agg_other[pos_name] += cost_val
                for pos_name, total_cost in agg_other.items():
                    person_name = _person_name_with_suffix(report_month, ptype, pos_name, "", default_supplier)
                    cur.execute("""
                        INSERT INTO t_htma_labor_cost
                        (report_month, position_type, position_name, person_name, company_cost, total_cost, supplier_name, store_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                    """, (report_month, ptype, pos_name, person_name or "", total_cost, total_cost, default_supplier, store_id))
                    counts[ptype] += 1
            conn.commit()
        elif is_leader_table:
            total_salary_col = _col("合计薪资")
            actual_salary_col = _col("实际薪资合计") or _col("实际薪资")
            luxury_bonus_col = _col("奢品奖金")
            actual_income_col = _col("实得收入")
            company_cost_col = _col("公司实际成本")
            total_cost_col = _total_cost_col()
            person_col = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            pre_tax_col = _col("税前应发", ["应发", "应发工资"])
            num_cols_leader = [total_salary_col, actual_salary_col, company_cost_col, total_cost_col]
            # 导入到人：每行一条明细，不汇总。姓名为空或汇总行（合计/小计等）跳过，避免重复计算
            first_col = df_header.columns[0] if len(df_header.columns) else None
            cur = conn.cursor()
            for i, (_, row) in enumerate(df_header.iterrows()):
                pos = row.get(pos_col)
                if _is_skip_position(pos) or _is_header_or_invalid_row(pos, row, pos_col, num_cols_leader):
                    continue
                if person_col is not None and _is_skip_person_row(row.get(person_col)):
                    continue
                pos_name = _normalize_position_name(pos)
                if not pos_name:
                    continue
                person_name = _normalize_person_name(row.get(person_col)) if person_col else ""
                if not person_name and first_col is not None:
                    first_val = row.get(first_col)
                    name_from_first = _normalize_position_name(first_val)
                    person_name = name_from_first if _normalize_person_name(name_from_first) else ("#%d" % (i + 1))
                total_s = _safe_num(row.get(total_salary_col))
                actual_s = _safe_num(row.get(actual_salary_col))
                luxury_b = _safe_num(row.get(luxury_bonus_col))
                actual_inc = _safe_num(row.get(actual_income_col))
                company_c = _safe_num(row.get(company_cost_col))
                tcost = _safe_num(row.get(total_cost_col)) or company_c
                pre_tax = _safe_num(row.get(pre_tax_col)) if pre_tax_col else total_s
                sup = _row_supplier(row)
                person_name = _person_name_with_suffix(report_month, "leader", pos_name, person_name, sup)
                cur.execute("""
                    INSERT INTO t_htma_labor_cost
                    (report_month, position_type, position_name, person_name, total_salary, pre_tax_pay, actual_salary, luxury_bonus,
                     actual_income, company_cost, total_cost, supplier_name, store_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                    total_salary=VALUES(total_salary), pre_tax_pay=VALUES(pre_tax_pay), actual_salary=VALUES(actual_salary),
                    luxury_bonus=VALUES(luxury_bonus), actual_income=VALUES(actual_income),
                    company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                """, (report_month, "leader", pos_name, person_name or "",
                      total_s, pre_tax, actual_s, luxury_b, actual_inc, company_c, tcost, sup, store_id))
                counts["leader"] += 1
                n_to_person_total[0] += 1
                if person_name and not str(person_name).strip().startswith("#"):
                    n_to_person_with_real_name[0] += 1
            conn.commit()
        elif is_fulltime_table:
            work_hours_col = _col("总工时", ["12月总工时", "总工时", "当月总工时", "本月总工时"]) or _col("12月总工时") or _col("当月总工时") or _col("本月总工时")
            base_salary_col = _col("基本工资")
            performance_col = _col("绩效", ["绩效工资"])
            position_allowance_col = _col("岗位补贴")
            total_salary_col = _col("合计薪资", ["本月合计薪资"])
            luxury_amount_col = _col("奢品", ["奢品奖金"])
            actual_income_col = _col("实得收入", ["本月实得收入"])
            company_cost_col = _col("公司实际成本")
            total_cost_col_ft = _total_cost_col()
            person_col_ft = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            pre_tax_col_ft = _col("税前应发", ["应发", "应发工资"])
            num_cols_fulltime = [work_hours_col, base_salary_col, total_salary_col, company_cost_col]
            first_col_ft = df_header.columns[0] if len(df_header.columns) else None
            cur = conn.cursor()
            for i, (_, row) in enumerate(df_header.iterrows()):
                pos = row.get(pos_col)
                if _is_skip_position(pos) or _is_header_or_invalid_row(pos, row, pos_col, num_cols_fulltime):
                    continue
                if person_col_ft is not None and _is_skip_person_row(row.get(person_col_ft)):
                    continue
                pos_name = _normalize_position_name(pos)
                if not pos_name:
                    continue
                person_name = _normalize_person_name(row.get(person_col_ft)) if person_col_ft else ""
                if not person_name and first_col_ft is not None:
                    first_val = row.get(first_col_ft)
                    name_from_first = _normalize_position_name(first_val)
                    person_name = name_from_first if _normalize_person_name(name_from_first) else ("#%d" % (i + 1))
                cost_val = _safe_num(row.get(total_cost_col_ft)) or _safe_num(row.get(company_cost_col))
                wh = _safe_num(row.get(work_hours_col))
                base_s = _safe_num(row.get(base_salary_col))
                perf = _safe_num(row.get(performance_col))
                allow = _safe_num(row.get(position_allowance_col))
                total_s = _safe_num(row.get(total_salary_col))
                luxury_a = _safe_num(row.get(luxury_amount_col))
                actual_inc = _safe_num(row.get(actual_income_col))
                company_c = _safe_num(row.get(company_cost_col))
                pre_tax = _safe_num(row.get(pre_tax_col_ft)) if pre_tax_col_ft else total_s
                sup = _row_supplier(row)
                person_name = _person_name_with_suffix(report_month, "fulltime", pos_name, person_name, sup)
                cur.execute("""
                    INSERT INTO t_htma_labor_cost
                    (report_month, position_type, position_name, person_name, work_hours, base_salary, performance,
                     position_allowance, total_salary, pre_tax_pay, luxury_amount, actual_income, company_cost, total_cost, supplier_name, store_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                    work_hours=VALUES(work_hours), base_salary=VALUES(base_salary), performance=VALUES(performance),
                    position_allowance=VALUES(position_allowance), total_salary=VALUES(total_salary), pre_tax_pay=VALUES(pre_tax_pay),
                    luxury_amount=VALUES(luxury_amount), actual_income=VALUES(actual_income),
                    company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                """, (report_month, "fulltime", pos_name, person_name or "",
                      wh, base_s, perf, allow, total_s, pre_tax, luxury_a, actual_inc, company_c, cost_val, sup, store_id))
                counts["fulltime"] += 1
                n_to_person_total[0] += 1
                if person_name and not str(person_name).strip().startswith("#"):
                    n_to_person_with_real_name[0] += 1
            conn.commit()
        elif is_parttime_table or is_hourly_table:
            ptype = "parttime" if "兼职" in sheet_name_lower else "hourly"
            # 成本列：开票金额/总成本 或 费用合计（斗米兼职/中锐/快聘表头多为「费用合计」）
            cost_col = _total_cost_col() or _col("费用合计", ["总成本", "费用合计"])
            if cost_col is None:
                continue
            person_col_ph = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            first_col_ph = df_header.columns[0] if len(df_header.columns) else None
            # 兼职/小时工全量明细列（与 Excel 一致）
            store_name_col = _col("店铺名", ["门店"])
            city_col = _col("城市")
            join_date_col = _col("入职日期")
            leave_date_col = _col("离职日期")
            total_hours_col = _col("总工时")
            normal_hours_col = _col("普通工时")
            triple_pay_col = _col("三薪工时")
            hourly_rate_col = _col("时薪")
            pay_amount_col = _col("发薪金额")
            service_fee_unit_col = _col("服务费单价")
            service_fee_total_col = _col("服务费总计")
            tax_col = _col("税费")
            cost_include_col = _col("成本计入")
            department_col = _col("用人部门")

            def _row_str(r, col, max_len=64):
                v = r.get(col) if col is not None else None
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                return str(v).strip()[:max_len] or None

            cur = conn.cursor()
            if person_col_ph is not None:
                # 到人：每行一条，姓名为空或汇总行跳过；全量写入明细列
                for i, (_, row) in enumerate(df_header.iterrows()):
                    pos = row.get(pos_col)
                    if _is_skip_position(pos) or _is_skip_person_row(row.get(person_col_ph)):
                        continue
                    pos_name = _normalize_position_name(pos)
                    if not pos_name:
                        continue
                    person_name = _normalize_person_name(row.get(person_col_ph)) or ""
                    if not person_name and first_col_ph is not None:
                        first_val = row.get(first_col_ph)
                        first_str = _normalize_person_name(first_val) if first_val is not None else ""
                        # 首列为「门店」「成本计入」「合计」等非人名的，用行号区分，避免多行合并为同一人
                        if first_str and not _is_skip_person_row(first_val) and first_str not in ("门店", "成本计入"):
                            person_name = first_str
                        else:
                            person_name = "#%d" % (i + 1)
                    cost_val = _safe_num(row.get(cost_col))
                    sup = _row_supplier(row)
                    store_name_val = _row_str(row, store_name_col)
                    city_val = _row_str(row, city_col, 32)
                    join_date_val = _row_str(row, join_date_col, 32)
                    leave_date_val = _row_str(row, leave_date_col, 32)
                    total_hrs = _safe_num(row.get(total_hours_col)) if total_hours_col else None
                    normal_hrs = _safe_num(row.get(normal_hours_col)) if normal_hours_col else None
                    triple_hrs = _safe_num(row.get(triple_pay_col)) if triple_pay_col else None
                    rate = _safe_num(row.get(hourly_rate_col)) if hourly_rate_col else None
                    pay_amt = _safe_num(row.get(pay_amount_col)) if pay_amount_col else None
                    svc_unit = _safe_num(row.get(service_fee_unit_col)) if service_fee_unit_col else None
                    svc_total = _safe_num(row.get(service_fee_total_col)) if service_fee_total_col else None
                    tax_val = _safe_num(row.get(tax_col)) if tax_col else None
                    cost_include_val = _row_str(row, cost_include_col, 32)
                    department_val = _row_str(row, department_col, 64)
                    person_name = _person_name_with_suffix(report_month, ptype, pos_name, person_name, sup)
                    cur.execute("""
                        INSERT INTO t_htma_labor_cost
                        (report_month, position_type, position_name, person_name, company_cost, total_cost, supplier_name, store_id,
                         store_name, city, join_date, leave_date, work_hours, normal_hours, triple_pay_hours, hourly_rate, pay_amount, service_fee_unit, service_fee_total, tax, cost_include, department)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE company_cost=VALUES(company_cost), total_cost=VALUES(total_cost),
                        store_name=VALUES(store_name), city=VALUES(city), join_date=VALUES(join_date), leave_date=VALUES(leave_date),
                        work_hours=VALUES(work_hours), normal_hours=VALUES(normal_hours), triple_pay_hours=VALUES(triple_pay_hours),
                        hourly_rate=VALUES(hourly_rate), pay_amount=VALUES(pay_amount), service_fee_unit=VALUES(service_fee_unit), service_fee_total=VALUES(service_fee_total), tax=VALUES(tax),
                        cost_include=VALUES(cost_include), department=VALUES(department)
                    """, (report_month, ptype, pos_name, person_name or "", cost_val, cost_val, sup, store_id,
                          store_name_val, city_val, join_date_val, leave_date_val, total_hrs, normal_hrs, triple_hrs, rate, pay_amt, svc_unit, svc_total, tax_val, cost_include_val, department_val))
                    counts[ptype] += 1
                    n_to_person_total[0] += 1
                    if person_name and not str(person_name).strip().startswith("#"):
                        n_to_person_with_real_name[0] += 1
            else:
                # 无姓名列：按岗位汇总
                agg_fee = {}
                for _, row in df_header.iterrows():
                    pos = row.get(pos_col)
                    if _is_skip_position(pos):
                        continue
                    pos_name = _normalize_position_name(pos)
                    if not pos_name:
                        continue
                    if pos_name not in agg_fee:
                        agg_fee[pos_name] = 0
                    agg_fee[pos_name] += _safe_num(row.get(cost_col))
                for pos_name, total_cost in agg_fee.items():
                    cur.execute("""
                        INSERT INTO t_htma_labor_cost
                        (report_month, position_type, position_name, person_name, company_cost, total_cost, supplier_name, store_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                    """, (report_month, ptype, pos_name, "", total_cost, total_cost, default_supplier, store_id))
                    counts[ptype] += 1
            conn.commit()

    if n_to_person_total[0] > 0 and n_to_person_with_real_name[0] / n_to_person_total[0] < 0.5:
        diagnostics.append("建议：多数明细姓名为空或行号，请在 Excel 中增加「姓名」列（或「人员」「员工姓名」）后重新导入，以便到人明细准确。")

    return counts, diagnostics, duplicates


def _ocr_image_to_table(image_path):
    """对附图做 OCR，返回 (headers, rows) 或 (None, None)。"""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return None, None
    try:
        im = Image.open(image_path)
        if im.mode not in ("L", "RGB", "RGBA"):
            im = im.convert("RGB")
        try:
            data = pytesseract.image_to_data(im, lang="chi_sim+eng", config="--psm 6")
        except Exception:
            data = pytesseract.image_to_data(im, lang="eng", config="--psm 6")
        by_line = {}
        for line in data.strip().split("\n")[1:]:
            parts = line.split("\t")
            if len(parts) < 12:
                continue
            try:
                text = (parts[11] or "").strip()
                if not text:
                    continue
                left = int(parts[6])
                top = int(parts[7])
                block = int(parts[1] or 0)
                line_num = int(parts[2] or 0)
                key = (block, line_num)
                if key not in by_line:
                    by_line[key] = []
                by_line[key].append((left, top, text))
            except (ValueError, IndexError):
                continue
        keys = sorted(by_line.keys(), key=lambda k: (by_line[k][0][1], by_line[k][0][0]))
        lines = []
        for key in keys:
            items = sorted(by_line[key], key=lambda x: (x[0], x[1]))
            xs = [x[0] for x in items]
            gap_threshold = 30
            if len(xs) > 1:
                gaps = [xs[i+1] - xs[i] for i in range(len(xs)-1)]
                if gaps:
                    gap_threshold = max(30, min(80, sum(gaps)/len(gaps) * 1.5))
            row = []
            current = []
            last_left = -999
            for left, _, text in items:
                if current and (left - last_left) > gap_threshold:
                    row.append(" ".join(current).strip())
                    current = [text]
                else:
                    current.append(text)
                last_left = left + 50
            if current:
                row.append(" ".join(current).strip())
            if row:
                lines.append(row)
        if not lines:
            return None, None
        return lines[0], lines[1:]
    except Exception:
        return None, None


def import_labor_cost_from_image(image_path, report_month, conn, store_id=None, position_type=None):
    """从附图 OCR 识别表格并导入人力成本。position_type='leader'|'fulltime' 必填，与组长表/组员表一一对应。返回 (leader_count, fulltime_count, diagnostics)。"""
    store_id = store_id or STORE_ID
    leader_count = 0
    fulltime_count = 0
    diagnostics = []
    if position_type not in ("leader", "fulltime"):
        diagnostics.append("附图导入请指定 position_type=leader（组长表）或 fulltime（组员表）。")
        return 0, 0, diagnostics

    def _safe_num(v, default=0):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        try:
            if isinstance(v, str):
                v = v.replace(",", "").replace(" ", "").strip()
            return float(v)
        except (TypeError, ValueError):
            return default

    def _is_skip_position(name):
        if not name or not str(name).strip():
            return True
        t = str(name).strip()
        for k in ("合计", "总计", "小计", "汇总", "求和项"):
            if k in t:
                return True
        return False

    def _is_header_or_junk_row(pos_cell, whole_row):
        """附图 OCR 后：岗位列为表头字样或整行为合计行则跳过"""
        if not pos_cell or not str(pos_cell).strip():
            return True
        t = str(pos_cell).strip()
        if t in ("岗位", "求和项:岗位") or t.replace(" ", "") == "岗位":
            return True
        if t.isdigit() and len(t) <= 5:
            return True
        for cell in (whole_row or []):
            if cell and ("合计" in str(cell) or "总计" in str(cell)):
                return True
        return False

    headers, rows = _ocr_image_to_table(image_path)
    if not headers or not rows:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception as e:
            diagnostics.append("OCR 不可用: " + str(e) + "。请安装 Tesseract（如 brew install tesseract tesseract-lang）或改用 Excel 导入。")
        else:
            diagnostics.append("未能从附图中识别出表格，请确保图片清晰、表头含「岗位」，或改用 Excel 导入。")
        return 0, 0, diagnostics

    def _norm(h):
        if not h:
            return ""
        s = str(h).strip().replace("求和项:", "").strip()
        if "(" in s:
            s = s.split("(")[0].strip()
        return s

    norm_headers = [_norm(h) for h in headers]
    pos_idx = None
    for i, h in enumerate(norm_headers):
        if "岗位" in h:
            pos_idx = i
            break
    if pos_idx is None:
        diagnostics.append("未识别到「岗位」列。")
        return 0, 0, diagnostics

    has_total_cost = any("费用总额" in h for h in norm_headers)
    has_luxury_bonus = any("奢品奖金" in h for h in norm_headers)
    has_work_hours = any("总工时" in h or "12月" in h or "当月总工时" in h or "本月总工时" in h for h in norm_headers)
    has_base_salary = any("基本工资" in h for h in norm_headers)

    def _col_idx(name, fallbacks=None):
        for i, h in enumerate(norm_headers):
            if name in h or (fallbacks and any(f in h for f in fallbacks)):
                return i
        return None

    is_leader_table = (has_total_cost or has_luxury_bonus) and not has_work_hours
    is_fulltime_table = has_work_hours and has_base_salary

    if position_type == "leader":
        if not is_leader_table:
            diagnostics.append("当前附图未识别为组长表（需含「费用总额」或「奢品奖金」且无「总工时」）。请上传组长表截图或检查表头是否清晰。")
            return 0, 0, diagnostics
        total_salary_idx = _col_idx("合计薪资")
        actual_salary_idx = _col_idx("实际薪资合计")
        luxury_bonus_idx = _col_idx("奢品奖金")
        actual_income_idx = _col_idx("实得收入")
        company_cost_idx = _col_idx("公司实际成本")
        total_cost_idx = _col_idx("费用总额")
        for row in rows:
            if len(row) <= pos_idx:
                continue
            pos_name = str(row[pos_idx]).strip()[:64] if pos_idx < len(row) else ""
            if _is_skip_position(pos_name) or _is_header_or_junk_row(row[pos_idx], row) or not pos_name:
                continue
            total_salary = _safe_num(row[total_salary_idx]) if total_salary_idx is not None and total_salary_idx < len(row) else 0
            actual_salary = _safe_num(row[actual_salary_idx]) if actual_salary_idx is not None and actual_salary_idx < len(row) else 0
            luxury_bonus = _safe_num(row[luxury_bonus_idx]) if luxury_bonus_idx is not None and luxury_bonus_idx < len(row) else 0
            actual_income = _safe_num(row[actual_income_idx]) if actual_income_idx is not None and actual_income_idx < len(row) else 0
            company_cost = _safe_num(row[company_cost_idx]) if company_cost_idx is not None and company_cost_idx < len(row) else 0
            total_cost = _safe_num(row[total_cost_idx]) if total_cost_idx is not None and total_cost_idx < len(row) else company_cost
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO t_htma_labor_cost
                (report_month, position_type, position_name, person_name, total_salary, actual_salary, luxury_bonus,
                 actual_income, company_cost, total_cost, supplier_name, store_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                total_salary=VALUES(total_salary), actual_salary=VALUES(actual_salary),
                luxury_bonus=VALUES(luxury_bonus), actual_income=VALUES(actual_income),
                company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
            """, (report_month, "leader", pos_name, "", total_salary, actual_salary, luxury_bonus,
                  actual_income, company_cost, total_cost, "斗米", store_id))
            leader_count += 1
        conn.commit()
        return leader_count, 0, diagnostics

    if position_type == "fulltime":
        if not is_fulltime_table:
            diagnostics.append("当前附图未识别为组员表（需含「总工时」「基本工资」等）。请上传组员表截图或检查表头是否清晰。")
            return 0, 0, diagnostics
        work_hours_idx = _col_idx("总工时", ["12月总工时", "总工时", "当月总工时", "本月总工时"])
        base_salary_idx = _col_idx("基本工资")
        performance_idx = _col_idx("绩效", ["绩效工资"])
        position_allowance_idx = _col_idx("岗位补贴")
        total_salary_idx = _col_idx("合计薪资", ["本月合计薪资"])
        luxury_amount_idx = _col_idx("奢品", ["奢品奖金"])
        actual_income_idx = _col_idx("实得收入", ["本月实得收入"])
        company_cost_idx = _col_idx("公司实际成本")
        for row in rows:
            if len(row) <= pos_idx:
                continue
            pos_name = str(row[pos_idx]).strip()[:64] if pos_idx < len(row) else ""
            if _is_skip_position(pos_name) or _is_header_or_junk_row(row[pos_idx], row) or not pos_name:
                continue
            work_hours = _safe_num(row[work_hours_idx]) if work_hours_idx is not None and work_hours_idx < len(row) else 0
            base_salary = _safe_num(row[base_salary_idx]) if base_salary_idx is not None and base_salary_idx < len(row) else 0
            performance = _safe_num(row[performance_idx]) if performance_idx is not None and performance_idx < len(row) else 0
            position_allowance = _safe_num(row[position_allowance_idx]) if position_allowance_idx is not None and position_allowance_idx < len(row) else 0
            total_salary = _safe_num(row[total_salary_idx]) if total_salary_idx is not None and total_salary_idx < len(row) else 0
            luxury_amount = _safe_num(row[luxury_amount_idx]) if luxury_amount_idx is not None and luxury_amount_idx < len(row) else 0
            actual_income = _safe_num(row[actual_income_idx]) if actual_income_idx is not None and actual_income_idx < len(row) else 0
            company_cost = _safe_num(row[company_cost_idx]) if company_cost_idx is not None and company_cost_idx < len(row) else 0
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO t_htma_labor_cost
                (report_month, position_type, position_name, person_name, work_hours, base_salary, performance,
                 position_allowance, total_salary, luxury_amount, actual_income, company_cost, total_cost, supplier_name, store_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                work_hours=VALUES(work_hours), base_salary=VALUES(base_salary), performance=VALUES(performance),
                position_allowance=VALUES(position_allowance), total_salary=VALUES(total_salary),
                luxury_amount=VALUES(luxury_amount), actual_income=VALUES(actual_income),
                company_cost=VALUES(company_cost), total_cost=VALUES(company_cost)
            """, (report_month, "fulltime", pos_name, "", work_hours, base_salary, performance,
                  position_allowance, total_salary, luxury_amount, actual_income, company_cost, company_cost, "斗米", store_id))
            fulltime_count += 1
        conn.commit()
        return 0, fulltime_count, diagnostics

    return 0, 0, diagnostics


def refresh_labor_cost_analysis(conn):
    """从 t_htma_labor_cost 汇总写入 t_htma_labor_cost_analysis，用于月度比对分析。返回刷新的月份数。"""
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT report_month,
               SUM(CASE WHEN position_type='leader' THEN 1 ELSE 0 END) AS leader_count,
               COALESCE(SUM(CASE WHEN position_type='leader' THEN total_cost ELSE 0 END), 0) AS leader_total_cost,
               SUM(CASE WHEN position_type='fulltime' THEN 1 ELSE 0 END) AS fulltime_count,
               COALESCE(SUM(CASE WHEN position_type='fulltime' THEN COALESCE(total_cost, company_cost) ELSE 0 END), 0) AS fulltime_total_cost,
               COALESCE(SUM(CASE WHEN position_type='fulltime' THEN work_hours ELSE 0 END), 0) AS fulltime_total_hours,
               COALESCE(SUM(total_cost), 0) AS total_all_cost
        FROM t_htma_labor_cost
        GROUP BY report_month
        ORDER BY report_month
    """)
    rows = cur.fetchall()
    if not rows:
        return 0
    cur.execute("""
        CREATE TABLE IF NOT EXISTS t_htma_labor_cost_analysis (
          report_month VARCHAR(7) NOT NULL PRIMARY KEY,
          leader_count INT NOT NULL DEFAULT 0,
          leader_total_cost DECIMAL(14,2) NOT NULL DEFAULT 0,
          fulltime_count INT NOT NULL DEFAULT 0,
          fulltime_total_cost DECIMAL(14,2) NOT NULL DEFAULT 0,
          fulltime_total_hours DECIMAL(12,2) NOT NULL DEFAULT 0,
          total_labor_cost DECIMAL(14,2) NOT NULL DEFAULT 0,
          prev_month_total DECIMAL(14,2) DEFAULT NULL,
          mom_pct DECIMAL(8,2) DEFAULT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()
    prev_by_month = {}
    for r in rows:
        total_all = float(r.get("total_all_cost") or 0)
        prev_by_month[r["report_month"]] = total_all
    n = 0
    for r in rows:
        month = r["report_month"]
        leader_total = round(float(r["leader_total_cost"] or 0), 2)
        fulltime_total = round(float(r["fulltime_total_cost"] or 0), 2)
        hours = round(float(r["fulltime_total_hours"] or 0), 2)
        total = round(float(r.get("total_all_cost") or 0), 2)
        prev_total = None
        mom_pct = None
        try:
            y, m = map(int, month.split("-"))
            if m == 1:
                prev_month = f"{y-1}-12"
            else:
                prev_month = f"{y}-{m-1:02d}"
            prev_total = prev_by_month.get(prev_month)
            if prev_total is not None and prev_total != 0:
                mom_pct = round((total - prev_total) / prev_total * 100, 2)
        except Exception:
            pass
        cur.execute("""
            INSERT INTO t_htma_labor_cost_analysis
            (report_month, leader_count, leader_total_cost, fulltime_count, fulltime_total_cost,
             fulltime_total_hours, total_labor_cost, prev_month_total, mom_pct)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
            leader_count=VALUES(leader_count), leader_total_cost=VALUES(leader_total_cost),
            fulltime_count=VALUES(fulltime_count), fulltime_total_cost=VALUES(fulltime_total_cost),
            fulltime_total_hours=VALUES(fulltime_total_hours), total_labor_cost=VALUES(total_labor_cost),
            prev_month_total=VALUES(prev_month_total), mom_pct=VALUES(mom_pct)
        """, (month, r["leader_count"], leader_total, r["fulltime_count"], fulltime_total,
              hours, total, prev_total, mom_pct))
        n += 1
    conn.commit()
    return n


# ---------- 分店商品档案导入 ----------
# Excel 表头（中文）-> 表字段名；str=字符串, dec=数值, dt=日期, dtt=日期时间
PRODUCT_MASTER_HEADERS = [
    ("商品状态", "product_status", "str"),
    ("货号", "sku_code", "str"),
    ("国际条码", "barcode", "str"),
    ("品名", "product_name", "str"),
    ("类别编码", "category_code", "str"),
    ("类别", "category_name", "str"),
    ("供应商编码", "supplier_code", "str"),
    ("供应商", "supplier_name", "str"),
    ("批发价", "wholesale_price", "dec"),
    ("零售价", "retail_price", "dec"),
    ("会员价", "member_price", "dec"),
    ("会员价1", "member_price_1", "dec"),
    ("会员价2", "member_price_2", "dec"),
    ("配送价", "delivery_price", "dec"),
    ("最低售价", "min_sale_price", "dec"),
    ("划线价", "list_price", "dec"),
    ("单位", "unit", "str"),
    ("规格", "spec", "str"),
    ("产地", "origin", "str"),
    ("商品类型", "product_type", "str"),
    ("允许折扣", "allow_discount", "str"),
    ("采购范围", "purchase_scope", "str"),
    ("前台议价", "counter_bargain", "str"),
    ("会员折扣", "member_discount", "str"),
    ("进项税", "input_tax", "dec"),
    ("是否扣除税", "deduct_tax", "str"),
    ("销项税", "output_tax", "dec"),
    ("是否免税", "tax_free", "str"),
    ("进货规格", "purchase_spec", "dec"),
    ("经销方式", "distribution_mode", "str"),
    ("维护库存", "maintain_stock", "str"),
    ("联营扣率", "joint_rate", "dec"),
    ("分店变价", "store_price_change", "str"),
    ("保质期", "shelf_life", "dec"),
    ("到期预警天数", "expiry_warning_days", "int"),
    ("计价方式", "pricing_mode", "str"),
    ("生鲜商品", "is_fresh", "str"),
    ("损耗率", "loss_rate", "dec"),
    ("积分值", "points_value", "dec"),
    ("品牌编码", "brand_code", "str"),
    ("品牌", "brand_name", "str"),
    ("课组", "class_group", "str"),
    ("助记码", "mnemonic_code", "str"),
    ("商品简称", "product_short_name", "str"),
    ("业务员提成比率", "salesman_commission_rate", "dec"),
    ("建档人编码", "creator_code", "str"),
    ("建档人名称", "creator_name", "str"),
    ("建档日期", "created_at", "dtt"),
    ("最后修改人编码", "modifier_code", "str"),
    ("最后修改人名称", "modifier_name", "str"),
    ("修改日期", "updated_at", "dtt"),
    ("停购日期", "stop_purchase_date", "dt"),
    ("出货规格", "shipment_spec", "dec"),
    ("提成率", "commission_rate", "dec"),
    ("采购周期", "purchase_cycle", "int"),
    ("批发价1", "wholesale_price_1", "dec"),
    ("批发价2", "wholesale_price_2", "dec"),
    ("批发价3", "wholesale_price_3", "dec"),
    ("批发价4", "wholesale_price_4", "dec"),
    ("是否积分", "is_points", "str"),
    ("备注", "remark", "str"),
    ("性别", "gender", "str"),
    ("上下装", "clothing_type", "str"),
    ("风格", "style", "str"),
    ("事业部", "division", "str"),
    ("色系", "color_family", "str"),
    ("色深", "color_depth", "str"),
    ("标准码", "standard_code", "str"),
    ("原条码", "original_barcode", "str"),
    ("厚度", "thickness", "str"),
    ("长度", "length_dim", "str"),
]


def _parse_datetime(v):
    """解析日期时间，支持 datetime、Excel 序列、YYYY-MM-DD HH:MM:SS"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S") if v else None
    if isinstance(v, (int, float)) and not pd.isna(v) and v > 1000:
        try:
            from datetime import timedelta
            d = datetime(1899, 12, 30) + timedelta(days=float(v))
            return d.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*(\d{1,2})?:?\s*(\d{1,2})?:?\s*(\d{1,2})?", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        h = int(m.group(4) or 0)
        mi = int(m.group(5) or 0)
        sec = int(m.group(6) or 0)
        return f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{sec:02d}"
    return _parse_date(v) + " 00:00:00" if _parse_date(v) else None


def _ensure_product_master_distribution_mode(conn):
    """确保 t_htma_product_master 有 distribution_mode 列（消费洞察等依赖）。
    表不存在时跳过；列已存在时跳过；缺列时补齐。供数据导入、启动脚本统一调用。"""
    try:
        cur = conn.cursor()
        # 表不存在则跳过（建表脚本 19 已含该列）
        cur.execute("""
            SELECT 1 FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_product_master' LIMIT 1
        """)
        if not cur.fetchone():
            cur.close()
            return
        # 列已存在则跳过
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_product_master' AND COLUMN_NAME = 'distribution_mode'
        """)
        if (cur.fetchone() or (0,))[0] > 0:
            cur.close()
            return
        # 补齐列（加在表末，避免依赖其他列）
        cur.execute("""
            ALTER TABLE t_htma_product_master ADD COLUMN distribution_mode VARCHAR(32) DEFAULT NULL
            COMMENT '经销方式(购销/代销等)'
        """)
        conn.commit()
        cur.close()
    except Exception:
        pass


def import_product_master(excel_path, conn, store_id=None, archive_date=None):
    """分店商品档案 Excel 导入 t_htma_product_master。仅操作 t_htma_product_master（按门店+货号覆盖），不触碰销售/库存/人力/品类表。按文件名解析 archive_date（分店商品档案_20260306-_101750.xlsx）。返回 (inserted_count, message)。"""
    _ensure_product_master_distribution_mode(conn)
    store_id = (store_id or STORE_ID or "默认").strip()[:32]
    if archive_date is None:
        m = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", os.path.basename(excel_path))
        if m:
            archive_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            archive_date = None
    try:
        df = pd.read_excel(excel_path, header=0, engine="openpyxl")
    except Exception as e:
        try:
            df = pd.read_excel(excel_path, header=0)
        except Exception as e2:
            return 0, "读取 Excel 失败: " + str(e2)
    if df.shape[0] == 0:
        return 0, "无数据行"
    # 列名 -> 列索引（表头可能带空格）
    col_map = {}
    for i, c in enumerate(df.columns):
        key = str(c).strip() if c is not None else ""
        if key and key not in col_map:
            col_map[key] = i
    # 构建 (列索引, 字段名, 类型) 仅包含 Excel 中存在的列
    cols_schema = []
    for chn, fld, typ in PRODUCT_MASTER_HEADERS:
        if chn in col_map:
            cols_schema.append((col_map[chn], fld, typ))
    if not any(c[1] == "sku_code" for c in cols_schema):
        return 0, "未找到「货号」列"
    # 插入用字段顺序：store_id, archive_date, 以及所有 Excel 映射到的字段
    all_fields = ["store_id", "archive_date"] + [c[1] for c in cols_schema]
    cur = conn.cursor()
    skip_no_sku = 0

    def _cell(row, idx, typ):
        if idx >= len(row):
            return None
        v = row.iloc[idx]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if typ == "str":
            s = str(v).strip()[:256]
            return s if s else None
        if typ == "dec":
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            x = _safe_decimal(v, 0)
            return x if x is not None else None
        if typ == "int":
            try:
                return int(float(v)) if v is not None and not (isinstance(v, float) and pd.isna(v)) else None
            except (TypeError, ValueError):
                return None
        if typ == "dt":
            return _parse_date(v)
        if typ == "dtt":
            return _parse_datetime(v)
        return None

    # 去重：按 (store_id, sku_code) 合并，同键保留最后一行（与销售汇总一致），再批量写入；写入时 ON DUPLICATE KEY UPDATE 覆盖表中已有同键数据
    dedup = {}  # (store_id, sku_code) -> tuple(vals)
    for _, row in df.iterrows():
        sku = _cell(row, next((c[0] for c in cols_schema if c[1] == "sku_code"), -1), "str")
        if not sku:
            skip_no_sku += 1
            continue
        sku = str(sku).strip()[:64]
        vals = [store_id, archive_date]
        for _, fld, typ in cols_schema:
            idx = next((c[0] for c in cols_schema if c[1] == fld), -1)
            v = _cell(row, idx, typ)
            vals.append(v)
        dedup[(store_id, sku)] = tuple(vals)

    inserted = 0
    batch_size = 500
    buf = []
    for v in dedup.values():
        buf.append(v)
        if len(buf) >= batch_size:
            _flush_product_master_batch(cur, all_fields, buf)
            inserted += len(buf)
            buf = []
    if buf:
        _flush_product_master_batch(cur, all_fields, buf)
        inserted += len(buf)
    conn.commit()
    cur.close()
    msg = f"去重后导入 {inserted} 条（同门店+货号已覆盖）"
    if skip_no_sku:
        msg += f"，跳过无货号 {skip_no_sku} 行"
    return inserted, msg


def _flush_product_master_batch(cur, all_fields, buf):
    """批量 INSERT ... ON DUPLICATE KEY UPDATE"""
    if not buf:
        return
    placeholders = ", ".join(["(" + ", ".join(["%s"] * len(all_fields)) + ")" for _ in buf])
    col_str = ", ".join(all_fields)
    update_parts = [f"{f}=VALUES({f})" for f in all_fields if f not in ("store_id", "sku_code")]
    sql = f"INSERT INTO t_htma_product_master ({col_str}) VALUES {placeholders} ON DUPLICATE KEY UPDATE " + ", ".join(update_parts)
    flat = []
    for v in buf:
        flat.extend(v)
    cur.execute(sql, flat)
