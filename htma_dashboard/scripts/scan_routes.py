#!/usr/bin/env python3
"""Scan routes, functions, and write operations across the project."""
import re
import os
import sys

PROJECT = "/Users/zhonglian/hotmaxxflag/htma_dashboard"
WRITE_KEYWORDS = re.compile(r'\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b', re.IGNORECASE)

def get_function_body(lines, start_idx):
    """Get the function body starting from 'def ...' line at start_idx."""
    body_lines = []
    # skip decorators backwards
    fn_start = start_idx
    brace_depth = 0
    in_triple = False
    triple_char = None
    for i in range(start_idx, min(start_idx + 200, len(lines))):
        line = lines[i]
        body_lines.append(line)
        # track triple quotes to avoid false positives
        stripped = line.strip()
        if not in_triple:
            if stripped.startswith('"""') and stripped.count('"""') == 1:
                in_triple = True
                triple_char = '"""'
                continue
            if stripped.startswith("'''") and stripped.count("'''") == 1:
                in_triple = True
                triple_char = "'''"
                continue
        else:
            if triple_char in stripped:
                in_triple = False
                triple_char = None
            continue
        if in_triple:
            continue
        for ch in stripped:
            if ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
        if stripped.startswith('def ') and i > start_idx:
            break
        if stripped.startswith('@app.route') and i > start_idx:
            break
        if stripped.startswith('@app.errorhandler') and i > start_idx:
            break
        if brace_depth < 0:
            break
    return '\n'.join(body_lines)

def scan_app_routes():
    """Scan app.py for all @app.route definitions."""
    path = os.path.join(PROJECT, "app.py")
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    routes = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('@app.route('):
            # Extract route path and methods
            route_match = re.search(r"@app\.route\(['\"]([^'\"]+)['\"]", stripped)
            methods_match = re.search(r"methods=\[(.*?)\]", stripped)
            route_path = route_match.group(1) if route_match else "???"
            methods = "GET"
            if methods_match:
                methods_str = methods_match.group(1)
                methods_list = re.findall(r"'([^']+)'", methods_str)
                methods = ", ".join(methods_list)
            
            # Next non-decorator, non-comment line should be 'def fn_name(...'
            fn_name = "???"
            write_db = "N"
            for j in range(i+1, min(i+10, len(lines))):
                def_match = re.match(r'def (\w+)\(', lines[j])
                if def_match:
                    fn_name = def_match.group(1)
                    # Get function body to check for write operations
                    body = get_function_body(lines, j)
                    if WRITE_KEYWORDS.search(body):
                        write_db = "Y"
                    break
            
            # Determine current category
            category = classify_route(route_path)
            
            routes.append({
                'path': route_path,
                'methods': methods,
                'fn_name': fn_name,
                'write_db': write_db,
                'category': category,
                'line': i + 1
            })
    return routes

def classify_route(path):
    """Classify route into ingest/clean/analyze/serve."""
    if path.startswith('/api/import') or path.startswith('/api/import_'):
        return 'ingest'
    if path.startswith('/api/product_master'):
        return 'clean' if 'sync' in path or 'import' in path else 'serve'
    if path.startswith('/api/tax_analysis/import'):
        return 'ingest'
    if path.startswith('/api/repair_'):
        return 'clean'
    if path.startswith('/api/sync_'):
        return 'ingest'
    if path.startswith('/api/platform_products_sync'):
        return 'ingest'
    if path.startswith('/api/channel/hongbeilou/batch') or path.startswith('/api/channel/hongbeilou/logic'):
        return 'clean'
    if path in ('/', '/login', '/pending', '/approval', '/admin', '/import', '/profit_share', '/tax_analysis', '/hongbeilou', '/attribution', '/undefined'):
        return 'serve'
    if path.startswith('/api/auth/'):
        return 'serve'
    if path.startswith('/api/feishu/'):
        return 'serve'
    if path.startswith('/api/analysis/'):
        return 'analyze'
    if path.startswith('/api/tax_analysis/'):
        return 'analyze'
    if path in ('/api/kpi', '/api/date_range', '/api/data_status', '/api/health'):
        return 'serve'
    if path.startswith('/api/profit_share/'):
        return 'analyze' if 'calculate' in path else 'serve'
    # Default - most /api/* routes serve data
    if path.startswith('/api/'):
        return 'serve'
    return 'serve'

