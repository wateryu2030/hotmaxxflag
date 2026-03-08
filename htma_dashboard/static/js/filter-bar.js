/**
 * 通用筛选器逻辑：与现有 DOM 协同，统一管理周期/日期并与 URL 同步。
 * 不替换品类级联 DOM，仅提供 getQueryParams()、syncFromUrl()、updateUrl() 供主页面使用。
 */
(function () {
  'use strict';

  function getEl(id) {
    return document.getElementById(id);
  }

  /**
   * @param {Object} options - { containerId, onApply }
   * @returns {{ getQueryParams: function(), syncFromUrl: function(), updateUrl: function(), apply: function() }}
   */
  window.createFilterBar = function (options) {
    const opts = options || {};
    const container = opts.containerId ? getEl(opts.containerId) : null;

    var state = {
      period: 'recent30',
      startDate: '',
      endDate: ''
    };

    function readFromDom() {
      var startIn = getEl('startDate');
      var endIn = getEl('endDate');
      if (startIn && endIn) {
        state.startDate = (startIn.value || '').replace(/\//g, '-').trim();
        state.endDate = (endIn.value || '').replace(/\//g, '-').trim();
      }
      var activeTab = document.querySelector('.filter-bar .tab-btn.active[data-period]');
      if (activeTab) {
        state.period = activeTab.getAttribute('data-period') || 'recent30';
      }
      if (state.startDate && state.endDate && state.startDate.length === 10 && state.endDate.length === 10) {
        state.period = 'custom';
      }
    }

    function writeToDom() {
      var startIn = getEl('startDate');
      var endIn = getEl('endDate');
      if (startIn) startIn.value = state.startDate;
      if (endIn) endIn.value = state.endDate;
      var tabs = document.querySelectorAll('.filter-bar .tab-btn[data-period]');
      tabs.forEach(function (btn) {
        if ((btn.getAttribute('data-period') || '') === state.period) {
          btn.classList.add('active');
        } else {
          btn.classList.remove('active');
        }
      });
      var dateRangeInline = getEl('dateRangeInline');
      if (dateRangeInline) dateRangeInline.style.display = state.period === 'custom' ? 'inline-flex' : 'none';
    }

    function initFromUrl() {
      try {
        var q = new URLSearchParams(window.location.search);
        var s = (q.get('start_date') || '').replace(/\//g, '-').trim();
        var e = (q.get('end_date') || '').replace(/\//g, '-').trim();
        var p = q.get('period') || '';
        if (s && e && s.length === 10 && e.length === 10) {
          state.startDate = s;
          state.endDate = e;
          state.period = 'custom';
        } else if (p) {
          state.period = p;
        }
        writeToDom();
      } catch (err) {}
    }

    /**
     * 返回用于 API 的查询参数对象（仅周期与日期；品类等由主页面合并）。
     */
    function getQueryParams() {
      readFromDom();
      var params = {};
      if (state.period) params.period = state.period;
      if (state.startDate && state.startDate.length === 10) params.start_date = state.startDate;
      if (state.endDate && state.endDate.length === 10) params.end_date = state.endDate;
      return params;
    }

    function updateUrl(extraParams) {
      try {
        var params = getQueryParams();
        if (extraParams) {
          Object.keys(extraParams).forEach(function (k) {
            if (extraParams[k] != null && extraParams[k] !== '') params[k] = extraParams[k];
          });
        }
        var url = new URL(window.location.href);
        ['period', 'start_date', 'end_date', 'category_large_code', 'category_mid_code', 'category_small_code', 'category', 'brand'].forEach(function (k) {
          if (params[k] != null && params[k] !== '') {
            url.searchParams.set(k, params[k]);
          } else {
            url.searchParams.delete(k);
          }
        });
        window.history.replaceState({}, '', url.toString());
      } catch (err) {}
    }

    function apply() {
      updateUrl();
      if (typeof opts.onApply === 'function') opts.onApply(getQueryParams());
    }

    initFromUrl();

    return {
      getQueryParams: getQueryParams,
      syncFromUrl: initFromUrl,
      updateUrl: updateUrl,
      apply: apply
    };
  };
})();
