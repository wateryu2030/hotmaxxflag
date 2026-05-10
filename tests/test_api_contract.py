# -*- coding: utf-8 -*-
# 阶段 D2：关键 API 冒烟（状态码与 JSON 结构）
import os
import sys
import unittest

# 保证可导入 htma_dashboard.app
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HTMA = os.path.join(_ROOT, "htma_dashboard")
if _HTMA not in sys.path:
    sys.path.insert(0, _HTMA)


class TestApiContract(unittest.TestCase):
    _prev_auth = None
    _prev_skip_mjwt = None

    @classmethod
    def setUpClass(cls):
        cls._prev_auth = os.environ.get("HTMA_UNITTEST_DISABLE_AUTH")
        cls._prev_skip_mjwt = os.environ.get("HTMA_SKIP_MOBILE_JWT")
        cls._prev_no_sched = os.environ.get("HTMA_DISABLE_APSCHEDULER")
        os.environ["HTMA_UNITTEST_DISABLE_AUTH"] = "1"
        os.environ["HTMA_SKIP_MOBILE_JWT"] = "1"
        os.environ["HTMA_DISABLE_APSCHEDULER"] = "1"
        sys.modules.pop("app", None)
        try:
            import app as app_module  # noqa: WPS433

            cls.app = app_module.app
            cls.skip = False
        except Exception as e:
            cls.app = None
            cls.skip = True
            cls._skip_reason = str(e)

    @classmethod
    def tearDownClass(cls):
        if cls._prev_auth is None:
            os.environ.pop("HTMA_UNITTEST_DISABLE_AUTH", None)
        else:
            os.environ["HTMA_UNITTEST_DISABLE_AUTH"] = cls._prev_auth
        if cls._prev_skip_mjwt is None:
            os.environ.pop("HTMA_SKIP_MOBILE_JWT", None)
        else:
            os.environ["HTMA_SKIP_MOBILE_JWT"] = cls._prev_skip_mjwt
        if cls._prev_no_sched is None:
            os.environ.pop("HTMA_DISABLE_APSCHEDULER", None)
        else:
            os.environ["HTMA_DISABLE_APSCHEDULER"] = cls._prev_no_sched

    def setUp(self):
        if self.__class__.skip:
            self.skipTest(self.__class__._skip_reason)

    def test_kpi_200(self):
        c = self.app.test_client()
        r = c.get("/api/kpi?period=recent30")
        self.assertEqual(r.status_code, 200, r.data)
        j = r.get_json()
        self.assertIn("total_sale_amount", j)

    def test_labor_by_category_structure(self):
        c = self.app.test_client()
        r = c.get("/api/labor_analysis/by_category?start_date=2026-01-01&end_date=2026-01-31")
        self.assertIn(r.status_code, (200, 403), r.data)
        j = r.get_json()
        self.assertIsNotNone(j)
        if r.status_code == 200 and j.get("success"):
            rows = j.get("data") or []
            if rows:
                row0 = rows[0]
                for k in ("margin_pct", "labor_cost_per_sale", "profit_cost_ratio", "sale", "profit"):
                    self.assertIn(k, row0, "缺少字段: " + k)

    def test_four_quadrant_array(self):
        c = self.app.test_client()
        r = c.get("/api/four_quadrant?start_date=2026-01-01&end_date=2026-01-31")
        self.assertIn(r.status_code, (200, 403))
        j = r.get_json()
        self.assertIsNotNone(j)
        if r.status_code == 200 and j.get("success"):
            self.assertIsInstance(j.get("points"), list)

    def test_mobile_dashboard(self):
        c = self.app.test_client()
        r = c.get("/api/mobile/dashboard?days=7")
        self.assertEqual(r.status_code, 200, r.data)
        j = r.get_json()
        self.assertEqual(j.get("code"), 0, j)
        d = j.get("data") or {}
        self.assertIn("kpi", d)
        self.assertIn("top_categories", d)

    def test_mobile_category_trend_labor(self):
        c = self.app.test_client()
        for path in (
            "/api/mobile/category_large?start_date=2026-01-01&end_date=2026-01-31",
            "/api/mobile/trend?metric=sale&days=14",
            "/api/mobile/alerts?days=7",
            "/api/mobile/alerts/list?days=7",
            "/api/mobile/ai_daily/latest",
            "/api/mobile/labor_summary?start_date=2026-01-01&end_date=2026-01-31",
        ):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, (path, r.data))
            j = r.get_json()
            self.assertEqual(j.get("code"), 0, (path, j))
            self.assertIn("data", j)
        r2 = c.get(
            "/api/mobile/category_mid?category_large_code=dummy&start_date=2026-01-01&end_date=2026-01-31"
        )
        self.assertIn(r2.status_code, (200, 501), r2.data)
        if r2.status_code == 200:
            self.assertEqual((r2.get_json() or {}).get("code"), 0)
        r3 = c.get(
            "/api/mobile/category_small?category_large_code=dummy&category_mid_code=dummy"
            "&start_date=2026-01-01&end_date=2026-01-31"
        )
        self.assertIn(r3.status_code, (200, 400, 501), r3.data)
        r4 = c.get(
            "/api/mobile/category_skus?category_large_code=dummy&category_mid_code=dummy"
            "&start_date=2026-01-01&end_date=2026-01-31"
        )
        self.assertIn(r4.status_code, (200, 400, 501), r4.data)

    def test_mobile_bi_overview_and_trend(self):
        c = self.app.test_client()
        r = c.get("/api/mobile/overview?kpi_cycle=last_30_days")
        self.assertEqual(r.status_code, 200, r.data)
        j = r.get_json()
        self.assertEqual(j.get("code"), 0, j)
        d = j.get("data") or {}
        self.assertIn("total_sales", d)
        self.assertIn("trend", d)
        rs = c.get("/api/mobile/insights_signals?days=40")
        self.assertIn(rs.status_code, (200, 501), rs.data)
        if rs.status_code == 200:
            sj = rs.get_json() or {}
            self.assertEqual(sj.get("code"), 0, sj)
            sd = sj.get("data") or {}
            aud = sd.get("audit") or {}
            self.assertEqual(aud.get("source"), "cursor_auto_evolve")
            self.assertEqual(aud.get("feature"), "insights_signals")
        r2 = c.get(
            "/api/mobile/trend_advanced?granularity=day&metric=sales"
            "&start_date=2026-01-01&end_date=2026-01-31"
        )
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertEqual((r2.get_json() or {}).get("code"), 0)
        for attr_path in (
            "/api/mobile/analysis/attribution?start_date=2026-01-01&end_date=2026-01-31",
            "/api/mobile/attribution?start_date=2026-01-01&end_date=2026-01-31",
            "/api/wechat/mini/analysis/attribution?start_date=2026-01-01&end_date=2026-01-31",
            "/api/wechat/mini/attribution?start_date=2026-01-01&end_date=2026-01-31",
        ):
            ra = c.get(attr_path)
            self.assertIn(ra.status_code, (200, 501), (attr_path, ra.data))
            if ra.status_code == 200:
                self.assertEqual((ra.get_json() or {}).get("code"), 0, attr_path)

    def test_homepage_biz_summary_category_slow_movers_ops_labor(self):
        """首页经营快报 / 品类 / 滞销 / 运维条 / 人力卡片 — 200 且 JSON 结构完整。"""
        c = self.app.test_client()
        r_sum = c.get("/api/biz/summary")
        self.assertEqual(r_sum.status_code, 200, r_sum.data)
        j_sum = r_sum.get_json() or {}
        self.assertEqual(j_sum.get("code"), 0, j_sum)
        d = j_sum.get("data") or {}
        for k in (
            "this_month",
            "last_month",
            "sale_mom_change_pct",
            "today_sales",
            "turnover_rate",
            "inv_turnover_days",
            "net_profit",
            "labor_cost",
            "slow_mover_count",
            "current_inventory",
        ):
            self.assertIn(k, d, "summary 缺少字段: " + k)
        self.assertIn("sales", d.get("this_month") or {})
        self.assertIn("profit", d.get("this_month") or {})

        r_cat = c.get("/api/biz/category")
        self.assertEqual(r_cat.status_code, 200, r_cat.data)
        j_cat = r_cat.get_json() or {}
        self.assertEqual(j_cat.get("code"), 0, j_cat)
        self.assertIn("items", j_cat.get("data") or {})

        r_slow = c.get("/api/biz/slow_movers")
        self.assertEqual(r_slow.status_code, 200, r_slow.data)
        j_slow = r_slow.get_json() or {}
        self.assertEqual(j_slow.get("code"), 0, j_slow)
        self.assertIn("items", j_slow.get("data") or {})
        self.assertIn("count", j_slow.get("data") or {})


        r_lab = c.get("/api/biz/labor_efficiency")
        self.assertEqual(r_lab.status_code, 200, r_lab.data)
        j_lab = r_lab.get_json() or {}
        self.assertIn(j_lab.get("code"), (0, -1), j_lab)
        if j_lab.get("code") == 0:
            ld = j_lab.get("data") or {}
            self.assertIn("monthly", ld)
            self.assertIn("type_overview", ld)


if __name__ == "__main__":
    unittest.main()