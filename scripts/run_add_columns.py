#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行 03_add_full_columns.sql，忽略已存在的列"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'htma_dashboard'))
import pymysql

DB = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", "62102218"),
    "database": "htma_dashboard",
    "charset": "utf8mb4",
}

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
    conn.close()
    print(f"\n完成: 新增 {added} 列, 跳过已存在 {skipped} 列")

if __name__ == "__main__":
    main()
