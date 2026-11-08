// R-24 active review time. Counts a second only when the page is visible, the window has focus,
// and there was keyboard/mouse/scroll input within the idle cutoff (config idle_cutoff_s, default 60).
// Sends the accumulated seconds every 30 s and when the page is hidden or closed.
(function () {
  "use strict";
  var root = document.querySelector(".casefile[data-track='yes']");
  if (!root) { return; }
  var url = "/ops/t/" + encodeURIComponent(root.dataset.tenantId) + "/cases/" +
            encodeURIComponent(root.dataset.caseId) + "/metrics";
  var csrf = root.dataset.csrf;
  var idleCutoffMs = (parseInt(root.dataset.idleCutoff, 10) || 60) * 1000;
  var focused = document.hasFocus();
  var lastInput = Date.now();
  var pending = 0;

  function active() {
    return document.visibilityState === "visible" && focused && (Date.now() - lastInput) <= idleCutoffMs;
  }
  ["keydown", "mousemove", "mousedown", "scroll", "wheel", "touchstart"].forEach(function (ev) {
    window.addEventListener(ev, function () { lastInput = Date.now(); }, { passive: true });
  });
  window.addEventListener("focus", function () { focused = true; lastInput = Date.now(); });
  window.addEventListener("blur", function () { focused = false; });
  setInterval(function () { if (active()) { pending += 1; } }, 1000);

  function flush(useBeacon) {
    if (pending <= 0) { return; }
    var body = JSON.stringify({ active_seconds: pending, csrf: csrf });
    pending = 0;
    if (useBeacon && navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
    } else {
      fetch(url, { method: "POST", credentials: "same-origin", keepalive: true,
                   headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: body });
    }
  }
  setInterval(function () { flush(false); }, 30000);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") { flush(true); }
  });
  window.addEventListener("pagehide", function () { flush(true); });
  document.querySelectorAll(".decision form").forEach(function (f) {
    f.addEventListener("submit", function () { flush(true); });
  });
})();
