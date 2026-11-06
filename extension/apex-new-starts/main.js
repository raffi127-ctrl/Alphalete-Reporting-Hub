// The PAGE half. Runs in Apex's own world, which is the whole reason the
// extension is split in two.
//
// The engine drives Kendo widgets through their own API
// ($(el).data('kendoComboBox')) and reads Angular's bindings. Those objects
// belong to the page. A normal content script runs in an isolated world where
// `window.kendo` and `window.angular` do not exist, so the engine would find
// every dropdown "unsettable" -- the exact class of failure that cost five
// rounds on Marital Status. Hence "world": "MAIN" for this half, and a
// CustomEvent as the only way in.
(function () {
  'use strict';
  if (window.__ansBridge) return;
  window.__ansBridge = true;

  document.addEventListener('ans-run', function (e) {
    const cfg = (e && e.detail) || {};
    if (typeof window.__ansEngine !== 'function') {
      document.dispatchEvent(new CustomEvent('ans-failed', {
        detail: {error: 'The run engine did not load. Reload this Apex tab.'}
      }));
      return;
    }
    try {
      window.__ansEngine(cfg);
    } catch (err) {
      document.dispatchEvent(new CustomEvent('ans-failed', {
        detail: {error: String((err && err.message) || err)}
      }));
    }
  });

  // Tell the other half the page is ready to be driven, so the button can say
  // so instead of appearing dead.
  document.dispatchEvent(new CustomEvent('ans-engine-ready', {
    detail: {ok: typeof window.__ansEngine === 'function'}
  }));
})();
