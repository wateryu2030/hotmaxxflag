#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 自动化：分析人力成本 Excel 表格构成（斗米兼职、中锐小时工、快聘小时工、保洁等），
输出每 sheet 表头、列名、数据行数（排除总计行）、样本，便于清洗与导入逻辑对齐。
用法: .venv/bin/python scripts/openclaw_labor_analyze_excel.py /path/to/12月薪资.xlsx
"""
import os
import sys
import re

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)

import pandas as pd


def _normalize_header(h):
    if h is None or (isinstance(h, float) and pd.isna(h)):
        return ""
    s = str(h).replace("\n", " ").replace("\r", " ").strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_total_row(row, name_col_idx, pos_col_idx, cols):
    """判断是否为总计/合计行：姓名或属性列为合计/总计，或整行主要为汇总数。"""
    if name_col_idx is not None and name_col_idx < len(row):
        v = str(row.iloc[name_col_idx]).strip()
        if v and ("合计" in v or "总计" in v or "小计" in v):
            return True
    if pos_col_idx is not None and pos_col_idx < len(row):
        v = str(row.iloc[pos_col_idx]).strip()
        if v and ("合计" in v or "总计" in v):
            return True
    return False


def main():
    paths = [p for p in sys.argv[1:] if os.path.isfile(p)]
    if not paths:
        print("用法: .venv/bin/python scripts/openclaw_labor_analyze_excel.py <Excel路径> [Excel路径2 ...]")
        sys.exit(1)

    # 需纳入「其他人力」的 sheet：斗米兼职、中锐小时工、快聘小时工、保洁
    TARGET_SHEETS = ("斗米兼职", "中锐小时工", "快聘小时工", "保洁")
    for excel_path in paths:
        print("\n" + "=" * 60)
        print("文件:", excel_path)
        print("=" * 60)
        try:
            xl = pd.ExcelFile(excel_path)
        except Exception as e:
            print("  打开失败:", e)
            continue
        for sheet_name in xl.sheet_names:
            if not any(t in (sheet_name or "") for t in TARGET_SHEETS):
                continue
            try:
                df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
                n_rows = len(df)
                if n_rows == 0:
                    print("\n[%s] 无数据" % sheet_name)
                    continue
                # 找表头行
                header_row = 0
                for r in range(min(12, n_rows)):
                    row = df.iloc[r]
                    s = " ".join(str(row.iloc[c]) for c in range(min(len(row), 20)))
                    if "姓名" in s or "中文姓名" in s or "属性" in s or "费用合计" in s or "总工时" in s:
                        header_row = r
                        break
                df_h = pd.read_excel(excel_path, sheet_name=sheet_name, header=header_row)
                df_h = df_h.dropna(how="all", axis=0).dropna(how="all", axis=1)
                cols = list(df_h.columns)
                col_norms = [_normalize_header(c) for c in cols]
                name_col = next((i for i, n in enumerate(col_norms) if "姓名" in n or "中文姓名" in n), None)
                pos_col = next((i for i, n in enumerate(col_norms) if "属性" in n or "岗位" in n), None)
                cost_col = next((i for i, n in enumerate(col_norms) if "费用合计" in n or "总成本" in n or "开票" in n), None)
                # 统计数据行（排除总计）
                data_count = 0
                total_rows = 0
                for i in range(len(df_h)):
                    row = df_h.iloc[i]
                    if _is_total_row(row, name_col, pos_col, cols):
                        total_rows += 1
                        continue
                    # 有成本或姓名的算数据行
                    cost_val = row.iloc[cost_col] if cost_col is not None and cost_col < len(row) else None
                    name_val = row.iloc[name_col] if name_col is not None and name_col < len(row) else None
                    try:
                        cv = float(cost_val) if cost_val is not None and str(cost_val).strip() else 0
                    except Exception:
                        cv = 0
                    if cv > 0 or (name_val and str(name_val).strip() and "合计" not in str(name_val)):
                        data_count += 1
                print("\n[%s]" % sheet_name)
                print("  表头行: %d | 列数: %d | 数据行(估): %d | 合计行(估): %d" % (header_row, len(cols), data_count, total_rows))
                print("  列名: %s" % (cols[:16] if len(cols) > 16 else cols))
                print("  姓名列索引: %s | 属性/岗位列: %s | 费用列: %s" % (name_col, pos_col, cost_col))
                if len(df_h) > 0 and (name_col is not None or pos_col is not None):
                    sample = df_h.iloc[0]
                    print("  首行样本 - 姓名: %s | 属性: %s | 费用: %s" % (
                        sample.iloc[name_col] if name_col is not None else "-",
                        sample.iloc[pos_col] if pos_col is not None else "-",
                        sample.iloc[cost_col] if cost_col is not None else "-",
                    ))
            except Exception as e:
                print("\n[%s] 异常: %s" % (sheet_name, e))
        print("")
    print("分析完成。可根据上述列名与数据行数核对导入逻辑（import_logic 中兼职/小时工/保洁）。")


if __name__ == "__main__":
    main()