def scan_file_routes(filepath):
    """Scan a file for @app.route or @.*.route decorators (blueprint routes)."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    routes = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if '.route(' in stripped and stripped.startswith('@'):
            route_match = re.search(r"route\(['\"]([^'\"]+)['\"]", stripped)
            methods_match = re.search(r"methods=\[(.*?)\]", stripped)
            route_path = route_match.group(1) if route_match else "???"
            methods = "GET"
            if methods_match:
                methods_str = methods_match.group(1)
                methods_list = re.findall(r"'([^']+)'", methods_str)
                methods = ", ".join(methods_list)
            
            fn_name = "???"
            write_db = "N"
            for j in range(i+1, min(i+10, len(lines))):
                def_match = re.match(r'def (\w+)\(', lines[j])
                if def_match:
                    fn_name = def_match.group(1)
                    body = get_function_body(lines, j)
                    if WRITE_KEYWORDS.search(body):
                        write_db = "Y"
                    break
            
            routes.append({
                'path': route_path,
                'methods': methods,
                'fn_name': fn_name,
                'write_db': write_db,
                'line': i + 1
            })
    return routes

def scan_functions(filepath):
    """Scan a file for all def functions."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    functions = re.findall(r'^def (\w+)\(', content, re.MULTILINE)
    return functions

def find_imports(module_name):
    """Find who imports from a given module."""
    result = []
    for root, dirs, files in os.walk(PROJECT):
        # Exclude __pycache__ and venv
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'venv', '.venv')]
        for fn in files:
            if fn.endswith('.py'):
                fpath = os.path.join(root, fn)
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    for i, line in enumerate(f, 1):
                        # Match: from X import Y (where X matches module_name)
                        if re.search(rf'from\s+.*{re.escape(module_name)}\s+import', line):
                            result.append((fpath, i, line.strip()))
                        elif re.search(rf'import\s+.*{re.escape(module_name)}', line):
                            result.append((fpath, i, line.strip()))
    return result

