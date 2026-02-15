#!/usr/bin/env node
/**
 * JimuReport 报表自动设计：登录 → 进入报表列表 → 新建报表并打开设计器。
 * 运行前确保 JimuReport 已启动（http://127.0.0.1:8085）
 * 执行：npx playwright install chromium && node scripts/jimureport_auto_design.mjs
 */

import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8085';
const USERNAME = 'admin';
const PASSWORD = '123456';
const REPORT_LIST_URL = `${BASE_URL}/jmreport/list`;

async function main() {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 1400, height: 900 },
    locale: 'zh-CN',
  });
  const page = await context.newPage();

  try {
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(1500);

    const userInput = page.getByPlaceholder('用户名').or(page.getByPlaceholder('请输入用户名')).first();
    await userInput.fill(USERNAME);
    const pwdInput = page.getByPlaceholder('密码').or(page.getByPlaceholder('请输入密码')).first();
    await pwdInput.fill(PASSWORD);
    await page.getByRole('button', { name: /登\s*录/ }).or(page.getByText('登录').first()).click();
    await page.waitForTimeout(2000);

    await page.goto(REPORT_LIST_URL, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(2000);

    const newBtn = page.getByText('新增').or(page.getByText('新建')).or(page.getByText('新建报表')).first();
    if (await newBtn.count() > 0) {
      await newBtn.click();
      await page.waitForTimeout(2000);
    }

    const modalInput = page.getByPlaceholder('报表名称').or(page.locator('input[placeholder*="名称"]')).first();
    if (await modalInput.count() > 0) {
      await modalInput.fill('好特卖销售明细');
      await page.getByRole('button', { name: '确定' }).or(page.getByText('确定').first()).click();
      await page.waitForTimeout(2000);
    }

    await page.waitForTimeout(3000);
    console.log('已打开报表设计器。请按提示完成绑定：');
    console.log('  (1) 左侧「数据集管理」确认 htma_sale');
    console.log('  (2) 第1行 A1~D1: 日期、品类、销售额、毛利');
    console.log('  (3) 第2行设为数据行，绑定 htma_sale；A2~D2 绑定 data_date, category, total_sale, total_profit');
    console.log('  (4) 预览 → 保存');
    console.log('浏览器将保持打开，完成后请手动关闭。');
    await page.waitForTimeout(60000);
  } catch (e) {
    console.error('执行出错:', e.message);
  } finally {
    await browser.close();
  }
}

main();
