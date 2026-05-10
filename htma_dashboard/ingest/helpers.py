# -*- coding: utf-8 -*-
"""底层工具函数 — 分组A：纯函数，不依赖其他模块"""
import os
import re
from datetime import datetime

import pandas as pd


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
    m = re.search(r"(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})", s)
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
    m = re.search(r"(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})\s*(\d{1,2})?:?\s*(\d{1,2})?:?\s*(\d{1,2})?", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        h = int(m.group(4) or 0)
        mi = int(m.group(5) or 0)
        sec = int(m.group(6) or 0)
        return f"{y}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{sec:02d}"
    return _parse_date(v) + " 00:00:00" if _parse_date(v) else None


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
            m = re.search(r"日期\s*[：:]\s*(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})", s)
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
