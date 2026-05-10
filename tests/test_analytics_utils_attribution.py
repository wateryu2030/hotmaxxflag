# -*- coding: utf-8 -*-
import os
import sys
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(_ROOT, "htma_dashboard") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "htma_dashboard"))

from analytics_utils import merge_category_large_sales_mom_attribution


class TestAttributionMerge(unittest.TestCase):
    def test_merge_basic(self):
        prev = [
            {"category_large_code": "A", "category_large": "食品", "sa": 100},
            {"category_large_code": "B", "category_large": "百货", "sa": 50},
        ]
        cur = [
            {"category_large_code": "A", "category_large": "食品", "sa": 80},
            {"category_large_code": "B", "category_large": "百货", "sa": 70},
        ]
        out = merge_category_large_sales_mom_attribution(prev, cur)
        self.assertEqual(out["prev_total"], 150.0)
        self.assertEqual(out["cur_total"], 150.0)
        self.assertEqual(out["delta_total"], 0.0)
        self.assertTrue(len(out["by_category"]) >= 2)


if __name__ == "__main__":
    unittest.main()
