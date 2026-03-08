/**
 * 下钻状态管理：与 URL 同步，提供面包屑渲染与清除。
 */
(function () {
  'use strict';

  var state = { level: 'overview', category: '', brand: '' };

  function initFromUrl() {
    try {
      var q = new URLSearchParams(window.location.search);
      var c = q.get('category');
      var b = q.get('brand');
      state.category = c != null ? decodeURIComponent(c) : '';
      state.brand = b != null ? decodeURIComponent(b) : '';
      state.level = state.brand ? 'brand' : (state.category ? 'category' : 'overview');
    } catch (e) {}
  }

  function updateUrl() {
    try {
      var u = new URL(window.location.href);
      if (state.category) u.searchParams.set('category', state.category); else u.searchParams.delete('category');
      if (state.brand) u.searchParams.set('brand', state.brand); else u.searchParams.delete('brand');
      window.history.replaceState({}, '', u.pathname + (u.searchParams.toString() ? '?' + u.searchParams.toString() : ''));
    } catch (e) {}
  }

  /**
   * @param {Object} options - { onDrillChange: function(state) }
   * @returns {{ setLevel: function, getState: function, renderBreadcrumb: function, clear: function, syncFromUrl: function }}
   */
  window.createDrillManager = function (options) {
    var opts = options || {};
    initFromUrl();

    function setLevel(level, category, brand) {
      state.level = level || 'overview';
      state.category = (category != null && category !== undefined) ? String(category) : '';
      state.brand = (brand != null && brand !== undefined) ? String(brand) : '';
      updateUrl();
      if (typeof opts.onDrillChange === 'function') opts.onDrillChange(getState());
    }

    function getState() {
      return { level: state.level, category: state.category, brand: state.brand };
    }

    function renderBreadcrumb(containerId) {
      var container = document.getElementById(containerId);
      if (!container) return;
      if (!state.category && !state.brand) {
        container.innerHTML = '';
        container.style.display = 'none';
        return;
      }
      container.style.display = '';
      var segs = [];
      segs.push('<a href="javascript:void(0)" class="insight-breadcrumb-link" data-category="" data-brand="" style="color:#38bdf8;text-decoration:none;">好特卖沈阳仓</a>');
      if (state.category) {
        var catEnc = (state.category || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
        if (state.brand) {
          segs.push('<a href="javascript:void(0)" class="insight-breadcrumb-link" data-category="' + catEnc + '" data-brand="" style="color:#38bdf8;text-decoration:none;">' + (state.category || '').replace(/</g, '&lt;') + '</a>');
        } else {
          segs.push('<span style="color:#e2e8f0;">' + (state.category || '').replace(/</g, '&lt;') + '</span>');
        }
      }
      if (state.brand) segs.push('<span style="color:#e2e8f0;">' + (state.brand || '').replace(/</g, '&lt;') + '</span>');
      segs.push(' <a href="javascript:void(0)" id="insightClearDrill" style="margin-left:8px;color:#38bdf8;">清除下钻</a>');
      container.innerHTML = segs.join(' &gt; ');
    }

    function clear() {
      setLevel('overview');
    }

    return {
      setLevel: setLevel,
      getState: getState,
      renderBreadcrumb: renderBreadcrumb,
      clear: clear,
      syncFromUrl: initFromUrl
    };
  };
})();
