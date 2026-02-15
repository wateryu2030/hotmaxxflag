#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JimuReport 报表自动设计脚本：登录 → 打开报表设计 → 引导到可绑定数据的状态。
运行前请确保 JimuReport 已启动（如 mvn spring-boot:run），且本机可访问 http://127.0.0.1:8085

使用：
  pip install playwright
  playwright install chromium
  python scripts/jimureport_auto_design.py
"""

import time
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("请先安装: pip install playwright && playwright install chromium")
    sys.exit(1)

BASE_URL = "http://127.0.0.1:8085"
USERNAME = "admin"
PASSWORD = "123456"
REPORT_LIST_URL = f"{BASE_URL}/jmreport/list"
# 报表设计器入口（新建后或从列表点“设计”会进这里）
DESIGN_PATH = "/jmreport/desreport"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()

        try:
            # 1. 打开首页并登录
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(1.5)

            # 登录表单（常见 placeholder 或 input name）
            user_input = page.get_by_placeholder("用户名").or_(page.get_by_placeholder("请输入用户名")).first
            if user_input.count() == 0:
                user_input = page.locator('input[name="username"], input[id*="user"]').first
            user_input.fill(USERNAME)

            pwd_input = page.get_by_placeholder("密码").or_(page.get_by_placeholder("请输入密码")).first
            if pwd_input.count() == 0:
                pwd_input = page.locator('input[name="password"], input[type="password"]').first
            pwd_input.fill(PASSWORD)

            page.get_by_role("button", name="登 录").or_(page.get_by_text("登录").first).click()
            time.sleep(2)

            # 2. 进入报表列表
            page.goto(REPORT_LIST_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)

            # 3. 点击「新增」或「新建报表」
            new_btn = (
                page.get_by_text("新增")
                .or_(page.get_by_text("新建"))
                .or_(page.get_by_text("新建报表"))
                .first
            )
            if new_btn.count() > 0:
                new_btn.click()
                time.sleep(2)
            else:
                print("未找到「新增/新建」按钮，请在此页面手动点击新建报表。")
                input("按回车继续关闭浏览器...")
                browser.close()
                return

            # 4. 若有弹窗（报表名称），可输入名称后确定
            modal_input = page.get_by_placeholder("报表名称").or_(page.locator('input[placeholder*="名称"]')).first
            if modal_input.count() > 0:
                modal_input.fill("好特卖销售明细")
                page.get_by_role("button", name="确定").or_(page.get_by_text("确定").first).click()
                time.sleep(2)

            # 5. 等待设计器加载（通常会有 iframe 或 canvas）
            time.sleep(3)
            print("已打开报表设计器。请按下面步骤手动完成绑定（约 1 分钟）：")
            print("  (1) 左侧「数据集管理」中确认有 htma_sale，若无则添加 SQL 数据集。")
            print("  (2) 第 1 行 A1~D1 输入：日期、品类、销售额、毛利。")
            print("  (3) 第 2 行设为数据行，绑定数据集 htma_sale；A2~D2 分别绑定 data_date, category, total_sale, total_profit。")
            print("  (4) 点击「预览」查看数据，再点「保存」。")
            input("完成后按回车关闭浏览器...")

        except Exception as e:
            print(f"执行出错: {e}")
            input("按回车关闭浏览器...")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
