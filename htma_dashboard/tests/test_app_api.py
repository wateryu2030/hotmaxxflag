# -*- coding: utf-8 -*-
"""API tests for /api/date_range, /api/kpi, /api/category_pie, /api/sales_trend (mocked DB)."""
import os
import sys
from unittest.mock import MagicMock, patch

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pytest


@pytest.fixture
def app_client():
    """Flask test client with get_conn mocked to avoid real DB."""
    with patch("htma_dashboard.app.get_conn") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn

        # date_range: one query MIN/MAX data_date
        mock_cursor.fetchone.side_effect = [
            {"min_d": __import__("datetime").date(2024, 1, 1), "max_d": __import__("datetime").date(2025, 12, 31)},
        ]

        from htma_dashboard.app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


def test_api_date_range(app_client):
    """GET /api/date_range returns JSON with min/max dates."""
    r = app_client.get("/api/date_range")
    assert r.status_code == 200
    data = r.get_json()
    assert "min_date" in data and "max_date" in data
    assert data.get("data_min_date") is not None or "data_max_date" in data


def test_api_kpi(app_client):
    """GET /api/kpi returns 200 and KPI keys (with mocked DB)."""
    with patch("htma_dashboard.app.get_conn") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn
        mock_cursor.fetchone.side_effect = [
            {"total_sale_amount": 1000.0, "total_gross_profit": 200.0},
            {"total_stock_amount": 5000.0},
        ]
        from htma_dashboard.app import app
        app.config["TESTING"] = True
        app.config["FEISHU_APP_ID"] = ""
        app.config["FEISHU_APP_SECRET"] = ""
        with app.test_client() as c:
            r = c.get("/api/kpi?period=recent30")
    assert r.status_code == 200
    data = r.get_json()
    assert "total_sale_amount" in data and "total_gross_profit" in data
    assert "avg_profit_rate_pct" in data and "total_stock_amount" in data


def test_api_category_pie(app_client):
    """GET /api/category_pie returns 200 and list (mocked)."""
    with patch("htma_dashboard.app.get_conn") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn
        mock_cursor.fetchall.return_value = [
            {"category": "A", "sale_amount": 100.0},
            {"category": "B", "sale_amount": 50.0},
        ]
        from htma_dashboard.app import app
        app.config["TESTING"] = True
        app.config["FEISHU_APP_ID"] = ""
        app.config["FEISHU_APP_SECRET"] = ""
        with app.test_client() as c:
            r = c.get("/api/category_pie?period=recent30")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    if data:
        assert "category" in data[0] and "sale_amount" in data[0]


def test_api_sales_trend(app_client):
    """GET /api/sales_trend returns 200 and object with data list (mocked)."""
    with patch("htma_dashboard.app.get_conn") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_conn.return_value = mock_conn
        mock_cursor.fetchall.return_value = []
        from htma_dashboard.app import app
        app.config["TESTING"] = True
        app.config["FEISHU_APP_ID"] = ""
        app.config["FEISHU_APP_SECRET"] = ""
        with app.test_client() as c:
            r = c.get("/api/sales_trend?granularity=day&period=recent30")
    assert r.status_code == 200
    data = r.get_json()
    assert "data" in data and isinstance(data["data"], list)
