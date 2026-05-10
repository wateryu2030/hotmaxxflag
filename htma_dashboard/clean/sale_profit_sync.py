# -*- coding: utf-8 -*-
"""从销售/利润表清洗并同步品类、商品、分类汇总等业务表 — clean 层"""
import pymysql

STORE_ID = "沈阳超级仓"

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


