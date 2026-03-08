#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从下载目录自动导入人力成本 Excel，可选先重建表、清空数据。供 OpenClaw 或终端一键执行。
用法（项目根目录，请用 .venv/bin/python 或 python3）:
  .venv/bin/python scripts/openclaw_labor_import_from_downloads.py 2026-01
  .venv/bin/python scripts/openclaw_labor_import_from_downloads.py --clear -f "~/Downloads/1月薪资.xlsx" -f "~/Downloads/12月薪资表-沈阳金融中心(1).xlsx" 2026-01 2025-12
  .venv/bin/python scripts/openclaw_labor_import_from_downloads.py --rebuild --clear 2026-01 2025-12 --dir ~/Downloads
  或一键: bash scripts/openclaw_labor_rebuild_and_import.sh 2026-01 2025-12
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


def _find_labor_excel(directory):
    """在目录下查找疑似人力/薪资 Excel（薪资、人力、12月、1月等），按修改时间取最新。"""
    patterns = [
        "*薪资*.xlsx", "*人力*.xlsx", "12月*.xlsx", "1月*.xlsx",
        "*工资*.xlsx", "*labor*.xlsx",
    ]
    seen = set()
    for p in patterns:
        for path in glob.glob(os.path.join(directory, p)):
            if path in seen or path.startswith("~"):
                continue
            if os.path.isfile(path) and not os.path.basename(path).startswith("."):
                seen.add(path)
    if not seen:
        return None
    return max(seen, key=lambda x: os.path.getmtime(x))


def _find_file_for_month(directory, month_num):
    """按月份数字在目录中找对应 Excel，如 1 -> *1月*.xlsx, 12 -> *12月*.xlsx。返回最新匹配的一个。"""
    pattern = os.path.join(directory, "*%d月*.xlsx" % month_num)
    found = [p for p in glob.glob(pattern) if os.path.isfile(p) and not os.path.basename(p).startswith(".")]
    if not found:
        for p in glob.glob(os.path.join(directory, "*%d月*.xls" % month_num)):
            if os.path.isfile(p) and not os.path.basename(p).startswith("."):
                found.append(p)
    return max(found, key=lambda x: os.path.getmtime(x)) if found else None


