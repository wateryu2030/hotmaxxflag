# -*- coding: utf-8 -*-
"""人力成本 Excel 导入 — 组长/组员/兼职/小时工/保洁 sheet 识别与写入"""
import os
import re
from datetime import datetime, timedelta

import pandas as pd
import pymysql

from ingest.helpers import (
    _safe_decimal, _safe_str, _parse_date, _parse_datetime,
    _extract_report_date, _is_summary_like, _is_sale_summary_row,
    _row_val_raw, _row_val, _trim_leading_junk_rows,
    _header_row_forward_fill, _detect_header_row, _find_col_by_header,
    _read_excel_safe, _normalize_header, _normalize_position_name,
    _normalize_person_name, _supplier_from_sheet, _ocr_image_to_table,
)

STORE_ID = "沈阳超级仓"


def _safe_num(v, default=0):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_skip_position(name):
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return True
    if not str(name).strip():
        return True
    t = str(name).strip().lower()
    if t in ("nan", "none", "#n/a", "-"):
        return True
    for k in ("合计", "总计", "小计", "汇总", "求和项"):
        if k in t:
            return True
    return False


def _is_skip_person_row(name_val):
    if name_val is None or (isinstance(name_val, float) and pd.isna(name_val)):
        return True
    t = str(name_val).strip()
    if not t:
        return True
    t_lower = t.lower()
    if t_lower in ("nan", "none", "#n/a", "-"):
        return True
    for k in ("合计", "总计", "小计", "汇总", "求和项"):
        if k in t_lower:
            return True
    if t.isdigit() or (len(t) <= 6 and t.replace(".", "", 1).replace("-", "", 1).isdigit()):
        return True
    return False


def _is_header_or_invalid_row(pos_val, row, pos_col, num_cols):
    if pos_val is None:
        return True
    t = str(pos_val).strip()
    if not t:
        return True
    if t == "岗位" or "求和项:岗位" in t or t.replace(" ", "") == "岗位" or t == "职务":
        return True
    if t.isdigit() and len(t) <= 5:
        return True
    if num_cols:
        has_num = any(_safe_num(row.get(c)) != 0 for c in num_cols if c is not None)
        if not has_num and len(t) < 3:
            return True
    return False


def _person_name_with_suffix(report_month, ptype, pos_name, person_name, supplier_name, _seen_keys=None, _duplicates=None):
    if _seen_keys is None:
        _seen_keys = {}
    if _duplicates is None:
        _duplicates = []
    pn = (person_name or "").strip()[:64]
    sup = (supplier_name or "").strip()[:64]
    key = (ptype, (pos_name or "").strip()[:64], pn, sup)
    if report_month not in _seen_keys:
        _seen_keys[report_month] = {}
    count = _seen_keys[report_month].get(key, -1) + 1
    _seen_keys[report_month][key] = count
    if count == 0:
        return (person_name or "").strip() or ""
    suffix = str(count)
    base = (person_name or "").strip() or "-"
    if base.startswith("#"):
        return base + suffix
    _duplicates.append({
        "report_month": report_month,
        "position_type": ptype,
        "person_name": base,
        "position_name": (pos_name or "").strip() or "-",
        "supplier_name": (supplier_name or "").strip() or "-",
        "suffix": suffix,
    })
    return base + suffix


