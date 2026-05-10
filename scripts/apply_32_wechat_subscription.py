#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用项目 .env 中的 MYSQL_* 连接数据库并执行
scripts/32_wechat_subscription_and_indexes.sql 中内容；
对 daily_category_stats 的索引做幂等检查后再创建。

用法（在项目根目录）:
  .venv/bin/python3 scripts/apply_32_wechat_subscription.py
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTM = os.path.join(_ROOT, "htma_dashboard")
if _HTM not in sys.path:
    sys.path.insert(0, _HTM)

from db_config import DB_CONFIG, get_conn  # noqa: E402


def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(
        """
        SELECT 1 AS o FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s
        LIMIT 1
        """,
        (table, index_name),
    )
    return bool(cur.fetchone())


def _table_exists(cur, name: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s LIMIT 1
        """,
        (name,),
    )
    return bool(cur.fetchone())


def main() -> int:
    print("数据库:", DB_CONFIG.get("host"), DB_CONFIG.get("database"))
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("USE `%s`" % DB_CONFIG["database"].replace("`", ""))

        # 订阅表（与 32_*.sql 一致）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS t_htma_wechat_subscription (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              user_id BIGINT UNSIGNED NOT NULL COMMENT 't_htma_wechat_user.id',
              template_id VARCHAR(64) NOT NULL COMMENT '订阅消息模板 ID',
              openid VARCHAR(64) NOT NULL,
              is_active TINYINT(1) NOT NULL DEFAULT 1,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uk_user_tpl (user_id, template_id),
              KEY idx_openid_active (openid, is_active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='小程序订阅消息'
            """
        )
        print("OK: t_htma_wechat_subscription（已存在则跳过）")

        if _table_exists(cur, "daily_category_stats"):
            specs = [
                ("idx_store_date", "(store_id, data_date)"),
                ("idx_large_date", "(category_large_code, data_date)"),
                ("idx_dcs_data_date", "(data_date)"),
            ]
            for iname, cols in specs:
                if _index_exists(cur, "daily_category_stats", iname):
                    print("skip index:", iname, "(已存在)")
                else:
                    try:
                        cur.execute(
                            "ALTER TABLE daily_category_stats ADD INDEX %s %s" % (iname, cols)
                        )
                        print("OK: ADD INDEX", iname, cols)
                    except Exception as e:
                        print("WARN:", iname, e)
        else:
            print("skip: 无表 daily_category_stats，不建索引")
        conn.commit()
        print("完成。")
        return 0
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print("错误:", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
