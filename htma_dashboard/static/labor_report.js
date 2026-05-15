const STORE = encodeURIComponent("沈阳超级仓");
let overviewData = null, personData = null, catData = null;
let shareEnabled = false;
// Chart.js 实例缓存
let chartTrend = null, chartRatio = null, chartType = null, chartCatLabor = null, chartCostStructure = null;
// 排序状态：{ col:'key', asc:true } per table
let sortState = { cat: {col:'sale', asc:false}, ps: {col:'total_cost', asc:false}, oa: {col:'total_cost', asc:false} };

// ── Tab 切换 ──
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// ── 通用排序逻辑 ──
function getVal(row, key) {
  if (key === 'person_name') return (row.person_name || '').toLowerCase();
  if (key === 'labor_cost') return row.labor_cost_direct || 0;
  if (key === 'labor_cost_shared') return row.labor_cost_shared || 0;
  if (key === 'labor_cost_total') return row.labor_cost || 0;
  if (key === 'labor_cost_per_profit') return row.labor_cost_per_profit !== null ? row.labor_cost_per_profit : -Infinity;
  if (key === 'margin_pct') return row.margin_pct || 0;
  if (key === 'profit_per_cost') return row.profit_per_cost !== null ? row.profit_per_cost : -Infinity;
  if (key === 'sale') return row.sale || 0;
  if (key === 'profit') return row.profit || 0;
  if (key === 'cost_sale_ratio') return row.cost_sale_ratio !== null ? row.cost_sale_ratio : -Infinity;
  if (key === 'cost_profit_ratio') return row.cost_profit_ratio !== null ? row.cost_profit_ratio : -Infinity;
  return row[key] || 0;
}
function updateSortIcon(table, col) {
  const st = sortState[table];
  document.querySelectorAll(`#${table === 'cat' ? 'cat' : table === 'ps' ? 'ps' : 'oa'}-sort-`).forEach(el => {});
  if (st.col === col) {
    const icon = document.getElementById(`${table === 'cat' ? 'cat' : table === 'ps' ? 'ps' : 'oa'}-sort-${col}`);
    if (icon) icon.textContent = st.asc ? '▲' : '▼';
  }
}
function doSort(data, table) {
  const st = sortState[table];
  const col = st.col;
  data.sort((a, b) => {
    const va = getVal(a, col), vb = getVal(b, col);
    if (typeof va === 'string' && typeof vb === 'string') return st.asc ? va.localeCompare(vb) : vb.localeCompare(va);
    return st.asc ? (va - vb) : (vb - va);
  });
  // update icons
  document.querySelectorAll(`#${table === 'cat' ? 'cat' : table === 'ps' ? 'ps' : 'oa'}-sort-`).forEach(()=>{});
  // reset all icons in this table
  const prefix = table === 'cat' ? 'cat' : table === 'ps' ? 'ps' : 'oa';
  document.querySelectorAll(`[id^="${prefix}-sort-"]`).forEach(el => el.textContent = '↕');
  const icon = document.getElementById(`${prefix}-sort-${col}`);
  if (icon) icon.textContent = st.asc ? '▲' : '▼';
}
function sortCatTable(col) {
  const st = sortState.cat;
  if (st.col === col) st.asc = !st.asc; else { st.col = col; st.asc = false; }
  if (catData) renderCatTable();
}
function sortPsTable(col) {
  const st = sortState.ps;
  if (st.col === col) st.asc = !st.asc; else { st.col = col; st.asc = false; }
  filterPersons();
}
function sortOverallTable(col) {
  const st = sortState.oa;
  if (st.col === col) st.asc = !st.asc; else { st.col = col; st.asc = false; }
  if (overallData) renderOverallTable();
}
let overallData = null;

// ── 分摊切换 ──
function toggleShare() {
  shareEnabled = !shareEnabled;
  document.getElementById("share-toggle").classList.toggle("active", shareEnabled);
  document.getElementById("share-toggle").textContent = shareEnabled ? "✅ 分摊已开启" : "🔀 分摊通用岗成本";
  document.getElementById("share-hint").textContent = shareEnabled ? "通用岗按销售占比已分摊到各品类" : "关闭：仅显示经营岗直接成本";
  loadCategory();
}

