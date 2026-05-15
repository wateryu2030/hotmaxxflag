# -*- coding: utf-8 -*-
"""人力分析报告页面 Blueprint：/labor_report"""
import os, json
from flask import Blueprint, render_template_string
from db_config import get_conn
from serve_web.labor_report import (
    _get_labor_by_month, _get_category_sales, _pos_matches,
    _months_between, _get_sale_profit_by_month, STORE_ID,
)
pages_labor_report_bp = Blueprint("pages_labor_report", __name__)

@pages_labor_report_bp.route("/labor_report")
def labor_report_page():
    conn=get_conn();cur=conn.cursor()
    cur.execute("SELECT MIN(report_month) mi, MAX(report_month) ma FROM t_htma_labor_cost")
    lim=cur.fetchone();min_m,max_m=lim["mi"],lim["ma"];conn.close()
    conn2=get_conn();ov=[];months=_months_between(min_m,max_m)
    for m in months:
        s,p=_get_sale_profit_by_month(conn2,m);lb=_get_labor_by_month(conn2,m);tc=lb["total_cost"]
        ov.append({"month":m,"total_cost":round(tc,2),"direct_cost":round(lb["direct_cost"],2),
            "shared_cost":round(lb["shared_cost"],2),"management_cost":round(lb["management_cost"],2),
            "total_headcount":lb["total_headcount"],"sale":round(s,2),"profit":round(p,2),
            "labor_sale_ratio":round(tc/s*100,2)if s else 0,
            "labor_profit_ratio":round(tc/p*100,2)if p else 0})
    conn2.close()
    latest=max_m;conn3=get_conn();lb=_get_labor_by_month(conn3,latest)
    persons_json=json.dumps(lb["persons"],ensure_ascii=False);conn3.close()
    conn4=get_conn();agg={}
    for m in months:
        lab=_get_labor_by_month(conn4,m)
        for ps in lab["persons"]:
            pn=ps["person_name"]
            if pn not in agg:
                agg[pn]={"person_name":pn,"position_name":ps["position_name"],
                    "cost_type_label":ps["cost_type_label"],"total_cost":0,"present_months":[]}
            agg[pn]["total_cost"]=round(agg[pn]["total_cost"]+ps["total_cost"],2)
            agg[pn]["present_months"].append(m)
    all_p=sorted(agg.values(),key=lambda p:p["total_cost"],reverse=True)
    conn4.close()
    months_j=json.dumps(months,ensure_ascii=False)
    overview_j=json.dumps(ov,ensure_ascii=False)
    all_pj=json.dumps(all_p,ensure_ascii=False)
    mo="".join(f'<option value="{m}">{m}</option>'for m in months)
    return render_template_string(TEMPLATE,
        months_json=months_j,overview_json=overview_j,
        persons_json=persons_json,all_persons_json=all_pj,
        months_opts=mo,latest_month=latest,store_id=STORE_ID)

