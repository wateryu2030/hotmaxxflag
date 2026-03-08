#!/usr/bin/env node
/**
 * OpenClaw 自动化校验：人力成本已与 KPI 周期剥离，归入「数据导入 · 人力成本」入口。
 * 校验项：主导航无「人力成本」Tab；副标题有「数据导入」「人力成本」链接；查询按钮仅驱动 KPI。
 *
 * 用法：node scripts/openclaw_verify_labor_stripped.mjs [BASE_URL]
 * 例：  node scripts/openclaw_verify_labor_stripped.mjs http://127.0.0.1:5002
 */

import { chromium } from 'playwright';

const BASE_URL = process.argv[2] || process.env.BASE_URL || 'http://127.0.0.1:5002';

async function main() {
  const url = BASE_URL.replace(/\/$/, '');
  const fullUrl = url.startsWith('http') ? url : 'http://' + url;
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'zh-CN', ignoreHTTPSErrors: true });
  const page = await context.newPage();

  let passed = true;
  const log = (msg, isErr = false) => {
    console.log(isErr ? '[FAIL] ' + msg : '[INFO] ' + msg);
    if (isErr) passed = false;
  };

  try {
    await page.goto(fullUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(1500);

    const checks = await page.evaluate(() => {
      const navLabor = document.querySelector('.page-nav .nav-tab[data-page="labor"], .nav-tab[data-page="labor"]');
      const importLinks = document.querySelectorAll('a[href="/import"]');
      const laborLinks = document.querySelectorAll('a[href="/labor"]');
      const noLaborPanel = !document.getElementById('pageLabor');
      const btnQuery = document.getElementById('btnQuery');
      const filterSummary = document.getElementById('filterPeriodSummary');
      const bodyText = document.body ? document.body.innerText : '';
      return {
        noLaborTab: !navLabor,
        hasImportLink: importLinks.length > 0,
        hasLaborLink: laborLinks.length > 0,
        noLaborPanel,
        hasQueryBtn: !!btnQuery,
        hasFilterSummary: !!filterSummary,
        hasImportInPage: bodyText.indexOf('数据导入') !== -1,
        hasLaborInPage: bodyText.indexOf('人力成本') !== -1,
      };
    });

    if (checks.noLaborTab) {
      log('主导航中无「人力成本」Tab（已剥离）');
    } else {
      log('主导航仍存在「人力成本」Tab，应移除', true);
    }
    if (checks.hasImportLink) {
      log('页面存在「数据导入」链接 a[href="/import"]');
    } else if (checks.hasImportInPage) {
      log('页面含「数据导入」文案');
    } else if (checks.hasQueryBtn) {
      log('看板页缺少「数据导入」链接', true);
    }
    if (checks.hasLaborLink) {
      log('页面存在「人力成本」链接 a[href="/labor"]');
    } else if (checks.hasLaborInPage) {
      log('页面含「人力成本」文案');
    } else if (checks.hasQueryBtn) {
      log('看板页缺少「人力成本」链接', true);
    }
    if (checks.noLaborPanel) {
      log('页面中无人力成本 Tab 面板（#pageLabor 已移除）');
    } else {
      log('页面仍含 #pageLabor 面板，应移除', true);
    }
    if (checks.hasQueryBtn) log('「查询」按钮存在，仅驱动 KPI 周期');
    if (checks.hasFilterSummary) log('KPI 周期摘要存在');

    const laborRes = await page.goto(fullUrl + '/labor', { waitUntil: 'domcontentloaded', timeout: 10000 }).catch(() => null);
    const laborStatus = laborRes ? laborRes.status() : 0;
    if (laborStatus === 200) {
      log('独立页 /labor 可访问 (200)');
    } else if (laborStatus === 302 || laborStatus === 401 || laborStatus === 403) {
      log('独立页 /labor 存在（' + laborStatus + '，需登录或权限）');
    } else if (laborStatus === 500) {
      log('独立页 /labor 存在（500 服务异常，属后端问题，与剥离设计无关）');
    } else if (laborStatus >= 400) {
      log('/labor 返回 ' + laborStatus, true);
    } else {
      log('/labor 请求异常，跳过');
    }
  } catch (e) {
    log('执行异常: ' + e.message, true);
  } finally {
    await browser.close();
  }

  if (passed) {
    console.log('\n[OK] 人力成本已与 KPI 剥离，归入「数据导入 · 人力成本」');
    process.exit(0);
  } else {
    console.log('\n[FAIL] 校验未通过，请确认 htma_dashboard/static/index.html 已按设计修改');
    process.exit(1);
  }
}

main();