def main():
    print("=" * 60)
    print("PHASE 0: Route & Function Map Scan")
    print("=" * 60)
    
    # 1. Scan app.py routes
    print("\n--- 1. Scanning app.py routes ---")
    routes = scan_app_routes()
    print(f"Found {len(routes)} routes in app.py")
    
    # Group by prefix
    prefix_groups = {}
    for r in routes:
        path = r['path']
        # Extract prefix
        if path.startswith('/api/channel/'):
            prefix = '/api/channel/'
        elif path.startswith('/api/tax_analysis/'):
            prefix = '/api/tax_analysis/'
        elif path.startswith('/api/profit_share/'):
            prefix = '/api/profit_share/'
        elif path.startswith('/api/product_master/'):
            prefix = '/api/product_master/'
        elif path.startswith('/api/auth/'):
            prefix = '/api/auth/'
        elif path.startswith('/api/price_compare'):
            prefix = '/api/price_compare*'
        elif path.startswith('/api/consumer_insight'):
            prefix = '/api/consumer_insight*'
        elif path.startswith('/api/category_rank'):
            prefix = '/api/category_rank*'
        elif path.startswith('/api/inv_'):
            prefix = '/api/inv_*'
        elif path.startswith('/api/profit_'):
            prefix = '/api/profit_*'
        elif path.startswith('/api/sale_') or path.startswith('/api/sales_'):
            prefix = '/api/sale_*'
        elif path.startswith('/api/kpi'):
            prefix = '/api/kpi*'
        elif path.startswith('/api/import'):
            prefix = '/api/import*'
        elif path.startswith('/api/brand_'):
            prefix = '/api/brand_*'
        elif path.startswith('/api/supplier_'):
            prefix = '/api/supplier_*'
        elif path.startswith('/api/price_band_'):
            prefix = '/api/price_band_*'
        elif path.startswith('/api/'):
            prefix = '/api/other'
        else:
            prefix = path
        prefix_groups.setdefault(prefix, []).append(r)
    
    for prefix, rlist in sorted(prefix_groups.items()):
        write_count = sum(1 for r in rlist if r['write_db'] == 'Y')
        print(f"  {prefix}: {len(rlist)} routes, {write_count} write operations")
    
    # 2. Scan route files
    route_files = [
        'labor_routes.py', 'routes_mobile.py', 'routes_biz_enhanced.py',
        'routes_ops.py', 'routes_sales.py', 'routes_category.py',
        'routes_insights.py', 'wechat_api.py'
    ]
    
    print("\n--- 2. Scanning route files ---")
    all_blueprint_routes = {}
    for fn in route_files:
        fp = os.path.join(PROJECT, fn)
        r = scan_file_routes(fp)
        all_blueprint_routes[fn] = r
        write_count = sum(1 for x in r if x['write_db'] == 'Y')
        print(f"  {fn}: {len(r)} routes, {write_count} write ops")
    
    # 3. Scan function exports
    scan_files = [
        'import_logic.py', 'analytics.py', 'labor_routes.py', 'routes_mobile.py',
        'routes_biz_enhanced.py', 'routes_ops.py', 'routes_sales.py',
        'routes_category.py', 'routes_insights.py', 'wechat_api.py',
        'auth.py', 'mobile_bi.py'
    ]
    
    print("\n--- 3. Scanning exported functions ---")
    all_funcs = {}
    for fn in scan_files:
        fp = os.path.join(PROJECT, fn)
        funcs = scan_functions(fp)
        all_funcs[fn] = funcs
        # Find imports
        module_name = fn.replace('.py', '')
        imports = find_imports(module_name)
        print(f"  {fn}: {len(funcs)} functions, imported by {len(imports)} locations")
        for imp in imports[:5]:
            print(f"    -> {os.path.basename(imp[0])}:{imp[1]} {imp[2]}")
        if len(imports) > 5:
            print(f"    ... and {len(imports)-5} more")
    
    # 4. Scan scripts for MySQL write operations
    print("\n--- 4. Scanning scripts/*.py and scripts/*.sql ---")
    scripts_dir = os.path.join(PROJECT, 'scripts')
    if os.path.exists(scripts_dir):
        for fn in os.listdir(scripts_dir):
            if fn.endswith('.py') or fn.endswith('.sql'):
                fp = os.path.join(scripts_dir, fn)
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                writes = WRITE_KEYWORDS.findall(content)
                if writes:
                    print(f"  {fn}: WRITE operations found: {set(writes)}")
                else:
                    print(f"  {fn}: no write operations")
    else:
        print("  (no scripts directory with .py/.sql files)")
    
    # 5. Stats
    print("\n--- 5. Statistics ---")
    total_routes = len(routes) + sum(len(v) for v in all_blueprint_routes.values())
    app_write_routes = sum(1 for r in routes if r['write_db'] == 'Y')
    bp_write_routes = sum(1 for v in all_blueprint_routes.values() for r in v if r['write_db'] == 'Y')
    print(f"  Total routes (app.py): {len(routes)}")
    print(f"  Total routes (blueprints): {sum(len(v) for v in all_blueprint_routes.values())}")
    print(f"  Total routes (all): {total_routes}")
    print(f"  Write-route count (app.py): {app_write_routes}")
    print(f"  Write-route count (blueprints): {bp_write_routes}")
    print(f"  Total write routes: {app_write_routes + bp_write_routes}")
    
    # 6. Most dangerous coupling points
    print("\n--- 6. Top 5 most dangerous coupling points ---")
    
    # Print all routes with write operations for analysis
    print("\nAll app.py routes (detailed):")
    print(f"{'Line':>5} | {'Method':<15} | {'Path':<50} | {'Function':<35} | {'WriteDB':<7} | {'Category':<10}")
    print("-" * 130)
    for r in sorted(routes, key=lambda x: x['line']):
        print(f"{r['line']:>5} | {r['methods']:<15} | {r['path']:<50} | {r['fn_name']:<35} | {r['write_db']:<7} | {r['category']:<10}")
    
    print("\nAll blueprint routes:")
    for fn, rlist in sorted(all_blueprint_routes.items()):
        if rlist:
            print(f"\n--- {fn} ---")
            for r in rlist:
                print(f"  {r['path']:<50} {r['methods']:<15} {r['fn_name']:<35} WriteDB={r['write_db']}")
    
    print("\n\n--- Function Export Summary ---")
    for fn in scan_files:
        funcs = all_funcs.get(fn, [])
        writes_in_funcs = 0
        fp = os.path.join(PROJECT, fn)
        if os.path.exists(fp):
            with open(fp, 'r', encoding='utf-8') as f:
                content = f.read()
            for func_name in funcs:
                # Find function body
                pattern = rf'def {re.escape(func_name)}\('
                match = re.search(pattern, content)
                if match:
                    start = content.index(match.group())
                    end = start + 10000  # read enough
                    block = content[start:end]
                    # find matching } or next def
                    lines_sub = block.split('\n')
                    body = '\n'.join(lines_sub[:200])
                    if WRITE_KEYWORDS.search(body):
                        writes_in_funcs += 1
        print(f"  {fn}: {len(funcs)} functions total, {writes_in_funcs} with write ops")

if __name__ == '__main__':
    main()
