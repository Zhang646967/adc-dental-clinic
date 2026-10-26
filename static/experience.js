(function () {
  "use strict";
  // Retire the former global display switch, including saved preferences.
  document.documentElement.removeAttribute("data-display");
  try { localStorage.removeItem("adc-display-mode"); } catch (_) {}
  document.querySelectorAll(".print-page").forEach(function (button) {
    button.addEventListener("click", function () { window.print(); });
  });
})();
