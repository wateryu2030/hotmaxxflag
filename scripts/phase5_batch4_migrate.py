#!/usr/bin/env python3
"""Phase 5 Batch 4: Extract remaining API routes from app.py into serve_web/ blueprints.

This script handles the tricky part: extracting function bodies correctly,
creating blueprint files, and updating app.py.

Each parent function + its helper functions at the same module scope are kept together.
"""

import re
import os

APP_PATH = '/Users/zhonglian/hotmaxxflag/htma_dashboard/app.py'
SERVE_DIR = '/Users/zhonglian/hotmaxxflag/htma_dashboard/serve_web'

with open(APP_PATH) as f:
    lines = f.readlines()

# ===========================================================
# 1. Parse all top-level @app.route blocks with their boundaries
# ===========================================================

def find_block_boundaries(lines):
    """Find (start_line, end_line) for each top-level @app.route block.
    start_line = the @app.route line
    end_line = line before the next @app.route or top-level construct
    Includes all helper functions at module scope between the route and its def.
    """
    blocks = []  # [(start, end, route, func_name)]
    
    app_route_lines = []
    for i, l in enumerate(lines):
        if re.match(r'^@app\.route\(', l.strip()):
            # Find function name
            for j in range(i+1, min(i+10, len(lines))):
                m = re.search(r'def\s+(\w+)', lines[j])
                if m:
                    route = re.search(r'"([^"]+)"', l)
                    route_path = route.group(1) if route else '?'
                    app_route_lines.append((i, j, route_path, m.group(1)))
                    break
    
    # Now determine block boundaries
    for idx, (app_ln, def_ln, route, func) in enumerate(app_route_lines):
        if idx + 1 < len(app_route_lines):
            next_start = app_route_lines[idx + 1][0]
        else:
            next_start = len(lines)
        
        blocks.append((app_ln, next_start, route, func))
    
    return blocks, app_route_lines


blocks, route_list = find_block_boundaries(lines)

# Print all blocks
print(f"Found {len(blocks)} blocks in app.py")
for start, end, route, func in blocks:
    print(f"  L{start+1:5d}-{end:5d}  {route:45s}  def {func}")

# ===========================================================
# 2. Group blocks by blueprint module
# ===========================================================

