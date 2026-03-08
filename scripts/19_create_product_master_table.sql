-- =====================================================
-- 分店商品档案全量表（与「分店商品档案_YYYYMMDD_*.xlsx」对应）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/19_create_product_master_table.sql
-- =====================================================

USE htma_dashboard;

DROP TABLE IF EXISTS t_htma_product_master;

CREATE TABLE t_htma_product_master (
  id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  store_id                VARCHAR(32)     NOT NULL DEFAULT '默认' COMMENT '门店/分店ID',
  archive_date            DATE            DEFAULT NULL COMMENT '档案导出日期(文件名中的日期)',
  -- 状态与标识
  product_status          VARCHAR(32)     DEFAULT NULL COMMENT '商品状态(新品/正常等)',
  sku_code                VARCHAR(64)     NOT NULL COMMENT '货号',
  barcode                 VARCHAR(64)     DEFAULT NULL COMMENT '国际条码',
  product_name            VARCHAR(256)    DEFAULT NULL COMMENT '品名',
  -- 品类
  category_code           VARCHAR(32)     DEFAULT NULL COMMENT '类别编码',
  category_name           VARCHAR(64)     DEFAULT NULL COMMENT '类别',
  -- 供应商
  supplier_code           VARCHAR(32)     DEFAULT NULL COMMENT '供应商编码',
  supplier_name           VARCHAR(128)    DEFAULT NULL COMMENT '供应商',
  -- 价格
  wholesale_price         DECIMAL(14, 4)  DEFAULT NULL COMMENT '批发价',
  retail_price            DECIMAL(14, 4)   DEFAULT NULL COMMENT '零售价',
  member_price            DECIMAL(14, 4)   DEFAULT NULL COMMENT '会员价',
  member_price_1          DECIMAL(14, 4)  DEFAULT NULL COMMENT '会员价1',
  member_price_2          DECIMAL(14, 4)  DEFAULT NULL COMMENT '会员价2',
  delivery_price          DECIMAL(14, 4)  DEFAULT NULL COMMENT '配送价',
  min_sale_price          DECIMAL(14, 4)  DEFAULT NULL COMMENT '最低售价',
  list_price              DECIMAL(14, 4)  DEFAULT NULL COMMENT '划线价',
  wholesale_price_1       DECIMAL(14, 4)  DEFAULT NULL COMMENT '批发价1',
  wholesale_price_2       DECIMAL(14, 4)  DEFAULT NULL COMMENT '批发价2',
  wholesale_price_3       DECIMAL(14, 4)  DEFAULT NULL COMMENT '批发价3',
  wholesale_price_4       DECIMAL(14, 4)  DEFAULT NULL COMMENT '批发价4',
  -- 单位与规格
  unit                    VARCHAR(16)     DEFAULT NULL COMMENT '单位',
  spec                    VARCHAR(128)    DEFAULT NULL COMMENT '规格',
  origin                  VARCHAR(64)     DEFAULT NULL COMMENT '产地',
  -- 商品属性
  product_type            VARCHAR(32)     DEFAULT NULL COMMENT '商品类型(普通商品/捆绑商品/代销等)',
  allow_discount          VARCHAR(16)     DEFAULT NULL COMMENT '允许折扣',
  purchase_scope           VARCHAR(32)     DEFAULT NULL COMMENT '采购范围',
  counter_bargain         VARCHAR(16)     DEFAULT NULL COMMENT '前台议价',
  member_discount         VARCHAR(16)     DEFAULT NULL COMMENT '会员折扣',
  -- 税
  input_tax               DECIMAL(8, 4)   DEFAULT NULL COMMENT '进项税',
  deduct_tax               VARCHAR(16)     DEFAULT NULL COMMENT '是否扣除税',
  output_tax              DECIMAL(8, 4)   DEFAULT NULL COMMENT '销项税',
  tax_free                VARCHAR(16)     DEFAULT NULL COMMENT '是否免税',
  -- 进销存与经营
  purchase_spec           DECIMAL(14, 4)  DEFAULT NULL COMMENT '进货规格',
  distribution_mode      VARCHAR(32)     DEFAULT NULL COMMENT '经销方式(购销/代销等)',
  maintain_stock          VARCHAR(16)     DEFAULT NULL COMMENT '维护库存',
  joint_rate              DECIMAL(8, 4)   DEFAULT NULL COMMENT '联营扣率',
  store_price_change      VARCHAR(16)     DEFAULT NULL COMMENT '分店变价',
  shelf_life              DECIMAL(12, 2)  DEFAULT NULL COMMENT '保质期',
  expiry_warning_days     INT             DEFAULT NULL COMMENT '到期预警天数',
  pricing_mode            VARCHAR(32)     DEFAULT NULL COMMENT '计价方式',
  is_fresh                VARCHAR(16)     DEFAULT NULL COMMENT '生鲜商品',
  loss_rate               DECIMAL(8, 4)   DEFAULT NULL COMMENT '损耗率',
  points_value            DECIMAL(12, 4)  DEFAULT NULL COMMENT '积分值',
  is_points               VARCHAR(16)     DEFAULT NULL COMMENT '是否积分',
  -- 品牌与课组
  brand_code              VARCHAR(32)     DEFAULT NULL COMMENT '品牌编码',
  brand_name              VARCHAR(64)     DEFAULT NULL COMMENT '品牌',
  class_group             VARCHAR(64)     DEFAULT NULL COMMENT '课组',
  mnemonic_code          VARCHAR(64)     DEFAULT NULL COMMENT '助记码',
  product_short_name     VARCHAR(128)    DEFAULT NULL COMMENT '商品简称',
  -- 提成与人员
  salesman_commission_rate DECIMAL(8, 4)  DEFAULT NULL COMMENT '业务员提成比率',
  commission_rate        DECIMAL(8, 4)   DEFAULT NULL COMMENT '提成率',
  creator_code           VARCHAR(32)     DEFAULT NULL COMMENT '建档人编码',
  creator_name           VARCHAR(64)     DEFAULT NULL COMMENT '建档人名称',
  created_at             DATETIME        DEFAULT NULL COMMENT '建档日期',
  modifier_code          VARCHAR(32)     DEFAULT NULL COMMENT '最后修改人编码',
  modifier_name          VARCHAR(64)     DEFAULT NULL COMMENT '最后修改人名称',
  updated_at             DATETIME        DEFAULT NULL COMMENT '修改日期',
  stop_purchase_date      DATE            DEFAULT NULL COMMENT '停购日期',
  shipment_spec          DECIMAL(14, 4)  DEFAULT NULL COMMENT '出货规格',
  purchase_cycle          INT             DEFAULT NULL COMMENT '采购周期',
  remark                 VARCHAR(512)    DEFAULT NULL COMMENT '备注',
  -- 服饰/属性扩展
  gender                  VARCHAR(32)     DEFAULT NULL COMMENT '性别',
  clothing_type          VARCHAR(32)     DEFAULT NULL COMMENT '上下装',
  style                  VARCHAR(64)     DEFAULT NULL COMMENT '风格',
  division                VARCHAR(64)     DEFAULT NULL COMMENT '事业部',
  color_family            VARCHAR(32)     DEFAULT NULL COMMENT '色系',
  color_depth            VARCHAR(32)     DEFAULT NULL COMMENT '色深',
  standard_code          VARCHAR(32)     DEFAULT NULL COMMENT '标准码',
  original_barcode        VARCHAR(64)     DEFAULT NULL COMMENT '原条码',
  thickness               VARCHAR(32)     DEFAULT NULL COMMENT '厚度',
  length_dim              VARCHAR(32)     DEFAULT NULL COMMENT '长度',
  --
  sync_at                DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_store_sku (store_id, sku_code),
  KEY idx_product_status (product_status),
  KEY idx_barcode (barcode),
  KEY idx_category_code (category_code),
  KEY idx_category_name (category_name),
  KEY idx_brand_name (brand_name),
  KEY idx_product_type (product_type),
  KEY idx_distribution_mode (distribution_mode),
  KEY idx_archive_date (archive_date),
  KEY idx_retail_price (retail_price),
  KEY idx_created_at (created_at),
  KEY idx_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分店商品档案全量-与Excel导出一一对应';