def _parse_expected_from_excel(excel_path):
    """从 Excel 的「合计」sheet 解析期望：总成本(开票金额/总成本)、正式人数、其他人数。用于零容差校验。"""
    import pandas as pd
    out = {"total": None, "formal": None, "other": None}
    try:
        xl = pd.ExcelFile(excel_path)
    except Exception:
        return out
    # 找名称含「合计」的 sheet（如 合计(跟发票对应)）
    sum_sheet = None
    for name in xl.sheet_names:
        if "合计" in (name or ""):
            sum_sheet = name
            break
    if not sum_sheet:
        return out
    try:
        df = pd.read_excel(excel_path, sheet_name=sum_sheet, header=None)
    except Exception:
        return out
    # 遍历所有单元格，根据关键词取相邻数字
    def _num(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _int_from_float(v):
        n = _num(v)
        if n is None:
            return None
        try:
            return int(round(n))
        except (ValueError, TypeError):
            return None

    for r in range(df.shape[0]):
        for c in range(df.shape[1]):
            cell = df.iloc[r, c]
            if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                continue
            s = str(cell).strip()
            # 总成本：单元格含 开票/总成本/发薪金额 等，取本格或右侧/下侧数字
            if out["total"] is None and ("开票" in s or "总成本" in s or ("发薪" in s and "对应" not in s)):
                for dc, dr in [(1, 0), (0, 1), (2, 0)]:
                    nc, nr = c + dc, r + dr
                    if nr < df.shape[0] and nc < df.shape[1]:
                        v = _num(df.iloc[nr, nc])
                        if v is not None and v > 1000:
                            out["total"] = round(v, 2)
                            break
                if out["total"] is None and _num(cell) is not None and _num(cell) > 1000:
                    out["total"] = round(_num(cell), 2)
            # 正式人数
            if out["formal"] is None and "正式" in s:
                for dc, dr in [(1, 0), (0, 1)]:
                    nc, nr = c + dc, r + dr
                    if nr < df.shape[0] and nc < df.shape[1]:
                        v = _int_from_float(df.iloc[nr, nc])
                        if v is not None and 0 <= v <= 500:
                            out["formal"] = v
                            break
            # 其他人数
            if out["other"] is None and "其他" in s:
                for dc, dr in [(1, 0), (0, 1)]:
                    nc, nr = c + dc, r + dr
                    if nr < df.shape[0] and nc < df.shape[1]:
                        v = _int_from_float(df.iloc[nr, nc])
                        if v is not None and 0 <= v <= 2000:
                            out["other"] = v
                            break
    return out


def main():
    ap = argparse.ArgumentParser(description="从下载目录导入人力成本 Excel，可选重建表/清空")
    ap.add_argument("report_months", nargs="*", help="报表月份，如 2026-01 2025-12")
    ap.add_argument("--rebuild", action="store_true", help="重建 t_htma_labor_cost 表结构后再导入")
    ap.add_argument("--clear", action="store_true", help="导入前清空人力成本明细与汇总表")
    ap.add_argument("--dir", "-d", default=None, help="下载目录，默认 IMPORT_DOWNLOADS_DIR 或 ~/Downloads")
    ap.add_argument("--file", "-f", action="append", dest="files", help="指定 Excel 路径，可多次使用以按月份一一对应；不指定则从 --dir 中查找一个")
    ap.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    args = ap.parse_args()

    download_dir = args.dir or _downloads_dir()
    if not os.path.isdir(download_dir):
        print("下载目录不存在:", download_dir)
        sys.exit(1)

    report_months = [m.strip() for m in args.report_months if m.strip()]
    if not report_months:
        report_months = ["2026-01"]
        print("未指定报表月份，默认 2026-01")
    else:
        print("报表月份:", ", ".join(report_months))

    files = (args.files or []) if hasattr(args, "files") and args.files else []
    if not files:
        # 多个月份时按月份自动匹配文件：2026-01 -> *1月*, 2025-12 -> *12月*
        if len(report_months) >= 2:
            files = []
            for m in report_months:
                num_str = (m or "").strip().split("-")[-1]
                try:
                    month_num = int(num_str)
                except Exception:
                    month_num = None
                if month_num is None:
                    break
                path = _find_file_for_month(download_dir, month_num)
                if path:
                    files.append(os.path.abspath(path))
            if len(files) == len(report_months):
                for m, p in zip(report_months, files):
                    print("  %s <- %s" % (m, p))
            else:
                files = []
        if not files:
            excel_path = _find_labor_excel(download_dir)
            if not excel_path or not os.path.isfile(excel_path):
                print("未在下载目录找到人力/薪资 Excel:", download_dir)
                print("请将 Excel 放入该目录（文件名含 薪资/人力/12月/1月 等）或使用 -f 指定路径")
                sys.exit(1)
            files = [os.path.abspath(excel_path)]
            print("使用 Excel:", files[0])
    else:
        files = [os.path.abspath(p) for p in files if os.path.isfile(p)]
        if len(files) != len(report_months):
            print("错误: -f 文件数(%d) 与报表月份数(%d) 不一致，请一一对应" % (len(files), len(report_months)))
            sys.exit(1)
        for m, p in zip(report_months, files):
            print("  %s <- %s" % (m, p))

    if args.rebuild:
        print("\n>>> 重建人力成本表结构...")
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(_root, "scripts", "rebuild_labor_tables.py"), "--yes"],
            cwd=_root,
            capture_output=False,
        )
        if r.returncode != 0:
            print("重建表失败，退出码", r.returncode)
            sys.exit(r.returncode)
        print("")

    if args.clear and not args.rebuild:
        print("\n>>> 清空人力成本数据...")
        from htma_dashboard.db_config import get_conn
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM t_htma_labor_cost")
            conn.commit()
            cur.execute("DELETE FROM t_htma_labor_cost_analysis")
            conn.commit()
            print("  已清空 t_htma_labor_cost 与 t_htma_labor_cost_analysis")
        finally:
            conn.close()
        print("")

    from htma_dashboard.db_config import get_conn
    from htma_dashboard.import_logic import import_labor_cost, refresh_labor_cost_analysis

    conn = get_conn()
    try:
        labels = {"leader": "组长", "fulltime": "组员", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
        type_labels = {"leader": "组长", "fulltime": "组员", "parttime": "兼职", "hourly": "小时工", "cleaner": "保洁", "management": "管理岗"}
        all_dupes = []
        # 单文件时对所有月份用同一文件；多文件时与 report_months 一一对应
        month_file_pairs = list(zip(report_months, files)) if len(files) == len(report_months) else [(m, files[0]) for m in report_months]
        for report_month, excel_path in month_file_pairs:
            print(">>> 导入", report_month, " <- ", excel_path, "...")
            counts, diag, dupes = import_labor_cost(excel_path, report_month, conn)
            if dupes:
                all_dupes.extend(dupes)
            parts = [f"{labels.get(k, k)} {v} 条" for k, v in counts.items() if v]
            print("   ", ", ".join(parts) if parts else "无数据")
            if diag:
                for d in diag:
                    print("   ", d)
        print("\n>>> 刷新 t_htma_labor_cost_analysis ...")
        n = refresh_labor_cost_analysis(conn)
        print("   已刷新", n, "个月份")

        # 期望值优先级：expected_labor.json > Excel 合计 sheet 解析 > 内置默认。零容差校验（人数与汇总金额必须一致）
        EXPECTED_FALLBACK = {
            "2026-01": {"total": 385582.62, "formal": 55, "other": 35},
            "2025-12": {"total": 532511.59, "formal": 69, "other": 312},
        }
        _expected_path = os.path.join(_root, "scripts", "expected_labor.json")
        if os.path.isfile(_expected_path):
            try:
                import json
                with open(_expected_path, "r", encoding="utf-8") as f:
                    _from_file = json.load(f)
                EXPECTED = {m: _from_file.get(m) for m in report_months if _from_file.get(m)}
                for m in report_months:
                    if m not in EXPECTED or not EXPECTED[m]:
                        EXPECTED[m] = EXPECTED_FALLBACK.get(m, {})
                print("\n>>> 期望值已从 scripts/expected_labor.json 加载（零容差校验）")
            except Exception as e:
                EXPECTED = {}
        else:
            EXPECTED = {}
        if not EXPECTED:
            for report_month, excel_path in month_file_pairs:
                parsed = _parse_expected_from_excel(excel_path)
                if parsed.get("total") is not None or parsed.get("formal") is not None or parsed.get("other") is not None:
                    EXPECTED[report_month] = {
                        "total": parsed["total"] if parsed.get("total") is not None else EXPECTED_FALLBACK.get(report_month, {}).get("total"),
                        "formal": parsed["formal"] if parsed.get("formal") is not None else EXPECTED_FALLBACK.get(report_month, {}).get("formal"),
                        "other": parsed["other"] if parsed.get("other") is not None else EXPECTED_FALLBACK.get(report_month, {}).get("other"),
                    }
                else:
                    EXPECTED[report_month] = EXPECTED_FALLBACK.get(report_month, {}).copy()
                if not any(EXPECTED[report_month].get(k) is not None for k in ("total", "formal", "other")):
                    print("\n>>> 警告: %s 未从 Excel 合计表解析到期望值，使用内置默认。" % report_month)

        print("\n>>> 与汇总表校验（开票金额/总成本，零容差）")
        cur = conn.cursor()
        verify_ok = True
        actual_for_lock = {}  # 用于校验通过时写入 expected_labor.json
        for report_month in report_months:
            cur.execute(
                "SELECT SUM(total_cost) AS s, SUM(CASE WHEN position_type IN ('leader','fulltime') THEN 1 ELSE 0 END) AS formal, SUM(CASE WHEN position_type NOT IN ('leader','fulltime') THEN 1 ELSE 0 END) AS other FROM t_htma_labor_cost WHERE report_month=%s",
                (report_month,),
            )
            row = cur.fetchone()
            if not row:
                verify_ok = False
                continue
            if isinstance(row, (list, tuple)):
                total, formal, other = (row[0] or 0), (row[1] or 0), (row[2] or 0)
            else:
                total = (row.get("s") or 0) if row else 0
                formal = int(row.get("formal") or 0) if row else 0
                other = int(row.get("other") or 0) if row else 0
            exp = EXPECTED.get(report_month)
            total_f = float(total)
            actual_for_lock[report_month] = {"total": round(total_f, 2), "formal": int(formal), "other": int(other)}
            if exp and exp.get("total") is not None and exp.get("formal") is not None and exp.get("other") is not None:
                # 零容差：总成本误差 < 0.01 元，人数完全一致
                ok_total = abs(total_f - exp["total"]) < 0.01
                ok_f = int(formal) == exp["formal"]
                ok_o = int(other) == exp["other"]
                if not (ok_total and ok_f and ok_o):
                    verify_ok = False
                status = "✓" if (ok_total and ok_f and ok_o) else "✗"
                print("   %s: 总成本 %.2f %s (期望 %.2f) | 正式 %d %s (期望 %d) | 其他 %d %s (期望 %d)" % (
                    report_month, total_f, status, exp["total"],
                    int(formal), "✓" if ok_f else "✗", exp["formal"],
                    int(other), "✓" if ok_o else "✗", exp["other"]))
                if not (ok_total and ok_f and ok_o):
                    print("      → 人数或汇总金额与 Excel 合计表不一致，请核对明细导入与合计 sheet 口径（开票金额/总成本、正式/其他人数）。")
            else:
                print("   %s: 总成本 %.2f | 正式 %d | 其他 %d（未配置期望，未做零容差校验）" % (report_month, total_f, int(formal), int(other)))

        # 成本分项：按类目汇总，便于核对总成本差异来自哪一类
        print("\n>>> 成本分项（按类目）")
        for report_month in report_months:
            cur.execute(
                "SELECT position_type, COUNT(*) AS cnt, COALESCE(SUM(total_cost), 0) AS cost FROM t_htma_labor_cost WHERE report_month = %s GROUP BY position_type ORDER BY position_type",
                (report_month,),
            )
            rows = cur.fetchall()
            total_by_type = 0
            for r in rows:
                t = r.get("position_type") or ""
                cnt = int(r.get("cnt") or 0)
                cost = float(r.get("cost") or 0)
                total_by_type += cost
                print("   %s %s: %d 人, 费用 %.2f 元" % (report_month, type_labels.get(t, t), cnt, cost))
            print("   %s 合计: %.2f 元" % (report_month, total_by_type))

        # 重复人员已加后缀：同一月同岗位同供应商下重复出现时，第2条起自动命名为 姓名1、姓名2，确保人数与汇总一致
        if all_dupes:
            print("\n>>> 重复人员已加后缀（同一月同岗位同供应商重复出现，已自动命名为 姓名1、姓名2… 以保留每人一条）")
            by_month = {}
            for d in all_dupes:
                m = d.get("report_month") or ""
                if m not in by_month:
                    by_month[m] = []
                by_month[m].append(d)
            for m in sorted(by_month.keys()):
                arr = by_month[m]
                print("   %s: %d 条已加后缀" % (m, len(arr)))
                for d in arr[:50]:
                    t = type_labels.get(d.get("position_type"), d.get("position_type"))
                    suf = d.get("suffix", "")
                    print("      - %s -> %s%s（%s / %s / %s）" % (
                        (d.get("person_name") or "-").strip(),
                        (d.get("person_name") or "-").strip(),
                        suf,
                        t,
                        (d.get("position_name") or "-").strip(),
                        (d.get("supplier_name") or "-").strip(),
                    ))
                if len(arr) > 50:
                    print("      ... 及其他 %d 条" % (len(arr) - 50))
    finally:
        conn.close()

    # 校验通过时，将本次实际值写入 expected_labor.json，供下次零容差校验使用（确保人数与汇总金额一致、无漂移）
    if verify_ok and report_months and actual_for_lock:
        try:
            import json
            _p = os.path.join(_root, "scripts", "expected_labor.json")
            _existing = {}
            if os.path.isfile(_p):
                try:
                    with open(_p, "r", encoding="utf-8") as f:
                        _existing = json.load(f)
                except Exception:
                    pass
            _existing.update(actual_for_lock)
            with open(_p, "w", encoding="utf-8") as f:
                json.dump(_existing, f, ensure_ascii=False, indent=2)
            print("\n>>> 已写入 scripts/expected_labor.json（本次实际值），下次运行将以此为期望零容差校验。")
        except Exception as e:
            print("\n>>> 写入 expected_labor.json 失败:", e)

    print("\n完成。请打开 /labor 查看人力汇总与类目拆分。")
    if verify_ok is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