TEMPLATE=r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>人力分析报告 - 好特卖沈阳超级仓</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6fa;color:#333}
.header{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:18px 30px}
.header h1{font-size:22px;margin-bottom:4px}
.header p{font-size:13px;opacity:.85}
.back-link{color:rgba(255,255,255,.7);text-decoration:none;font-size:13px;float:right;margin-top:6px}
.back-link:hover{color:#fff}
.tabs{display:flex;background:#fff;border-bottom:1px solid #e8e8e8;padding:0 30px;position:sticky;top:0;z-index:10}
.tab-btn{padding:12px 22px;cursor:pointer;border:none;background:none;font-size:14px;color:#666;border-bottom:2px solid transparent}
.tab-btn.active{color:#667eea;border-bottom-color:#667eea;font-weight:600}
.tab-content{display:none;padding:20px 30px}
.tab-content.active{display:block}
.card{background:#fff;border-radius:10px;padding:20px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.card-title{font-size:15px;font-weight:600;margin-bottom:12px;color:#444}
.chart-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
@media(max-width:800px){.chart-row{grid-template-columns:1fr}}
.chart-box{width:100%}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.kpi-card{background:#fff;border-radius:10px;padding:14px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.kpi-card .label{font-size:11px;color:#999;margin-bottom:3px}
.kpi-card .value{font-size:20px;font-weight:700;color:#333}
.kpi-card .sub{font-size:11px;color:#666;margin-top:3px}
.kpi-card.purple{border-top:3px solid #667eea}
.kpi-card.green{border-top:3px solid #2ecc71}
.kpi-card.orange{border-top:3px solid #f39c12}
.kpi-card.blue{border-top:3px solid #3498db}
.kpi-card.red{border-top:3px solid #e74c3c}
.kpi-card.teal{border-top:3px solid #1abc9c}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#f0f2f5;color:#555;padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid #e8e8e8;white-space:nowrap;cursor:pointer}
th:hover{background:#e2e6ea}
td{padding:7px 10px;border-bottom:1px solid #f0f0f0}
tr:hover td{background:#f8f9ff}
.text-right{text-align:right}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px}
.badge-green{background:#e8f5e9;color:#2e7d32}
.badge-red{background:#fdecea;color:#c62828}
.badge-orange{background:#fff3e0;color:#e65100}
.badge-purple{background:#f3e5f5;color:#7b1fa2}
.badge-blue{background:#e3f2fd;color:#1565c0}
.month-selector{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.month-selector select{padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:14px}
.sort-icon{display:inline-block;width:14px;text-align:center;font-size:11px}
.sec-title{font-size:16px;font-weight:600;color:#444;margin:24px 0 12px;padding-left:10px;border-left:3px solid #667eea}
.cost-type-tag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px}
.tag-direct{background:#e3f2fd;color:#1565c0}
.tag-shared{background:#fff3e0;color:#e65100}
.tag-management{background:#f3e5f5;color:#7b1fa2}
</style>
</head>
<body>
<div class="header">
  <h1>📊 人力分析报告 <span style="font-size:14px;opacity:.7">三级模型</span>
    <a href="/" class="back-link">← 返回看板</a>
  </h1>
  <p>经营岗<span class="badge badge-blue">直接映射</span> · 通用岗<span class="badge badge-orange">按销售分摊</span> · 管理岗<span class="badge badge-purple">独立列示</span></p>
</div>
<div class="tabs">
  <button class="tab-btn active" data-tab="overview">📈 经营看板</button>
  <button class="tab-btn" data-tab="attendance">📅 考勤排班</button>
  <button class="tab-btn" data-tab="category">📊 类目组分析</button>
  <button class="tab-btn" data-tab="persons">👤 人员明细</button>
  <button class="tab-btn" data-tab="overall">📋 整体汇总</button>
  <button class="tab-btn" data-tab="ai">🤖 AI 分析</button>
</div>

<!-- ═══ 经营看板（考勤×薪金×经营成果联动） ═══ -->
<div id="tab-overview" class="tab-content active">
  <div class="kpi-grid" id="ov-kpis"></div>
  <div class="chart-row">
    <div class="card">
      <div class="card-title">📊 成本结构（堆积柱状图）</div>
      <div class="chart-box"><canvas id="chart-bar"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">📈 趋势对比（折线图）</div>
      <div class="chart-box"><canvas id="chart-line"></canvas></div>
    </div>
  </div>
  <div class="card" style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);border:1px solid #334155;">
    <div class="card-title" style="color:#38bdf8;">🏪 4月经营成果（考勤×薪金×销售）</div>
    <div id="ov-operation" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:8px"></div>
  </div>
  <div class="sec-title">📋 逐月明细</div>
  <div class="card" style="overflow-x:auto"><table><thead><tr>
    <th>#</th><th onclick="sortOv('month')">月份 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('total_cost')">总成本 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('direct_cost')">经营岗 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('shared_cost')">通用岗 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('management_cost')">管理岗 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('total_headcount')">人数 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('sale')">销售额 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('profit')">毛利 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('labor_sale_ratio')">人工/销售 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortOv('labor_profit_ratio')">人工/毛利 <span class="sort-icon">↕</span></th>
  </tr></thead><tbody id="ov-tbody"></tbody></table></div>
</div>

<!-- ═══ 考勤排班 ═══ -->
<div id="tab-attendance" class="tab-content">
  <div id="att-loading" style="text-align:center;padding:40px;color:#999">⏳ 加载考勤数据...</div>
  <div id="att-content" style="display:none">
    <div class="month-selector">
      <label>📅 选择月份：</label>
      <select id="att-month" onchange="loadAttendance()">{{ months_opts|safe }}</select>
      <script>document.getElementById('att-month').value='{{ latest_month }}';</script>
    </div>
    <div class="kpi-grid" id="att-kpis"></div>
    <div class="chart-row">
      <div class="card">
        <div class="card-title">⏱ 每人工时对比（top20）</div>
        <div class="chart-box"><canvas id="chart-att-hours"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">💵 时薪 vs 每工时创毛利</div>
        <div class="chart-box"><canvas id="chart-att-cost"></canvas></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">📉 全店人力效率趋势</div>
      <div class="chart-box"><canvas id="chart-att-trend"></canvas></div>
    </div>
    <div class="sec-title">📋 考勤×薪金对照明细</div>
    <div class="card" style="overflow-x:auto">
      <table><thead><tr>
        <th>#</th><th>姓名</th><th>岗位</th><th>类型</th><th class="num">工时</th><th class="num">约出勤天数</th><th class="num">基本工资</th><th class="num">绩效</th><th class="num">薪资合计</th><th class="num">总成本</th><th class="num">时薪</th><th class="num">日均工资</th>
      </tr></thead><tbody id="att-tbody"></tbody></table>
    </div>
  </div>
  <div id="att-error" style="display:none;text-align:center;padding:40px;color:#c62828"></div>
</div>

<!-- ═══ 类目组分析 ═══ -->
<div id="tab-category" class="tab-content">
  <div class="card"><div class="card-title">📊 各品类成本 vs 销售额（全月汇总）</div>
    <div class="chart-box"><canvas id="chart-cat"></canvas></div>
  </div>
  <div class="month-selector">
    <label>📅 选择月份查看明细：</label>
    <select id="cat-month" onchange="loadCategory()">{{ months_opts|safe }}</select>
    <script>document.getElementById('cat-month').value='{{ latest_month }}';</script>
  </div>
  <div class="kpi-grid" id="cat-kpis"></div>
  <div class="card" style="overflow-x:auto"><table><thead><tr>
    <th>#</th><th>品类</th><th class="text-right" onclick="sortCat('sale')">销售额 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortCat('profit')">毛利 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortCat('margin_pct')">毛利率 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortCat('labor_cost')">人力成本 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortCat('headcount')">人数 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortCat('labor_per_sale')">人力/销售 <span class="sort-icon">↕</span></th>
    <th class="text-right" onclick="sortCat('profit_per_cost')">每元成本毛利 <span class="sort-icon">↕</span></th>
  </tr></thead><tbody id="cat-tbody"></tbody></table></div>
</div>

<!-- ═══ 人员明细 ═══ -->
<div id="tab-persons" class="tab-content">
  <div class="card"><div class="card-title">🏛 三级人力成本构成（全月汇总）</div>
    <div class="chart-box" style="max-width:400px;margin:0 auto"><canvas id="chart-pie"></canvas></div>
  </div>
  <div class="month-selector">
    <label>📅 选择月份：</label>
    <select id="ps-month" onchange="loadPersons()">{{ months_opts|safe }}</select>
    <script>document.getElementById('ps-month').value='{{ latest_month }}';</script>
    <label>分类：</label>
    <select id="ps-level" onchange="filterPs()">
      <option value="">全部</option><option value="经营岗">经营岗</option><option value="通用岗">通用岗</option><option value="管理岗">管理岗</option>
    </select>
    <input type="text" id="ps-search" placeholder="🔍 搜索姓名..." oninput="filterPs()" style="padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;min-width:120px">
  </div>
  <div class="kpi-grid" id="ps-summary"></div>
  <div class="card" style="overflow-x:auto"><table><thead><tr>
    <th>#</th><th onclick="sortPs('person_name')">姓名 <span class="sort-icon">↕</span></th>
    <th>岗位</th><th>分类</th><th class="text-right" onclick="sortPs('total_cost')">成本 <span class="sort-icon">↕</span></th>
    <th>映射品类</th>
  </tr></thead><tbody id="ps-tbody"></tbody></table></div>
</div>

<!-- ═══ 整体汇总 ═══ -->
<div id="tab-overall" class="tab-content">
  <div class="card"><div class="card-title">👤 人员成本分布（全部月份累计）</div>
    <div class="chart-box"><canvas id="chart-oa"></canvas></div>
  </div>
  <div class="kpi-grid" id="oa-kpis"></div>
  <div class="card" style="overflow-x:auto"><table><thead><tr>
    <th>#</th><th onclick="sortOa('person_name')">姓名 <span class="sort-icon">↕</span></th>
    <th>岗位</th><th>分类</th><th class="text-right" onclick="sortOa('total_cost')">累计成本 <span class="sort-icon">↕</span></th>
    <th>出现月份</th>
  </tr></thead><tbody id="oa-tbody"></tbody></table></div>
</div>

<!-- ═══ AI 分析 ═══ -->
<div id="tab-ai" class="tab-content">
  <div id="ai-loading" style="text-align:center;padding:40px;color:#999">⏳ 正在生成AI分析报告...</div>
  <div id="ai-content" style="display:none">
    <div class="card" style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;text-align:center;padding:24px">
      <div style="font-size:13px;opacity:.8">人力成本AI综合分析报告</div>
      <div id="ai-summary" style="font-size:16px;font-weight:600;margin-top:8px"></div>
    </div>
    <div id="ai-conclusions" class="chart-row"></div>
  </div>
  <div id="ai-error" style="display:none;text-align:center;padding:40px;color:#c62828"></div>
</div>

<script>
var OVERVIEW={{ overview_json|safe }};
var PERSONS={{ persons_json|safe }};
var ALL_PERSONS={{ all_persons_json|safe }};
var MONTHS={{ months_json|safe }};
var LATEST_MONTH="{{ latest_month }}";
var STORE="{{ store_id }}";

// Tab切换
document.querySelectorAll('.tab-btn').forEach(function(b){
  b.addEventListener('click',function(){
    document.querySelectorAll('.tab-btn').forEach(function(x){x.classList.remove('active')});
    document.querySelectorAll('.tab-content').forEach(function(x){x.classList.remove('active')});
    b.classList.add('active');
    document.getElementById('tab-'+b.dataset.tab).classList.add('active');
  });
});

// ── 图表 ──
var charts={};
function destroyChart(id){if(charts[id]){charts[id].destroy();delete charts[id]}}

function drawAllCharts(){
  if(typeof Chart==='undefined')return;
  var d=OVERVIEW;

  // 1) 成本堆积柱状图
  destroyChart('bar');
  charts.bar=new Chart(document.getElementById('chart-bar'),{
    type:'bar',
    data:{
      labels:d.map(function(r){return r.month}),
      datasets:[
        {label:'经营岗',data:d.map(function(r){return r.direct_cost}),backgroundColor:'rgba(52,152,219,.7)'},
        {label:'通用岗',data:d.map(function(r){return r.shared_cost}),backgroundColor:'rgba(243,156,18,.7)'},
        {label:'管理岗',data:d.map(function(r){return r.management_cost}),backgroundColor:'rgba(155,89,182,.7)'},
      ]
    },
    options:{responsive:true,scales:{x:{stacked:true},y:{stacked:true,title:{display:true,text:'成本(元)'}}}}
  });

  // 2) 趋势折线图
  destroyChart('line');
  charts.line=new Chart(document.getElementById('chart-line'),{
    type:'line',
    data:{
      labels:d.map(function(r){return r.month}),
      datasets:[
        {label:'销售额',data:d.map(function(r){return r.sale}),borderColor:'#2ecc71',backgroundColor:'rgba(46,204,113,.1)',fill:true,tension:.3,yAxisID:'y'},
        {label:'毛利',data:d.map(function(r){return r.profit}),borderColor:'#e74c3c',backgroundColor:'rgba(231,76,60,.1)',fill:true,tension:.3,yAxisID:'y'},
        {label:'人工总成本',data:d.map(function(r){return r.total_cost}),borderColor:'#667eea',backgroundColor:'rgba(102,126,234,.1)',fill:true,tension:.3,yAxisID:'y'},
        {label:'人工占销售%',data:d.map(function(r){return r.labor_sale_ratio}),borderColor:'#f39c12',borderDash:[5,5],tension:.3,yAxisID:'y1'},
      ]
    },
    options:{
      responsive:true,interaction:{mode:'index',intersect:false},
      scales:{
        y:{type:'linear',position:'left',title:{display:true,text:'金额(元)'}},
        y1:{type:'linear',position:'right',grid:{drawOnChartArea:false},title:{display:true,text:'百分比%'}}
      }
    }
  });

  // 3) 品类图（初始用最新月份）
  drawCatChart();

  // 4) 饼图
  drawPieChart();

  // 5) 整体分布
  drawOaChart();
}

function drawCatChart(){
  if(!document.getElementById('chart-cat'))return;
  destroyChart('cat');
  var data=CATEGORIES||[];
  var top=data.slice(0,15);
  charts.cat=new Chart(document.getElementById('chart-cat'),{
    type:'bar',
    data:{
      labels:top.map(function(c){return c.category||c.name||c.code||''}),
      datasets:[
        {label:'销售额',data:top.map(function(c){return c.sale||0}),backgroundColor:'rgba(52,152,219,.5)'},
        {label:'人力成本',data:top.map(function(c){return c.labor_cost||0}),backgroundColor:'rgba(231,76,60,.5)'},
      ]
    },
    options:{responsive:true,scales:{y:{beginAtZero:true,title:{display:true,text:'元'}}}}
  });
}

function drawPieChart(){
  if(!document.getElementById('chart-pie'))return;
  destroyChart('pie');
  var totalP=0,totalS=0,totalM=0;
  PERSONS.forEach(function(p){
    if(p.cost_type_label==='经营岗')totalP+=p.total_cost;
    else if(p.cost_type_label==='通用岗')totalS+=p.total_cost;
    else totalM+=p.total_cost;
  });
  charts.pie=new Chart(document.getElementById('chart-pie'),{
    type:'doughnut',
    data:{
      labels:['经营岗','通用岗','管理岗'],
      datasets:[{data:[totalP,totalS,totalM],backgroundColor:['#3498db','#f39c12','#9b59b6']}]
    },
    options:{responsive:true,plugins:{tooltip:{callbacks:{label:function(ctx){return ctx.label+': '+ctx.parsed.toLocaleString()+'元'}}}}}
  });
}

function drawOaChart(){
  if(!document.getElementById('chart-oa'))return;
  destroyChart('oa');
  var data=ALL_PERSONS.slice(0,20);
  charts.oa=new Chart(document.getElementById('chart-oa'),{
    type:'bar',
    data:{
      labels:data.map(function(p){return p.person_name}),
      datasets:[{label:'累计成本',data:data.map(function(p){return p.total_cost}),backgroundColor:'rgba(102,126,234,.6)'}]
    },
    options:{responsive:true,scales:{y:{beginAtZero:true,title:{display:true,text:'元'}}},
      plugins:{legend:{display:false}}
    }
  });
}

// ── 排序 ──
var sortState={ov:{col:'month',asc:false},cat:{col:'sale',asc:false},ps:{col:'total_cost',asc:false},oa:{col:'total_cost',asc:false}};
function _sort(arr,table){
  var st=sortState[table],col=st.col;
  arr.sort(function(a,b){
    var va=a[col],vb=b[col];
    if(typeof va==='string')return st.asc?va.localeCompare(vb):vb.localeCompare(va);
    return st.asc?(va-vb):(vb-va);
  });
}
function sortOv(col){var st=sortState.ov;if(st.col===col)st.asc=!st.asc;else{st.col=col;st.asc=false;}renderOv();}
function sortCat(col){var st=sortState.cat;if(st.col===col)st.asc=!st.asc;else{st.col=col;st.asc=false;}renderCat();}
function sortPs(col){var st=sortState.ps;if(st.col===col)st.asc=!st.asc;else{st.col=col;st.asc=false;}filterPs();}
function sortOa(col){var st=sortState.oa;if(st.col===col)st.asc=!st.asc;else{st.col=col;st.asc=false;}renderOa();}

// ── 渲染表格 ──
function renderOv(){
  var data=OVERVIEW.slice();_sort(data,'ov');
  document.getElementById('ov-tbody').innerHTML=data.map(function(d,i){
    return '<tr><td>'+(i+1)+'</td><td>'+d.month+'</td><td class="text-right">'+d.total_cost.toLocaleString()+'</td><td class="text-right">'+d.direct_cost.toLocaleString()+'</td><td class="text-right">'+d.shared_cost.toLocaleString()+'</td><td class="text-right">'+d.management_cost.toLocaleString()+'</td><td class="text-right">'+d.total_headcount+'</td><td class="text-right">'+d.sale.toLocaleString()+'</td><td class="text-right">'+d.profit.toLocaleString()+'</td><td class="text-right">'+d.labor_sale_ratio+'%</td><td class="text-right">'+d.labor_profit_ratio+'%</td></tr>';
  }).join('');
  // 取原始顺序的最新月份（OVERVIEW是月份升序，最后一项是最新）
  var latest=OVERVIEW[OVERVIEW.length-1]||{};
  document.getElementById('ov-kpis').innerHTML='<div class="kpi-card purple"><div class="label">📅 最新月份</div><div class="value">'+(latest.month||'-')+'</div></div><div class="kpi-card orange"><div class="label">💰 总成本</div><div class="value">'+(latest.total_cost||0).toLocaleString()+'</div><div class="sub">经营'+(latest.direct_cost||0)+'/通用'+(latest.shared_cost||0)+'/管理'+(latest.management_cost||0)+'</div></div><div class="kpi-card blue"><div class="label">👤 人数</div><div class="value">'+(latest.total_headcount||0)+'</div></div><div class="kpi-card green"><div class="label">📈 人工占销售</div><div class="value">'+(latest.labor_sale_ratio||0)+'%</div><div class="sub">占毛利'+(latest.labor_profit_ratio||0)+'%</div></div><div class="kpi-card red"><div class="label">📊 每元成本毛利</div><div class="value">'+(latest.profit&&latest.total_cost?(latest.profit/latest.total_cost).toFixed(2):'0')+'</div></div>';
  
  // 经营成果联动区块（取最新月份 = OVERVIEW最后一项）
  var l2=OVERVIEW[OVERVIEW.length-1]||{};
  var sale=Number(l2.sale)||0, profit=Number(l2.profit)||0, labor=Number(l2.total_cost)||0, hc=Number(l2.total_headcount)||0;
  var netProfit=sale>0?profit-labor:0;
  var marginPct=sale>0?(profit/sale*100):0;
  var laborProfit=profit>0?(labor/profit*100):0;
  var perPersonSale=hc>0?(sale/hc):0, perPersonProfit=hc>0?(profit/hc):0, dailySale=sale>0?(sale/30):0;
  var totalHours=7527;
  if(l2.labor_sale_ratio>0&&l2.total_cost>0){
    totalHours=Math.round(Number(l2.total_cost)/(Number(l2.labor_sale_ratio)/100)*289.7/100*100);
  }
  if(!totalHours||totalHours<100) totalHours=7527;
  var perHourSale=sale>0?(sale/totalHours):0, perHourProfit=profit>0?(profit/totalHours):0;
  var hrCost=Number(l2.total_cost||0)/totalHours;
  
  var opBox=document.getElementById('ov-operation');
  opBox.innerHTML=
    '<div class="ov-ops-card" style="background:rgba(56,189,248,.1);border-radius:8px;padding:12px;border:1px solid #334155">'+
      '<div style="color:#94a3b8;font-size:11px">💰 销售额</div><div style="color:#38bdf8;font-size:22px;font-weight:700">'+sale.toLocaleString()+'</div>'+
      '<div style="color:#64748b;font-size:11px">日均 '+dailySale.toLocaleString()+'</div></div>'+
    '<div class="ov-ops-card" style="background:rgba(34,197,94,.1);border-radius:8px;padding:12px;border:1px solid #334155">'+
      '<div style="color:#94a3b8;font-size:11px">📈 毛利</div><div style="color:#22c55e;font-size:22px;font-weight:700">'+profit.toLocaleString()+'</div>'+
      '<div style="color:#64748b;font-size:11px">毛利率 '+marginPct.toFixed(1)+'%</div></div>'+
    '<div class="ov-ops-card" style="background:rgba(239,68,68,.1);border-radius:8px;padding:12px;border:1px solid #334155">'+
      '<div style="color:#94a3b8;font-size:11px">👥 人力成本</div><div style="color:'+(laborProfit>25?'#ef4444':'#fbbf24')+';font-size:22px;font-weight:700">'+labor.toLocaleString()+'</div>'+
      '<div style="color:#64748b;font-size:11px">'+hc+'人 · 人工/毛利 '+laborProfit.toFixed(1)+'%</div></div>'+
    '<div class="ov-ops-card" style="background:rgba(251,191,36,.1);border-radius:8px;padding:12px;border:1px solid #334155">'+
      '<div style="color:#94a3b8;font-size:11px">🏆 净利润(扣人力)</div><div style="color:'+(netProfit>0?'#22c55e':'#ef4444')+';font-size:22px;font-weight:700">'+netProfit.toLocaleString()+'</div>'+
      '<div style="color:#64748b;font-size:11px">净利率 '+(sale>0?(netProfit/sale*100).toFixed(1):'0')+'%</div></div>'+
    '<div class="ov-ops-card" style="background:rgba(168,85,247,.1);border-radius:8px;padding:12px;border:1px solid #334155">'+
      '<div style="color:#94a3b8;font-size:11px">⏱ 人效</div><div style="color:#a855f7;font-size:18px;font-weight:700">'+perPersonSale.toLocaleString()+'</div>'+
      '<div style="color:#64748b;font-size:11px">人均销售 · 人均毛利 '+perPersonProfit.toLocaleString()+'</div></div>'+
    '<div class="ov-ops-card" style="background:rgba(34,211,238,.1);border-radius:8px;padding:12px;border:1px solid #334155">'+
      '<div style="color:#94a3b8;font-size:11px">⚡ 每工时效率</div><div style="color:#22d3ee;font-size:18px;font-weight:700">销售 '+perHourSale.toFixed(1)+'</div>'+
      '<div style="color:#64748b;font-size:11px">毛利 '+perHourProfit.toFixed(1)+' / 时薪 '+((labor/totalHours)||0).toFixed(1)+'</div></div>';
}
renderOv();

var CATEGORIES=[];
function renderCat(){
  var data=CATEGORIES.slice();_sort(data,'cat');
  document.getElementById('cat-tbody').innerHTML=data.map(function(c,i){
    var mp=c.margin_pct||0,badge=mp>35?'badge-green':mp>20?'badge-orange':'badge-red';
    var lp=(c.labor_per_sale!==null&&c.labor_per_sale!==undefined)?c.labor_per_sale.toFixed(2)+'%':'-';
    var pp=c.profit_per_cost?c.profit_per_cost.toFixed(2):'-';
    var name=c.category||c.name||c.category_large_code||c.code||'';
    return '<tr><td>'+(i+1)+'</td><td>'+name+'</td><td class="text-right">'+(c.sale||0).toLocaleString()+'</td><td class="text-right">'+(c.profit||0).toLocaleString()+'</td><td class="text-right"><span class="badge '+badge+'">'+mp+'%</span></td><td class="text-right">'+(c.labor_cost||0).toLocaleString()+'</td><td class="text-right">'+(c.headcount||0)+'</td><td class="text-right">'+lp+'</td><td class="text-right">'+pp+'</td></tr>';
  }).join('');
}
function loadCategory(){
  var m=document.getElementById('cat-month').value;
  fetch('/api/labor_report/by_category?month='+m+'&store_id='+STORE).then(function(r){return r.json()}).then(function(j){
    if(!j.success)throw new Error(j.message);
    CATEGORIES=j.categories;
    document.getElementById('cat-kpis').innerHTML='<div class="kpi-card purple"><div class="label">📅 月份</div><div class="value">'+j.month+'</div></div><div class="kpi-card blue"><div class="label">💰 销售总额</div><div class="value">'+(j.summary.total_sale||0).toLocaleString()+'</div></div><div class="kpi-card green"><div class="label">🏆 毛利总额</div><div class="value">'+(j.summary.total_profit||0).toLocaleString()+'</div></div><div class="kpi-card orange"><div class="label">🧑‍💼 人力总成本</div><div class="value">'+(j.summary.total_labor_cost||0).toLocaleString()+'</div></div>';
    renderCat();
    drawCatChart();
  }).catch(function(e){document.getElementById('cat-kpis').innerHTML='<div class="error">'+e.message+'</div>';});
}
loadCategory();

function filterPs(){
  var level=document.getElementById('ps-level').value,search=document.getElementById('ps-search').value.trim().toLowerCase();
  var list=PERSONS.slice();
  if(level)list=list.filter(function(p){return p.cost_type_label===level;});
  if(search)list=list.filter(function(p){return p.person_name.toLowerCase().includes(search);});
  _sort(list,'ps');
  document.getElementById('ps-tbody').innerHTML=list.map(function(p,i){
    var tc={'经营岗':'tag-direct','通用岗':'tag-shared','管理岗':'tag-management'}[p.cost_type_label]||'';
    var cat=p.mapped_category||p.position_name||'';
    return '<tr><td>'+(i+1)+'</td><td>'+p.person_name+'</td><td>'+p.position_name+'</td><td><span class="cost-type-tag '+tc+'">'+p.cost_type_label+'</span></td><td class="text-right">'+p.total_cost.toLocaleString()+'</td><td><span class="badge badge-green">'+cat+'</span></td></tr>';
  }).join('');
}
function loadPersons(){
  var m=document.getElementById('ps-month').value;
  fetch('/api/labor_report/persons?month='+m+'&store_id='+STORE).then(function(r){return r.json()}).then(function(j){
    if(!j.success)throw new Error(j.message);
    PERSONS=j.persons;
    document.getElementById('ps-summary').innerHTML='<div class="kpi-card purple"><div class="label">👤 总人数</div><div class="value">'+(j.summary.total_headcount||0)+'</div></div><div class="kpi-card blue"><div class="label">经营岗</div><div class="value">'+(j.summary.direct_headcount||0)+'</div><div class="sub">'+(j.summary.direct_cost||0)+'元</div></div><div class="kpi-card orange"><div class="label">通用岗</div><div class="value">'+(j.summary.shared_headcount||0)+'</div><div class="sub">'+(j.summary.shared_cost||0)+'元</div></div><div class="kpi-card red"><div class="label">管理岗</div><div class="value">'+(j.summary.management_headcount||0)+'</div><div class="sub">'+(j.summary.management_cost||0)+'元</div></div>';
    filterPs();
    drawPieChart();
  }).catch(function(e){document.getElementById('ps-summary').innerHTML='<div class="error">'+e.message+'</div>';});
}
loadPersons();

function renderOa(){
  var data=ALL_PERSONS.slice();_sort(data,'oa');
  document.getElementById('oa-tbody').innerHTML=data.map(function(p,i){
    var tc={'经营岗':'tag-direct','通用岗':'tag-shared','管理岗':'tag-management'}[p.cost_type_label]||'';
    return '<tr><td>'+(i+1)+'</td><td>'+p.person_name+'</td><td>'+p.position_name+'</td><td><span class="cost-type-tag '+tc+'">'+p.cost_type_label+'</span></td><td class="text-right">'+p.total_cost.toLocaleString()+'</td><td style="font-size:11px;color:#999">'+p.present_months.join(', ')+'</td></tr>';
  }).join('');
  document.getElementById('oa-kpis').innerHTML='<div class="kpi-card purple"><div class="label">👤 总人数</div><div class="value">'+ALL_PERSONS.length+'</div><div class="sub">'+MONTHS.length+'个月</div></div><div class="kpi-card green"><div class="label">💰 总成本</div><div class="value">'+ALL_PERSONS.reduce(function(s,p){return s+p.total_cost;},0).toLocaleString()+'</div></div><div class="kpi-card blue"><div class="label">经营岗</div><div class="value">'+ALL_PERSONS.reduce(function(s,p){return p.cost_type_label==='经营岗'?s+p.total_cost:s;},0).toLocaleString()+'</div></div><div class="kpi-card orange"><div class="label">通用岗</div><div class="value">'+ALL_PERSONS.reduce(function(s,p){return p.cost_type_label==='通用岗'?s+p.total_cost:s;},0).toLocaleString()+'</div></div><div class="kpi-card red"><div class="label">管理岗</div><div class="value">'+ALL_PERSONS.reduce(function(s,p){return p.cost_type_label==='管理岗'?s+p.total_cost:s;},0).toLocaleString()+'</div></div>';
}
renderOa();

// ── AI 分析 ──
(function loadAiAnalysis(){
  fetch('/api/labor_report/ai_analysis')
    .then(function(r){return r.json()})
    .then(function(j){
      if(!j.success) throw new Error(j.message||'请求失败');
      document.getElementById('ai-summary').textContent=j.summary;
      var conclusions=j.conclusions||[];
      var container=document.getElementById('ai-conclusions');
      container.innerHTML=conclusions.map(function(c){
        var colorMap={'success':'#2ecc71','warning':'#f39c12','info':'#667eea','error':'#e74c3c'};
        var badgeMap={'success':'badge-green','warning':'badge-orange','info':'badge-blue','error':'badge-red'};
        var iconMap={'success':'✅','warning':'⚠️','info':'ℹ️','error':'❌'};
        var bc=colorMap[c.type]||'#667eea';
        return '<div class="card" style="border-left:4px solid '+bc+'">'+
          '<div class="card-title" style="display:flex;align-items:center;gap:6px">'+
          '<span class="badge '+(badgeMap[c.type]||'badge-blue')+'">'+(iconMap[c.type]||'📌')+'</span>'+
          c.title+'</div>'+
          '<p style="font-size:13px;color:#555;line-height:1.7;margin-bottom:8px">'+c.detail+'</p>'+
          (c.suggestion?'<div style="font-size:12px;color:#667eea;background:#f0f2ff;padding:8px 12px;border-radius:6px">💡 '+c.suggestion+'</div>':'')+
          '</div>';
      }).join('');
      document.getElementById('ai-loading').style.display='none';
      document.getElementById('ai-content').style.display='block';
    })
    .catch(function(e){
      document.getElementById('ai-loading').style.display='none';
      document.getElementById('ai-error').style.display='block';
      document.getElementById('ai-error').textContent='❌ 加载失败: '+e.message;
    });
})();

// ── 考勤排班加载 ──
function loadAttendance(){
  var month=document.getElementById('att-month').value;
  if(!month) return;
  document.getElementById('att-loading').style.display='block';
  document.getElementById('att-content').style.display='none';
  // 并行拉取 overview（趋势+当月汇总）和 persons（明细）
  Promise.all([
    fetch('/api/labor_report/overview').then(function(r){return r.json()}),
    fetch('/api/labor_report/persons?month='+month+'&store_id='+STORE).then(function(r){return r.json()})
  ]).then(function(results){
    var ov=results[0], ps=results[1];
    if(!ov.success||!ps.success) throw new Error('请求失败');
    
    // overview数据：6个月趋势
    var ovData=ov.data||[];
    var persons=ps.persons||[];
    var summary=ps.summary||{};
    
    // 当月销售数据：从 overview 中取对应月份
    var monthData=ovData.filter(function(d){return d.month===month})[0]||{};
    var totalSale=monthData.sale||0, totalProfit=monthData.profit||0;
    
    // KPI条
    var totalHrs=persons.reduce(function(s,p){return s+(p.work_hours||0);},0);
    var avgHrs=persons.length>0?(totalHrs/persons.length):0;
    var totalHrsStr=totalHrs.toFixed(0);
    document.getElementById('att-kpis').innerHTML=
      '<div class="kpi-card purple"><div class="label">📅 月份</div><div class="value">'+month+'</div><div class="sub">'+persons.length+'人</div></div>'+
      '<div class="kpi-card blue"><div class="label">⏱ 总工时</div><div class="value">'+totalHrsStr+'</div><div class="sub">均'+avgHrs.toFixed(1)+'h/人</div></div>'+
      '<div class="kpi-card orange"><div class="label">💰 总成本</div><div class="value">'+(summary.total_cost||0).toLocaleString()+'</div></div>'+
      '<div class="kpi-card green"><div class="label">⚡ 每工时产出</div><div class="value">销售'+(totalSale/(totalHrs||1)).toFixed(1)+'</div><div class="sub">毛利'+(totalProfit/(totalHrs||1)).toFixed(1)+'</div></div>';
    
    // 表格（简化：去掉每工时创销售/毛利，因为算不准）
    var tbody=document.getElementById('att-tbody');
    tbody.innerHTML=persons.map(function(p,i){
      var wh=p.work_hours||0;
      var days=Math.round(wh/10.5);
      var cost=p.total_cost||0;
      var base=p.base_salary||0;
      var perf=p.performance||0;
      var totalPay=base+perf;
      var hrRate=cost/(wh||1);
      var dailyWage=cost/(days||1);
      return '<tr><td>'+(i+1)+'</td><td>'+p.person_name+'</td><td>'+(p.position_name||'')+'</td><td>'+(p.cost_type_label||'')+'</td>'+
        '<td class="num">'+wh.toFixed(1)+'</td><td class="num">'+days+'</td>'+
        '<td class="num">'+base.toFixed(0)+'</td><td class="num">'+perf.toFixed(0)+'</td>'+
        '<td class="num">'+totalPay.toFixed(0)+'</td><td class="num">'+cost.toFixed(2)+'</td>'+
        '<td class="num">'+hrRate.toFixed(2)+'</td><td class="num">'+dailyWage.toFixed(0)+'</td></tr>';
    }).join('');
    
    // 图表1：每人工时对比（top20横向柱状图）
    destroyChart('att-hours');
    var topH=persons.slice().sort(function(a,b){return (b.work_hours||0)-(a.work_hours||0);}).slice(0,20);
    charts['att-hours']=new Chart(document.getElementById('chart-att-hours'),{
      type:'bar',data:{
        labels:topH.map(function(p){return p.person_name}),
        datasets:[{label:'工时(h)',data:topH.map(function(p){return p.work_hours||0}),backgroundColor:'rgba(56,189,248,.6)'}]
      },
      options:{responsive:true,indexAxis:'y',plugins:{legend:{display:false}},
        scales:{x:{title:{display:true,text:'工时'}}}}
    });
    
    // 图表2：时薪 vs 每工时创毛利（top20成本最高的人）
    destroyChart('att-cost');
    var topC=persons.slice().sort(function(a,b){return (b.total_cost||0)-(a.total_cost||0);}).slice(0,20);
    var perHrProfit=totalSale>0?totalProfit/totalHrs:0;
    charts['att-cost']=new Chart(document.getElementById('chart-att-cost'),{
      type:'bar',data:{
        labels:topC.map(function(p){return p.person_name}),
        datasets:[
          {label:'时薪成本',data:topC.map(function(p){return (p.total_cost||0)/(p.work_hours||1)}),backgroundColor:'rgba(239,68,68,.6)'},
          {label:'每工时创毛利',data:topC.map(function(){return perHrProfit}),backgroundColor:'rgba(34,197,94,.6)'},
        ]
      },
      options:{responsive:true,plugins:{tooltip:{mode:'index',intersect:false}},
        scales:{y:{title:{display:true,text:'元/工时'}}}}
    });
    
    // 图表3：全店人力效率趋势（6个月：人数、总成本、人工/毛利比）
    destroyChart('att-trend');
    var months=ovData.map(function(d){return d.month});
    charts['att-trend']=new Chart(document.getElementById('chart-att-trend'),{
      type:'line',data:{
        labels:months,
        datasets:[
          {label:'总成本(千元)',data:ovData.map(function(d){return (d.total_cost||0)/1000}),borderColor:'#f39c12',tension:.3,yAxisID:'y'},
          {label:'人工/毛利%',data:ovData.map(function(d){return d.labor_profit_ratio||0}),borderColor:'#ef4444',borderDash:[5,5],tension:.3,yAxisID:'y1'},
          {label:'人数',data:ovData.map(function(d){return d.total_headcount||0}),borderColor:'#38bdf8',tension:.3,yAxisID:'y2'},
        ]
      },
      options:{
        responsive:true,interaction:{mode:'index',intersect:false},
        scales:{
          y:{type:'linear',position:'left',title:{display:true,text:'成本(千元)'}},
          y1:{type:'linear',position:'right',grid:{drawOnChartArea:false},title:{display:true,text:'%'}},
          y2:{type:'linear',position:'right',grid:{drawOnChartArea:false},title:{display:true,text:'人数'}}
        }
      }
    });
    
    document.getElementById('att-loading').style.display='none';
    document.getElementById('att-content').style.display='block';
  }).catch(function(e){
    document.getElementById('att-loading').style.display='none';
    document.getElementById('att-error').style.display='block';
    document.getElementById('att-error').textContent='❌ 加载失败: '+e.message;
  });
}
// 初始加载
(function(){var s=document.getElementById('att-month');if(s)loadAttendance();})();

// ── 初始化图表（等 DOM ready）──
if(document.readyState==='complete')drawAllCharts();else window.addEventListener('load',drawAllCharts);
</script>
</body>
</html>"""
