# -*- coding: utf-8 -*-
"""Unit tests for query_layer (date_condition, no Flask/DB)."""
import os
import sys

# 确保能导入 htma_dashboard 包（从项目根或 htma_dashboard 目录运行 pytest）
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pytest
from htma_dashboard.query_layer import date_condition, DEFAULT_DAYS


class TestDateCondition:
    """date_condition(period, start_date, end_date) -> (date_cond, params)."""

    def test_custom_range(self):
        cond, params = date_condition("custom", "2025-01-01", "2025-01-31")
        assert "BETWEEN" in cond and "%s" in cond
        assert len(params) == 2
        assert str(params[0]) == "2025-01-01"
        assert str(params[1]) == "2025-01-31"

    def test_custom_range_swapped(self):
        cond, params = date_condition("custom", "2025-01-31", "2025-01-01")
        assert len(params) == 2
        assert params[0] <= params[1]

    def test_period_day(self):
        cond, params = date_condition("day", None, None)
        assert "data_date" in cond and "CURDATE()" in cond
        assert params == ()

    def test_period_week(self):
        cond, params = date_condition("week", None, None)
        assert "BETWEEN" in cond or "CURDATE()" in cond
        assert params == () or len(params) == 1

    def test_period_month(self):
        cond, params = date_condition("month", None, None)
        assert "DATE_FORMAT" in cond or "data_date" in cond
        assert params == ()

    def test_period_recent30(self):
        cond, params = date_condition("recent30", None, None)
        assert "BETWEEN" in cond and "INTERVAL" in cond
        assert len(params) == 1
        assert params[0] == DEFAULT_DAYS or isinstance(params[0], int)

    def test_custom_no_dates_falls_back(self):
        """period=custom but no start/end uses default days."""
        cond, params = date_condition("custom", None, None)
        assert "INTERVAL" in cond
        assert len(params) == 1
