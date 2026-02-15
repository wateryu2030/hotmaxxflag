-- =====================================================
-- 好特卖超级仓 - 补齐全量字段
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 htma_dashboard < scripts/03_add_full_columns.sql
-- 若某列已存在会报错，可忽略继续
-- =====================================================

USE htma_dashboard;

-- 销售表 t_htma_sale 补齐字段
ALTER TABLE t_htma_sale ADD COLUMN warehouse_code VARCHAR(32) DEFAULT NULL COMMENT '仓库编码';
ALTER TABLE t_htma_sale ADD COLUMN warehouse_name VARCHAR(64) DEFAULT NULL COMMENT '仓库名称';
ALTER TABLE t_htma_sale ADD COLUMN product_name VARCHAR(128) DEFAULT NULL COMMENT '品名';
ALTER TABLE t_htma_sale ADD COLUMN barcode VARCHAR(64) DEFAULT NULL COMMENT '国际条码';
ALTER TABLE t_htma_sale ADD COLUMN short_name VARCHAR(64) DEFAULT NULL COMMENT '简称';
ALTER TABLE t_htma_sale ADD COLUMN unit VARCHAR(16) DEFAULT NULL COMMENT '单位';
ALTER TABLE t_htma_sale ADD COLUMN spec VARCHAR(64) DEFAULT NULL COMMENT '规格';
ALTER TABLE t_htma_sale ADD COLUMN category_code VARCHAR(32) DEFAULT NULL COMMENT '类别编码';
ALTER TABLE t_htma_sale ADD COLUMN category_large_code VARCHAR(32) DEFAULT NULL COMMENT '大类编码';
ALTER TABLE t_htma_sale ADD COLUMN category_large VARCHAR(64) DEFAULT NULL COMMENT '大类名称';
ALTER TABLE t_htma_sale ADD COLUMN category_mid_code VARCHAR(32) DEFAULT NULL COMMENT '中类编码';
ALTER TABLE t_htma_sale ADD COLUMN category_mid VARCHAR(64) DEFAULT NULL COMMENT '中类名称';
ALTER TABLE t_htma_sale ADD COLUMN category_small_code VARCHAR(32) DEFAULT NULL COMMENT '小类编码';
ALTER TABLE t_htma_sale ADD COLUMN category_small VARCHAR(64) DEFAULT NULL COMMENT '小类名称';
ALTER TABLE t_htma_sale ADD COLUMN supplier_code VARCHAR(64) DEFAULT NULL COMMENT '供应商编码';
ALTER TABLE t_htma_sale ADD COLUMN supplier_name VARCHAR(128) DEFAULT NULL COMMENT '供应商名称';
ALTER TABLE t_htma_sale ADD COLUMN supplier_main_code VARCHAR(64) DEFAULT NULL COMMENT '主供应商编码';
ALTER TABLE t_htma_sale ADD COLUMN supplier_main_name VARCHAR(128) DEFAULT NULL COMMENT '主供应商名称';
ALTER TABLE t_htma_sale ADD COLUMN brand_code VARCHAR(32) DEFAULT NULL COMMENT '品牌编码';
ALTER TABLE t_htma_sale ADD COLUMN brand_name VARCHAR(64) DEFAULT NULL COMMENT '品牌名称';
ALTER TABLE t_htma_sale ADD COLUMN category_group_code VARCHAR(32) DEFAULT NULL COMMENT '课组编码';
ALTER TABLE t_htma_sale ADD COLUMN category_group_name VARCHAR(64) DEFAULT NULL COMMENT '课组名称';
ALTER TABLE t_htma_sale ADD COLUMN location_code VARCHAR(32) DEFAULT NULL COMMENT '库位编码';
ALTER TABLE t_htma_sale ADD COLUMN location_name VARCHAR(64) DEFAULT NULL COMMENT '库位名称';
ALTER TABLE t_htma_sale ADD COLUMN joint_rate DECIMAL(8,4) DEFAULT NULL COMMENT '联营扣率';
ALTER TABLE t_htma_sale ADD COLUMN avg_sale_price DECIMAL(14,4) DEFAULT NULL COMMENT '平均售价';
ALTER TABLE t_htma_sale ADD COLUMN sale_price DECIMAL(14,4) DEFAULT NULL COMMENT '售价';
ALTER TABLE t_htma_sale ADD COLUMN return_qty DECIMAL(12,2) DEFAULT 0 COMMENT '退货数量';
ALTER TABLE t_htma_sale ADD COLUMN return_amount DECIMAL(14,2) DEFAULT 0 COMMENT '退货金额';
ALTER TABLE t_htma_sale ADD COLUMN gift_qty DECIMAL(12,2) DEFAULT 0 COMMENT '赠送数量';
ALTER TABLE t_htma_sale ADD COLUMN gift_amount DECIMAL(14,2) DEFAULT 0 COMMENT '赠送金额';
ALTER TABLE t_htma_sale ADD COLUMN qty_total DECIMAL(12,2) DEFAULT NULL COMMENT '数量小计';
ALTER TABLE t_htma_sale ADD COLUMN qty_ratio DECIMAL(8,4) DEFAULT NULL COMMENT '数量小计占比';
ALTER TABLE t_htma_sale ADD COLUMN amount_total DECIMAL(14,2) DEFAULT NULL COMMENT '金额小计';
ALTER TABLE t_htma_sale ADD COLUMN amount_ratio DECIMAL(8,4) DEFAULT NULL COMMENT '金额小计占比';
ALTER TABLE t_htma_sale ADD COLUMN return_price DECIMAL(14,4) DEFAULT NULL COMMENT '退货价';
ALTER TABLE t_htma_sale ADD COLUMN cost_amount DECIMAL(14,2) DEFAULT NULL COMMENT '参考进价金额';
ALTER TABLE t_htma_sale ADD COLUMN margin_amount DECIMAL(14,2) DEFAULT NULL COMMENT '进销差价金额';
ALTER TABLE t_htma_sale ADD COLUMN current_stock DECIMAL(12,2) DEFAULT NULL COMMENT '当前库存';
ALTER TABLE t_htma_sale ADD COLUMN gender VARCHAR(32) DEFAULT NULL COMMENT '性别';
ALTER TABLE t_htma_sale ADD COLUMN top_bottom VARCHAR(32) DEFAULT NULL COMMENT '上下装';
ALTER TABLE t_htma_sale ADD COLUMN style VARCHAR(64) DEFAULT NULL COMMENT '风格';
ALTER TABLE t_htma_sale ADD COLUMN division VARCHAR(64) DEFAULT NULL COMMENT '事业部';
ALTER TABLE t_htma_sale ADD COLUMN color_system VARCHAR(32) DEFAULT NULL COMMENT '色系';
ALTER TABLE t_htma_sale ADD COLUMN color_depth VARCHAR(32) DEFAULT NULL COMMENT '色深';
ALTER TABLE t_htma_sale ADD COLUMN standard_code VARCHAR(64) DEFAULT NULL COMMENT '标准码';
ALTER TABLE t_htma_sale ADD COLUMN original_barcode VARCHAR(64) DEFAULT NULL COMMENT '原条码';
ALTER TABLE t_htma_sale ADD COLUMN thickness VARCHAR(32) DEFAULT NULL COMMENT '厚度';
ALTER TABLE t_htma_sale ADD COLUMN length VARCHAR(32) DEFAULT NULL COMMENT '长度';
ALTER TABLE t_htma_sale ADD COLUMN source_sheet VARCHAR(16) DEFAULT 'sale_daily' COMMENT '来源';
ALTER TABLE t_htma_sale ADD COLUMN biz_mode VARCHAR(32) DEFAULT NULL COMMENT '经营方式';

