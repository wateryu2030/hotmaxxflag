#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速查看人力成本 Excel 各 sheet 的表头与数据行数，便于对齐导入逻辑与汇总表。
用法: .venv/bin/python scripts/inspect_labor_excel.py /path/to/1月薪资.xlsx [/path/to/12月.xlsx]
      （若系统无 python 命令，请用 .venv/bin/python 或 python3）
"""
import sys
import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)

import pandas as pd


def main():
    paths = [p for p in sys.argv[1:] if os.path.isfile(p)]
    if not paths:
        print("用法: .venv/bin/python scripts/inspect_labor_excel.py <Excel路径> [Excel路径2 ...]")
        sys.exit(1)
    for excel_path in paths:
        print("\n=== %s ===" % excel_path)
        try:
            xl = pd.ExcelFile(excel_path)
        except Exception as e:
            print("  打开失败:", e)
            continue
        for sheet_name in xl.sheet_names:
            skip = "合计" in (sheet_name or "") and ("发票" in (sheet_name or "") or "对应" in (sheet_name or ""))
            try:
                df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
                n_rows = len(df)
                # 找表头行：第一行含「姓名」「岗位」「开票」「费用」等
                header_row = None
                for r in range(min(8, n_rows)):
                    row = df.iloc[r]
                    s = " ".join(str(x) for x in row.dropna().astype(str))
                    if "姓名" in s or "岗位" in s or "开票" in s or "费用" in s or "用工类型" in s:
                        header_row = r
                        break
                if header_row is not None and header_row + 1 <= n_rows:
                    df_h = pd.read_excel(excel_path, sheet_name=sheet_name, header=header_row)
                    df_h = df_h.dropna(how="all", axis=0).dropna(how="all", axis=1)
                    cols = list(df_h.columns[:12])  # 前12列
                    data_rows = max(0, n_rows - header_row - 1)
                    print("  [%s] 表头行=%d 数据行≈%d 列(前12): %s" % (
                        sheet_name, header_row, data_rows, cols[:8]))
                else:
                    print("  [%s] 行数=%d (未识别表头)" % (sheet_name, n_rows))
                if skip:
                    print("      ^ 汇总表 sheet，导入时已跳过")
            except Exception as e:
                print("  [%s] 读取异常: %s" % (sheet_name, e))
    print()


if __name__ == "__main__":
    main()
