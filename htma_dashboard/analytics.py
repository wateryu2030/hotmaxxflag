#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零售业数据分析模型 — Phase 4: 门面模块，所有实现已迁至 analyze/
保持 from analytics import ... 行为不变
"""
from datetime import datetime

try:
    from query_layer import date_condition as _date_condition
except Exception:
    _date_condition = None

# ── Phase 4：实现已迁至 analyze/ ──
from analyze.margin import get_unified_margin
from analyze.insights import (
    build_insights, build_enhanced_insights,
    _get_price_compare_insights, _row,
)
# report 与 ai_chat 中所用的 _fmt_money 等工具函数统一从此导入
from analyze.report import (
    build_structured_report, build_marketing_report, category_rank_data,
    _fmt_money, _excluded_cond_sale, _excluded_cond_stock, _neg_diagnosis_hint,
)
from analyze.ai_chat import (
    _ai_fetch_context, _format_drill_prefix, _with_drill,
    ai_chat_response, advanced_search_consumer_insight,
)
