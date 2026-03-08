/**
 * 通用图表组件：封装 ECharts 初始化与配置，支持趋势图、饼图、柱状图。
 * 依赖：页面已加载 ECharts（echarts）。
 */
(function () {
  'use strict';

  function getEl(id) {
    return document.getElementById(id);
  }

  /**
   * 基础图表：管理容器、实例与 resize。
   */
  function BaseChart(containerId) {
    this.container = getEl(containerId);
    this.chart = null;
    var self = this;
    function onResize() {
      if (self.chart) self.chart.resize();
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('resize', onResize);
    }
  }

  BaseChart.prototype.ensureInit = function () {
    if (typeof echarts === 'undefined') return false;
    if (!this.container) return false;
    if (!this.chart) this.chart = echarts.init(this.container);
    return true;
  };

  BaseChart.prototype.setOption = function (option) {
    if (!this.ensureInit()) return;
    this.chart.setOption(option);
  };

  BaseChart.prototype.dispose = function () {
    if (this.chart) {
      this.chart.dispose();
      this.chart = null;
    }
  };

  /**
   * 趋势图（折线/柱状，双系列）：data = { labels: [], series: [{ name, data, type?: 'line'|'bar' }] }，options 可覆盖 tooltip/legend/grid 等
   */
  window.createTrendChart = function (containerId) {
    var base = new BaseChart(containerId);
    return {
      render: function (data, options) {
        if (!data || !data.labels || !data.series || !data.series.length) return;
        if (!base.ensureInit()) return;
        var option = {
          tooltip: options && options.tooltip ? options.tooltip : { trigger: 'axis' },
          legend: { data: data.series.map(function (s) { return s.name; }), bottom: 0, textStyle: { color: '#94a3b8' } },
          grid: { left: 55, right: 25, top: 45, bottom: 75 },
          xAxis: { type: 'category', data: data.labels, axisLabel: { color: '#94a3b8', rotate: 40, fontSize: 10, interval: 0 } },
          yAxis: { type: 'value', min: 0, axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#334155' } } },
          series: data.series.map(function (s, i) {
            var colors = ['#38bdf8', '#34d399', '#fbbf24'];
            return {
              name: s.name,
              type: s.type || 'line',
              data: s.data,
              itemStyle: { color: s.color || colors[i % colors.length] },
              lineStyle: s.type === 'line' ? { color: s.color || colors[i % colors.length] } : undefined
            };
          })
        };
        if (options) {
          if (options.grid) option.grid = options.grid;
          if (options.yAxis) option.yAxis = options.yAxis;
        }
        base.setOption(option);
      },
      resize: function () { if (base.chart) base.chart.resize(); },
      dispose: function () { base.dispose(); }
    };
  };

  /**
   * 饼图：data = [{ name, value }]，options 可覆盖默认配置（如 radius, color）
   */
  window.createPieChart = function (containerId, defaultOptions) {
    var base = new BaseChart(containerId);
    var opts = defaultOptions || {};
    return {
      render: function (data, options) {
        if (!data || !data.length) return;
        if (!base.ensureInit()) return;
        var option = {
          tooltip: { trigger: 'item' },
          legend: opts.legend !== false ? { bottom: 0, left: 'center', textStyle: { color: '#94a3b8', fontSize: 11 }, type: 'scroll' } : undefined,
          color: opts.color || ['#38bdf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#64748b', '#22d3ee', '#fb923c', '#c084fc', '#4ade80'],
          series: [{
            type: 'pie',
            radius: opts.radius || ['40%', '70%'],
            center: opts.center || ['50%', '45%'],
            data: data,
            label: opts.label !== false ? { show: true, position: 'outside', color: '#e2e8f0', fontSize: 11 } : undefined,
            labelLine: opts.labelLine !== false ? { show: true, lineStyle: { color: '#64748b' } } : undefined,
            emphasis: { scale: true }
          }]
        };
        if (options && typeof options === 'object') {
          for (var k in options) option[k] = options[k];
        }
        base.setOption(option);
      },
      setOption: function (option) {
        if (!base.ensureInit()) return;
        base.setOption(option);
      },
      resize: function () { if (base.chart) base.chart.resize(); },
      dispose: function () { base.dispose(); }
    };
  };

  /**
   * 柱状图：data = { xAxis: [] 或 categories, series: [{ name, data }] }；horizontal 为 true 时为横向柱状图
   */
  window.createBarChart = function (containerId, horizontal) {
    var base = new BaseChart(containerId);
    return {
      render: function (data) {
        if (!data || !data.series || !data.series.length) return;
        if (!base.ensureInit()) return;
        var categories = data.xAxis || data.categories || [];
        var option = {
          tooltip: { trigger: 'axis' },
          grid: { left: 80, right: 20, top: 10, bottom: 30 },
          xAxis: horizontal
            ? { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#334155' } } }
            : { type: 'category', data: categories, axisLabel: { color: '#94a3b8' } },
          yAxis: horizontal
            ? { type: 'category', data: categories, axisLabel: { color: '#94a3b8' } }
            : { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#334155' } } },
          series: data.series.map(function (s, i) {
            var colors = ['#38bdf8', '#34d399', '#fbbf24'];
            return { name: s.name, type: 'bar', data: s.data, itemStyle: { color: s.color || colors[i % colors.length] } };
          })
        };
        base.setOption(option);
      },
      resize: function () { if (base.chart) base.chart.resize(); },
      dispose: function () { base.dispose(); }
    };
  };
})();
