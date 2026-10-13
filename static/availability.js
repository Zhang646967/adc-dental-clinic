/* A local-time widget constraint, not an authorization/timezone decision.
 * Values represent Beijing wall time. Never silently move the user's end time.
 * Server validation is authoritative, including when JavaScript is unavailable.
 */
(() => {
  'use strict';
  function nextMinute(value) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) || value.startsWith('0000')) return '';
    const n = new Date(value + ':00Z'); // Neutral arithmetic on wall-clock digits, NOT browser timezone.
    if (!Number.isFinite(n.getTime()) || n.toISOString().slice(0, 16) !== value) return '';
    n.setUTCMinutes(n.getUTCMinutes() + 1);
    const result = n.toISOString().slice(0, 16);
    return /^\d{4}-/.test(result) ? result : '';
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {nextMinute};
  if (typeof document === 'undefined') return;
  const form = document.querySelector('[data-availability-form]');
  if (!form) return;
  const start = form.querySelector('[name=start]');
  const end = form.querySelector('[name=end]');
  if (!start || !end) return;
  const initialMin = end.getAttribute('min') || '';
  const update = () => {
    const min = nextMinute(start.value);
    end.min = min || initialMin;
    end.setCustomValidity(start.value && end.value && end.value <= start.value ? '结束时间必须晚于开始时间。' : '');
  };
  start.addEventListener('input', update); end.addEventListener('input', update); update();
})();