def import_labor_cost(excel_path, report_month, conn, store_id=None):
    """
    导入人力成本 Excel：支持单 sheet 或多 sheet，自动识别类型并归类。
    用工类型与汇总表一致：管理组→leader(组长)、全职→fulltime(组员)、保洁全职→cleaner、兼职→parttime、小时工→hourly；
    成本以「开票金额/总成本」为准；供应商(斗米/中锐/快聘/保洁)从列或 sheet 名解析。
    组长/组员 sheet：全部到人导入（姓名为空或汇总行跳过）；兼职/小时工/保洁：到人且每人有人名。
    report_month 如 2026-01。返回 (counts_dict, diagnostics)。
    仅操作 t_htma_labor_cost（先按 report_month 删除该月再写入），不触碰其他表。
    """
    store_id = store_id or STORE_ID
    counts = {"leader": 0, "fulltime": 0, "parttime": 0, "hourly": 0, "cleaner": 0, "management": 0}
    diagnostics = []
    n_to_person_with_real_name = [0]
    n_to_person_total = [0]
    _seen_keys = {}
    duplicates = []

    # 导入前删除该月数据，避免旧逻辑与新逻辑并存造成重复
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM t_htma_labor_cost WHERE report_month = %s", (report_month,))
        conn.commit()
    except Exception as e:
        diagnostics.append("清理该月数据时: " + str(e))

    try:
        xl = pd.ExcelFile(excel_path)
        sheets = xl.sheet_names
    except Exception as e:
        diagnostics.append(str(e))
        return counts, diagnostics, []

    for sheet_name in sheets:
        _sn = (sheet_name or "").strip()
        if "合计" in _sn and ("发票" in _sn or "发薪" in _sn or "对应" in _sn):
            continue
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
        if df.shape[0] == 0:
            continue
        sheet_name_lower = _sn.lower()
        preferred_leader = "组长" in sheet_name_lower or "管理组" in sheet_name_lower
        preferred_fulltime = "组员" in sheet_name_lower or ("全职" in sheet_name_lower and "保洁" not in sheet_name_lower)

        header_row = 0
        for r in range(min(12, df.shape[0])):
            row = df.iloc[r]
            for c in range(min(50, len(row))):
                v = str(row.iloc[c]).strip() if c < len(row) else ""
                if any(k in v for k in (
                    "岗位", "职务", "合计薪资", "总工时", "本月合计薪资", "费用总额",
                    "费用合计", "属性", "开票金额", "总成本",
                )):
                    header_row = r
                    break
            else:
                continue
            break
        df_header = pd.read_excel(excel_path, sheet_name=sheet_name, header=header_row)
        df_header = df_header.dropna(how="all", axis=0).dropna(how="all", axis=1)
        col_map = {}
        for col in df_header.columns:
            n = _normalize_header(col)
            if n:
                col_map[col] = n

        pos_col = None
        for c in df_header.columns:
            nm = col_map.get(c) or _normalize_header(str(c))
            if "岗位" in nm:
                pos_col = c
                break
        if not pos_col and (preferred_leader or not preferred_fulltime):
            for c in df_header.columns:
                nm = col_map.get(c) or _normalize_header(str(c))
                if "职务" in nm:
                    pos_col = c
                    break
        if not pos_col and ("兼职" in sheet_name_lower or "小时工" in sheet_name_lower):
            for c in df_header.columns:
                nm = col_map.get(c) or _normalize_header(str(c))
                if "属性" in nm:
                    pos_col = c
                    break
        if not pos_col:
            for c in df_header.columns:
                nm = col_map.get(c) or _normalize_header(str(c))
                if "姓名" in nm or "人员" in nm or "名字" in nm:
                    pos_col = c
                    break
        has_any_cost_col = any(
            (col_map.get(c) or "").find("费用") >= 0 or (col_map.get(c) or "").find("开票") >= 0 or (col_map.get(c) or "").find("总成本") >= 0
            for c in df_header.columns
        )
        if not pos_col and has_any_cost_col:
            first_col = df_header.columns[0] if len(df_header.columns) else None
            if first_col is not None:
                pos_col = first_col
        if not pos_col:
            continue

        if pos_col in df_header.columns:
            df_header[pos_col] = df_header[pos_col].ffill()

        has_total_cost = any("费用总额" in (col_map.get(c) or "") or "人力成本" in (col_map.get(c) or "") or "开票金额" in (col_map.get(c) or "") or "总成本" in (col_map.get(c) or "") for c in df_header.columns)
        has_fee_total = any("费用合计" in (col_map.get(c) or "") for c in df_header.columns)
        has_luxury_bonus = any("奢品奖金" in (col_map.get(c) or "") for c in df_header.columns)
        has_work_hours = any("总工时" in (col_map.get(c) or "") or "当月总工时" in (col_map.get(c) or "") or "本月总工时" in (col_map.get(c) or "") for c in df_header.columns)
        has_base_salary = any("基本工资" in (col_map.get(c) or "") for c in df_header.columns)

        def _col(name, fallbacks=None):
            for c in df_header.columns:
                n = col_map.get(c) or _normalize_header(str(c))
                if n == name or (fallbacks and any(f in n for f in fallbacks)):
                    return c
                if name == "姓名" and n.replace(" ", "").replace("\u3000", "") == "姓名":
                    return c
            return None

        def _total_cost_col():
            col = _col("开票金额", ["开票金额/总成本", "总成本", "开票金额"])
            if col is not None:
                return col
            col = _col("费用总额", ["费用总额", "人力成本总额", "含服务费"])
            if col is not None:
                return col
            return _col("公司实际成本")

        supplier_col = _col("供应商")
        default_supplier = _supplier_from_sheet(sheet_name)

        def _row_supplier(row):
            v = row.get(supplier_col) if supplier_col is not None else None
            v = _normalize_position_name(v) if v is not None else ""
            return (v or default_supplier)[:64]

        is_leader_table = (has_total_cost or has_luxury_bonus) and not has_work_hours
        if preferred_leader:
            is_leader_table = True
        if preferred_fulltime or "兼职" in sheet_name_lower or "小时工" in sheet_name_lower:
            is_leader_table = False
        is_fulltime_table = has_work_hours and has_base_salary
        if preferred_fulltime:
            is_fulltime_table = True
        if preferred_leader:
            is_fulltime_table = False
        has_cost_for_ph = has_fee_total or has_total_cost
        is_parttime_table = "兼职" in sheet_name_lower and has_cost_for_ph and pos_col is not None
        is_hourly_table = "小时工" in sheet_name_lower and has_cost_for_ph and pos_col is not None
        is_cleaner_table = "保洁" in sheet_name_lower
        is_management_table = ("管理岗" in sheet_name_lower or "宝赞" in sheet_name_lower) and (has_total_cost or has_fee_total)

        if is_cleaner_table or is_management_table:
            ptype = "cleaner" if "保洁" in sheet_name_lower else "management"
            total_cost_col = _total_cost_col()
            if total_cost_col is None and is_cleaner_table:
                total_cost_col = _col("公司实际成本") or _col("应发") or _col("实发") or _col("本月应发") or _col("人力成本") or _col("应发工资")
            company_cost_col_other = _col("公司实际成本")
            person_col_other = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            first_col_other = df_header.columns[0] if len(df_header.columns) else None
            base_sal_col = _col("基本工资")
            perf_col = _col("绩效")
            allow_col = _col("岗位补贴")
            meal_col = _col("饭补")
            cur = conn.cursor()
            if person_col_other is not None:
                for i, (_, row) in enumerate(df_header.iterrows()):
                    pos = row.get(pos_col)
                    if _is_skip_position(pos) or _is_skip_person_row(row.get(person_col_other)):
                        continue
                    pos_name = _normalize_position_name(pos)
                    if not pos_name:
                        continue
                    person_name = _normalize_person_name(row.get(person_col_other)) or ""
                    if not person_name and first_col_other is not None:
                        first_val = row.get(first_col_other)
                        person_name = _normalize_person_name(first_val) or ("#%d" % (i + 1))
                    cost_val = _safe_num(row.get(total_cost_col)) if total_cost_col else _safe_num(row.get(company_cost_col_other))
                    if not cost_val and company_cost_col_other:
                        cost_val = _safe_num(row.get(company_cost_col_other))
                    if not cost_val and is_cleaner_table and (base_sal_col is not None or perf_col is not None):
                        cost_val = _safe_num(row.get(base_sal_col)) + _safe_num(row.get(perf_col)) + _safe_num(row.get(allow_col)) + _safe_num(row.get(meal_col))
                    sup = _row_supplier(row)
                    person_name = _person_name_with_suffix(report_month, ptype, pos_name, person_name, sup, _seen_keys, duplicates)
                    cur.execute("""
                        INSERT INTO t_htma_labor_cost
                        (report_month, position_type, position_name, person_name, company_cost, total_cost, supplier_name, store_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                    """, (report_month, ptype, pos_name, person_name or "", cost_val, cost_val, sup, store_id))
                    counts[ptype] += 1
                    n_to_person_total[0] += 1
                    if person_name and not str(person_name).strip().startswith("#"):
                        n_to_person_with_real_name[0] += 1
            else:
                agg_other = {}
                for _, row in df_header.iterrows():
                    pos = row.get(pos_col)
                    if _is_skip_position(pos):
                        continue
                    pos_name = _normalize_position_name(pos)
                    if not pos_name:
                        continue
                    cost_val = _safe_num(row.get(total_cost_col)) if total_cost_col else _safe_num(row.get(company_cost_col_other))
                    if not cost_val and company_cost_col_other:
                        cost_val = _safe_num(row.get(company_cost_col_other))
                    if pos_name not in agg_other:
                        agg_other[pos_name] = 0
                    agg_other[pos_name] += cost_val
                for pos_name, total_cost in agg_other.items():
                    person_name = _person_name_with_suffix(report_month, ptype, pos_name, "", default_supplier, _seen_keys, duplicates)
                    cur.execute("""
                        INSERT INTO t_htma_labor_cost
                        (report_month, position_type, position_name, person_name, company_cost, total_cost, supplier_name, store_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                    """, (report_month, ptype, pos_name, person_name or "", total_cost, total_cost, default_supplier, store_id))
                    counts[ptype] += 1
            conn.commit()
        elif is_leader_table:
            total_salary_col = _col("合计薪资")
            actual_salary_col = _col("实际薪资合计") or _col("实际薪资")
            luxury_bonus_col = _col("奢品奖金")
            actual_income_col = _col("实得收入")
            company_cost_col = _col("公司实际成本")
            total_cost_col = _total_cost_col()
            person_col = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            pre_tax_col = _col("税前应发", ["应发", "应发工资"])
            num_cols_leader = [total_salary_col, actual_salary_col, company_cost_col, total_cost_col]
            first_col = df_header.columns[0] if len(df_header.columns) else None
            cur = conn.cursor()
            for i, (_, row) in enumerate(df_header.iterrows()):
                pos = row.get(pos_col)
                if _is_skip_position(pos) or _is_header_or_invalid_row(pos, row, pos_col, num_cols_leader):
                    continue
                if person_col is not None and _is_skip_person_row(row.get(person_col)):
                    continue
                pos_name = _normalize_position_name(pos)
                if not pos_name:
                    continue
                person_name = _normalize_person_name(row.get(person_col)) if person_col else ""
                if not person_name and first_col is not None:
                    first_val = row.get(first_col)
                    name_from_first = _normalize_position_name(first_val)
                    person_name = name_from_first if _normalize_person_name(name_from_first) else ("#%d" % (i + 1))
                total_s = _safe_num(row.get(total_salary_col))
                actual_s = _safe_num(row.get(actual_salary_col))
                luxury_b = _safe_num(row.get(luxury_bonus_col))
                actual_inc = _safe_num(row.get(actual_income_col))
                company_c = _safe_num(row.get(company_cost_col))
                tcost = _safe_num(row.get(total_cost_col)) or company_c
                pre_tax = _safe_num(row.get(pre_tax_col)) if pre_tax_col else total_s
                sup = _row_supplier(row)
                person_name = _person_name_with_suffix(report_month, "leader", pos_name, person_name, sup, _seen_keys, duplicates)
                cur.execute("""
                    INSERT INTO t_htma_labor_cost
                    (report_month, position_type, position_name, person_name, total_salary, pre_tax_pay, actual_salary, luxury_bonus,
                     actual_income, company_cost, total_cost, supplier_name, store_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                    total_salary=VALUES(total_salary), pre_tax_pay=VALUES(pre_tax_pay), actual_salary=VALUES(actual_salary),
                    luxury_bonus=VALUES(luxury_bonus), actual_income=VALUES(actual_income),
                    company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                """, (report_month, "leader", pos_name, person_name or "",
                      total_s, pre_tax, actual_s, luxury_b, actual_inc, company_c, tcost, sup, store_id))
                counts["leader"] += 1
                n_to_person_total[0] += 1
                if person_name and not str(person_name).strip().startswith("#"):
                    n_to_person_with_real_name[0] += 1
            conn.commit()
        elif is_fulltime_table:
            work_hours_col = _col("总工时", ["总工时", "当月总工时", "本月总工时"]) or _col("当月总工时") or _col("本月总工时")
            base_salary_col = _col("基本工资")
            performance_col = _col("绩效", ["绩效工资"])
            position_allowance_col = _col("岗位补贴")
            total_salary_col = _col("合计薪资", ["本月合计薪资"])
            luxury_amount_col = _col("奢品", ["奢品奖金"])
            actual_income_col = _col("实得收入", ["本月实得收入"])
            company_cost_col = _col("公司实际成本")
            total_cost_col_ft = _total_cost_col()
            person_col_ft = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            pre_tax_col_ft = _col("税前应发", ["应发", "应发工资"])
            num_cols_fulltime = [work_hours_col, base_salary_col, total_salary_col, company_cost_col]
            first_col_ft = df_header.columns[0] if len(df_header.columns) else None
            cur = conn.cursor()
            for i, (_, row) in enumerate(df_header.iterrows()):
                pos = row.get(pos_col)
                if _is_skip_position(pos) or _is_header_or_invalid_row(pos, row, pos_col, num_cols_fulltime):
                    continue
                if person_col_ft is not None and _is_skip_person_row(row.get(person_col_ft)):
                    continue
                pos_name = _normalize_position_name(pos)
                if not pos_name:
                    continue
                person_name = _normalize_person_name(row.get(person_col_ft)) if person_col_ft else ""
                if not person_name and first_col_ft is not None:
                    first_val = row.get(first_col_ft)
                    name_from_first = _normalize_position_name(first_val)
                    person_name = name_from_first if _normalize_person_name(name_from_first) else ("#%d" % (i + 1))
                cost_val = _safe_num(row.get(total_cost_col_ft)) or _safe_num(row.get(company_cost_col))
                wh = _safe_num(row.get(work_hours_col))
                base_s = _safe_num(row.get(base_salary_col))
                perf = _safe_num(row.get(performance_col))
                allow = _safe_num(row.get(position_allowance_col))
                total_s = _safe_num(row.get(total_salary_col))
                luxury_a = _safe_num(row.get(luxury_amount_col))
                actual_inc = _safe_num(row.get(actual_income_col))
                company_c = _safe_num(row.get(company_cost_col))
                pre_tax = _safe_num(row.get(pre_tax_col_ft)) if pre_tax_col_ft else total_s
                sup = _row_supplier(row)
                person_name = _person_name_with_suffix(report_month, "fulltime", pos_name, person_name, sup, _seen_keys, duplicates)
                cur.execute("""
                    INSERT INTO t_htma_labor_cost
                    (report_month, position_type, position_name, person_name, work_hours, base_salary, performance,
                     position_allowance, total_salary, pre_tax_pay, luxury_amount, actual_income, company_cost, total_cost, supplier_name, store_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                    work_hours=VALUES(work_hours), base_salary=VALUES(base_salary), performance=VALUES(performance),
                    position_allowance=VALUES(position_allowance), total_salary=VALUES(total_salary), pre_tax_pay=VALUES(pre_tax_pay),
                    luxury_amount=VALUES(luxury_amount), actual_income=VALUES(actual_income),
                    company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
                """, (report_month, "fulltime", pos_name, person_name or "",
                      wh, base_s, perf, allow, total_s, pre_tax, luxury_a, actual_inc, company_c, cost_val, sup, store_id))
                counts["fulltime"] += 1
                n_to_person_total[0] += 1
                if person_name and not str(person_name).strip().startswith("#"):
                    n_to_person_with_real_name[0] += 1
            conn.commit()
        elif is_parttime_table or is_hourly_table:
            ptype = "parttime" if "兼职" in sheet_name_lower else "hourly"
            cost_col = _total_cost_col() or _col("费用合计", ["总成本", "费用合计"])
            if cost_col is None:
                continue
            person_col_ph = _col("姓名", ["人员", "名字", "员工姓名", "中文姓名"])
            first_col_ph = df_header.columns[0] if len(df_header.columns) else None
            store_name_col = _col("店铺名", ["门店"])
            city_col = _col("城市")
            join_date_col = _col("入职日期")
            leave_date_col = _col("离职日期")
            total_hours_col = _col("总工时")
            normal_hours_col = _col("普通工时")
            triple_pay_col = _col("三薪工时")
            hourly_rate_col = _col("时薪")
            pay_amount_col = _col("发薪金额")
            service_fee_unit_col = _col("服务费单价")
            service_fee_total_col = _col("服务费总计")
            tax_col = _col("税费")
            cost_include_col = _col("成本计入")
            department_col = _col("用人部门")

            def _row_str(r, col, max_len=64):
                v = r.get(col) if col is not None else None
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                return str(v).strip()[:max_len] or None

            cur = conn.cursor()
            if person_col_ph is not None:
                for i, (_, row) in enumerate(df_header.iterrows()):
                    pos = row.get(pos_col)
                    if _is_skip_position(pos) or _is_skip_person_row(row.get(person_col_ph)):
                        continue
                    pos_name = _normalize_position_name(pos)
                    if not pos_name:
                        continue
                    person_name = _normalize_person_name(row.get(person_col_ph)) or ""
                    if not person_name and first_col_ph is not None:
                        first_val = row.get(first_col_ph)
                        first_str = _normalize_person_name(first_val) if first_val is not None else ""
                        if first_str and not _is_skip_person_row(first_val) and first_str not in ("门店", "成本计入"):
                            person_name = first_str
                        else:
                            person_name = "#%d" % (i + 1)
                    cost_val = _safe_num(row.get(cost_col))
                    sup = _row_supplier(row)
                    store_name_val = _row_str(row, store_name_col)
                    city_val = _row_str(row, city_col, 32)
                    join_date_val = _row_str(row, join_date_col, 32)
                    leave_date_val = _row_str(row, leave_date_col, 32)
                    total_hrs = _safe_num(row.get(total_hours_col)) if total_hours_col else None
                    normal_hrs = _safe_num(row.get(normal_hours_col)) if normal_hours_col else None
                    triple_hrs = _safe_num(row.get(triple_pay_col)) if triple_pay_col else None
                    rate = _safe_num(row.get(hourly_rate_col)) if hourly_rate_col else None
                    pay_amt = _safe_num(row.get(pay_amount_col)) if pay_amount_col else None
                    svc_unit = _safe_num(row.get(service_fee_unit_col)) if service_fee_unit_col else None
                    svc_total = _safe_num(row.get(service_fee_total_col)) if service_fee_total_col else None
                    tax_val = _safe_num(row.get(tax_col)) if tax_col else None
                    cost_include_val = _row_str(row, cost_include_col, 32)
                    department_val = _row_str(row, department_col, 64)
                    person_name = _person_name_with_suffix(report_month, ptype, pos_name, person_name, sup, _seen_keys, duplicates)
                    cur.execute("""
                        INSERT INTO t_htma_labor_cost
                        (report_month, position_type, position_name, person_name, company_cost, total_cost, supplier_name, store_id,
                         store_name, city, join_date, leave_date, work_hours, normal_hours, triple_pay_hours, hourly_rate, pay_amount, service_fee_unit, service_fee_total, tax, cost_include, department)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE company_cost=VALUES(company_cost), total_cost=VALUES(total_cost),
                        store_name=VALUES(store_name), city=VALUES(city), join_date=VALUES(join_date), leave_date=VALUES(leave_date),
                        work_hours=VALUES(work_hours), normal_hours=VALUES(normal_hours), triple_pay_hours=VALUES(triple_pay_hours),
                        hourly_rate=VALUES(hourly_rate), pay_amount=VALUES(pay_amount), service_fee_unit=VALUES(service_fee_unit), service_fee_total=VALUES(service_fee_total), tax=VALUES(tax),
                        cost_include=VALUES(cost_include), department=VALUES(department)
                    """, (report_month, ptype, pos_name, person_name or "", cost_val, cost_val, sup, store_id,
                          store_name_val, city_val, join_date_val, leave_date_val, total_hrs, normal_hrs, triple_hrs, rate, pay_amt, svc_unit, svc_total, tax_val, cost_include_val, department_val))
                    counts[ptype] += 1
            conn.commit()
        else:
            diagnostics.append(f"Sheet [{sheet_name}]: 无法识别类型，跳过")

    diagnostics.append(f"导入到人: 总{n_to_person_total[0]}人({n_to_person_with_real_name[0]}人真实姓名)")
    if duplicates:
        diagnostics.append(f"因唯一键重复而添加后缀 {len(duplicates)} 人: {', '.join(d['person_name'] + d['suffix'] for d in duplicates[:5])}")
    return counts, diagnostics, duplicates


