#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从下载目录（或指定目录）导入分店商品档案 Excel 到 t_htma_product_master。
供 OpenClaw 或终端执行：先手工建表（mysql < scripts/19_create_product_master_table.sql），再运行本脚本导入。
用法（项目根目录）:
  python scripts/openclaw_product_master_import_from_downloads.py
  python scripts/openclaw_product_master_import_from_downloads.py --dir ~/Downloads
  python scripts/openclaw_product_master_import_from_downloads.py -f /path/to/分店商品档案_20260306-_101750.xlsx
"""
import os
import sys
import glob
import argparse

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)
os.chdir(_root)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass


def _downloads_dir():
    d = os.environ.get("IMPORT_DOWNLOADS_DIR") or os.environ.get("DOWNLOADS") or os.path.expanduser("~/Downloads")
    if not os.path.isdir(d) and os.path.isdir("/Users/apple/Downloads"):
        d = "/Users/apple/Downloads"
    return d


def _find_product_master_excel(directory):
    """在目录下查找 分店商品档案_*.xlsx / *.xls，按修改时间取最新。"""
    patterns = ["分店商品档案_*.xlsx", "分店商品档案_*.xls"]
    found = []
    for p in patterns:
        for path in glob.glob(os.path.join(directory, p)):
            if os.path.isfile(path) and not os.path.basename(path).startswith("."):
                found.append(path)
    if not found:
        return None
    return max(found, key=lambda x: os.path.getmtime(x))


def main():
    ap = argparse.ArgumentParser(description="从下载目录或指定文件导入分店商品档案")
    ap.add_argument("--dir", "-d", default=None, help="扫描目录，默认 IMPORT_DOWNLOADS_DIR 或 ~/Downloads")
    ap.add_argument("-f", "--file", action="append", dest="files", default=[], help="指定 Excel 文件，可多次")
    args = ap.parse_args()
    directory = args.dir or _downloads_dir()
    if not os.path.isdir(directory) and not args.files:
        print("目录不存在且未指定 -f 文件: %s" % directory, flush=True)
        sys.exit(1)

    from htma_dashboard.db_config import get_conn
    from htma_dashboard.import_logic import import_product_master

    files_to_import = list(args.files) if args.files else []
    if not files_to_import and os.path.isdir(directory):
        one = _find_product_master_excel(directory)
        if one:
            files_to_import = [one]

    if not files_to_import:
        print("未找到分店商品档案 Excel（分店商品档案_*.xlsx）。请将文件放入 %s 或使用 -f 指定。" % directory, flush=True)
        sys.exit(0)

    print("=== 分店商品档案导入 ===", flush=True)
    print("文件: %s" % [os.path.basename(p) for p in files_to_import], flush=True)
    conn = get_conn()
    try:
        total = 0
        for path in files_to_import:
            if not os.path.isfile(path):
                print("  跳过（不存在）: %s" % path, flush=True)
                continue
            cnt, msg = import_product_master(path, conn)
            total += cnt
            print("  %s: %s" % (os.path.basename(path), msg), flush=True)
        print("合计导入: %d 条" % total, flush=True)
    finally:
        conn.close()
    print("完成。请打开 /product_master 查看分析。", flush=True)


if __name__ == "__main__":
    main()