// ── 总体看板 ──
async function loadOverview() {
  try {
    const r = await fetch(`/api/labor_report/overview?store_id=${STORE}`);
    const j = await r.json();
    if (!j.success) throw new Error("请求失败");
    overviewData = j;
    const last = j.data[j.data.length - 1];
    document.getElementById("overview-kpis").innerHTML = `
      <div class="kpi-card purple"><div class="label">📅 最新月份</div><div class="value">${last.month}</div></div>
      <div class="kpi-card orange"><div class="label">💰 人工总成本</div><div class="value">${last.total_cost.toLocaleString()}</div><div class="sub">经营 ${last.direct_cost} / 通用 ${last.shared_cost} / 管理 ${last.management_cost}</div></div>
      <div class="kpi-card blue"><div class="label">👤 在岗人数</div><div class="value">${last.total_headcount}</div><div class="sub">经营 ${last.direct_headcount} / 通用 ${last.shared_headcount} / 管理 ${last.management_headcount}</div></div>
      <div class="kpi-card green"><div class="label">📈 人工占销售</div><div class="value">${last.labor_sale_ratio}%</div><div class="sub">人工占毛利 ${last.labor_profit_ratio}%</div></div>
      <div class="kpi-card red"><div class="label">📊 每元成本毛利</div><div class="value">${last.profit_per_cost}</div><div class="sub">人均销售 ${Math.round(last.sale_per_capita).toLocaleString()}</div></div>
    `;

    if (typeof Chart === 'undefined') { console.warn('Chart.js not loaded, skipping charts'); return; }
    const months = j.data.map(d => d.month);

    // 三级模型堆积柱状图
    if (chartTrend) chartTrend.destroy();
    chartTrend = new Chart(document.getElementById("chart-trend"), {
      type: "bar",
      data: {
        labels: months,
        datasets: [
          { label: "经营岗成本", data: j.data.map(d => d.direct_cost), backgroundColor: "rgba(52,152,219,.7)" },
          { label: "通用岗成本", data: j.data.map(d => d.shared_cost), backgroundColor: "rgba(243,156,18,.7)" },
          { label: "管理岗成本", data: j.data.map(d => d.management_cost), backgroundColor: "rgba(155,89,182,.7)" },
          { label: "销售额", data: j.data.map(d => d.sale), backgroundColor: "rgba(46,204,113,.3)", yAxisID: "y1" },
        ]
      },
      options: {
        responsive: true, interaction: { mode: "index", intersect: false },
        scales: {
          x: { stacked: true },
          y: { stacked: true, title: { display: true, text: "成本(元)" } },
          y1: { type: "linear", position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "销售额" } },
        }
      }
    });

    if (chartRatio) chartRatio.destroy();
    chartRatio = new Chart(document.getElementById("chart-ratio"), {
      type: "line",
      data: {
        labels: months,
        datasets: [
          { label: "人工占销售(%)", data: j.data.map(d => d.labor_sale_ratio), borderColor: "#e67e22", tension: .3, fill: false },
          { label: "人工占毛利(%)", data: j.data.map(d => d.labor_profit_ratio), borderColor: "#c0392b", tension: .3, fill: false },
          { label: "每元成本毛利", data: j.data.map(d => d.profit_per_cost), borderColor: "#27ae60", tension: .3, fill: false, yAxisID: "y1" },
        ]
      },
      options: {
        responsive: true,
        scales: { y: { title: { display: true, text: "%" } }, y1: { type: "linear", position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "倍数" } } }
      }
    });

    // 岗位类型堆积
    const typeData = {};
    j.data.forEach(d => {
      for (const [t, v] of Object.entries(d.by_position_type || {})) {
        if (!typeData[t]) typeData[t] = [];
        typeData[t].push(v.cost);
      }
    });
    const tc = { leader:"#9b59b6", fulltime:"#3498db", parttime:"#1abc9c", hourly:"#f39c12", cleaner:"#e74c3c", management:"#2ecc71" };
    const tl = { leader:"组长", fulltime:"全职", parttime:"兼职", hourly:"小时工", cleaner:"保洁", management:"管理岗" };
    const ds = Object.entries(typeData).map(([k,v]) => ({ label: tl[k]||k, data: v, backgroundColor: tc[k]||"#95a5a6" }));
    if (chartType) chartType.destroy();
    chartType = new Chart(document.getElementById("chart-type"), {
      type: "bar",
      data: { labels: months, datasets: ds },
      options: { responsive: true, scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "成本(元)" } } } }
    });

  } catch(e) {
    document.getElementById("overview-kpis").innerHTML = `<div class="error">加载失败: ${e.message}</div>`;
  }
}

