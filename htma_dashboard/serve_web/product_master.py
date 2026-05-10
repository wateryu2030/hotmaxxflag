# -*- coding: utf-8 -*-
"""serve_web/product_master：商品主档 API（只读：分析、下钻、查询）"""

from flask import Blueprint, jsonify, request
from datetime import date, datetime, timedelta
import json, pymysql, pymysql.cursors

from core.db import get_conn
from core.context import _effective_store_id
from core.utils import safe_float, safe_str
from query_layer import query_filters_from_request as _ql_query_filters

product_bp = Blueprint("product", __name__)


def _query_filters():
    """兼容 app.py 的 _query_filters 包装。"""
    date_cond, date_params, params, category_cond, _ = _ql_query_filters()
    if params and params[0] is None:
        sid = _effective_store_id()
        params = (sid,) + tuple(params[1:])
    return date_cond, date_params, params, category_cond, _

@product_bp.route("/api/product_master_status")
def api_product_master_status():
    """分店商品档案状态：总条数、最新档案日期。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM t_htma_product_master")
        row = cur.fetchone()
        total = (row[0] if row and isinstance(row, (list, tuple)) else (row.get("c", 0) if isinstance(row, dict) else 0)) or 0
        cur.execute("SELECT MAX(archive_date) AS d FROM t_htma_product_master")
        r2 = cur.fetchone()
        latest = r2[0] if r2 and isinstance(r2, (list, tuple)) else (r2.get("d") if isinstance(r2, dict) else None)
        cur.close()
        conn.close()
        return jsonify({"success": True, "total": total, "latest_archive_date": latest.isoformat() if hasattr(latest, "isoformat") else str(latest) if latest else None})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _product_master_analysis(conn, store_id=None):
    """从 t_htma_product_master 聚合：概览KPI、按状态/品类/品牌/经销方式/价格带/供应商/性别/上下装/风格/色系/产地、数据质量与价格异常。store_id 为空则全部门店。"""
    store_id = (store_id or _effective_store_id() or "默认").strip()[:32]
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cond = " WHERE store_id = %s "
    params = [store_id]

    def _f(r, key, default=0):
        if r is None:
            return default
        v = r.get(key) if isinstance(r, dict) else (r[0] if key == 0 else default)
        if v is None:
            return default
        try:
            return float(v) if isinstance(v, (int, float)) else default
        except (TypeError, ValueError):
            return default

    def _i(r, key, default=0):
        v = _f(r, key, default)
        return int(round(v))

    # ---------- 1. 整体概览 KPI（按 DISTINCT sku_code 统计，避免重复行导致虚高）----------
    cur.execute("""
        SELECT
            COUNT(DISTINCT sku_code) AS total_sku,
            COUNT(DISTINCT CASE WHEN TRIM(COALESCE(product_status,'')) = '正常' THEN sku_code END) AS normal_count,
            COUNT(DISTINCT CASE WHEN TRIM(COALESCE(product_status,'')) = '新品' THEN sku_code END) AS new_count,
            COUNT(DISTINCT CASE WHEN TRIM(COALESCE(product_status,'')) = '停售' THEN sku_code END) AS stop_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail,
            MAX(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS max_retail,
            MIN(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS min_retail,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(brand_name,'')), '')) AS brand_count,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(supplier_code,'')), '')) AS supplier_count
        FROM t_htma_product_master
        """ + cond, params)
    row = cur.fetchone()
    total_sku = _i(row, "total_sku")
    overview = {
        "total_sku": total_sku,
        "normal_count": _i(row, "normal_count"),
        "new_count": _i(row, "new_count"),
        "stop_count": _i(row, "stop_count"),
        "avg_retail": round(_f(row, "avg_retail"), 2) if _f(row, "avg_retail") else None,
        "max_retail": round(_f(row, "max_retail"), 2) if _f(row, "max_retail") else None,
        "min_retail": round(_f(row, "min_retail"), 2) if _f(row, "min_retail") else None,
        "brand_count": _i(row, "brand_count"),
        "supplier_count": _i(row, "supplier_count"),
        "member_price_count": None,
        "member_discount_count": None,
    }
    try:
        cur.execute("SELECT SUM(CASE WHEN COALESCE(member_price, 0) > 0 THEN 1 ELSE 0 END) AS c1, SUM(CASE WHEN TRIM(COALESCE(member_discount,'')) = '是' THEN 1 ELSE 0 END) AS c2 FROM t_htma_product_master " + cond, params)
        r2 = cur.fetchone()
        overview["member_price_count"] = _i(r2, "c1")
        overview["member_discount_count"] = _i(r2, "c2")
    except Exception:
        pass
    try:
        cur.execute(
            "SELECT COUNT(DISTINCT sku_code) AS c FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)",
            [store_id],
        )
        r3 = cur.fetchone()
        overview["sale_sku_count_30d"] = _i(r3, "c")
    except Exception:
        overview["sale_sku_count_30d"] = None

    # ---------- 2. 按商品状态（含占比、平均零售价、品牌数，按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(product_status), ''), '未填') AS k,
            COUNT(DISTINCT sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(brand_name,'')), '')) AS brand_count
        FROM t_htma_product_master
        """ + cond + """ GROUP BY k ORDER BY sku_count DESC LIMIT 20""", params)
    by_status = []
    for r in cur.fetchall():
        k = (r.get("k") or "未填").strip()
        cnt = _i(r, "sku_count")
        by_status.append({
            "name": k,
            "count": cnt,
            "pct": round(cnt / total_sku * 100, 2) if total_sku else 0,
            "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None,
            "brand_count": _i(r, "brand_count"),
        })

    # ---------- 3. 按品类（类别）：SKU数、占比、均价、最高/最低价、品牌数、供应商数、近30天销量/销售额（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(p.category_name), ''), '未分类') AS cat,
            COUNT(DISTINCT p.sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS avg_retail,
            MAX(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS max_retail,
            MIN(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS min_retail,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(p.brand_name,'')), '')) AS brand_count,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(p.supplier_code,'')), '')) AS supplier_count
        FROM t_htma_product_master p
        """ + cond.replace("store_id", "p.store_id") + """ GROUP BY cat ORDER BY sku_count DESC LIMIT 50""", params)
    by_category = []
    for r in cur.fetchall():
        cat = (r.get("cat") or "未分类").strip()
        cnt = _i(r, "sku_count")
        by_category.append({
            "name": cat,
            "count": cnt,
            "pct": round(cnt / total_sku * 100, 2) if total_sku else 0,
            "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None,
            "max_retail": round(_f(r, "max_retail"), 2) if _f(r, "max_retail") else None,
            "min_retail": round(_f(r, "min_retail"), 2) if _f(r, "min_retail") else None,
            "brand_count": _i(r, "brand_count"),
            "supplier_count": _i(r, "supplier_count"),
            "sale_qty": None,
            "sale_amount": None,
        })
    # 近30天销售：JOIN sale 按品类汇总（sku_code 关联）
    try:
        cur.execute("""
            SELECT COALESCE(NULLIF(TRIM(p.category_name), ''), '未分类') AS cat,
                COALESCE(SUM(s.sale_qty), 0) AS sale_qty, COALESCE(SUM(s.sale_amount), 0) AS sale_amount
            FROM t_htma_sale s
            INNER JOIN t_htma_product_master p ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            WHERE s.store_id = %s AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY cat
        """, [store_id])
        sale_by_cat = {(r.get("cat") or "未分类").strip(): r for r in cur.fetchall()}
        for c in by_category:
            sb = sale_by_cat.get(c["name"])
            if sb:
                c["sale_qty"] = round(_f(sb, "sale_qty"), 2)
                c["sale_amount"] = round(_f(sb, "sale_amount"), 2)
    except Exception:
        pass

    # ---------- 4. 按品牌：SKU数、占比、均价、最高/最低、覆盖品类数、主要品类 Top3、近30天销量/销售额（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(brand_name), ''), '未填') AS brand,
            COUNT(DISTINCT sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail,
            MAX(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS max_retail,
            MIN(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS min_retail,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(category_name,'')), '')) AS category_count
        FROM t_htma_product_master
        """ + cond + """ GROUP BY brand ORDER BY sku_count DESC LIMIT 50""", params)
    by_brand = []
    for r in cur.fetchall():
        brand = (r.get("brand") or "未填").strip()
        cnt = _i(r, "sku_count")
        by_brand.append({
            "name": brand,
            "count": cnt,
            "pct": round(cnt / total_sku * 100, 2) if total_sku else 0,
            "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None,
            "max_retail": round(_f(r, "max_retail"), 2) if _f(r, "max_retail") else None,
            "min_retail": round(_f(r, "min_retail"), 2) if _f(r, "min_retail") else None,
            "category_count": _i(r, "category_count"),
            "top_categories": None,
            "sale_qty": None,
            "sale_amount": None,
        })
    # 近30天销售：JOIN sale 按品牌汇总
    try:
        cur.execute("""
            SELECT COALESCE(NULLIF(TRIM(p.brand_name), ''), '未填') AS brand,
                COALESCE(SUM(s.sale_qty), 0) AS sale_qty, COALESCE(SUM(s.sale_amount), 0) AS sale_amount
            FROM t_htma_sale s
            INNER JOIN t_htma_product_master p ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            WHERE s.store_id = %s AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY brand
        """, [store_id])
        sale_by_brand = {(r.get("brand") or "未填").strip(): r for r in cur.fetchall()}
        for b in by_brand:
            sb = sale_by_brand.get(b["name"])
            if sb:
                b["sale_qty"] = round(_f(sb, "sale_qty"), 2)
                b["sale_amount"] = round(_f(sb, "sale_amount"), 2)
    except Exception:
        pass
    # 为每个品牌取主要品类 Top3（子查询或后续补）
    for b in by_brand[:15]:
        cur.execute("""
            SELECT category_name AS cat FROM t_htma_product_master
            """ + cond + """ AND TRIM(COALESCE(brand_name,'')) = %s AND TRIM(COALESCE(category_name,'')) != ''
            GROUP BY category_name ORDER BY COUNT(*) DESC LIMIT 3""", params + [b["name"]])
        b["top_categories"] = ", ".join([(x.get("cat") or "").strip() for x in cur.fetchall() if x.get("cat")]) or "-"

    # ---------- 5. 价格带：SKU数、占比、覆盖品类数、品牌数、主要品类 ----------
    cur.execute("""
        SELECT
            CASE
                WHEN COALESCE(retail_price, 0) = 0 THEN '0'
                WHEN retail_price < 50 THEN '1-49'
                WHEN retail_price < 100 THEN '50-99'
                WHEN retail_price < 200 THEN '100-199'
                WHEN retail_price < 500 THEN '200-499'
                WHEN retail_price < 1000 THEN '500-999'
                ELSE '1000+'
            END AS band,
            COUNT(DISTINCT sku_code) AS sku_count,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(category_name,'')), '')) AS category_count,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(brand_name,'')), '')) AS brand_count
        FROM t_htma_product_master
        """ + cond + """
        GROUP BY band ORDER BY FIELD(band,'0','1-49','50-99','100-199','200-499','500-999','1000+')""", params)
    by_price_band = []
    for r in cur.fetchall():
        band = (r.get("band") or "0").strip()
        cnt = _i(r, "sku_count")
        by_price_band.append({
            "band": band,
            "count": cnt,
            "pct": round(cnt / total_sku * 100, 2) if total_sku else 0,
            "category_count": _i(r, "category_count"),
            "brand_count": _i(r, "brand_count"),
            "top_categories": None,
        })
    for pb in by_price_band:
        if pb["band"] == "0":
            band_cond = " AND COALESCE(retail_price, 0) = 0"
        elif pb["band"] == "1-49":
            band_cond = " AND retail_price >= 1 AND retail_price < 50"
        elif pb["band"] == "50-99":
            band_cond = " AND retail_price >= 50 AND retail_price < 100"
        elif pb["band"] == "100-199":
            band_cond = " AND retail_price >= 100 AND retail_price < 200"
        elif pb["band"] == "200-499":
            band_cond = " AND retail_price >= 200 AND retail_price < 500"
        elif pb["band"] == "500-999":
            band_cond = " AND retail_price >= 500 AND retail_price < 1000"
        elif pb["band"] == "1000+":
            band_cond = " AND retail_price >= 1000"
        else:
            band_cond = " AND 1=0"
        cur.execute("""
            SELECT category_name AS cat FROM t_htma_product_master
            """ + cond + band_cond + """ AND TRIM(COALESCE(category_name,'')) != ''
            GROUP BY category_name ORDER BY COUNT(*) DESC LIMIT 3""", params)
        pb["top_categories"] = ", ".join([(x.get("cat") or "").strip() for x in cur.fetchall() if x.get("cat")]) or "-"

    # ---------- 6. 按经销方式：SKU数、占比、平均零售价、联营扣率均值（表无 distribution_mode 时跳过）----------
    by_distribution = []
    try:
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(distribution_mode), ''), '未填') AS mode,
                COUNT(DISTINCT sku_code) AS sku_count,
                AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail,
                AVG(CASE WHEN COALESCE(joint_rate, 0) > 0 THEN joint_rate END) AS joint_rate_avg
            FROM t_htma_product_master
            """ + cond + """ GROUP BY mode ORDER BY sku_count DESC LIMIT 10""", params)
        for r in cur.fetchall():
            mode = (r.get("mode") or "未填").strip()
            cnt = _i(r, "sku_count")
            by_distribution.append({
                "name": mode,
                "count": cnt,
                "pct": round(cnt / total_sku * 100, 2) if total_sku else 0,
                "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None,
                "joint_rate_avg": round(_f(r, "joint_rate_avg"), 4) if _f(r, "joint_rate_avg") else None,
            })
    except Exception:
        pass

    # ---------- 7. 按供应商：SKU数、占比、覆盖品类数、主要经销方式、平均零售价、联营扣率均值（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(supplier_name), ''), NULLIF(TRIM(supplier_code), ''), '未填') AS supplier,
            COUNT(DISTINCT sku_code) AS sku_count,
            COUNT(DISTINCT NULLIF(TRIM(COALESCE(category_name,'')), '')) AS category_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail,
            AVG(CASE WHEN COALESCE(joint_rate, 0) > 0 THEN joint_rate END) AS joint_rate_avg
        FROM t_htma_product_master
        """ + cond + """ GROUP BY supplier ORDER BY sku_count DESC LIMIT 25""", params)
    by_supplier = []
    for r in cur.fetchall():
        sup = (r.get("supplier") or "未填").strip()
        cnt = _i(r, "sku_count")
        by_supplier.append({
            "name": sup,
            "count": cnt,
            "pct": round(cnt / total_sku * 100, 2) if total_sku else 0,
            "category_count": _i(r, "category_count"),
            "main_distribution": None,
            "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None,
            "joint_rate_avg": round(_f(r, "joint_rate_avg"), 4) if _f(r, "joint_rate_avg") else None,
        })
    for s in by_supplier[:15]:
        try:
            cur.execute("""
                SELECT distribution_mode AS d FROM t_htma_product_master
                """ + cond + """ AND (TRIM(COALESCE(supplier_name,'')) = %s OR TRIM(COALESCE(supplier_code,'')) = %s)
                AND TRIM(COALESCE(distribution_mode,'')) != ''
                GROUP BY distribution_mode ORDER BY COUNT(*) DESC LIMIT 1""", params + [s["name"], s["name"]])
            row_d = cur.fetchone()
            s["main_distribution"] = (row_d.get("d") or "").strip() if row_d else "-"
        except Exception:
            s["main_distribution"] = "-"

    # ---------- 8. 性别分布（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(gender), ''), '未指定') AS k,
            COUNT(DISTINCT sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail
        FROM t_htma_product_master
        """ + cond + """ GROUP BY k ORDER BY sku_count DESC LIMIT 10""", params)
    by_gender = []
    for r in cur.fetchall():
        k = (r.get("k") or "未指定").strip()
        cnt = _i(r, "sku_count")
        by_gender.append({
            "name": k,
            "count": cnt,
            "pct": round(cnt / total_sku * 100, 2) if total_sku else 0,
            "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None,
            "top_categories": None,
        })
    for g in by_gender[:8]:
        cur.execute("""
            SELECT category_name AS cat FROM t_htma_product_master
            """ + cond + """ AND TRIM(COALESCE(gender,'')) = %s AND TRIM(COALESCE(category_name,'')) != ''
            GROUP BY category_name ORDER BY COUNT(*) DESC LIMIT 3""", params + [g["name"] if g["name"] != "未指定" else ""])
        g["top_categories"] = ", ".join([(x.get("cat") or "").strip() for x in cur.fetchall() if x.get("cat")]) or "-"

    # ---------- 9. 上下装/配件（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(clothing_type), ''), '其他') AS k,
            COUNT(DISTINCT sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail
        FROM t_htma_product_master
        """ + cond + """ GROUP BY k ORDER BY sku_count DESC LIMIT 15""", params)
    by_clothing_type = [{"name": (r.get("k") or "其他").strip(), "count": _i(r, "sku_count"), "pct": round(_i(r, "sku_count") / total_sku * 100, 2) if total_sku else 0, "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None} for r in cur.fetchall()]

    # ---------- 10. 风格（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(style), ''), '未填') AS k,
            COUNT(DISTINCT sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail
        FROM t_htma_product_master
        """ + cond + """ GROUP BY k ORDER BY sku_count DESC LIMIT 15""", params)
    by_style = [{"name": (r.get("k") or "未填").strip(), "count": _i(r, "sku_count"), "pct": round(_i(r, "sku_count") / total_sku * 100, 2) if total_sku else 0, "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None} for r in cur.fetchall()]

    # ---------- 11. 色系（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(color_family), ''), '未填') AS k,
            COUNT(DISTINCT sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail
        FROM t_htma_product_master
        """ + cond + """ GROUP BY k ORDER BY sku_count DESC LIMIT 15""", params)
    by_color = [{"name": (r.get("k") or "未填").strip(), "count": _i(r, "sku_count"), "pct": round(_i(r, "sku_count") / total_sku * 100, 2) if total_sku else 0, "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None} for r in cur.fetchall()]

    # ---------- 12. 产地（按 DISTINCT sku_code 统计）----------
    cur.execute("""
        SELECT
            COALESCE(NULLIF(TRIM(origin), ''), '未填') AS k,
            COUNT(DISTINCT sku_code) AS sku_count,
            AVG(CASE WHEN COALESCE(retail_price, 0) > 0 THEN retail_price END) AS avg_retail
        FROM t_htma_product_master
        """ + cond + """ GROUP BY k ORDER BY sku_count DESC LIMIT 15""", params)
    by_origin = [{"name": (r.get("k") or "未填").strip(), "count": _i(r, "sku_count"), "pct": round(_i(r, "sku_count") / total_sku * 100, 2) if total_sku else 0, "avg_retail": round(_f(r, "avg_retail"), 2) if _f(r, "avg_retail") else None} for r in cur.fetchall()]

    # ---------- 13. 数据质量：关键字段缺失 ----------
    cur.execute("""
        SELECT
            SUM(CASE WHEN COALESCE(TRIM(barcode), '') = '' THEN 1 ELSE 0 END) AS miss_barcode,
            SUM(CASE WHEN COALESCE(retail_price, 0) <= 0 THEN 1 ELSE 0 END) AS miss_retail,
            SUM(CASE WHEN COALESCE(TRIM(brand_name), '') = '' THEN 1 ELSE 0 END) AS miss_brand,
            SUM(CASE WHEN COALESCE(TRIM(category_name), '') = '' THEN 1 ELSE 0 END) AS miss_category,
            SUM(CASE WHEN COALESCE(TRIM(supplier_code), '') = '' AND COALESCE(TRIM(supplier_name), '') = '' THEN 1 ELSE 0 END) AS miss_supplier,
            SUM(CASE WHEN COALESCE(TRIM(gender), '') = '' THEN 1 ELSE 0 END) AS miss_gender
        FROM t_htma_product_master
        """ + cond, params)
    q = cur.fetchone()
    data_quality_counts = {
        "missing_barcode": _i(q, "miss_barcode"),
        "missing_retail_price": _i(q, "miss_retail"),
        "missing_brand": _i(q, "miss_brand"),
        "missing_category": _i(q, "miss_category"),
        "missing_supplier": _i(q, "miss_supplier"),
        "missing_gender": _i(q, "miss_gender"),
    }
    # 新 dict 合并数量与占比，避免迭代中 update 导致 "dictionary changed size during iteration"
    pct_map = {k + "_pct": round(data_quality_counts[k] / total_sku * 100, 2) if total_sku else 0 for k in data_quality_counts}
    data_quality = {**data_quality_counts, **pct_map}

    # ---------- 14. 价格异常 ----------
    cur.execute("""
        SELECT
            SUM(CASE WHEN COALESCE(retail_price, 0) <= 0 THEN 1 ELSE 0 END) AS retail_le_zero,
            SUM(CASE WHEN COALESCE(wholesale_price, 0) > 0 AND COALESCE(retail_price, 0) > 0 AND retail_price < wholesale_price THEN 1 ELSE 0 END) AS retail_lt_wholesale,
            SUM(CASE WHEN COALESCE(list_price, 0) > 0 AND COALESCE(retail_price, 0) > 0 AND list_price < retail_price THEN 1 ELSE 0 END) AS list_lt_retail
        FROM t_htma_product_master
        """ + cond, params)
    pa = cur.fetchone()
    price_anomaly = {
        "retail_le_zero": _i(pa, "retail_le_zero"),
        "retail_lt_wholesale": _i(pa, "retail_lt_wholesale"),
        "list_lt_retail": _i(pa, "list_lt_retail"),
    }

    # ---------- 15. 特殊商品：生鲜、捆绑、有保质期、积分、允许折扣等 ----------
    cur.execute("""
        SELECT
            SUM(CASE WHEN TRIM(COALESCE(is_fresh,'')) = '是' THEN 1 ELSE 0 END) AS fresh_count,
            AVG(CASE WHEN TRIM(COALESCE(is_fresh,'')) = '是' AND COALESCE(loss_rate, 0) > 0 THEN loss_rate END) AS fresh_avg_loss_rate,
            SUM(CASE WHEN TRIM(COALESCE(product_type,'')) LIKE '%%捆绑%%' THEN 1 ELSE 0 END) AS bundle_count,
            SUM(CASE WHEN COALESCE(shelf_life, 0) > 0 THEN 1 ELSE 0 END) AS has_shelf_life_count,
            SUM(CASE WHEN TRIM(COALESCE(is_points,'')) = '是' THEN 1 ELSE 0 END) AS points_count,
            SUM(CASE WHEN TRIM(COALESCE(allow_discount,'')) = '是' THEN 1 ELSE 0 END) AS allow_discount_count,
            SUM(CASE WHEN TRIM(COALESCE(counter_bargain,'')) = '是' THEN 1 ELSE 0 END) AS counter_bargain_count,
            SUM(CASE WHEN TRIM(COALESCE(member_discount,'')) = '是' THEN 1 ELSE 0 END) AS member_discount_count
        FROM t_htma_product_master
        """ + cond, params)
    sp = cur.fetchone()
    special = {
        "fresh_count": _i(sp, "fresh_count"),
        "fresh_avg_loss_rate": round(_f(sp, "fresh_avg_loss_rate"), 4) if _f(sp, "fresh_avg_loss_rate") else None,
        "bundle_count": _i(sp, "bundle_count"),
        "has_shelf_life_count": _i(sp, "has_shelf_life_count"),
        "points_count": _i(sp, "points_count"),
        "allow_discount_count": _i(sp, "allow_discount_count"),
        "counter_bargain_count": _i(sp, "counter_bargain_count"),
        "member_discount_count": _i(sp, "member_discount_count"),
    }
    special["bundle_pct"] = round(special["bundle_count"] / total_sku * 100, 2) if total_sku else 0
    special["points_pct"] = round(special["points_count"] / total_sku * 100, 2) if total_sku else 0

    # ---------- 品类层级（大类，来自销售表与档案 JOIN，含价格与近30天销售，供前端 大类→中类→小类→品牌→商品 下钻）----------
    by_category_large = []
    try:
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_large_code), ''), '未分类') AS large_code,
                COALESCE(NULLIF(TRIM(s.category_large), ''), s.category_large_code, '未分类') AS large_name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                AVG(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS avg_retail,
                MAX(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS max_retail,
                MIN(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS min_retail,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large
                FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s
            GROUP BY large_code, large_name ORDER BY sku_count DESC LIMIT 100
        """, [store_id, store_id, store_id])
        for r in cur.fetchall():
            by_category_large.append({
                "large_code": (r.get("large_code") or "未分类").strip(),
                "large_name": (r.get("large_name") or "未分类").strip(),
                "sku_count": _i(r, "sku_count"),
                "avg_retail_price": round(float(r.get("avg_retail") or 0), 2) if r.get("avg_retail") is not None else None,
                "max_retail_price": round(float(r.get("max_retail") or 0), 2) if r.get("max_retail") is not None else None,
                "min_retail_price": round(float(r.get("min_retail") or 0), 2) if r.get("min_retail") is not None else None,
                "sales_amount": round(float(r.get("sales_amount") or 0), 2),
                "sales_quantity": round(float(r.get("sales_quantity") or 0), 2),
            })
    except Exception:
        pass

    cur.close()
    return {
        "overview": overview,
        "by_status": by_status,
        "by_category": by_category,
        "by_category_large": by_category_large,
        "by_brand": by_brand,
        "by_distribution": by_distribution,
        "by_price_band": by_price_band,
        "by_supplier": by_supplier,
        "by_gender": by_gender,
        "by_clothing_type": by_clothing_type,
        "by_style": by_style,
        "by_color": by_color,
        "by_origin": by_origin,
        "data_quality": data_quality,
        "price_anomaly": price_anomaly,
        "special": special,
        # 兼容旧版简单结构（仅 name/count 或 band/count）
        "by_status_legacy": [{"name": x["name"], "count": x["count"]} for x in by_status],
        "by_category_legacy": [{"name": x["name"], "count": x["count"]} for x in by_category],
        "by_brand_legacy": [{"name": x["name"], "count": x["count"]} for x in by_brand],
        "by_distribution_legacy": [{"name": x["name"], "count": x["count"]} for x in by_distribution],
        "by_price_band_legacy": [{"band": x["band"], "count": x["count"]} for x in by_price_band],
    }

@product_bp.route("/api/product_master_analysis")
def api_product_master_analysis():
    """分店商品档案分析数据。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    try:
        conn = get_conn()
        data = _product_master_analysis(conn)
        conn.close()
        return jsonify({"success": True, **data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@product_bp.route("/api/product_master_category_mid")
def api_product_master_category_mid():
    """商品档案·按品类层级：指定大类后返回中类列表（SKU 数来自档案+销售口径）。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    large_code = (request.args.get("category_large_code") or request.args.get("category_large") or "").strip()
    if not large_code:
        return jsonify({"success": False, "message": "请提供 category_large_code"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_mid_code), ''), '未分类') AS mid_code,
                COALESCE(NULLIF(TRIM(s.category_mid), ''), s.category_mid_code, '未分类') AS mid_name,
                COUNT(DISTINCT p.sku_code) AS sku_count
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid
                FROM t_htma_sale WHERE store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)
                GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            WHERE p.store_id = %s
            GROUP BY mid_code, mid_name ORDER BY sku_count DESC LIMIT 100
        """, [store_id, large_code, large_code, store_id])
        rows = [{"mid_code": (r.get("mid_code") or "").strip(), "mid_name": (r.get("mid_name") or "未分类").strip(), "sku_count": int(r.get("sku_count") or 0)} for r in cur.fetchall()]
        return jsonify({"success": True, "category_large_code": large_code, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master_category_small")
def api_product_master_category_small():
    """商品档案·按品类层级：指定大类+中类后返回小类列表。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    large_code = (request.args.get("category_large_code") or request.args.get("category_large") or "").strip()
    mid_code = (request.args.get("category_mid_code") or request.args.get("category_mid") or "").strip()
    if not large_code or not mid_code:
        return jsonify({"success": False, "message": "请提供 category_large_code 与 category_mid_code"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_small_code), ''), '未分类') AS small_code,
                COALESCE(NULLIF(TRIM(s.category_small), ''), s.category_small_code, COALESCE(NULLIF(TRIM(s.category), ''), '未分类')) AS small_name,
                COUNT(DISTINCT p.sku_code) AS sku_count
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                FROM t_htma_sale WHERE store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)
                  AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)
                GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            WHERE p.store_id = %s
            GROUP BY small_code, small_name ORDER BY sku_count DESC LIMIT 100
        """, [store_id, large_code, large_code, mid_code, mid_code, store_id])
        rows = [{"small_code": (r.get("small_code") or "").strip(), "small_name": (r.get("small_name") or "未分类").strip(), "sku_count": int(r.get("sku_count") or 0)} for r in cur.fetchall()]
        return jsonify({"success": True, "category_large_code": large_code, "category_mid_code": mid_code, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master_drill")
def api_product_master_drill():
    """商品档案下钻：品类→品牌列表；品类+品牌→SKU 销售明细。支持 category_small_code 按小类筛品牌。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    category = (request.args.get("category") or "").strip()
    brand = (request.args.get("brand") or "").strip()
    category_large_code = (request.args.get("category_large_code") or "").strip()
    category_mid_code = (request.args.get("category_mid_code") or "").strip()
    category_small_code = (request.args.get("category_small_code") or "").strip()
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(20, int(request.args.get("page_size", 50))))
    store_id = (_effective_store_id() or "默认").strip()[:32]
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cond = " WHERE p.store_id = %s "
        params = [store_id]
        if category:
            cond += " AND TRIM(COALESCE(p.category_name,'')) = %s "
            params.append(category)
        if category_small_code:
            sku_sub = " SELECT sku_code FROM t_htma_sale WHERE store_id = %s "
            sub_params = [store_id]
            if category_large_code:
                sku_sub += " AND (COALESCE(TRIM(category_large_code),'') = %s OR COALESCE(TRIM(category_large),'') = %s) "
                sub_params.extend([category_large_code, category_large_code])
            if category_mid_code:
                sku_sub += " AND (COALESCE(TRIM(category_mid_code),'') = %s OR COALESCE(TRIM(category_mid),'') = %s) "
                sub_params.extend([category_mid_code, category_mid_code])
            sku_sub += " AND (COALESCE(TRIM(category_small_code),'') = %s OR COALESCE(TRIM(category_small),'') = %s OR COALESCE(TRIM(category),'') = %s) GROUP BY sku_code "
            sub_params.extend([category_small_code, category_small_code, category_small_code])
            cond += " AND p.sku_code IN (" + sku_sub + ") "
            params.extend(sub_params)
        if brand:
            cond += " AND TRIM(COALESCE(p.brand_name,'')) = %s "
            params.append(brand)

        if not brand:
            # 品类下钻：返回该品类下的品牌列表（含销售）
            cur.execute("""
                SELECT COALESCE(NULLIF(TRIM(p.brand_name), ''), '未填') AS brand,
                    COUNT(DISTINCT p.sku_code) AS sku_count,
                    AVG(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS avg_retail,
                    COALESCE(SUM(s.sale_qty), 0) AS sale_qty,
                    COALESCE(SUM(s.sale_amount), 0) AS sale_amount
                FROM t_htma_product_master p
                LEFT JOIN t_htma_sale s ON s.sku_code = p.sku_code AND s.store_id = p.store_id AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                """ + cond + """
                GROUP BY brand ORDER BY sale_amount DESC, sku_count DESC LIMIT 100
            """, params)
            rows = cur.fetchall()
            brands = []
            for r in rows:
                brands.append({
                    "name": (r.get("brand") or "未填").strip(),
                    "sku_count": int(r.get("sku_count") or 0),
                    "avg_retail": round(float(r.get("avg_retail") or 0), 2) if r.get("avg_retail") else None,
                    "sale_qty": round(float(r.get("sale_qty") or 0), 2),
                    "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                })
            return jsonify({"success": True, "drill_type": "brands", "category": category, "brands": brands})
        else:
            # 品牌下钻：返回 SKU 销售明细
            cur.execute("""
                SELECT COUNT(*) AS total FROM t_htma_product_master p """ + cond, params)
            total = cur.fetchone().get("total") or 0
            offset = (page - 1) * page_size
            cur.execute("""
                SELECT p.sku_code, p.product_name, p.category_name, p.brand_name, p.retail_price, p.member_price, p.member_discount,
                    COALESCE(SUM(s.sale_qty), 0) AS sale_qty,
                    COALESCE(SUM(s.sale_amount), 0) AS sale_amount,
                    COALESCE(SUM(s.gross_profit), 0) AS gross_profit
                FROM t_htma_product_master p
                LEFT JOIN t_htma_sale s ON s.sku_code = p.sku_code AND s.store_id = p.store_id AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                """ + cond + """
                GROUP BY p.sku_code, p.product_name, p.category_name, p.brand_name, p.retail_price, p.member_price, p.member_discount
                ORDER BY sale_amount DESC
                LIMIT %s OFFSET %s
            """, params + [page_size, offset])
            rows = cur.fetchall()
            skus = []
            for r in rows:
                skus.append({
                    "sku_code": r.get("sku_code"),
                    "product_name": (r.get("product_name") or "").strip() or "-",
                    "category_name": (r.get("category_name") or "").strip() or "-",
                    "brand_name": (r.get("brand_name") or "").strip() or "-",
                    "retail_price": round(float(r.get("retail_price") or 0), 2) if r.get("retail_price") else None,
                    "member_price": round(float(r.get("member_price") or 0), 2) if r.get("member_price") else None,
                    "member_discount": (r.get("member_discount") or "").strip() or None,
                    "sale_qty": round(float(r.get("sale_qty") or 0), 2),
                    "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                    "gross_profit": round(float(r.get("gross_profit") or 0), 2),
                })
            return jsonify({
                "success": True, "drill_type": "skus", "category": category, "brand": brand,
                "skus": skus, "total": total, "page": page, "page_size": page_size
            })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()

def _pm_drill_price_sales_select():
    """返回商品档案下钻用到的价格与近30天销售字段片段（兼容无 wholesale/list_price 列）。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_product_master'
            AND COLUMN_NAME IN ('wholesale_price', 'list_price')
        """)
        cols = {r[0] for r in cur.fetchall()}
        conn.close()
    except Exception:
        cols = set()
    sel = "AVG(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS avg_retail_price, MAX(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS max_retail_price, MIN(CASE WHEN COALESCE(p.retail_price, 0) > 0 THEN p.retail_price END) AS min_retail_price"
    if "wholesale_price" in cols:
        sel += ", AVG(CASE WHEN COALESCE(p.wholesale_price, 0) > 0 THEN p.wholesale_price END) AS avg_wholesale_price"
    else:
        sel += ", NULL AS avg_wholesale_price"
    if "list_price" in cols:
        sel += ", AVG(CASE WHEN COALESCE(p.list_price, 0) > 0 THEN p.list_price END) AS avg_list_price"
    else:
        sel += ", NULL AS avg_list_price"
    return sel
@product_bp.route("/api/product_master/drill_large_categories")
def api_product_master_drill_large():
    """品类下钻：所有大类（含 SKU 数、价格统计、近30天销量/销售额）。需 product_master 权限。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    store_id = (_effective_store_id() or "默认").strip()[:32]
    price_sel = _pm_drill_price_sales_select()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_large_code), ''), '未分类') AS code,
                COALESCE(NULLIF(TRIM(s.category_large), ''), s.category_large_code, '未分类') AS name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                """ + price_sel + """,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large
                FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s
            GROUP BY s.category_large_code, s.category_large ORDER BY sku_count DESC LIMIT 200
        """, [store_id, store_id, store_id])
        rows = _format_drill_rows(cur.fetchall(), "code", "name")
        return jsonify({"success": True, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master/drill_mid_categories")
def api_product_master_drill_mid():
    """品类下钻：指定大类下的中类（含价格与销售统计）。参数 large_code 或 category_large_code。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    large_code = (request.args.get("large_code") or request.args.get("category_large_code") or "").strip()
    if not large_code:
        return jsonify({"success": False, "message": "请提供 large_code"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    price_sel = _pm_drill_price_sales_select()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_mid_code), ''), '未分类') AS code,
                COALESCE(NULLIF(TRIM(s.category_mid), ''), s.category_mid_code, '未分类') AS name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                """ + price_sel + """,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid
                FROM t_htma_sale WHERE store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)
                GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s
            GROUP BY s.category_mid_code, s.category_mid ORDER BY sku_count DESC LIMIT 200
        """, [store_id, large_code, large_code, store_id, store_id])
        rows = _format_drill_rows(cur.fetchall(), "code", "name")
        return jsonify({"success": True, "large_code": large_code, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master/drill_small_categories")
def api_product_master_drill_small():
    """品类下钻：指定大类+中类下的小类。参数 large_code, mid_code。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    large_code = (request.args.get("large_code") or request.args.get("category_large_code") or "").strip()
    mid_code = (request.args.get("mid_code") or request.args.get("category_mid_code") or "").strip()
    if not large_code or not mid_code:
        return jsonify({"success": False, "message": "请提供 large_code 与 mid_code"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    price_sel = _pm_drill_price_sales_select()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_small_code), ''), '未分类') AS code,
                COALESCE(NULLIF(TRIM(s.category_small), ''), NULLIF(TRIM(s.category), ''), s.category_small_code, '未分类') AS name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                """ + price_sel + """,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                FROM t_htma_sale WHERE store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)
                  AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)
                GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s
            GROUP BY s.category_small_code, s.category_small, s.category ORDER BY sku_count DESC LIMIT 200
        """, [store_id, large_code, large_code, mid_code, mid_code, store_id, store_id])
        rows = _format_drill_rows(cur.fetchall(), "code", "name")
        return jsonify({"success": True, "large_code": large_code, "mid_code": mid_code, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master/drill_brands")
def api_product_master_drill_brands():
    """品类下钻：指定大类+中类+小类下的品牌列表。参数 large_code, mid_code, small_code。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    large_code = (request.args.get("large_code") or "").strip()
    mid_code = (request.args.get("mid_code") or "").strip()
    small_code = (request.args.get("small_code") or "").strip()
    if not large_code or not mid_code or not small_code:
        return jsonify({"success": False, "message": "请提供 large_code, mid_code, small_code"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    price_sel = _pm_drill_price_sales_select()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(p.brand_name), ''), '未填') AS name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                """ + price_sel + """,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id FROM t_htma_sale WHERE store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)
                  AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)
                  AND (COALESCE(TRIM(category_small_code), '') = %s OR COALESCE(TRIM(category_small), '') = %s OR COALESCE(TRIM(category), '') = %s)
                GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s
            GROUP BY p.brand_name ORDER BY sku_count DESC LIMIT 200
        """, [store_id, large_code, large_code, mid_code, mid_code, small_code, small_code, small_code, store_id, store_id])
        rows = _format_drill_rows(cur.fetchall(), "name", "name")
        return jsonify({"success": True, "large_code": large_code, "mid_code": mid_code, "small_code": small_code, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master/drill_skus")
def api_product_master_drill_skus():
    """品类/品牌下钻：SKU 列表（含零售价、批发价、划线价、近30天销量/销售额）。参数 large_code, mid_code, small_code, brand；分页 page, page_size。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    large_code = (request.args.get("large_code") or "").strip()
    mid_code = (request.args.get("mid_code") or "").strip()
    small_code = (request.args.get("small_code") or "").strip()
    brand = (request.args.get("brand") or "").strip()
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(10, int(request.args.get("page_size", 50))))
    store_id = (_effective_store_id() or "默认").strip()[:32]
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cond = " WHERE p.store_id = %s "
        params = [store_id]
        if large_code or mid_code or small_code:
            sku_sub = """ SELECT sku_code FROM t_htma_sale WHERE store_id = %s """
            sub_p = [store_id]
            if large_code:
                sku_sub += " AND (COALESCE(TRIM(category_large_code),'') = %s OR COALESCE(TRIM(category_large),'') = %s) "
                sub_p.extend([large_code, large_code])
            if mid_code:
                sku_sub += " AND (COALESCE(TRIM(category_mid_code),'') = %s OR COALESCE(TRIM(category_mid),'') = %s) "
                sub_p.extend([mid_code, mid_code])
            if small_code:
                sku_sub += " AND (COALESCE(TRIM(category_small_code),'') = %s OR COALESCE(TRIM(category_small),'') = %s OR COALESCE(TRIM(category),'') = %s) "
                sub_p.extend([small_code, small_code, small_code])
            sku_sub += " GROUP BY sku_code "
            cond += " AND p.sku_code IN (" + sku_sub + ") "
            params.extend(sub_p)
        if brand:
            cond += " AND TRIM(COALESCE(p.brand_name,'')) = %s "
            params.append(brand)
        cur.execute("SELECT COUNT(DISTINCT p.sku_code) AS total FROM t_htma_product_master p " + cond, params)
        total = cur.fetchone().get("total") or 0
        offset = (page - 1) * page_size
        cur.execute("""
            SELECT p.sku_code, p.product_name, p.category_name, p.brand_name,
                p.retail_price, p.wholesale_price, p.list_price, p.member_price, p.member_discount,
                COALESCE(SUM(s.sale_qty), 0) AS sale_qty,
                COALESCE(SUM(s.sale_amount), 0) AS sale_amount,
                COALESCE(SUM(s.gross_profit), 0) AS gross_profit
            FROM t_htma_product_master p
            LEFT JOIN t_htma_sale s ON s.sku_code = p.sku_code AND s.store_id = p.store_id AND s.data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            """ + cond + """
            GROUP BY p.sku_code, p.product_name, p.category_name, p.brand_name, p.retail_price, p.wholesale_price, p.list_price, p.member_price, p.member_discount
            ORDER BY sale_amount DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])
        rows = cur.fetchall()
        skus = []
        for r in rows:
            skus.append({
                "sku_code": r.get("sku_code"),
                "product_name": (r.get("product_name") or "").strip() or "-",
                "category_name": (r.get("category_name") or "").strip() or "-",
                "brand_name": (r.get("brand_name") or "").strip() or "-",
                "retail_price": _round_price(r.get("retail_price")),
                "wholesale_price": _round_price(r.get("wholesale_price")),
                "list_price": _round_price(r.get("list_price")),
                "member_price": _round_price(r.get("member_price")),
                "member_discount": (r.get("member_discount") or "").strip() or None,
                "sale_qty": round(float(r.get("sale_qty") or 0), 2),
                "sale_amount": round(float(r.get("sale_amount") or 0), 2),
                "gross_profit": round(float(r.get("gross_profit") or 0), 2),
            })
        return jsonify({"success": True, "items": skus, "total": total, "page": page, "page_size": page_size})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()

def _round_price(v):
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None
def _format_drill_rows(rows, code_key, name_key):
    """将下钻查询结果格式化为统一结构（含价格与销售）。"""
    out = []
    for r in rows:
        code = (r.get(code_key) or "未分类").strip()
        name = (r.get(name_key) or code).strip() if name_key else code
        out.append({
            "code": code,
            "name": name,
            "sku_count": int(r.get("sku_count") or 0),
            "avg_retail_price": _round_price(r.get("avg_retail_price")),
            "max_retail_price": _round_price(r.get("max_retail_price")),
            "min_retail_price": _round_price(r.get("min_retail_price")),
            "avg_wholesale_price": _round_price(r.get("avg_wholesale_price")),
            "avg_list_price": _round_price(r.get("avg_list_price")),
            "sales_amount": round(float(r.get("sales_amount") or 0), 2),
            "sales_quantity": round(float(r.get("sales_quantity") or 0), 2),
        })
    return out
@product_bp.route("/api/product_master/brand_large_categories")
def api_product_master_brand_large():
    """品牌下钻：指定品牌下的大类分布（含 SKU 数、价格与销售）。参数 brand。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    brand = (request.args.get("brand") or "").strip()
    if not brand:
        return jsonify({"success": False, "message": "请提供 brand"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    price_sel = _pm_drill_price_sales_select()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_large_code), ''), '未分类') AS code,
                COALESCE(NULLIF(TRIM(s.category_large), ''), s.category_large_code, '未分类') AS name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                """ + price_sel + """,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_large_code) AS category_large_code, MAX(category_large) AS category_large
                FROM t_htma_sale WHERE store_id = %s GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s AND TRIM(COALESCE(p.brand_name,'')) = %s
            GROUP BY s.category_large_code, s.category_large ORDER BY sku_count DESC LIMIT 200
        """, [store_id, store_id, store_id, brand])
        rows = _format_drill_rows(cur.fetchall(), "code", "name")
        return jsonify({"success": True, "brand": brand, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master/brand_mid_categories")
def api_product_master_brand_mid():
    """品牌下钻：指定品牌+大类下的中类分布。参数 brand, large_code。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    brand = (request.args.get("brand") or "").strip()
    large_code = (request.args.get("large_code") or "").strip()
    if not brand or not large_code:
        return jsonify({"success": False, "message": "请提供 brand 与 large_code"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    price_sel = _pm_drill_price_sales_select()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_mid_code), ''), '未分类') AS code,
                COALESCE(NULLIF(TRIM(s.category_mid), ''), s.category_mid_code, '未分类') AS name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                """ + price_sel + """,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_mid_code) AS category_mid_code, MAX(category_mid) AS category_mid
                FROM t_htma_sale WHERE store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)
                GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s AND TRIM(COALESCE(p.brand_name,'')) = %s
            GROUP BY s.category_mid_code, s.category_mid ORDER BY sku_count DESC LIMIT 200
        """, [store_id, large_code, large_code, store_id, store_id, brand])
        rows = _format_drill_rows(cur.fetchall(), "code", "name")
        return jsonify({"success": True, "brand": brand, "large_code": large_code, "items": rows})
    finally:
        conn.close()

@product_bp.route("/api/product_master/brand_small_categories")
def api_product_master_brand_small():
    """品牌下钻：指定品牌+大类+中类下的小类分布。参数 brand, large_code, mid_code。"""
    if _auth_enabled() and not _has_module_access("product_master"):
        return jsonify({"success": False, "message": "无权访问"}), 403
    brand = (request.args.get("brand") or "").strip()
    large_code = (request.args.get("large_code") or "").strip()
    mid_code = (request.args.get("mid_code") or "").strip()
    if not brand or not large_code or not mid_code:
        return jsonify({"success": False, "message": "请提供 brand, large_code 与 mid_code"}), 400
    store_id = (_effective_store_id() or "默认").strip()[:32]
    price_sel = _pm_drill_price_sales_select()
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(s.category_small_code), ''), '未分类') AS code,
                COALESCE(NULLIF(TRIM(s.category_small), ''), NULLIF(TRIM(s.category), ''), s.category_small_code, '未分类') AS name,
                COUNT(DISTINCT p.sku_code) AS sku_count,
                """ + price_sel + """,
                COALESCE(SUM(sale.sale_amount), 0) AS sales_amount,
                COALESCE(SUM(sale.sale_qty), 0) AS sales_quantity
            FROM t_htma_product_master p
            INNER JOIN (
                SELECT sku_code, MAX(store_id) AS store_id, MAX(category_small_code) AS category_small_code, MAX(category_small) AS category_small, MAX(category) AS category
                FROM t_htma_sale WHERE store_id = %s
                  AND (COALESCE(TRIM(category_large_code), '') = %s OR COALESCE(TRIM(category_large), '') = %s)
                  AND (COALESCE(TRIM(category_mid_code), '') = %s OR COALESCE(TRIM(category_mid), '') = %s)
                GROUP BY sku_code
            ) s ON p.sku_code = s.sku_code AND p.store_id = s.store_id
            LEFT JOIN (
                SELECT sku_code, SUM(sale_amount) AS sale_amount, SUM(sale_qty) AS sale_qty
                FROM t_htma_sale WHERE store_id = %s AND data_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY sku_code
            ) sale ON sale.sku_code = p.sku_code
            WHERE p.store_id = %s AND TRIM(COALESCE(p.brand_name,'')) = %s
            GROUP BY s.category_small_code, s.category_small, s.category ORDER BY sku_count DESC LIMIT 200
        """, [store_id, large_code, large_code, mid_code, mid_code, store_id, store_id, brand])
        rows = _format_drill_rows(cur.fetchall(), "code", "name")
        return jsonify({"success": True, "brand": brand, "large_code": large_code, "mid_code": mid_code, "items": rows})
    finally:
        conn.close()

