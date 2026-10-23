(function () {
  "use strict";
  var key = "adc-display-mode";
  function apply(mode) {
    var large = mode === "comfortable";
    document.documentElement.dataset.display = large ? "comfortable" : "standard";
    document.querySelectorAll(".mode-toggle").forEach(function (button) {
      button.hidden = false;
      button.textContent = large ? "切回标准模式" : "大字简明模式";
      button.setAttribute("aria-pressed", String(large));
    });
  }
  var saved = "standard";
  try { saved = localStorage.getItem(key) || saved; } catch (_) {}
  apply(saved);
  document.querySelectorAll(".mode-toggle").forEach(function (button) {
    button.addEventListener("click", function () {
      var mode = document.documentElement.dataset.display === "comfortable" ? "standard" : "comfortable";
      apply(mode);
      try { localStorage.setItem(key, mode); } catch (_) {}
    });
  });
  document.querySelectorAll(".print-page").forEach(function (button) {
    button.addEventListener("click", function () { window.print(); });
  });
})();