// ── 类目组分析 ──
async function loadCategory() {
  const month = document.getElementById("cat-month").value;
  if (!month) return;
  try {
    const url = `/api/labor_report/by_category?month=${month}&store_id=${STORE}&share=${shareEnabled}`;
    const r = await fetch(url);
    const j = await r.json();
    if (!j.success) throw new Error(j.message);
    catData = j;

    const s = j.summary;
    const cb = j.cost_type_breakdown || {};
    document.getElementById("cat-kpis").innerHTML = `
      <div class="kpi-card purple"><div class="label">📅 月份</div><div class="value">${j.month}</div></div>
      <div class="kpi-card blue"><div class="label">💰 销售总额</div><div class="value">${s.total_sale.toLocaleString()}</div></div>
      <div class="kpi-card green"><div class="label">🏆 毛利总额</div><div class="value">${s.total_profit.toLocaleString()}</div></div>
      <div class="kpi-card orange"><div class="label">🧑‍💼 人力总成本</div><div class="value">${s.total_labor_cost.toLocaleString()}</div><div class="sub">经营 ${s.labor_cost_direct} / 通用 ${s.labor_cost_shared} / 管理 ${s.labor_cost_management}</div></div>
    `;

    if (typeof Chart === 'undefined') { console.warn('Chart.js not loaded, skipping cat charts'); return; }
    // 图表：只显示有品类（排除管理/后台）
    const cats = j.categories.filter(c => c.category_large_code !== "__管理__");

    if (chartCatLabor) chartCatLabor.destroy();
    chartCatLabor = new Chart(document.getElementById("chart-cat-labor"), {
      type: "bar",
      data: {
        labels: cats.map(c => c.category),
        datasets: [
          { label: "销售额", data: cats.map(c => c.sale), backgroundColor: "rgba(52,152,219,.4)", yAxisID: "y" },
          { label: "经营岗成本", data: cats.map(c => c.labor_cost_direct), backgroundColor: "rgba(52,152,219,.8)", yAxisID: "y1" },
          ...(shareEnabled ? [{ label: "通用岗分摊", data: cats.map(c => c.labor_cost_shared), backgroundColor: "rgba(243,156,18,.6)", yAxisID: "y1" }] : []),
        ]
      },
      options: {
        responsive: true,
        scales: { y: { type: "linear", position: "left", title: { display: true, text: "销售额" } }, y1: { type: "linear", position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "成本" } } }
      }
    });

    // 成本结构饼图
    if (chartCostStructure) chartCostStructure.destroy();
    if (cb.direct || cb.management) {
      chartCostStructure = new Chart(document.getElementById("chart-cost-structure"), {
        type: "doughnut",
        data: {
          labels: ["经营岗", "通用岗", "管理岗"],
          datasets: [{
            data: [cb.direct?.cost||0, cb.shared?.cost||0, cb.management?.cost||0],
            backgroundColor: ["#3498db", "#f39c12", "#9b59b6"],
          }]
        },
        options: { responsive: true, plugins: { tooltip: { callbacks: { label: ctx => ctx.label + ': ' + ctx.parsed.toLocaleString() + '元' } } } }
      });
    }

    // 表格
    renderCatTable();
  } catch(e) {
    document.getElementById("cat-kpis").innerHTML = `<div class="error">加载失败: ${e.message}</div>`;
  }
}

