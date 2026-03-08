/**
 * 通用 KPI 卡片组件：按配置数组渲染多个指标卡片，支持 number/money/percent 格式化及可选样式类。
 */
(function () {
  'use strict';

  function formatValue(item) {
    var v = item.value;
    if (v == null || v === '') return '-';
    var format = item.format || 'number';
    if (format === 'money') {
      return '¥' + Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    }
    if (format === 'percent') {
      return Number(v).toFixed(2) + '%';
    }
    return Number(v) >= 10000 ? (Number(v) / 10000).toFixed(1) + '万' : Number(v).toLocaleString();
  }

  /**
   * @param {string} containerId - 容器元素 id（通常为 kpi-row 的 id）
   * @param {Object} options - 可选配置，如 { rowClass: 'kpi-row' }
   * @returns {{ render: function(Array) }}
   */
  window.createKpiCards = function (containerId, options) {
    var opts = options || {};
    var container = document.getElementById(containerId);
    if (!container) return { render: function () {} };

    function render(data) {
      if (!data || !data.length) return;
      var html = '';
      data.forEach(function (item) {
        var text = item.label != null ? String(item.label).replace(/</g, '&lt;') : '';
        var val = formatValue(item);
        var valueClass = 'value';
        if (item.valueClass) valueClass += ' ' + item.valueClass;
        html += '<div class="kpi-card"><div class="label">' + text + '</div><div class="' + valueClass + '">' + val + '</div></div>';
      });
      container.innerHTML = html;
    }

    return { render: render };
  };
})();