-- 库存表 t_htma_stock 补齐字段
ALTER TABLE t_htma_stock ADD COLUMN warehouse_code VARCHAR(32) DEFAULT NULL COMMENT '仓库编码';
ALTER TABLE t_htma_stock ADD COLUMN warehouse_name VARCHAR(64) DEFAULT NULL COMMENT '仓库名称';
ALTER TABLE t_htma_stock ADD COLUMN category_name VARCHAR(64) DEFAULT NULL COMMENT '类别名称';
ALTER TABLE t_htma_stock ADD COLUMN barcode VARCHAR(64) DEFAULT NULL COMMENT '国际条码';
ALTER TABLE t_htma_stock ADD COLUMN product_name VARCHAR(128) DEFAULT NULL COMMENT '商品名称';
ALTER TABLE t_htma_stock ADD COLUMN spec VARCHAR(64) DEFAULT NULL COMMENT '规格';
ALTER TABLE t_htma_stock ADD COLUMN unit VARCHAR(16) DEFAULT NULL COMMENT '单位';
ALTER TABLE t_htma_stock ADD COLUMN product_status VARCHAR(32) DEFAULT NULL COMMENT '商品状态';
ALTER TABLE t_htma_stock ADD COLUMN branch_manage VARCHAR(32) DEFAULT NULL COMMENT '分店经营';
ALTER TABLE t_htma_stock ADD COLUMN stock_boxes DECIMAL(12,2) DEFAULT NULL COMMENT '库存箱数';
ALTER TABLE t_htma_stock ADD COLUMN stock_amount_retail DECIMAL(14,2) DEFAULT NULL COMMENT '库存金额(零售价)';
ALTER TABLE t_htma_stock ADD COLUMN sale_price DECIMAL(14,4) DEFAULT NULL COMMENT '售价';
ALTER TABLE t_htma_stock ADD COLUMN short_name VARCHAR(64) DEFAULT NULL COMMENT '商品简称';
ALTER TABLE t_htma_stock ADD COLUMN brand_code VARCHAR(32) DEFAULT NULL COMMENT '品牌编码';
ALTER TABLE t_htma_stock ADD COLUMN brand_name VARCHAR(64) DEFAULT NULL COMMENT '品牌名称';
ALTER TABLE t_htma_stock ADD COLUMN supplier_code VARCHAR(64) DEFAULT NULL COMMENT '供应商编码';
ALTER TABLE t_htma_stock ADD COLUMN supplier_name VARCHAR(128) DEFAULT NULL COMMENT '主供应商';
ALTER TABLE t_htma_stock ADD COLUMN location_code VARCHAR(32) DEFAULT NULL COMMENT '库位';
ALTER TABLE t_htma_stock ADD COLUMN location_name VARCHAR(64) DEFAULT NULL COMMENT '库位名称';
ALTER TABLE t_htma_stock ADD COLUMN contact VARCHAR(64) DEFAULT NULL COMMENT '联系方式';
ALTER TABLE t_htma_stock ADD COLUMN biz_mode VARCHAR(32) DEFAULT NULL COMMENT '经营方式';

