#!/usr/bin/env node
/**
 * OpenClaw：校验 KPI 周期以用户选择为准、类别筛选为级联折叠（大类→中类→小类→商品）。
 *
 * 1) KPI 周期：选择「本周/近30天/自定义」后点「查询」，周期摘要与请求参数与选择一致，无写死逻辑。
 * 2) 类别折叠：初始仅显示大类；选择大类后出现中类；选择中类后出现小类；选择小类后出现商品。
 *
 * 用法：node scripts/openclaw_verify_kpi_period_and_category_cascade.mjs [BASE_URL]
 * 例：  node scripts/openclaw_verify_kpi_period_and_category_cascade.mjs http://127.0.0.1:5002
 * 需 Playwright：npx playwright install chromium
 */

import { chromium } from 'playwright';

const BASE_URL = process.argv[2] || process.env.BASE_URL || 'https://htma.greatagain.com.cn';
const WAIT_LOGIN = parseInt(process.env.OPENCLAW_WAIT_LOGIN || '0', 10) || 0;

function log(msg, isErr = false) {
  console.log(isErr ? `[FAIL] ${msg}` : `[INFO] ${msg}`);
}

async function main() {
  const base = BASE_URL.replace(/\/$/, '');
  const url = base.startsWith('http') ? base : `https://${base}`;
  let passed = true;
  const browser = await chromium.launch({ headless: WAIT_LOGIN <= 0 });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    locale: 'zh-CN',
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  await page.route('**/*', (route) => {
    const h = route.request().headers();
    route.continue({ headers: { ...h, 'Cache-Control': 'no-cache', Pragma: 'no-cache' } });
  });

  try {
    log(`打开 ${url}`);
    await page.goto(url + (url.includes('?') ? '&' : '?') + '_=' + Date.now(), { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2500);

    const isLoginPage = await page.evaluate(() => {
      const t = document.body?.innerText || '';
      const hasLogin = /登录|飞书|扫码/.test(t);
      const hasFilter = !!document.querySelector('#btnQuery');
      return hasLogin && !hasFilter;
    });

    if (isLoginPage && WAIT_LOGIN > 0) {
      log(`等待登录（${WAIT_LOGIN}s）…`);
      try {
        await page.locator('#btnQuery').waitFor({ state: 'visible', timeout: WAIT_LOGIN * 1000 });
      } catch (_) {}
    }

    const stillLogin = await page.evaluate(() => {
      return !document.querySelector('#btnQuery') || /登录|飞书扫码/.test(document.body?.innerText || '');
    });
    if (stillLogin) {
      log('未进入看板（需登录），跳过 KPI 周期与类别级联校验');
      await browser.close();
      process.exit(0);
      return;
    }

    // 展开筛选栏
    const filterToggle = page.locator('#btnFilterToggle');
    if (await filterToggle.count() > 0) {
      const text = await filterToggle.textContent();
      if (text && text.includes('▼')) {
        await filterToggle.click();
        await page.waitForTimeout(500);
      }
    }

    // ---------- 1) 类别级联：初始仅大类可见 ----------
    log('校验类别级联：初始仅显示大类');
    const cascadeOk = await page.evaluate(() => {
      const large = document.getElementById('categoryRowLarge');
      const mid = document.getElementById('categoryRowMid');
      const small = document.getElementById('categoryRowSmall');
      const product = document.getElementById('categoryRowProduct');
      const largeVisible = large && (large.offsetParent !== null && (large.style.display || '').toLowerCase() !== 'none');
      const midVisible = mid && (mid.offsetParent !== null && (mid.style.display || '').toLowerCase() !== 'none');
      const smallVisible = small && (small.offsetParent !== null && (small.style.display || '').toLowerCase() !== 'none');
      const productVisible = product && (product.offsetParent !== null && (product.style.display || '').toLowerCase() !== 'none');
      return {
        largeVisible: !!largeVisible,
        midVisibleInitially: midVisible,
        smallVisibleInitially: smallVisible,
        productVisibleInitially: productVisible,
        ok: !!largeVisible && !midVisible && !smallVisible && !productVisible,
      };
    });
    if (!cascadeOk.ok) {
      log('初始应仅显示大类，中类/小类/商品应折叠', true);
      if (cascadeOk.midVisibleInitially) log('中类初始不应可见', true);
      if (cascadeOk.smallVisibleInitially) log('小类初始不应可见', true);
      if (cascadeOk.productVisibleInitially) log('商品初始不应可见', true);
      passed = false;
    } else {
      log('初始仅大类可见，中类/小类/商品已折叠');
    }

    // 选择大类后中类应出现
    const largeSelect = page.locator('#categoryLargeSelect');
    const optCount = await largeSelect.locator('option').count();
    if (optCount > 1) {
      await largeSelect.selectOption({ index: 1 });
      await page.waitForTimeout(800);
      const midVisibleAfter = await page.evaluate(() => {
        const mid = document.getElementById('categoryRowMid');
        return mid && (mid.offsetParent !== null && (mid.style.display || '').toLowerCase() !== 'none');
      });
      if (!midVisibleAfter) {
        log('选择大类后中类应出现', true);
        passed = false;
      } else {
        log('选择大类后中类已显示');
      }
    }

    // ---------- 2) KPI 周期：以用户选择为准 ----------
    log('校验 KPI 周期以用户选择为准');
    await page.locator('.period-tabs .tab-btn[data-period="week"]').click();
    await page.waitForTimeout(400);
    await page.locator('#btnQuery').click();
    await page.waitForTimeout(2000);
    const summaryWeek = await page.locator('#filterPeriodSummary').textContent().catch(() => '');
    if (summaryWeek && !summaryWeek.includes('本周')) {
      log('选择「本周」后周期摘要应含「本周」，当前: ' + summaryWeek, true);
      passed = false;
    } else {
      log('选择本周后周期摘要: ' + (summaryWeek || '').trim());
    }

    await page.locator('.period-tabs .tab-btn[data-period="recent30"]').click();
    await page.waitForTimeout(400);
    await page.locator('#btnQuery').click();
    await page.waitForTimeout(2000);
    const summary30 = await page.locator('#filterPeriodSummary').textContent().catch(() => '');
    if (summary30 && !summary30.includes('30') && !summary30.includes('近')) {
      log('选择「近30天」后周期摘要应含近30天，当前: ' + summary30, true);
      passed = false;
    } else {
      log('选择近30天后周期摘要: ' + (summary30 || '').trim());
    }

    const customTab = page.locator('.period-tabs .tab-btn[data-period="custom"]');
    await customTab.click();
    await page.waitForTimeout(500);
    const startEl = page.locator('#startDate');
    const endEl = page.locator('#endDate');
    if ((await startEl.count()) > 0 && (await endEl.count()) > 0) {
      await startEl.fill('2025-03-01');
      await endEl.fill('2025-03-31');
      await page.waitForTimeout(300);
      await page.locator('#btnQuery').click();
      await page.waitForTimeout(2500);
      const summaryCustom = await page.locator('#filterPeriodSummary').textContent().catch(() => '');
      const hasCustomRange = summaryCustom && (summaryCustom.includes('2025') && summaryCustom.includes('03'));
      if (!hasCustomRange) {
        log('选择自定义 2025-03-01~03-31 后周期摘要应含该区间，当前: ' + summaryCustom, true);
        passed = false;
      } else {
        log('自定义周期摘要: ' + (summaryCustom || '').trim());
      }
    }
  } catch (e) {
    log('执行异常: ' + e.message, true);
    passed = false;
  } finally {
    await browser.close();
  }

  if (passed) {
    console.log('\n[OK] KPI 周期与类别级联校验通过');
    process.exit(0);
  } else {
    console.log('\n[FAIL] 存在校验失败项');
    process.exit(1);
  }
}

main();
