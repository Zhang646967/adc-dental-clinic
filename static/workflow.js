/* Error navigation only: native forms and all business values remain untouched. */
(function () {
  'use strict';
  var summary = document.querySelector('[data-error-summary]');
  if (!summary) return;
  function reveal(element) {
    for (var parent = element.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
  }
  reveal(summary);
  summary.focus();
  document.querySelectorAll('[data-error-summary] a[href^="#"]').forEach(function (link) {
    link.addEventListener('click', function (event) {
      var target = document.getElementById(link.hash.slice(1));
      if (!target) return;
      reveal(target);
      var input = target.matches('input,select,textarea') ? target : target.querySelector('input,select,textarea');
      if (input) { event.preventDefault(); input.focus(); input.scrollIntoView({block: 'center'}); }
    });
  });
})();