groups = {
    'content': {
        'description': '消费洞察',
        'imports': [
            'from flask import Blueprint, jsonify, request',
            'from datetime import date, datetime, timedelta',
            'import pymysql',
            'import pymysql.cursors',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id, _query_filters',
            'from core.utils import safe_float',
            '',
            'content_bp = Blueprint("content", __name__)',
        ],
        'routes': [
            '/api/consumer_insight',
            '/api/consumer_insight_trend',
        ],
    },
    'tax': {
        'description': '税率分析',
        'imports': [
            'from flask import Blueprint, jsonify, request, send_file',
            'from datetime import date, datetime, timedelta',
            'import io, csv, pymysql, pymysql.cursors',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id, _query_filters, _profit_category_cond_and_params',
            'from core.utils import safe_float',
            '',
            'tax_bp = Blueprint("tax", __name__)',
        ],
        'routes': [
            '/api/tax_burden_summary',
            '/api/tax_burden_export',
            '/api/tax_analysis/import_invoice',
            '/api/tax_analysis/invoice_months',
            '/api/tax_analysis/invoice_detail',
            '/api/tax_analysis/compare',
            '/api/tax_analysis/tax_summary',
            '/api/tax_analysis/invoicing_ledger_export',
            '/api/tax_analysis/import_full_invoice',
            '/api/tax_analysis/full_invoice_months',
            '/api/tax_analysis/uninvoiced_goods_analysis',
        ],
    },
    'import_route': {
        'description': '数据导入',
        'imports': [
            'from flask import Blueprint, jsonify, request',
            'from datetime import date, datetime, timedelta',
            'import os, json, pymysql, pymysql.cursors',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id, _query_filters',
            'from core.utils import safe_str, safe_int, safe_float',
            '',
            'import_bp = Blueprint("import", __name__)',
        ],
        'routes': [
            '/api/import',
            '/api/import_from_downloads',
            '/api/import_preview',
        ],
    },
    'profit_share': {
        'description': '利润分成',
        'imports': [
            'from flask import Blueprint, jsonify, request',
            'from datetime import date, datetime, timedelta',
            'from decimal import Decimal',
            'import json, re, pymysql, pymysql.cursors',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id',
            'from core.utils import safe_float',
            '',
            'profit_share_bp = Blueprint("profit_share", __name__)',
        ],
        'routes': [
            '/api/profit_share/rule',
            '/api/profit_share/rule/<int:rule_id>',
            '/api/profit_share/exclude_categories',
            '/api/profit_share/exclude_categories/<int:exclude_id>',
            '/api/profit_share/calculate',
            '/api/profit_share/results',
            '/api/profit_share/result/<int:result_id>',
            '/api/profit_share/category_options',
            '/api/profit_share/preview',
        ],
    },
    'product_master': {
        'description': '商品主档',
        'imports': [
            'from flask import Blueprint, jsonify, request',
            'from datetime import date, datetime, timedelta',
            'import pymysql, pymysql.cursors, json',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id, _query_filters',
            'from core.utils import safe_str, safe_float',
            '',
            'product_bp = Blueprint("product", __name__)',
        ],
        'routes': [
            '/api/import_product_master',
            '/api/product_master_status',
            '/api/product_master_analysis',
            '/api/product_master_category_mid',
            '/api/product_master_category_small',
            '/api/product_master_drill',
            '/api/product_master/drill_large_categories',
            '/api/product_master/drill_mid_categories',
            '/api/product_master/drill_small_categories',
            '/api/product_master/drill_brands',
            '/api/product_master/drill_skus',
            '/api/product_master/brand_large_categories',
            '/api/product_master/brand_mid_categories',
            '/api/product_master/brand_small_categories',
        ],
    },
    'channel': {
        'description': '渠道分析（红牌楼）',
        'imports': [
            'from flask import Blueprint, jsonify, request, send_file',
            'from datetime import date, datetime, timedelta',
            'import io, csv, json, pymysql, pymysql.cursors',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id',
            'from core.utils import safe_str, safe_float',
            '',
            'channel_bp = Blueprint("channel", __name__)',
        ],
        'routes': [
            '/api/channel/hongbeilou/logic',
            '/api/channel/hongbeilou/preview',
            '/api/channel/hongbeilou/export',
            '/api/channel/hongbeilou/export_pdf',
            '/api/channel/hongbeilou/batch',
        ],
    },
    'catalog': {
        'description': '商品目录与销售导出',
        'imports': [
            'from flask import Blueprint, jsonify, request, send_file',
            'from datetime import date, datetime, timedelta',
            'import io, csv, pymysql, pymysql.cursors, math, json',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id, _query_filters',
            'from core.utils import safe_str, safe_float',
            '',
            'catalog_bp = Blueprint("catalog", __name__)',
        ],
        'routes': [
            '/api/categories',
            '/api/products',
            '/api/sale_detail',
            '/api/export',
            '/api/dow_sales',
        ],
    },
    'price_compare': {
        'description': '比价分析',
        'imports': [
            'from flask import Blueprint, jsonify, request',
            'from datetime import date, datetime, timedelta',
            'import pymysql, pymysql.cursors',
            '',
            'from core.db import get_conn',
            'from core.context import _effective_store_id, _query_filters',
            'from core.utils import safe_float, safe_int',
            '',
            'price_bp = Blueprint("price", __name__)',
        ],
        'routes': [
            '/api/price_compare_products',
            '/api/price_compare/capability',
            '/api/price_compare',
            '/api/price_compare_daily',
            '/api/price_compare_results',
        ],
    },
    'sync': {
        'description': '平台同步',
        'imports': [
            'from flask import Blueprint, jsonify, request',
            'from datetime import datetime',
            'import pymysql',
            '',
            'from core.db import get_conn',
            '',
            'sync_bp = Blueprint("sync", __name__)',
        ],
        'routes': [
            '/api/platform_products_sync',
            '/api/sync_products_category',
        ],
    },
}

