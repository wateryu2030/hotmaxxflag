# -*- coding: utf-8 -*-
"""analytics_utils：Z-Score、7 日均线动量、大类洞察纯函数单测。"""
import os
import sys
import unittest
from datetime import date, timedelta

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTMA = os.path.join(_ROOT, "htma_dashboard")
if _HTMA not in sys.path:
    sys.path.insert(0, _HTMA)

from analytics_utils import (  # noqa: E402
    compute_large_category_insights,
    total_sales_ma7_slope_pct,
    zscore_last_vs_history,
)


class TestAnalyticsInsights(unittest.TestCase):
    def test_zscore_last_vs_history(self):
        # 历史有离散度，最后一项明显高于历史均值
        hist = [8.0, 10.0, 12.0, 9.0, 11.0]
        z = zscore_last_vs_history(hist + [20.0])
        self.assertIsNotNone(z)
        self.assertGreater(z, 1.5)

    def test_zscore_short_series(self):
        self.assertIsNone(zscore_last_vs_history([1.0]))
        self.assertIsNone(zscore_last_vs_history([]))

    def test_total_sales_ma7_slope_pct(self):
        base = [1000.0] * 14
        up = base + [2000.0] * 7
        slope = total_sales_ma7_slope_pct(up)
        self.assertIsNotNone(slope)
        self.assertGreater(slope, 0.0)
        short = [100.0] * 10
        self.assertIsNone(total_sales_ma7_slope_pct(short))

    def test_compute_large_category_insights_margin_z(self):
        """单大类：前期高毛利，最后一天低毛利 + 足够销额 → 负 Z 进入 low 列表。"""
        d0 = date(2026, 1, 1)
        rows = []
        code = "L01"
        name = "测试大类"
        for i in range(20):
            ds = d0 + timedelta(days=i)
            if i < 19:
                # 略波动的毛利，避免历史标准差为 0
                jitter = (i % 5) * 20.0
                sa, gp = 2000.0, 560.0 + jitter
            else:
                sa, gp = 2000.0, 120.0
            rows.append(
                {
                    "data_date": ds,
                    "category_large_code": code,
                    "category_large": name,
                    "sa": sa,
                    "gp": gp,
                }
            )
        out = compute_large_category_insights(
            rows, z_threshold=1.5, min_hist_days=5, min_last_sales=500
        )
        lows = out.get("margin_zscore_low") or []
        self.assertTrue(len(lows) >= 1)
        self.assertEqual(lows[0].get("category_large_code"), code)
        self.assertLess(lows[0].get("zscore_margin", 0), 0)
        self.assertIsNotNone(out.get("sales_ma7_slope_pct"))


if __name__ == "__main__":
    unittest.main()
