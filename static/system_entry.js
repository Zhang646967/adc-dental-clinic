/* Personal, in-memory observations only. Never submit business commands. */
(function () {
  'use strict';
  function readResults(cards) {
    return cards.map(function (card) {
      var selected = card.querySelector('input[type="radio"]:checked');
      return { title: card.querySelector('h3').textContent.trim(), value: selected ? selected.value : 'NOT_CHECKED' };
    });
  }
  function summarize(results) {
    var counts = { NOT_CHECKED: 0, MATCHED: 0, ISSUE: 0 };
    results.forEach(function (row) { counts[Object.hasOwn(counts, row.value) ? row.value : 'NOT_CHECKED'] += 1; });
    return '尚未核验 ' + counts.NOT_CHECKED + ' 条 · 符合预期 ' + counts.MATCHED + ' 条 · 发现问题 ' + counts.ISSUE + ' 条';
  }
  function report(results) {
    var labels = { NOT_CHECKED: '尚未核验', MATCHED: '符合预期', ISSUE: '发现问题' };
    return ['ADC 业务个人核对记录', '', summarize(results), '',
      '以下仅为本页人工选择，未经独立验证，不是系统测试报告或正式验收结论。',
      '未选择的路线保持“尚未核验”；本页不记录患者、账号、病历或资金明细。', '']
      .concat(results.map(function (row, index) { return (index + 1) + '. ' + row.title + '：' + (labels[row.value] || labels.NOT_CHECKED); }))
      .concat(['', '反馈发现问题时，请提供路线、操作、预期与实际结果；不要附密码或真实患者资料。', '']).join('\n');
  }
  function init() {
    var filter = document.getElementById('role-filter');
    if (!filter) return;
    var cards = Array.from(document.querySelectorAll('[data-scenario]'));
    // Browsers may restore radio values across reload/back navigation. The page
    // explicitly starts a new observation; it does not silently retain results.
    cards.forEach(function (card) { card.querySelector('input[value="NOT_CHECKED"]').checked = true; });
    filter.value = 'all';
    document.querySelectorAll('.verification-tools, .result-picker, .verification-summary').forEach(function (node) { node.hidden = false; });
    var visibleText = document.getElementById('visible-routes');
    var summary = document.getElementById('result-summary');
    function update() { summary.textContent = summarize(readResults(cards)); }
    function applyFilter() {
      var visible = 0;
      cards.forEach(function (card) {
        card.hidden = filter.value !== 'all' && !card.dataset.roles.split('、').includes(filter.value);
        if (!card.hidden) visible += 1;
      });
      visibleText.textContent = filter.value === 'all' ? '显示全部 ' + visible + ' 条路线' : '显示 ' + visible + ' 条与“' + filter.value + '”相关的路线';
    }
    filter.addEventListener('change', applyFilter);
    cards.forEach(function (card) { card.addEventListener('change', update); });
    document.getElementById('expand-routes').addEventListener('click', function () {
      cards.filter(function (card) { return !card.hidden; }).forEach(function (card) { card.querySelector('details').open = true; });
    });
    document.getElementById('download-results').addEventListener('click', function () {
      // Include all six routes, including filtered-out ones, so export cannot
      // turn an unseen/unverified scenario into an implied passing result.
      var url = URL.createObjectURL(new Blob(['\ufeff', report(readResults(cards))], { type: 'text/plain;charset=utf-8' }));
      var anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'ADC-personal-verification.txt';
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
    update(); applyFilter();
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { summarize: summarize, report: report };
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
  }
}());