function renderCatTable() {
  if (!catData) return;
  const allRows = [...catData.categories];
  doSort(allRows, 'cat');
  document.getElementById("cat-table-body").innerHTML = allRows.map(c => {
      const isMgmt = c.category_large_code === "__管理__";
      const eff = c.efficiency || {};
      const laborTotal = c.labor_cost;
      const laborDirect = c.labor_cost_direct;
      const laborShared = c.labor_cost_shared || 0;
      const laborMarginRatio = c.labor_cost_per_profit !== null ? c.labor_cost_per_profit.toFixed(2) + "%" : "-";
      const ppc = c.profit_per_cost !== null && c.profit_per_cost !== undefined ? c.profit_per_cost.toFixed(2) : "-";
      const effBadge = eff.color ? `<span class="badge" style="background:${eff.color}22;color:${eff.color}">${eff.label}</span>` : "";
      return `<tr style="${isMgmt ? 'background:#f8f4ff' : ''}">
        <td>${c.category}${c.category_large_code && !isMgmt ? " ("+c.category_large_code+")" : ""}</td>
        <td class="text-right">${c.sale.toLocaleString()}</td>
        <td class="text-right">${c.profit.toLocaleString()}</td>
        <td class="text-right"><span class="badge ${c.margin_pct > 35 ? 'badge-green' : c.margin_pct > 20 ? 'badge-orange' : 'badge-red'}">${c.margin_pct}%</span></td>
        <td class="text-right">${laborDirect.toLocaleString()}</td>
        <td class="text-right">${shareEnabled && laborShared > 0 ? '+' + laborShared.toLocaleString() : '-'}</td>
        <td class="text-right"><strong>${laborTotal.toLocaleString()}</strong></td>
        <td class="text-right">${laborMarginRatio}</td>
        <td class="text-right">${ppc}</td>
        <td class="text-center">${effBadge}</td>
      </tr>`;
    }).join("");
}

// ── 人员明细 ──
async function loadPersons() {
  const month = document.getElementById("ps-month").value;
  if (!month) return;
  try {
    const r = await fetch(`/api/labor_report/persons?month=${month}&store_id=${STORE}`);
    const j = await r.json();
    if (!j.success) throw new Error(j.message);
    personData = j;

    const s = j.summary;
    document.getElementById("ps-summary").innerHTML = `
      <div class="kpi-card purple"><div class="label">👤 总人数</div><div class="value">${s.total_headcount}</div></div>
      <div class="kpi-card blue"><div class="label">经营岗</div><div class="value">${s.direct_headcount}</div><div class="sub">${s.direct_cost}元</div></div>
      <div class="kpi-card orange"><div class="label">通用岗</div><div class="value">${s.shared_headcount}</div><div class="sub">${s.shared_cost}元</div></div>
      <div class="kpi-card red"><div class="label">管理岗</div><div class="value">${s.management_headcount}</div><div class="sub">${s.management_cost}元</div></div>
    `;

    // 岗位名下拉
    const positions = [...new Set(j.persons.map(p => p.position_name))].sort();
    document.getElementById("ps-pos").innerHTML = '<option value="">全部岗位</option>' + positions.map(p => `<option value="${p}">${p}</option>`).join("");

    filterPersons();
  } catch(e) {
    document.getElementById("ps-summary").innerHTML = `<div class="error">加载失败: ${e.message}</div>`;
  }
}

function filterPersons() {
  if (!personData) return;
  const levelFilter = document.getElementById("ps-level").value;
  const posFilter = document.getElementById("ps-pos").value;
  const search = document.getElementById("ps-search").value.trim().toLowerCase();
  let list = personData.persons;
  if (levelFilter) list = list.filter(p => p.cost_type_label === levelFilter);
  if (posFilter) list = list.filter(p => p.position_name === posFilter);
  if (search) list = list.filter(p => p.person_name.toLowerCase().includes(search));
  list = [...list];
  doSort(list, 'ps');

  document.getElementById("ps-table-body").innerHTML = list.map(p => {
    const csr = p.cost_sale_ratio !== null ? p.cost_sale_ratio.toFixed(2) + "%" : "-";
    const cpr = p.cost_profit_ratio !== null ? p.cost_profit_ratio.toFixed(2) + "%" : "-";
    const tagClass = { "经营岗": "tag-direct", "通用岗": "tag-shared", "管理岗": "tag-management" }[p.cost_type_label] || "";
    const mappedBadge = p.mapped_category === "（管理岗）" ? "badge-purple" : p.mapped_category === "（通用岗）" ? "badge-orange" : "badge-green";
    return `<tr>
      <td><strong>${p.person_name}</strong></td>
      <td>${p.position_name}</td>
      <td><span class="cost-type-tag ${tagClass}">${p.cost_type_label}</span></td>
      <td class="text-right">${p.total_cost.toLocaleString()}</td>
      <td><span class="badge ${mappedBadge}">${p.mapped_category}</span></td>
      <td class="text-right">${p.category_sale.toLocaleString()}</td>
      <td class="text-right">${p.category_profit.toLocaleString()}</td>
      <td class="text-right">${csr}</td>
      <td class="text-right">${cpr}</td>
    </tr>`;
  }).join("");
}

