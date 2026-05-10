# -*- coding: utf-8 -*-
"""
静态守卫：routes_biz_enhanced 中凡触及 t_htma_sale / t_htma_stock 的 SQL
必须显式带 store_id 条件，防止首页口径再次退化为全库聚合。
"""
import os
import re
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_BIZ = os.path.join(_ROOT, "htma_dashboard", "routes_biz_enhanced.py")


def _extract_execute_sql_literals(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    blocks: list[str] = []
    for m in re.finditer(r'cur\.execute\s*\(\s*"""(.*?)"""', content, re.DOTALL):
        blocks.append(m.group(1))
    for m in re.finditer(r"cur\.execute\s*\(\s*'''(.*?)'''", content, re.DOTALL):
        blocks.append(m.group(1))
    # 单行 cur.execute(" ... ", (sid,))
    for m in re.finditer(
        r'cur\.execute\s*\(\s*"((?:[^"\\]|\\.)*)"\s*,',
        content,
        re.DOTALL,
    ):
        blocks.append(m.group(1).replace("\\\n", "\n"))
    return blocks


class TestBizEnhancedStoreIdGuard(unittest.TestCase):
    def test_sale_and_stock_sql_blocks_include_store_id(self):
        if not os.path.isfile(_BIZ):
            self.skipTest("missing routes_biz_enhanced.py")
        for sql in _extract_execute_sql_literals(_BIZ):
            low = sql.lower()
            if "t_htma_sale" not in low and "t_htma_stock" not in low:
                continue
            self.assertIn(
                "store_id",
                low,
                "SQL 含销售/库存表但缺少 store_id 过滤:\n" + sql[:400],
            )


if __name__ == "__main__":
    unittest.main()