-- 毛利表 t_htma_profit 补齐分类层级字段（与销售表一致，便于按层级筛选）
ALTER TABLE t_htma_profit ADD COLUMN category_code VARCHAR(32) DEFAULT NULL COMMENT '类别编码';
ALTER TABLE t_htma_profit ADD COLUMN category_large_code VARCHAR(32) DEFAULT NULL COMMENT '大类编码';
ALTER TABLE t_htma_profit ADD COLUMN category_large VARCHAR(64) DEFAULT NULL COMMENT '大类名称';
ALTER TABLE t_htma_profit ADD COLUMN category_mid_code VARCHAR(32) DEFAULT NULL COMMENT '中类编码';
ALTER TABLE t_htma_profit ADD COLUMN category_mid VARCHAR(64) DEFAULT NULL COMMENT '中类名称';
ALTER TABLE t_htma_profit ADD COLUMN category_small_code VARCHAR(32) DEFAULT NULL COMMENT '小类编码';
ALTER TABLE t_htma_profit ADD COLUMN category_small VARCHAR(64) DEFAULT NULL COMMENT '小类名称';

-- 品类映射表 t_htma_category_mapping 补齐字段
ALTER TABLE t_htma_category_mapping ADD COLUMN category_large_code VARCHAR(32) DEFAULT NULL COMMENT '大类编码';
ALTER TABLE t_htma_category_mapping ADD COLUMN category_large VARCHAR(64) DEFAULT NULL COMMENT '大类名称';
ALTER TABLE t_htma_category_mapping ADD COLUMN category_mid_code VARCHAR(32) DEFAULT NULL COMMENT '中类编码';
ALTER TABLE t_htma_category_mapping ADD COLUMN category_mid VARCHAR(64) DEFAULT NULL COMMENT '中类名称';
ALTER TABLE t_htma_category_mapping ADD COLUMN category_small_code VARCHAR(32) DEFAULT NULL COMMENT '小类编码';
ALTER TABLE t_htma_category_mapping ADD COLUMN category_small VARCHAR(64) DEFAULT NULL COMMENT '小类名称';

SELECT 'Done. 字段已补齐' AS msg;
