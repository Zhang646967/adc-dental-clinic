(() => {
  const list = document.querySelector('[data-report-notices]');
  if (!list) return;

  // Keep only the chosen control's DOM id on this browser history entry.
  list.addEventListener('click', event => {
    const link = event.target.closest('.report-actions a[id]');
    if (!link || event.defaultPrevented || event.button !== 0 ||
        event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    history.replaceState({ ...history.state, reportNoticeControl: link.id }, '');
  });

  window.addEventListener('pageshow', event => {
    const { reportNoticeControl: id, ...remaining } = history.state || {};
    if (!id) return;
    history.replaceState(remaining, '');
    const navigation = performance.getEntriesByType('navigation')[0];
    if (!event.persisted && navigation?.type !== 'back_forward') return;
    const link = document.getElementById(id);
    if (!list.contains(link) || !link.matches('.report-actions a[id]')) return;
    requestAnimationFrame(() => {
      link.focus({ preventScroll: true });
      link.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    });
  });
})();