def import_labor_cost_from_image(image_path, report_month, conn, store_id=None, position_type=None):
    """从附图 OCR 识别表格并导入人力成本。position_type='leader'|'fulltime' 必填，与组长表/组员表一一对应。返回 (leader_count, fulltime_count, diagnostics)。"""
    store_id = store_id or STORE_ID
    leader_count = 0
    fulltime_count = 0
    diagnostics = []
    if position_type not in ("leader", "fulltime"):
        diagnostics.append("附图导入请指定 position_type=leader（组长表）或 fulltime（组员表）。")
        return 0, 0, diagnostics

    def _is_header_or_junk_row(pos_cell, whole_row):
        """附图 OCR 后：岗位列为表头字样或整行为合计行则跳过"""
        if not pos_cell or not str(pos_cell).strip():
            return True
        t = str(pos_cell).strip()
        if t in ("岗位", "求和项:岗位") or t.replace(" ", "") == "岗位":
            return True
        if t.isdigit() and len(t) <= 5:
            return True
        for cell in (whole_row or []):
            if cell and ("合计" in str(cell) or "总计" in str(cell)):
                return True
        return False

    headers, rows = _ocr_image_to_table(image_path)
    if not headers or not rows:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception as e:
            diagnostics.append("OCR 不可用: " + str(e) + "。请安装 Tesseract（如 brew install tesseract tesseract-lang）或改用 Excel 导入。")
        else:
            diagnostics.append("未能从附图中识别出表格，请确保图片清晰、表头含「岗位」，或改用 Excel 导入。")
        return 0, 0, diagnostics

    def _norm(h):
        if not h:
            return ""
        s = str(h).strip().replace("求和项:", "").strip()
        if "(" in s:
            s = s.split("(")[0].strip()
        return s

    norm_headers = [_norm(h) for h in headers]
    pos_idx = None
    for i, h in enumerate(norm_headers):
        if "岗位" in h:
            pos_idx = i
            break
    if pos_idx is None:
        diagnostics.append("未识别到「岗位」列。")
        return 0, 0, diagnostics

    has_total_cost = any("费用总额" in h for h in norm_headers)
    has_luxury_bonus = any("奢品奖金" in h for h in norm_headers)
    has_work_hours = any("总工时" in h or "12月" in h or "当月总工时" in h or "本月总工时" in h for h in norm_headers)
    has_base_salary = any("基本工资" in h for h in norm_headers)

    def _col_idx(name, fallbacks=None):
        for i, h in enumerate(norm_headers):
            if name in h or (fallbacks and any(f in h for f in fallbacks)):
                return i
        return None

    is_leader_table = (has_total_cost or has_luxury_bonus) and not has_work_hours
    is_fulltime_table = has_work_hours and has_base_salary

    if position_type == "leader":
        if not is_leader_table:
            diagnostics.append("当前附图未识别为组长表（需含「费用总额」或「奢品奖金」且无「总工时」）。请上传组长表截图或检查表头是否清晰。")
            return 0, 0, diagnostics
        total_salary_idx = _col_idx("合计薪资")
        actual_salary_idx = _col_idx("实际薪资合计")
        luxury_bonus_idx = _col_idx("奢品奖金")
        actual_income_idx = _col_idx("实得收入")
        company_cost_idx = _col_idx("公司实际成本")
        total_cost_idx = _col_idx("费用总额")
        for row in rows:
            if len(row) <= pos_idx:
                continue
            pos_name = str(row[pos_idx]).strip()[:64] if pos_idx < len(row) else ""
            if _is_skip_position(pos_name) or _is_header_or_junk_row(row[pos_idx], row) or not pos_name:
                continue
            total_salary = _safe_num(row[total_salary_idx]) if total_salary_idx is not None and total_salary_idx < len(row) else 0
            actual_salary = _safe_num(row[actual_salary_idx]) if actual_salary_idx is not None and actual_salary_idx < len(row) else 0
            luxury_bonus = _safe_num(row[luxury_bonus_idx]) if luxury_bonus_idx is not None and luxury_bonus_idx < len(row) else 0
            actual_income = _safe_num(row[actual_income_idx]) if actual_income_idx is not None and actual_income_idx < len(row) else 0
            company_cost = _safe_num(row[company_cost_idx]) if company_cost_idx is not None and company_cost_idx < len(row) else 0
            total_cost = _safe_num(row[total_cost_idx]) if total_cost_idx is not None and total_cost_idx < len(row) else company_cost
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO t_htma_labor_cost
                (report_month, position_type, position_name, person_name, total_salary, actual_salary, luxury_bonus,
                 actual_income, company_cost, total_cost, supplier_name, store_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                total_salary=VALUES(total_salary), actual_salary=VALUES(actual_salary),
                luxury_bonus=VALUES(luxury_bonus), actual_income=VALUES(actual_income),
                company_cost=VALUES(company_cost), total_cost=VALUES(total_cost)
            """, (report_month, "leader", pos_name, "", total_salary, actual_salary, luxury_bonus,
                  actual_income, company_cost, total_cost, "斗米", store_id))
            leader_count += 1
        conn.commit()
        return leader_count, 0, diagnostics

    if position_type == "fulltime":
        if not is_fulltime_table:
            diagnostics.append("当前附图未识别为组员表（需含「总工时」「基本工资」等）。请上传组员表截图或检查表头是否清晰。")
            return 0, 0, diagnostics
        work_hours_idx = _col_idx("总工时", ["12月总工时", "总工时", "当月总工时", "本月总工时"])
        base_salary_idx = _col_idx("基本工资")
        performance_idx = _col_idx("绩效", ["绩效工资"])
        position_allowance_idx = _col_idx("岗位补贴")
        total_salary_idx = _col_idx("合计薪资", ["本月合计薪资"])
        luxury_amount_idx = _col_idx("奢品", ["奢品奖金"])
        actual_income_idx = _col_idx("实得收入", ["本月实得收入"])
        company_cost_idx = _col_idx("公司实际成本")
        for row in rows:
            if len(row) <= pos_idx:
                continue
            pos_name = str(row[pos_idx]).strip()[:64] if pos_idx < len(row) else ""
            if _is_skip_position(pos_name) or _is_header_or_junk_row(row[pos_idx], row) or not pos_name:
                continue
            work_hours = _safe_num(row[work_hours_idx]) if work_hours_idx is not None and work_hours_idx < len(row) else 0
            base_salary = _safe_num(row[base_salary_idx]) if base_salary_idx is not None and base_salary_idx < len(row) else 0
            performance = _safe_num(row[performance_idx]) if performance_idx is not None and performance_idx < len(row) else 0
            position_allowance = _safe_num(row[position_allowance_idx]) if position_allowance_idx is not None and position_allowance_idx < len(row) else 0
            total_salary = _safe_num(row[total_salary_idx]) if total_salary_idx is not None and total_salary_idx < len(row) else 0
            luxury_amount = _safe_num(row[luxury_amount_idx]) if luxury_amount_idx is not None and luxury_amount_idx < len(row) else 0
            actual_income = _safe_num(row[actual_income_idx]) if actual_income_idx is not None and actual_income_idx < len(row) else 0
            company_cost = _safe_num(row[company_cost_idx]) if company_cost_idx is not None and company_cost_idx < len(row) else 0
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO t_htma_labor_cost
                (report_month, position_type, position_name, person_name, work_hours, base_salary, performance,
                 position_allowance, total_salary, luxury_amount, actual_income, company_cost, total_cost, supplier_name, store_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                work_hours=VALUES(work_hours), base_salary=VALUES(base_salary), performance=VALUES(performance),
                position_allowance=VALUES(position_allowance), total_salary=VALUES(total_salary),
                luxury_amount=VALUES(luxury_amount), actual_income=VALUES(actual_income),
                company_cost=VALUES(company_cost), total_cost=VALUES(company_cost)
            """, (report_month, "fulltime", pos_name, "", work_hours, base_salary, performance,
                  position_allowance, total_salary, luxury_amount, actual_income, company_cost, company_cost, "斗米", store_id))
            fulltime_count += 1
        conn.commit()
        return 0, fulltime_count, diagnostics

    return 0, 0, diagnostics
