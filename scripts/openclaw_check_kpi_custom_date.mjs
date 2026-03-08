#!/usr/bin/env node
/**
 * OpenClaw 自动化检查：KPI 自定义周期起止日期是否可选。
 * 打开看板 → 点「筛选」展开（若有）→ 点「自定义」→ 校验 #startDate/#endDate 可见、可写、有 min/max。
 *
 * 用法：
 *   node scripts/openclaw_check_kpi_custom_date.mjs [BASE_URL]
 *   BASE_URL 默认 https://htma.greatagain.com.cn
 * 例：
 *   node scripts/openclaw_check_kpi_custom_date.mjs
 *   node scripts/openclaw_check_kpi_custom_date.mjs http://127.0.0.1:5200
 *
 * 首次运行前请安装浏览器：npx playwright install chromium
 * 或：npm run htma:check-kpi-date
 */

import { chromium } from 'playwright';

const BASE_URL = process.argv[2] || process.env.BASE_URL || 'https://htma.greatagain.com.cn';
const WAIT_LOGIN = parseInt(process.env.OPENCLAW_WAIT_LOGIN || '0', 10) || 0;

async function main() {
  const base = BASE_URL.replace(/\/$/, '');
  const url = base.startsWith('http') ? base : `https://${base}`;
  const browser = await chromium.launch({ headless: WAIT_LOGIN <= 0 });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    locale: 'zh-CN',
    ignoreHTTPSErrors: true,
    bypassCSP: true,
  });
  const page = await context.newPage();

  // 禁用缓存，确保加载最新前端
  await page.route('**/*', (route) => {
    const headers = route.request().headers();
    route.continue({ headers: { ...headers, 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' } });
  });

  let passed = true;
  let isLoginPage = false;
  const apiRequests = []; // 记录所有带日期参数的 /api/* 请求 URL
  page.on('request', (req) => {
    const u = req.url();
    if (u.includes('/api/kpi') || u.includes('/api/trend_analysis') || u.includes('/api/sales_trend') ||
        u.includes('/api/category_pie') || u.includes('/api/profit_summary') || u.includes('/api/insights')) {
      apiRequests.push(u);
    }
  });

  const log = (msg, isErr = false) => {
    console.log(isErr ? `[FAIL] ${msg}` : `[INFO] ${msg}`);
    if (isErr) passed = false;
  };

  try {
    log(`打开 ${url}（禁用缓存）`);
    await page.goto(url + (url.includes('?') ? '&' : '?') + '_=' + Date.now(), { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000);

    isLoginPage = await page.evaluate(() => {
      const body = document.body?.innerText || '';
      const hasLogin = /登录|飞书|扫码/.test(body);
      const tab = document.querySelector('#tabCustom, .period-tabs .tab-btn[data-period="custom"]');
      const tabVisible = tab && (tab.offsetParent !== null || window.getComputedStyle(tab).visibility !== 'hidden');
      return hasLogin && !tabVisible;
    });
    if (isLoginPage && WAIT_LOGIN > 0) {
      log(`等待登录（${WAIT_LOGIN}s 内出现「查询」按钮即继续）…`);
      try {
        await page.locator('#btnQuery').waitFor({ state: 'visible', timeout: WAIT_LOGIN * 1000 });
        isLoginPage = false;
        log('已进入看板，继续执行自定义日期校验');
      } catch (_) {
        log('超时未检测到看板，将仅做 API 校验');
      }
    }
    if (isLoginPage) {
      log('检测到登录页，跳过「自定义」Tab 与日期控件检查（需登录后才可见）');
      log('提示：设置 OPENCLAW_WAIT_LOGIN=60 并再次运行，可在浏览器中登录后自动继续校验');
      // 通过 API 直接校验自定义日期查询是否生效
      const origin = new URL(url).origin;
      try {
        const kpiUrl = origin + '/api/kpi?start_date=2025-03-04&end_date=2026-03-04';
        const r = await page.request.get(kpiUrl, { timeout: 10000 });
        if (!r.ok) {
          if (r.status() === 401) log('需登录后校验自定义日期 API（当前 401）');
          else log('自定义日期 API 校验失败: /api/kpi 返回 ' + r.status(), true);
        } else {
          const d = await r.json().catch(() => ({}));
          if (d.login_required || d.success === false) {
            log('需登录后校验自定义日期 API（接口返回需登录）');
          } else {
            const hasAmount = typeof d.total_sale_amount === 'number';
            const labelOk = d.period_label && (String(d.period_label).includes('2025') && String(d.period_label).includes('2026'));
            if (!hasAmount) log('自定义日期 API 返回缺少 total_sale_amount 或非数字', true);
            if (!labelOk) log('自定义日期 API 返回 period_label 未含所选区间: ' + (d.period_label || ''), true);
            if (hasAmount && labelOk) log('自定义日期 API 校验通过: period_label=' + (d.period_label || '') + ', total_sale_amount=' + d.total_sale_amount);
          }
        }
        const trendUrl = origin + '/api/trend_analysis?granularity=day&start_date=2025-03-04&end_date=2026-03-04';
        const tr = await page.request.get(trendUrl, { timeout: 10000 }).catch(() => null);
        if (tr && tr.ok()) {
          const td = await tr.json().catch(() => ({}));
          const pts = td.data_points ?? 0;
          if (pts <= 7) log('后端 trend_analysis 带 start/end 仍返回仅 ' + pts + ' 天，自定义区间未生效', true);
          else log('后端 trend_analysis 自定义区间 data_points=' + pts);
        }
      } catch (e) {
        log('自定义日期 API 请求异常: ' + e.message, true);
      }
    }

    if (!isLoginPage) {
      apiRequests.length = 0;
      const urlWithRange = url + (url.includes('?') ? '&' : '?') + 'start_date=2025-02-20&end_date=2026-03-04';
      log('通过 URL 参数加载自定义区间: ' + urlWithRange);
      await page.goto(urlWithRange, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(4000);
      const withParams = apiRequests.filter(u => {
        try {
          const q = new URL(u).searchParams;
          return q.has('start_date') && q.has('end_date');
        } catch (_) { return false; }
      });
      if (apiRequests.length > 0 && withParams.length === 0) {
        log('带 start_date/end_date 的 URL 加载后，接口请求未携带起止日期', true);
        apiRequests.slice(0, 3).forEach((u, i) => log('请求' + (i + 1) + ': ' + u.slice(0, 160) + (u.length > 160 ? '...' : ''), true));
      } else if (withParams.length > 0) {
        log('URL 参数生效: ' + withParams.length + ' 个请求携带 start_date/end_date');
      }
      if (apiRequests.length > 0) {
        const missing = apiRequests.filter(u => {
          try {
            const q = new URL(u).searchParams;
            return !q.has('start_date') || !q.has('end_date');
          } catch (_) { return true; }
        });
        if (missing.length > 0) log('以下请求缺少 start_date/end_date，自定义周期可能未生效: ' + missing.length + ' 个', true);
      }

      const filterBtn = page.locator('#btnFilterToggle');
      if (await filterBtn.count() > 0) {
        const text = await filterBtn.textContent();
        if (text && text.includes('▼')) {
          log('点击「筛选」展开');
          await filterBtn.click();
          await page.waitForTimeout(500);
        }
      }

      const customTab = page.locator('.period-tabs .tab-btn[data-period="custom"], #tabCustom').first();
      if (await customTab.count() === 0) {
        log('未找到「自定义」周期 Tab', true);
      } else {
        log('点击「自定义」');
        await customTab.click();
        await page.waitForTimeout(800);
      }

      const dateInline = page.locator('#dateRangeInline');
      await dateInline.waitFor({ state: 'visible', timeout: 3000 }).catch(() => null);
      const inlineVisible = await dateInline.isVisible();
      if (!inlineVisible) {
        log('自定义起止日期区域 #dateRangeInline 未显示', true);
      } else {
        log('#dateRangeInline 已显示');
      }

      const startDate = page.locator('#startDate');
      const endDate = page.locator('#endDate');
      if (await startDate.count() === 0) log('#startDate 不存在', true);
      if (await endDate.count() === 0) log('#endDate 不存在', true);

      if (await startDate.count() > 0) {
        const disabled = await startDate.getAttribute('disabled');
        const readonly = await startDate.getAttribute('readonly');
        const min = await startDate.getAttribute('min');
        const max = await startDate.getAttribute('max');
        if (disabled) log('起始日期 #startDate 为 disabled', true);
        if (readonly) log('起始日期 #startDate 为 readonly', true);
        if (!min) log('起始日期 #startDate 缺少 min 属性（请检查 /api/date_range）', true);
        if (!max) log('起始日期 #startDate 缺少 max 属性', true);
        if (!disabled && !readonly && min && max) log(`起始日期 可选，min=${min} max=${max}`);
      }
      if (await endDate.count() > 0) {
        const disabled = await endDate.getAttribute('disabled');
        const readonly = await endDate.getAttribute('readonly');
        const min = await endDate.getAttribute('min');
        const max = await endDate.getAttribute('max');
        if (disabled) log('结束日期 #endDate 为 disabled', true);
        if (readonly) log('结束日期 #endDate 为 readonly', true);
        if (!min || !max) log('结束日期 #endDate 缺少 min/max', true);
        if (!disabled && !readonly && min && max) log(`结束日期 可选，min=${min} max=${max}`);
      }

      const queryBtn = page.locator('#btnQuery');
      if (await queryBtn.count() === 0) log('未找到「查询」按钮', true);

      const dateRangeApi = await page.evaluate(async (origin) => {
        try {
          const r = await fetch(origin + '/api/date_range', { credentials: 'include' });
          if (!r.ok) return null;
          return await r.json();
        } catch (e) {
          return null;
        }
      }, new URL(url).origin);
      const minDate = dateRangeApi?.min_date || '2010-01-01';
      const maxDate = dateRangeApi?.max_date || '2030-12-31';
      const startVal = '2025-03-04';
      const endVal = '2026-03-04';

      log(`填写起止日期并点击「查询」: ${startVal} ~ ${endVal}`);
      await startDate.fill(startVal).catch(() => null);
      await page.waitForTimeout(200);
      await endDate.fill(endVal).catch(() => null);
      await page.waitForTimeout(200);
      await startDate.dispatchEvent('input');
      await endDate.dispatchEvent('input');
      await page.waitForTimeout(300);
      apiRequests.length = 0;
      await queryBtn.click();
      await page.waitForTimeout(3500);

      const hasCustomInRequests = apiRequests.some((u) => {
        try {
          const q = new URL(u).searchParams;
          return q.has('start_date') && q.has('end_date');
        } catch (_) {
          return false;
        }
      });
      if (apiRequests.length > 0 && !hasCustomInRequests) {
        log('查询触发的接口请求未携带 start_date/end_date，自定义区间未生效', true);
        log('示例请求: ' + (apiRequests[0] || '').slice(0, 120) + '...');
      } else if (apiRequests.length > 0) {
        log('接口请求已携带自定义起止日期');
      }

      const summaryText = await page.locator('#filterPeriodSummary').textContent().catch(() => '');
      const kpiSaleText = await page.locator('#kpiSale').textContent().catch(() => '');
      const hasRangeInSummary = summaryText && (summaryText.includes('2025') && summaryText.includes('2026'));
      const hasData = kpiSaleText && kpiSaleText.trim() !== '' && kpiSaleText.trim() !== '-';
      if (!hasRangeInSummary) {
        log('查询后周期摘要未包含所选起止日期: ' + (summaryText || '(空)'), true);
      } else {
        log('周期摘要已更新: ' + (summaryText || '').trim());
      }
      if (!hasData) {
        log('KPI 销售额未刷新（仍为 - 或空），可能接口未按自定义日期返回', true);
      } else {
        log('KPI 已刷新，销售额: ' + kpiSaleText.trim());
      }

      const origin = new URL(url).origin;
      const kpiCheck = await page.evaluate(async ({ origin, startVal, endVal }) => {
        try {
          const r = await fetch(origin + '/api/kpi?period=custom&start_date=' + encodeURIComponent(startVal) + '&end_date=' + encodeURIComponent(endVal), { credentials: 'include' });
          if (!r.ok) return { ok: false, status: r.status };
          const d = await r.json();
          const label = (d.period_label || '').toString();
          const hasRange = label.indexOf(startVal) !== -1 && label.indexOf(endVal) !== -1;
          return { ok: true, period_label: label, hasRange, total_sale: d.total_sale_amount };
        } catch (e) {
          return { ok: false, err: e.message };
        }
      }, { origin, startVal: '2025-03-04', endVal: '2026-03-04' });
      if (kpiCheck.ok) {
        if (!kpiCheck.hasRange) log('KPI 接口 period_label 未包含所选起止日期: ' + (kpiCheck.period_label || '(空)'), true);
        else log('KPI 接口 period_label 正确: ' + (kpiCheck.period_label || ''));
      } else {
        log('KPI 接口校验失败: ' + (kpiCheck.err || 'status ' + kpiCheck.status), true);
      }
      const trendCheck = await page.evaluate(async ({ origin, startVal, endVal }) => {
        try {
          const r = await fetch(origin + '/api/trend_analysis?granularity=day&start_date=' + encodeURIComponent(startVal) + '&end_date=' + encodeURIComponent(endVal), { credentials: 'include' });
          if (!r.ok) return { ok: false, status: r.status };
          const d = await r.json();
          const points = d.data_points ?? 0;
          const latest = (d.trend_summary && d.trend_summary.latest_date) || '';
          const inRange = latest && latest <= endVal && latest >= startVal;
          return { ok: true, data_points: points, latest_date: latest, inRange, tooFew: points <= 7 };
        } catch (e) {
          return { ok: false, err: e.message };
        }
      }, { origin, startVal: '2025-03-04', endVal: '2026-03-04' });
      if (trendCheck.ok) {
        if (trendCheck.tooFew) log('走势接口返回仅 ' + trendCheck.data_points + ' 天数据，自定义区间未生效（应为整年）', true);
        else log('走势接口 data_points=' + trendCheck.data_points + ', latest_date=' + trendCheck.latest_date);
        if (trendCheck.latest_date && !trendCheck.inRange) log('周期内最近一日 ' + trendCheck.latest_date + ' 超出所选区间', true);
      } else {
        log('走势接口校验失败: ' + (trendCheck.err || 'status ' + trendCheck.status), true);
      }
    }

    const dateRangeOk = await page.evaluate(async (origin) => {
      try {
        const r = await fetch(origin + '/api/date_range', { credentials: 'include' });
        if (!r.ok) return { ok: false };
        const d = await r.json();
        return { ok: true, min_date: d.min_date, max_date: d.max_date };
      } catch (e) {
        return { ok: false };
      }
    }, new URL(url).origin);
    if (dateRangeOk.ok && dateRangeOk.min_date && dateRangeOk.max_date) {
      log(`/api/date_range 正常: min_date=${dateRangeOk.min_date} max_date=${dateRangeOk.max_date}`);
    } else {
      log('/api/date_range 请求失败或返回缺少 min_date/max_date', true);
    }
  } catch (e) {
    log(`执行异常: ${e.message}`, true);
  } finally {
    await browser.close();
  }

  if (passed) {
    if (isLoginPage) {
      console.log('\n[OK] /api/date_range 正常。生产环境需登录后在浏览器中验证「自定义」日期是否可选。');
    } else {
      console.log('\n[OK] KPI 自定义时间起点检查通过');
    }
    process.exit(0);
  } else {
    console.log('\n[FAIL] 存在问题。请：① 重新部署看板（确保 htma_dashboard/static/index.html 已更新）；② 确认 /api/date_range 接口返回 min_date/max_date');
    process.exit(1);
  }
}

main();
