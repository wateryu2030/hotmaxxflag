# -*- coding: utf-8 -*-
"""
全量发票查询导出 xlsx：解析「信息汇总表」(明细)、「发票基础信息」(按票汇总)，写入 t_htma_full_invoice_*。
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pymysql

SHEET_LINES = "信息汇总表"
SHEET_HEADERS = "发票基础信息"

# 汇总/页脚行常见字样（出现在任一关键列则整行丢弃）
_SUMMARY_SUBSTRINGS = (
    "合计",
    "总计",
    "小计",
    "汇总",
    "价税合计",
    "金额合计",
    "税额合计",
    "本页合计",
    "本张合计",
    "分页小计",
    "SUBTOTAL",
    "GRAND TOTAL",
)


def _text_has_summary_marker(s: Any) -> bool:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return False
    t = str(s).strip().upper()
    if not t:
        return False
    u = str(s).strip()
    for k in _SUMMARY_SUBSTRINGS:
        if k.upper() in t or k in u:
            return True
    return False


def _valid_digital_invoice_no(dig: Any) -> bool:
    """数电发票号码一般为长串数字，汇总行常为空白、中文或异常短串。"""
    if dig is None or (isinstance(dig, float) and pd.isna(dig)):
        return False
    s = str(dig).strip().replace(" ", "")
    if not s or len(s) < 15:
        return False
    if any("\u4e00" <= c <= "\u9fff" for c in s):
        return False
    if not s.isdigit():
        return False
    return True


def _seq_looks_like_data_row(seq: Any) -> bool:
    """序号列：汇总行常为『合计行』、非数字或空。"""
    if seq is None or (isinstance(seq, float) and pd.isna(seq)):
        return True
    st = str(seq).strip()
    if not st:
        return True
    if _text_has_summary_marker(st):
        return False
    try:
        float(st)
        return True
    except Exception:
        return False


def normalize_goods_name(name: Any) -> str:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = str(name).strip()
    if not s or "合计" in s:
        return ""
    s = re.sub(r"^\*[^*]+\*", "", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()[:250]


def _to_decimal(v: Any, default: Decimal = Decimal("0")) -> Decimal:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    if isinstance(v, Decimal):
        return v
    s = str(v).strip().replace(",", "")
    if not s:
        return default
    try:
        return Decimal(s)
    except Exception:
        return default


def _to_datetime(v: Any) -> Optional[datetime]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def _skip_line_row(row: pd.Series) -> bool:
    """过滤汇总行、页脚、异常行，避免把合计金额写入明细表。"""
    if not _seq_looks_like_data_row(row.get("序号")):
        return True
    dig = row.get("数电发票号码")
    if not _valid_digital_invoice_no(dig):
        return True
    # 关键列任一带汇总字样
    for col in (
        "货物或应税劳务名称",
        "购买方名称",
        "销方名称",
        "数电发票号码",
        "发票号码",
        "发票代码",
        "备注",
        "特定业务类型",
    ):
        if col in row.index and _text_has_summary_marker(row[col]):
            return True
    # 税务平台正常明细行均带货物名称；无名称的多为页脚/异常行
    gn = row.get("货物或应税劳务名称")
    if pd.isna(gn) or not str(gn).strip():
        return True
    if _text_has_summary_marker(gn):
        return True
    return False


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return int(float(v))
    except Exception:
        return None


def _skip_header_row(row: pd.Series) -> bool:
    """发票基础信息 sheet：按票汇总，剔除合计行与无效票号。"""
    if not _seq_looks_like_data_row(row.get("序号")):
        return True
    if not _valid_digital_invoice_no(row.get("数电发票号码")):
        return True
    for col in ("购买方名称", "销方名称", "数电发票号码", "备注", "发票票种", "发票状态"):
        if col in row.index and _text_has_summary_marker(row[col]):
            return True
    return False


def import_full_invoice_excel(
    excel_path: str,
    period_month: str,
    store_id: str,
    conn: pymysql.connections.Connection,
    original_filename: str = "",
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    period_month: YYYY-MM。同一门店同月会先删除旧批次再导入。
    """
    if not os.path.isfile(excel_path):
        return False, "文件不存在", {}
    try:
        y, m = int(period_month[:4]), int(period_month[5:7])
        pdate = date(y, m, 1)
    except Exception:
        return False, "period_month 须为 YYYY-MM", {}

    xl = pd.ExcelFile(excel_path)
    if SHEET_LINES not in xl.sheet_names or SHEET_HEADERS not in xl.sheet_names:
        return (
            False,
            f"Excel 须包含工作表「{SHEET_LINES}」「{SHEET_HEADERS}」，当前: {xl.sheet_names}",
            {},
        )

    df_line = pd.read_excel(excel_path, sheet_name=SHEET_LINES)
    df_hdr = pd.read_excel(excel_path, sheet_name=SHEET_HEADERS)

    cur = conn.cursor()
    cur.execute(
        "DELETE FROM t_htma_full_invoice_import_batch WHERE period_month = %s AND store_id = %s",
        (pdate, store_id),
    )
    conn.commit()

    cur.execute(
        """INSERT INTO t_htma_full_invoice_import_batch
           (period_month, store_id, file_name, line_row_count, header_row_count)
           VALUES (%s, %s, %s, %s, %s)""",
        (pdate, store_id, (original_filename or os.path.basename(excel_path))[:500], 0, 0),
    )
    batch_id = cur.lastrowid

    line_rows: List[tuple] = []
    for _, row in df_line.iterrows():
        if _skip_line_row(row):
            continue
        dig = row.get("数电发票号码")
        if not _valid_digital_invoice_no(dig):
            continue
        dig_s = str(dig).strip()[:64]
        gname = row.get("货物或应税劳务名称")
        tax_r = row.get("税率")
        tax_raw = str(tax_r).strip() if pd.notna(tax_r) else ""
        line_rows.append(
            (
                batch_id,
                pdate,
                store_id,
                _safe_int(row.get("序号")),
                str(row.get("发票代码") or "")[:64] or None,
                str(row.get("发票号码") or "")[:64] or None,
                dig_s,
                str(row.get("销方识别号") or "")[:32] or None,
                str(row.get("销方名称") or "")[:256] or None,
                str(row.get("购方识别号") or "")[:32] or None,
                str(row.get("购买方名称") or "")[:256] or None,
                _to_datetime(row.get("开票日期")),
                str(row.get("税收分类编码") or "")[:32] or None,
                str(row.get("特定业务类型") or "")[:128] or None,
                str(gname)[:512] if pd.notna(gname) else None,
                str(row.get("规格型号") or "")[:256] if pd.notna(row.get("规格型号")) else None,
                str(row.get("单位") or "")[:32] if pd.notna(row.get("单位")) else None,
                float(_to_decimal(row.get("数量"))) if pd.notna(row.get("数量")) else None,
                float(_to_decimal(row.get("单价"))) if pd.notna(row.get("单价")) else None,
                float(_to_decimal(row.get("金额"))),
                tax_raw[:32],
                float(_to_decimal(row.get("税额"))),
                float(_to_decimal(row.get("价税合计"))),
                str(row.get("发票来源") or "")[:128] or None,
                str(row.get("发票票种") or "")[:128] or None,
                str(row.get("发票状态") or "")[:64] or None,
                str(row.get("是否正数发票") or "")[:16] or None,
                str(row.get("发票风险等级") or "")[:64] or None,
                str(row.get("开票人") or "")[:64] or None,
                str(row.get("备注") or "") if pd.notna(row.get("备注")) else None,
                normalize_goods_name(gname) or None,
            )
        )

    hdr_rows: List[tuple] = []
    for _, row in df_hdr.iterrows():
        if _skip_header_row(row):
            continue
        dig = row.get("数电发票号码")
        if not _valid_digital_invoice_no(dig):
            continue
        dig_s = str(dig).strip()[:64]
        hdr_rows.append(
            (
                batch_id,
                pdate,
                store_id,
                _safe_int(row.get("序号")),
                str(row.get("发票代码") or "")[:64] or None,
                str(row.get("发票号码") or "")[:64] or None,
                dig_s,
                str(row.get("销方识别号") or "")[:32] or None,
                str(row.get("销方名称") or "")[:256] or None,
                str(row.get("购方识别号") or "")[:32] or None,
                str(row.get("购买方名称") or "")[:256] or None,
                _to_datetime(row.get("开票日期")),
                float(_to_decimal(row.get("金额"))),
                float(_to_decimal(row.get("税额"))),
                float(_to_decimal(row.get("价税合计"))),
                str(row.get("发票来源") or "")[:128] or None,
                str(row.get("发票票种") or "")[:128] or None,
                str(row.get("发票状态") or "")[:64] or None,
                str(row.get("是否正数发票") or "")[:16] or None,
                str(row.get("发票风险等级") or "")[:64] or None,
                str(row.get("开票人") or "")[:64] or None,
                str(row.get("备注") or "") if pd.notna(row.get("备注")) else None,
            )
        )

    sql_line = """INSERT INTO t_htma_full_invoice_line_raw
    (batch_id, period_month, store_id, seq_no, invoice_code, invoice_no, digital_invoice_no,
     seller_tax_id, seller_name, buyer_tax_id, buyer_name, invoice_datetime,
     tax_class_code, specific_business_type, goods_name, spec_model, unit_name, qty, unit_price,
     amount_excl_tax, tax_rate_raw, tax_amount, total_incl_tax,
     invoice_source, invoice_type, invoice_status, is_positive_invoice, risk_level, drawer, remark, goods_norm_key)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
    for i in range(0, len(line_rows), 400):
        cur.executemany(sql_line, line_rows[i : i + 400])

    sql_hdr = """INSERT INTO t_htma_full_invoice_header_raw
    (batch_id, period_month, store_id, seq_no, invoice_code, invoice_no, digital_invoice_no,
     seller_tax_id, seller_name, buyer_tax_id, buyer_name, invoice_datetime,
     amount_excl_tax, tax_amount, total_incl_tax,
     invoice_source, invoice_type, invoice_status, is_positive_invoice, risk_level, drawer, remark)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
    for i in range(0, len(hdr_rows), 400):
        cur.executemany(sql_hdr, hdr_rows[i : i + 400])

    cur.execute(
        """UPDATE t_htma_full_invoice_import_batch SET line_row_count=%s, header_row_count=%s WHERE id=%s""",
        (len(line_rows), len(hdr_rows), batch_id),
    )
    conn.commit()
    cur.close()

    return True, "导入成功", {
        "batch_id": batch_id,
        "line_rows": len(line_rows),
        "header_rows": len(hdr_rows),
    }


