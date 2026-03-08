#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行 03_add_full_columns.sql，忽略已存在的列。数据库配置从 .env 的 MYSQL_* 读取。"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass
sys.path.insert(0, _ROOT)

import pymysql
from htma_dashboard.db_config import DB_CONFIG

# 建列不需要 DictCursor
DB = {k: v for k, v in DB_CONFIG.items() if k != "cursorclass"}

ALTERS = [
    # t_htma_sale
    ("t_htma_sale", "warehouse_code", "VARCHAR(32) DEFAULT NULL COMMENT '仓库编码'"),
    ("t_htma_sale", "warehouse_name", "VARCHAR(64) DEFAULT NULL COMMENT '仓库名称'"),
    ("t_htma_sale", "product_name", "VARCHAR(128) DEFAULT NULL COMMENT '品名'"),
    ("t_htma_sale", "barcode", "VARCHAR(64) DEFAULT NULL COMMENT '国际条码'"),
    ("t_htma_sale", "short_name", "VARCHAR(64) DEFAULT NULL COMMENT '简称'"),
    ("t_htma_sale", "unit", "VARCHAR(16) DEFAULT NULL COMMENT '单位'"),
    ("t_htma_sale", "spec", "VARCHAR(64) DEFAULT NULL COMMENT '规格'"),
    ("t_htma_sale", "category_code", "VARCHAR(32) DEFAULT NULL COMMENT '类别编码'"),
    ("t_htma_sale", "category_large_code", "VARCHAR(32) DEFAULT NULL COMMENT '大类编码'"),
    ("t_htma_sale", "category_large", "VARCHAR(64) DEFAULT NULL COMMENT '大类名称'"),
    ("t_htma_sale", "category_mid_code", "VARCHAR(32) DEFAULT NULL COMMENT '中类编码'"),
    ("t_htma_sale", "category_mid", "VARCHAR(64) DEFAULT NULL COMMENT '中类名称'"),
    ("t_htma_sale", "category_small_code", "VARCHAR(32) DEFAULT NULL COMMENT '小类编码'"),
    ("t_htma_sale", "category_small", "VARCHAR(64) DEFAULT NULL COMMENT '小类名称'"),
    ("t_htma_sale", "supplier_code", "VARCHAR(64) DEFAULT NULL COMMENT '供应商编码'"),
    ("t_htma_sale", "supplier_name", "VARCHAR(128) DEFAULT NULL COMMENT '供应商名称'"),
    ("t_htma_sale", "supplier_main_code", "VARCHAR(64) DEFAULT NULL COMMENT '主供应商编码'"),
    ("t_htma_sale", "supplier_main_name", "VARCHAR(128) DEFAULT NULL COMMENT '主供应商名称'"),
    ("t_htma_sale", "brand_code", "VARCHAR(32) DEFAULT NULL COMMENT '品牌编码'"),
    ("t_htma_sale", "brand_name", "VARCHAR(64) DEFAULT NULL COMMENT '品牌名称'"),
    ("t_htma_sale", "category_group_code", "VARCHAR(32) DEFAULT NULL COMMENT '课组编码'"),
    ("t_htma_sale", "category_group_name", "VARCHAR(64) DEFAULT NULL COMMENT '课组名称'"),
    ("t_htma_sale", "location_code", "VARCHAR(32) DEFAULT NULL COMMENT '库位编码'"),
    ("t_htma_sale", "location_name", "VARCHAR(64) DEFAULT NULL COMMENT '库位名称'"),
    ("t_htma_sale", "joint_rate", "DECIMAL(8,4) DEFAULT NULL COMMENT '联营扣率'"),
    ("t_htma_sale", "avg_sale_price", "DECIMAL(14,4) DEFAULT NULL COMMENT '平均售价'"),
    ("t_htma_sale", "sale_price", "DECIMAL(14,4) DEFAULT NULL COMMENT '售价'"),
    ("t_htma_sale", "return_qty", "DECIMAL(12,2) DEFAULT 0 COMMENT '退货数量'"),
    ("t_htma_sale", "return_amount", "DECIMAL(14,2) DEFAULT 0 COMMENT '退货金额'"),
    ("t_htma_sale", "gift_qty", "DECIMAL(12,2) DEFAULT 0 COMMENT '赠送数量'"),
    ("t_htma_sale", "gift_amount", "DECIMAL(14,2) DEFAULT 0 COMMENT '赠送金额'"),
    ("t_htma_sale", "qty_total", "DECIMAL(12,2) DEFAULT NULL COMMENT '数量小计'"),
    ("t_htma_sale", "qty_ratio", "DECIMAL(8,4) DEFAULT NULL COMMENT '数量小计占比'"),
    ("t_htma_sale", "amount_total", "DECIMAL(14,2) DEFAULT NULL COMMENT '金额小计'"),
    ("t_htma_sale", "amount_ratio", "DECIMAL(8,4) DEFAULT NULL COMMENT '金额小计占比'"),
    ("t_htma_sale", "return_price", "DECIMAL(14,4) DEFAULT NULL COMMENT '退货价'"),
    ("t_htma_sale", "cost_amount", "DECIMAL(14,2) DEFAULT NULL COMMENT '参考进价金额'"),
    ("t_htma_sale", "margin_amount", "DECIMAL(14,2) DEFAULT NULL COMMENT '进销差价金额'"),
    ("t_htma_sale", "current_stock", "DECIMAL(12,2) DEFAULT NULL COMMENT '当前库存'"),
    ("t_htma_sale", "gender", "VARCHAR(32) DEFAULT NULL COMMENT '性别'"),
    ("t_htma_sale", "top_bottom", "VARCHAR(32) DEFAULT NULL COMMENT '上下装'"),
    ("t_htma_sale", "style", "VARCHAR(64) DEFAULT NULL COMMENT '风格'"),
    ("t_htma_sale", "division", "VARCHAR(64) DEFAULT NULL COMMENT '事业部'"),
    ("t_htma_sale", "color_system", "VARCHAR(32) DEFAULT NULL COMMENT '色系'"),
    ("t_htma_sale", "color_depth", "VARCHAR(32) DEFAULT NULL COMMENT '色深'"),
    ("t_htma_sale", "standard_code", "VARCHAR(64) DEFAULT NULL COMMENT '标准码'"),
    ("t_htma_sale", "original_barcode", "VARCHAR(64) DEFAULT NULL COMMENT '原条码'"),
    ("t_htma_sale", "thickness", "VARCHAR(32) DEFAULT NULL COMMENT '厚度'"),
    ("t_htma_sale", "length", "VARCHAR(32) DEFAULT NULL COMMENT '长度'"),
    ("t_htma_sale", "source_sheet", "VARCHAR(16) DEFAULT 'sale_daily' COMMENT '来源'"),
    ("t_htma_sale", "biz_mode", "VARCHAR(32) DEFAULT NULL COMMENT '经营方式'"),
    # t_htma_stock
    ("t_htma_stock", "warehouse_code", "VARCHAR(32) DEFAULT NULL COMMENT '仓库编码'"),
    ("t_htma_stock", "warehouse_name", "VARCHAR(64) DEFAULT NULL COMMENT '仓库名称'"),
    ("t_htma_stock", "category_name", "VARCHAR(64) DEFAULT NULL COMMENT '类别名称'"),
    ("t_htma_stock", "barcode", "VARCHAR(64) DEFAULT NULL COMMENT '国际条码'"),
    ("t_htma_stock", "product_name", "VARCHAR(128) DEFAULT NULL COMMENT '商品名称'"),
    ("t_htma_stock", "spec", "VARCHAR(64) DEFAULT NULL COMMENT '规格'"),
    ("t_htma_stock", "unit", "VARCHAR(16) DEFAULT NULL COMMENT '单位'"),
    ("t_htma_stock", "product_status", "VARCHAR(32) DEFAULT NULL COMMENT '商品状态'"),
    ("t_htma_stock", "branch_manage", "VARCHAR(32) DEFAULT NULL COMMENT '分店经营'"),
    ("t_htma_stock", "stock_boxes", "DECIMAL(12,2) DEFAULT NULL COMMENT '库存箱数'"),
    ("t_htma_stock", "stock_amount_retail", "DECIMAL(14,2) DEFAULT NULL COMMENT '库存金额(零售价)'"),
    ("t_htma_stock", "sale_price", "DECIMAL(14,4) DEFAULT NULL COMMENT '售价'"),
    ("t_htma_stock", "short_name", "VARCHAR(64) DEFAULT NULL COMMENT '商品简称'"),
    ("t_htma_stock", "brand_code", "VARCHAR(32) DEFAULT NULL COMMENT '品牌编码'"),
    ("t_htma_stock", "brand_name", "VARCHAR(64) DEFAULT NULL COMMENT '品牌名称'"),
    ("t_htma_stock", "supplier_code", "VARCHAR(64) DEFAULT NULL COMMENT '供应商编码'"),
    ("t_htma_stock", "supplier_name", "VARCHAR(128) DEFAULT NULL COMMENT '主供应商'"),
    ("t_htma_stock", "location_code", "VARCHAR(32) DEFAULT NULL COMMENT '库位'"),
    ("t_htma_stock", "location_name", "VARCHAR(64) DEFAULT NULL COMMENT '库位名称'"),
    ("t_htma_stock", "contact", "VARCHAR(64) DEFAULT NULL COMMENT '联系方式'"),
    ("t_htma_stock", "biz_mode", "VARCHAR(32) DEFAULT NULL COMMENT '经营方式'"),
    # t_htma_stock 格式二（库存查询_默认）所需列
    ("t_htma_stock", "category_large_code", "VARCHAR(32) DEFAULT NULL COMMENT '大类编码'"),
    ("t_htma_stock", "category_large", "VARCHAR(64) DEFAULT NULL COMMENT '大类名称'"),
    ("t_htma_stock", "category_mid_code", "VARCHAR(32) DEFAULT NULL COMMENT '中类编码'"),
    ("t_htma_stock", "category_mid", "VARCHAR(64) DEFAULT NULL COMMENT '中类名称'"),
    ("t_htma_stock", "category_small_code", "VARCHAR(32) DEFAULT NULL COMMENT '小类编码'"),
    ("t_htma_stock", "category_small", "VARCHAR(64) DEFAULT NULL COMMENT '小类名称'"),
    ("t_htma_stock", "product_code", "VARCHAR(64) DEFAULT NULL COMMENT '品号'"),
    ("t_htma_stock", "avg_price", "DECIMAL(14,4) DEFAULT NULL COMMENT '平均价'"),
    ("t_htma_stock", "aging", "DECIMAL(10,4) DEFAULT NULL COMMENT '账龄'"),
    ("t_htma_stock", "last_change_date", "DATETIME DEFAULT NULL COMMENT '上次变动日期'"),
    ("t_htma_stock", "avg_inbound_price", "DECIMAL(14,4) DEFAULT NULL COMMENT '平均入库价'"),
    # t_htma_profit 分类层级
    ("t_htma_profit", "category_code", "VARCHAR(32) DEFAULT NULL COMMENT '类别编码'"),
    ("t_htma_profit", "category_large_code", "VARCHAR(32) DEFAULT NULL COMMENT '大类编码'"),
    ("t_htma_profit", "category_large", "VARCHAR(64) DEFAULT NULL COMMENT '大类名称'"),
    ("t_htma_profit", "category_mid_code", "VARCHAR(32) DEFAULT NULL COMMENT '中类编码'"),
    ("t_htma_profit", "category_mid", "VARCHAR(64) DEFAULT NULL COMMENT '中类名称'"),
    ("t_htma_profit", "category_small_code", "VARCHAR(32) DEFAULT NULL COMMENT '小类编码'"),
    ("t_htma_profit", "category_small", "VARCHAR(64) DEFAULT NULL COMMENT '小类名称'"),
    # t_htma_category_mapping
    ("t_htma_category_mapping", "category_large_code", "VARCHAR(32) DEFAULT NULL COMMENT '大类编码'"),
    ("t_htma_category_mapping", "category_large", "VARCHAR(64) DEFAULT NULL COMMENT '大类名称'"),
    ("t_htma_category_mapping", "category_mid_code", "VARCHAR(32) DEFAULT NULL COMMENT '中类编码'"),
    ("t_htma_category_mapping", "category_mid", "VARCHAR(64) DEFAULT NULL COMMENT '中类名称'"),
    ("t_htma_category_mapping", "category_small_code", "VARCHAR(32) DEFAULT NULL COMMENT '小类编码'"),
    ("t_htma_category_mapping", "category_small", "VARCHAR(64) DEFAULT NULL COMMENT '小类名称'"),
    # t_htma_labor_cost：姓名、税前应发、供应商，便于与汇总表口径一致（开票金额/总成本、斗米/中锐/快聘/保洁）
    ("t_htma_labor_cost", "person_name", "VARCHAR(64) DEFAULT '' COMMENT '姓名'"),
    ("t_htma_labor_cost", "pre_tax_pay", "DECIMAL(14,2) DEFAULT NULL COMMENT '税前应发'"),
    ("t_htma_labor_cost", "supplier_name", "VARCHAR(64) NOT NULL DEFAULT '' COMMENT '供应商(斗米/中锐/快聘/保洁等)'"),
    # 兼职/小时工明细扩展（全量导入）
    ("t_htma_labor_cost", "store_name", "VARCHAR(64) DEFAULT NULL COMMENT '店铺名'"),
    ("t_htma_labor_cost", "city", "VARCHAR(32) DEFAULT NULL COMMENT '城市'"),
    ("t_htma_labor_cost", "join_date", "VARCHAR(32) DEFAULT NULL COMMENT '入职日期'"),
    ("t_htma_labor_cost", "leave_date", "VARCHAR(32) DEFAULT NULL COMMENT '离职日期'"),
    ("t_htma_labor_cost", "normal_hours", "DECIMAL(12,2) DEFAULT NULL COMMENT '普通工时'"),
    ("t_htma_labor_cost", "triple_pay_hours", "DECIMAL(12,2) DEFAULT NULL COMMENT '三薪工时'"),
    ("t_htma_labor_cost", "hourly_rate", "DECIMAL(10,2) DEFAULT NULL COMMENT '时薪'"),
    ("t_htma_labor_cost", "pay_amount", "DECIMAL(14,2) DEFAULT NULL COMMENT '发薪金额'"),
    ("t_htma_labor_cost", "service_fee_unit", "DECIMAL(10,2) DEFAULT NULL COMMENT '服务费单价'"),
    ("t_htma_labor_cost", "service_fee_total", "DECIMAL(14,2) DEFAULT NULL COMMENT '服务费总计'"),
    ("t_htma_labor_cost", "tax", "DECIMAL(14,2) DEFAULT NULL COMMENT '税费'"),
    ("t_htma_labor_cost", "cost_include", "VARCHAR(32) DEFAULT NULL COMMENT '成本计入(兼职/小时工)'"),
    ("t_htma_labor_cost", "department", "VARCHAR(64) DEFAULT NULL COMMENT '用人部门(中锐/快聘等)'"),
]