# Auth + analysis routes are handled specially since they're close to page routes
groups['auth'] = {
    'description': '认证授权',
    'imports': [
        'from flask import Blueprint, jsonify, request, session, redirect, url_for',
        'from datetime import datetime, timedelta',
        'import pymysql, pymysql.cursors',
        '',
        'from core.db import get_conn',
        'from core.utils import safe_str, safe_int',
        'from auth import is_feishu_configured, get_feishu_authorize_url, feishu_exchange_code_and_user, _super_admin_open_id',
        '',
        'auth_bp = Blueprint("auth", __name__)',
    ],
    'routes': [
        '/api/auth/me',
        '/api/auth/feishu_url',
        '/api/auth/feishu_callback',
        '/api/auth/pending_count',
        '/api/auth/approvals',
        '/api/auth/approve',
        '/api/auth/logout',
    ],
}
groups['analysis'] = {
    'description': '归因分析',
    'imports': [
        'from flask import Blueprint, jsonify, request',
        'from datetime import datetime, timedelta',
        'import pymysql, pymysql.cursors, json',
        '',
        'from core.db import get_conn',
        'from core.context import _effective_store_id, _query_filters, period_over_period_ranges',
        'from core.utils import safe_float',
        '',
        'analysis_bp = Blueprint("analysis", __name__)',
    ],
    'routes': [
        '/api/analysis/attribution',
    ],
}

# Also need to extract helper functions that belong to these routes
# e.g. _get_tax_burden_data (line 579), _build_bi_insight (line 333)
# These are between routes, not inside them.

print("\n\n=== Creating blueprint files ===")

for module_name, group in groups.items():
    dest_path = os.path.join(SERVE_DIR, f'{module_name}.py')
    if os.path.exists(dest_path):
        print(f"  SKIP {module_name}.py (already exists)")
        continue
    
    route_set = set(group['routes'])
    
    # Collect all blocks belonging to this module
    module_blocks = []
    module_helpers = []
    
    for start, end, route, func in blocks:
        if route in route_set:
            module_blocks.append((start, end, route, func))
    
    if not module_blocks:
        print(f"  WARN {module_name}: no matching routes found")
        continue
    
    # Find helper functions (module-level functions between these blocks that aren't @app.route decorated)
    # These are functions like _get_tax_burden_data, _build_bi_insight, _get_consumer_insight_data, etc.
    min_start = min(b[0] for b in module_blocks)
    max_end = max(b[1] for b in module_blocks)
    
    helper_functions = []
    for i in range(min_start, max_end):
        s = lines[i].strip()
        # Match module-level def not preceded by @app.route
        if s.startswith('def ') and not s.startswith('def _get_consumer_insight_data'):
            # Check if preceded by @app.route
            if i == 0 or not re.match(r'^@app\.', lines[i-1].strip()):
                # Find end of this helper
                j = i + 1
                while j < max_end and not (lines[j].strip().startswith('def ') and re.match(r'^    ', lines[j]) is None 
                                           and not re.match(r'^@app\.', lines[j-1].strip() if j > 0 else '')):
                    j += 1
                helper_functions.append((i, j, s))
    
    print(f"\n  {module_name}.py ({group['description']}): {len(module_blocks)} routes, {len(helper_functions)} helpers")
    
    # Compile the module content
    bp_lines = []
    
    # Header
    bp_lines.append('# -*- coding: utf-8 -*-')
    bp_lines.append(f'"""serve_web/{module_name}：{group["description"]} API"""')
    bp_lines.append('')
    
    # Imports
    bp_lines.extend(group['imports'])
    bp_lines.append('')
    
    # Helper functions first
    for start, end, sig in sorted(helper_functions, key=lambda x: x[0]):
        if end > len(lines):
            end = len(lines)
        bp_lines.append('')
        for l in lines[start:end]:
            bp_lines.append(l.rstrip())
        bp_lines.append('')
    
    # Route functions
    for start, end, route, func in sorted(module_blocks, key=lambda x: x[0]):
        # Change @app.route to @content_bp.route etc.
        block_text = ''.join(lines[start:end])
        bp_name = f'{module_name}_bp'
        block_text = re.sub(r'@app\.route\(', f'@{bp_name}.route(', block_text)
        bp_lines.append('\n' + block_text.rstrip())
    
    content = '\n'.join(bp_lines) + '\n'
    
    with open(dest_path, 'w') as f:
        f.write(content)
    
    print(f"    Written {len(content.splitlines())} lines")

print("\n=== DONE creating blueprint files ===")