def compute_uninvoiced_goods_analysis(
    conn: pymysql.connections.Connection,
    period_month: str,
    store_id: str = "沈阳超级仓",
) -> Dict[str, Any]:
    """按归一化品名汇总系统销售(当月)与发票明细不含税金额，输出差额与标记。"""
    try:
        y, m = int(period_month[:4]), int(period_month[5:7])
        start_d = date(y, m, 1)
        if m == 12:
            end_d = date(y, 12, 31)
        else:
            from datetime import timedelta

            end_d = date(y, m + 1, 1) - timedelta(days=1)
    except Exception:
        return {"success": False, "message": "period_month 格式错误"}

    cur = conn.cursor(pymysql.cursors.DictCursor)
    pdate = date(y, m, 1)

    cur.execute(
        """SELECT COALESCE(NULLIF(TRIM(product_name), ''), sku_code, '未命名') AS pname, SUM(sale_amount) AS amt
           FROM t_htma_sale WHERE store_id = %s AND data_date >= %s AND data_date <= %s
           GROUP BY COALESCE(NULLIF(TRIM(product_name), ''), sku_code, '未命名')""",
        (store_id, start_d, end_d),
    )
    system_by_name: Dict[str, float] = {}
    for r in cur.fetchall():
        k = normalize_goods_name(r["pname"]) or str(r["pname"]).strip().lower()
        if not k:
            k = "_empty_"
        system_by_name[k] = system_by_name.get(k, 0) + float(r["amt"] or 0)

    cur.execute(
        """SELECT goods_norm_key, SUM(amount_excl_tax) AS amt
           FROM t_htma_full_invoice_line_raw
           WHERE store_id = %s AND period_month = %s AND goods_norm_key IS NOT NULL AND goods_norm_key != ''
           GROUP BY goods_norm_key""",
        (store_id, pdate),
    )
    inv_by_key: Dict[str, float] = {}
    for r in cur.fetchall():
        inv_by_key[str(r["goods_norm_key"])] = float(r["amt"] or 0)

    cur.execute(
        """SELECT SUM(amount_excl_tax) AS t FROM t_htma_full_invoice_line_raw WHERE store_id=%s AND period_month=%s""",
        (store_id, pdate),
    )
    total_inv = float((cur.fetchone() or {}).get("t") or 0)

    cur.execute(
        """SELECT SUM(sale_amount) AS t FROM t_htma_sale WHERE store_id=%s AND data_date >= %s AND data_date <= %s""",
        (store_id, start_d, end_d),
    )
    total_sys = float((cur.fetchone() or {}).get("t") or 0)

    all_keys = set(system_by_name.keys()) | set(inv_by_key.keys())
    cur.execute(
        """SELECT goods_norm_key, MAX(goods_name) AS sample_goods
           FROM t_htma_full_invoice_line_raw
           WHERE store_id = %s AND period_month = %s AND goods_norm_key IS NOT NULL AND goods_norm_key != ''
           GROUP BY goods_norm_key""",
        (store_id, pdate),
    )
    sample_inv = {str(r["goods_norm_key"]): (r["sample_goods"] or "")[:120] for r in cur.fetchall()}

    rows: List[Dict[str, Any]] = []
    for k in sorted(all_keys):
        if k == "_empty_":
            continue
        sa = round(system_by_name.get(k, 0), 2)
        ia = round(inv_by_key.get(k, 0), 2)
        gap = round(sa - ia, 2)
        if sa > 0 and ia <= 0:
            flag = "系统有销未开票"
        elif ia > 0 and sa <= 0:
            flag = "有票无系统匹配"
        elif abs(gap) <= max(0.02 * max(sa, ia, 1), 1):
            flag = "基本对齐"
        elif gap > 0:
            flag = "部分/未开票"
        else:
            flag = "开票多于系统"
        rows.append(
            {
                "goods_norm_key": k,
                "sample_invoice_goods": sample_inv.get(k) or "",
                "system_sale_amount": sa,
                "invoice_amount_excl_tax": ia,
                "gap_amount": gap,
                "flag": flag,
            }
        )

    rows.sort(key=lambda x: abs(x["gap_amount"]), reverse=True)
    rows = rows[:300]

    cur.close()
    return {
        "success": True,
        "summary": {
            "period_month": period_month,
            "system_sale_total": round(total_sys, 2),
            "invoice_line_excl_total": round(total_inv, 2),
            "month_gap": round(total_sys - total_inv, 2),
        },
        "by_goods": rows,
    }