def main():
    conn = pymysql.connect(**DB)
    added = 0
    skipped = 0
    for tbl, col, defn in ALTERS:
        try:
            conn.cursor().execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {defn}")
            conn.commit()
            print(f"  + {tbl}.{col}")
            added += 1
        except pymysql.err.OperationalError as e:
            if "Duplicate column" in str(e):
                skipped += 1
            else:
                print(f"  ! {tbl}.{col}: {e}")
    # t_htma_labor_cost 唯一键改为含 person_name、supplier_name，支持同一岗位多人、多供应商
    try:
        cur = conn.cursor()
        cur.execute("UPDATE t_htma_labor_cost SET person_name = '' WHERE person_name IS NULL")
        conn.commit()
        cur.execute("UPDATE t_htma_labor_cost SET supplier_name = '' WHERE supplier_name IS NULL")
        conn.commit()
        cur.execute("ALTER TABLE t_htma_labor_cost DROP INDEX uk_month_type_position")
        conn.commit()
        cur.execute("ALTER TABLE t_htma_labor_cost ADD UNIQUE KEY uk_month_type_position (report_month, position_type, position_name, person_name(64), supplier_name(64), store_id)")
        conn.commit()
        print("  t_htma_labor_cost: 唯一键已含 person_name, supplier_name")
    except pymysql.err.OperationalError as e:
        if "check that column/key exists" in str(e).lower() or "1091" in str(e) or "Duplicate" in str(e) or "Unknown column" in str(e):
            pass
        else:
            print("  ! t_htma_labor_cost 唯一键:", e)
    conn.close()
    print(f"\n完成: 新增 {added} 列, 跳过已存在 {skipped} 列")

if __name__ == "__main__":
    main()
