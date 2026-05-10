# -*- coding: utf-8 -*-
"""分店商品档案 Excel 导入 — product_master"""
import os
import re
from datetime import datetime, timedelta

import pandas as pd
import pymysql

from ingest.helpers import (
    _safe_decimal, _safe_str, _parse_date, _parse_datetime,
    _extract_report_date,
)

STORE_ID = "沈阳超级仓"

# ---------- 分店商品档案导入 ----------
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


def _ensure_product_master_distribution_mode(conn):
    """确保 t_htma_product_master 有 distribution_mode 列"""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_product_master' LIMIT 1
        """)
        if not cur.fetchone():
            cur.close()
            return
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_product_master' AND COLUMN_NAME = 'distribution_mode'
        """)
        if (cur.fetchone() or (0,))[0] > 0:
            cur.close()
            return
        cur.execute("""
            ALTER TABLE t_htma_product_master ADD COLUMN distribution_mode VARCHAR(32) DEFAULT NULL
            COMMENT '经销方式(购销/代销等)'
        """)
        conn.commit()
        cur.close()
    except Exception:
        pass


def import_product_master(excel_path, conn, store_id=None, archive_date=None):
    """分店商品档案 Excel 导入 t_htma_product_master。返回 (inserted_count, message)。"""
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
    col_map = {}
    for i, c in enumerate(df.columns):
        key = str(c).strip() if c is not None else ""
        if key and key not in col_map:
            col_map[key] = i
    cols_schema = []
    for chn, fld, typ in PRODUCT_MASTER_HEADERS:
        if chn in col_map:
            cols_schema.append((col_map[chn], fld, typ))
    if not any(c[1] == "sku_code" for c in cols_schema):
        return 0, "未找到「货号」列"
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

    dedup = {}
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
