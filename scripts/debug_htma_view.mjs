#!/usr/bin/env node
/**
 * 调试好特卖报表 view 页面，抓取 show 请求、控制台错误、页面内容
 */
import { chromium } from 'playwright';

const URL = process.env.VIEW_URL || 'http://127.0.0.1:8085/jmreport/view/8946110000000000001';

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

  const showRequests = [];
  const errors = [];
  const consoleLogs = [];

  const page = await context.newPage();

  page.on('request', (req) => {
    const u = req.url();
    if (u.includes('/jmreport/show') || u.includes('/show?id=')) {
      showRequests.push({ url: u, method: req.method(), postData: req.postData() });
    }
  });

  page.on('response', async (res) => {
    const u = res.url();
    if (u.includes('/jmreport/show') || u.includes('/show')) {
      const status = res.status();
      let body = '';
      try {
        body = await res.text();
      } catch (_) {}
      const idx = showRequests.findIndex((r) => r.url === u);
      if (idx >= 0) showRequests[idx].status = status;
      if (body.length > 0 && body.length < 5000) {
        try {
          const j = JSON.parse(body);
          const js = j?.result?.jsonStr ? JSON.parse(j.result.jsonStr) : null;
          console.log('\n=== show response summary ===');
          console.log('status:', status);
          console.log('success:', j?.success);
          console.log('jsonStr has styles:', js?.styles != null);
          console.log('jsonStr has rows:', Object.keys(js?.rows || {}).length);
          console.log('dataList.htma_profit.list:', j?.result?.dataList?.htma_profit?.list?.length ?? 0);
        } catch (_) {}
      }
    }
  });

  page.on('console', (msg) => {
    const text = msg.text();
    const type = msg.type();
    if (type === 'error') errors.push(text);
    consoleLogs.push({ type, text });
  });

  try {
    console.log('Navigating to:', URL);
    await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(12000);

    console.log('\n=== show requests ===');
    console.log(JSON.stringify(showRequests, null, 2));

    console.log('\n=== console errors ===');
    errors.slice(0, 15).forEach((e, i) => console.log(i + 1, e));

    const state = await page.evaluate(() => {
      const sheet = document.querySelector('#jm-sheet-wrapper');
      const allText = document.body?.innerText || '';
      const sheetText = sheet?.innerText || '';
      // JimuReport 主表用 canvas 渲染，DOM 中 .cell 有部分文本；优先用 .cell 再回退 td/th
      const cellsByClass = sheet?.querySelectorAll('.cell') || [];
      const cellsByTdTh = sheet?.querySelectorAll('td, th') || [];
      const cellTexts = Array.from(cellsByClass).length > 0
        ? Array.from(cellsByClass).map((c) => c?.textContent?.trim() || '').filter(Boolean)
        : Array.from(cellsByTdTh).map((c) => c?.textContent?.trim() || '').filter(Boolean);
      const hasPagination = /共\s*\d+条/.test(allText);
      return {
        hasSheet: !!sheet,
        sheetText: sheetText.slice(0, 800),
        bodyTextLength: allText.length,
        bodyTextSample: allText.slice(0, 500),
        cellCount: Math.max(cellsByClass.length, cellsByTdTh.length),
        cellTexts: cellTexts.slice(0, 30),
        hasPagination,
        hasDate: /20\d{2}/.test(allText),
        hasCategory: allText.includes('品类') || sheetText.includes('品类'),
        hasHeader: allText.includes('日期') || sheetText.includes('日期'),
      };
    });
    console.log('\n=== page state ===');
    console.log(JSON.stringify(state, null, 2));

    if (process.env.SCREENSHOT) {
      await page.screenshot({ path: '/tmp/htma_view.png', fullPage: true });
      console.log('\nScreenshot saved to /tmp/htma_view.png');
    }

    const hasPagination = state.hasPagination || (state.bodyTextSample.includes('共') && state.bodyTextSample.includes('条'));
    const hasCellText = (state.cellTexts && state.cellTexts.length > 0) || state.cellCount > 0;
    if (!hasPagination && !hasCellText) {
      console.log('\n*** FAIL: Data not visible ***');
      process.exit(1);
    } else {
      console.log('\n*** SUCCESS: Data visible ***');
    }
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
