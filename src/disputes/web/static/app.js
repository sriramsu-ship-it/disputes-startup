// Minimal progressive enhancement (CSP: script-src 'self', no inline scripts or styles).
(function () {
  "use strict";
  // Tenant switcher: navigate to the chosen client's queue.
  var sel = document.querySelector("[data-switch-tenant]");
  if (sel) {
    sel.addEventListener("change", function () {
      window.location.href = "/ops/t/" + encodeURIComponent(sel.value) + "/queue";
    });
  }
  // Deadline ruler marks: positions come from data-at (percent) because inline styles are blocked by CSP.
  document.querySelectorAll(".ruler-mark[data-at]").forEach(function (el) {
    var v = parseFloat(el.getAttribute("data-at"));
    if (!isNaN(v)) { el.style.setProperty("--at", Math.max(0, Math.min(100, v)) + "%"); }
  });
})();
