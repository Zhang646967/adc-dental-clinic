/* Native page controls only. Business forms and permission checks stay server-side. */
(function () {
  "use strict";
  var nav = document.getElementById("workspace-navigation");
  var toggle = document.querySelector(".nav-toggle");
  if (nav && toggle) {
    var narrow = window.matchMedia("(max-width: 900px)");
    toggle.hidden = false;
    function setNavigation(open) {
      nav.classList.toggle("is-collapsed", !open);
      toggle.setAttribute("aria-expanded", String(open));
    }
    function resizeNavigation() {
      if (narrow.matches && nav.contains(document.activeElement)) toggle.focus();
      setNavigation(!narrow.matches);
    }
    toggle.addEventListener("click", function () {
      setNavigation(toggle.getAttribute("aria-expanded") !== "true");
    });
    narrow.addEventListener("change", resizeNavigation);
    resizeNavigation();
  }
  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;
    button.hidden = false;
    function hidePassword() {
      input.type = "password";
      button.textContent = "显示密码";
      button.setAttribute("aria-pressed", "false");
    }
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "隐藏密码" : "显示密码";
      button.setAttribute("aria-pressed", String(show));
    });
    input.form.addEventListener("submit", hidePassword);
  });
})();
