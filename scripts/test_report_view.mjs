#!/usr/bin/env node
/**
 * 无痕模式测试报表预览页
 * 运行前确保 JimuReport 已启动（http://127.0.0.1:8085）
 * 执行：node scripts/test_report_view.mjs
 *
 * 报表 ID：1350035590569136128（简单明细表，内置可用）
 * 8946110000000000001 有好特卖数据但需在设计中完善 cellTextJson 配置
 */

import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8085';
const REPORT_ID = process.env.VIEW_REPORT_ID || '1350035590569136128';
const VIEW_URL = `${BASE}/jmreport/view/${REPORT_ID}`;

async function main() {
  const browser = await chromium.launch({
    headless: true,
    channel: 'chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const context = await browser.newContext({
    viewport: { width: 1200, height: 800 },
    locale: 'zh-CN',
    ignoreHTTPSErrors: true,
  });

  const consoleLogs = [];
  const errors = [];

  const page = await context.newPage();

  page.on('console', (msg) => {
    const text = msg.text();
    const type = msg.type();
    if (type === 'error') {
      errors.push(text);
    }
    consoleLogs.push({ type, text });
  });

  page.on('requestfailed', (req) => {
    errors.push(`Request failed: ${req.url()} - ${req.failure()?.errorText || 'unknown'}`);
  });

  try {
    console.log('Navigating to:', VIEW_URL);
    await page.goto(VIEW_URL, { waitUntil: 'networkidle', timeout: 30000 });

    await page.waitForTimeout(8000);

    const html = await page.content();
    const baseFullMatch = html.match(/baseFull\s*=\s*['"]([^'"]*)['"]/);
    const baseFullVal = baseFullMatch ? baseFullMatch[1].trim() : '';
    console.log('\n=== baseFull in HTML:', baseFullVal || 'NOT FOUND');

    const hasData = await page.evaluate(() => {
      const sheet = document.querySelector('#jm-sheet-wrapper');
      if (!sheet) return { hasSheet: false };
      const bodyText = document.body?.innerText || '';
      const sheetText = sheet.innerText || '';
      const text = sheetText || bodyText;
      const cellsByClass = sheet.querySelectorAll('.cell');
      const cellsByTdTh = sheet.querySelectorAll('td, th');
      const cellTexts = cellsByClass.length > 0
        ? Array.from(cellsByClass).map((c) => c?.textContent?.trim() || '').filter(Boolean)
        : Array.from(cellsByTdTh).map((c) => c?.textContent?.trim() || '').filter(Boolean);
      const hasPagination = /共\s*\d+条/.test(bodyText);
      return {
        hasSheet: true,
        cellCount: Math.max(cellsByClass.length, cellsByTdTh.length),
        cellTextsCount: cellTexts.length,
        hasText: text.length > 50,
        hasDate: /20\d{2}/.test(text),
        hasPagination,
        hasData:
          hasPagination ||
          text.includes('品类') ||
          text.includes('总销售额') ||
          text.includes('员工') ||
          text.includes('姓名') ||
          text.includes('所在部门') ||
          cellTexts.length > 5 ||
          text.length > 50,
      };
    });
    console.log('\n=== Page state:', JSON.stringify(hasData, null, 2));

    const networkErrors = errors.filter((e) => e.includes('undefined') || e.includes('404'));
    console.log('\n=== Critical errors:', networkErrors.length ? networkErrors : 'none');

    const baseOk = baseFullVal && baseFullVal.length > 5 && !baseFullVal.includes('undefined');
    if (hasData.hasSheet && baseOk && networkErrors.length === 0) {
      console.log('\n*** SUCCESS: Report page loaded, baseFull OK, no critical errors ***');
    } else if (hasData.hasSheet && hasData.hasData) {
      console.log('\n*** SUCCESS: Report data appears to be loading ***');
    } else {
      console.log('\n*** FAIL: Report may not be loading correctly ***');
      console.log('Sample console errors:', errors.slice(0, 5));
    }
  } catch (e) {
    console.error('Test failed:', e.message);
  } finally {
    await browser.close();
  }
}

main();
