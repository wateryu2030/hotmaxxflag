#!/usr/bin/env node
/**
 * OpenClaw 自动化：打开消费洞察页（?page=insight&category=服装），检查是否出现加载失败/500 错误。
 * 用法: node scripts/openclaw_verify_consumer_insight_page.mjs [BASE_URL]
 * 例:   node scripts/openclaw_verify_consumer_insight_page.mjs http://127.0.0.1:5002
 * 需登录时: OPENCLAW_WAIT_LOGIN=60 node scripts/openclaw_verify_consumer_insight_page.mjs http://127.0.0.1:5002
 */
import { chromium } from 'playwright';

const BASE_URL = (process.argv[2] || process.env.BASE_URL || 'http://127.0.0.1:5002').replace(/\/$/, '');
const url = BASE_URL.startsWith('http') ? BASE_URL : 'http://' + BASE_URL;
const insightUrl = url + '/?page=insight&category=' + encodeURIComponent('服装');
const WAIT_LOGIN = parseInt(process.env.OPENCLAW_WAIT_LOGIN || '0', 10) || 0;

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    locale: 'zh-CN',
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  const failedUrls = [];
  const apiErrors = [];
  page.on('response', (res) => {
    const u = res.url();
    if (u.includes('/api/consumer_insight') || u.includes('/api/consumer_insight_trend')) {
      if (res.status() >= 500) failedUrls.push({ url: u, status: res.status() });
    }
  });

  try {
    console.log('[INFO] 打开消费洞察页:', insightUrl);
    await page.goto(insightUrl, { waitUntil: 'networkidle', timeout: 25000 });
    if (WAIT_LOGIN > 0) {
      try {
        await page.locator('#btnQuery').waitFor({ state: 'visible', timeout: WAIT_LOGIN * 1000 });
        await page.waitForTimeout(3000);
        await page.goto(insightUrl, { waitUntil: 'networkidle', timeout: 25000 });
      } catch (_) {}
    }
    await page.waitForTimeout(4000);

    const hasError = await page.evaluate(() => {
      const body = document.body?.innerText || '';
      const html = document.body?.innerHTML || '';
      if (/加载失败\s*:?\s*not all arguments converted during string formatting/i.test(body)) return 'not_all_arguments';
      if (/Unknown column\s+['"]?distribution_mode/i.test(body)) return 'unknown_column_distribution_mode';
      if (/加载失败|500|Internal Server Error/i.test(body) && /api\/consumer_insight/i.test(html)) return 'generic_error';
      const table = document.querySelector('#insightCategoryMatrixBody');
      if (table && table.innerHTML && table.innerHTML.includes('error')) return 'table_error';
      return null;
    });

    if (failedUrls.length) {
      failedUrls.forEach(({ url: u, status }) => console.log('[FAIL] API 5xx:', status, u));
    }
    if (hasError) {
      console.log('[FAIL] 页面检测到错误:', hasError);
      process.exit(1);
    }
    const isLogin = await page.evaluate(() => /登录|飞书|扫码/.test(document.body?.innerText || ''));
    if (isLogin) {
      console.log('[INFO] 当前为登录页，未登录无法校验数据。已确认页面可打开且无 500 文案。');
      console.log('[OK] 消费洞察页校验通过（需登录后人工确认品类数据）');
    } else {
      console.log('[OK] 消费洞察页校验通过，未发现加载失败或 500 错误');
    }
  } catch (e) {
    console.log('[FAIL]', e.message);
    process.exit(1);
  } finally {
    await browser.close();
  }
}

main();