// ── 整体汇总 ──
async function loadOverall() {
  const monthFrom = document.getElementById("overall-from").value;
  const monthTo = document.getElementById("overall-to").value;
  try {
    const r = await fetch(`/api/labor_report/by_person?month_from=${monthFrom}&month_to=${monthTo}&store_id=${STORE}`);
    const j = await r.json();
    if (!j.success) throw new Error(j.message);
    const s = j.summary;
    document.getElementById("overall-kpis").innerHTML = `
      <div class="kpi-card purple"><div class="label">👤 总人数</div><div class="value">${s.total_headcount}</div><div class="sub">${s.month_count} 个月累计</div></div>
      <div class="kpi-card blue"><div class="label">经营岗</div><div class="value">${s.direct_cost.toLocaleString()}</div></div>
      <div class="kpi-card orange"><div class="label">通用岗</div><div class="value">${s.shared_cost.toLocaleString()}</div></div>
      <div class="kpi-card red"><div class="label">管理岗</div><div class="value">${s.management_cost.toLocaleString()}</div></div>
      <div class="kpi-card green"><div class="label">💰 总成本</div><div class="value">${s.total_cost.toLocaleString()}</div></div>
    `;
    overallData = j;
    renderOverallTable();
  } catch(e) {
    document.getElementById("overall-kpis").innerHTML = `<div class="error">加载失败: ${e.message}</div>`;
  }
}

function renderOverallTable() {
  if (!overallData) return;
  const sorted = [...overallData.persons];
  doSort(sorted, 'oa');
  document.getElementById("overall-table-body").innerHTML = sorted.map(p => {
      const monthsStr = p.present_months.join(", ");
      const tagClass = { "经营岗": "tag-direct", "通用岗": "tag-shared", "管理岗": "tag-management" }[p.cost_type_label] || "";
      return `<tr>
        <td><strong>${p.person_name}</strong></td>
        <td>${p.position_name}</td>
        <td><span class="cost-type-tag ${tagClass}">${p.cost_type_label}</span></td>
        <td class="text-right">${p.total_cost.toLocaleString()}</td>
        <td class="text-right">${p.avg_monthly_cost.toLocaleString()}</td>
        <td><span class="badge badge-green">${p.mapped_category}</span></td>
        <td class="text-right">${p.category_sale.toLocaleString()}</td>
        <td class="text-right">${p.category_profit.toLocaleString()}</td>
        <td style="font-size:11px;color:#999">${monthsStr}</td>
      </tr>`;
    }).join("");
}

// ── 月份选择器填充（扩展）──
const _origFill = fillMonthSelectors;
fillMonthSelectors = async function() {
  await _origFill();
  const r = await fetch(`/api/labor_report/overview?store_id=${STORE}`);
  const j = await r.json();
  const months = j.months || [];
  const opts = months.map(m => `<option value="${m}">${m}</option>`).join("");
  var elFrom = document.getElementById("overall-from");
  var elTo = document.getElementById("overall-to");
  if (elFrom && elTo) {
    elFrom.innerHTML = opts;
    elTo.innerHTML = opts;
    if (months.length) {
      elFrom.value = months[0];
      elTo.value = months[months.length - 1];
    }
    loadOverall();
  }
};
async function fillMonthSelectors() {
  const r = await fetch(`/api/labor_report/overview?store_id=${STORE}`);
  const j = await r.json();
  const months = j.months || [];
  const opts = months.map(m => `<option value="${m}">${m}</option>`).join("");
  document.getElementById("cat-month").innerHTML = opts;
  document.getElementById("ps-month").innerHTML = opts;
  if (months.length) {
    document.getElementById("cat-month").value = months[months.length - 1];
    document.getElementById("ps-month").value = months[months.length - 1];
  }
  loadOverview();
  if (months.length) { loadCategory(); loadPersons(); }
}
document.addEventListener('DOMContentLoaded', function() { fillMonthSelectors().catch(e => console.error('Init error:', e)); });