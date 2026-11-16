(() => {
  const form = document.querySelector('[data-booking-confirmation]');
  if (!form || !window.fetch || !window.AbortController) return;

  const submit = form.querySelector('button[type="submit"]');
  const back = form.querySelector('[data-confirm-back]');
  const feedback = document.querySelector('[data-booking-feedback]');
  const title = feedback.querySelector('[data-feedback-title]');
  const message = feedback.querySelector('[data-feedback-message]');
  const query = feedback.querySelector('[data-query-booking]');
  const reselect = feedback.querySelector('[data-reselect-booking]');
  const visitList = feedback.querySelector('[data-visit-list]');
  const kind = form.dataset.bookingConfirmation;
  const operation = kind === 'reschedule' ? '改期' : '预约';
  let resultFields;

  async function send(url, fields) {
    const controller = new AbortController();
    const deadline = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url, {
        method: 'POST',
        body: fields,
        headers: {Accept: 'application/json'},
        credentials: 'same-origin',
        signal: controller.signal,
      });
      const json = response.headers.get('content-type')?.includes('application/json');
      if (response.redirected || [401, 403].includes(response.status) || (response.status === 409 && !json)) {
        location.replace(form.dataset.subjectUrl);
        return null;
      }
      if (!json) throw new Error('Confirmation outcome unavailable');
      return await response.json();
    } finally {
      window.clearTimeout(deadline);
    }
  }

  function openVisit(result) {
    if (result.state !== 'SAVED' || typeof result.url !== 'string') return false;
    const url = new URL(result.url, location.href);
    if (url.origin !== location.origin) return false;
    location.assign(url.href);
    return true;
  }

  function showFeedback(heading, text, {canQuery = false, canReselect = false} = {}) {
    form.hidden = true;
    feedback.hidden = false;
    title.textContent = heading;
    message.textContent = text;
    query.hidden = !canQuery;
    reselect.hidden = !canReselect;
    visitList.hidden = canReselect && !feedback.hasAttribute('data-source-visit');
    title.focus();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submit.disabled) return;

    const fields = new FormData(form);
    resultFields = new FormData();
    resultFields.set('kind', kind);
    resultFields.set('proposal_token', fields.get(kind === 'reschedule' ? 'proposal_token' : 'token'));
    resultFields.set('csrfmiddlewaretoken', fields.get('csrfmiddlewaretoken'));
    resultFields.set('workspace_token', fields.get('workspace_token'));
    submit.disabled = true;
    submit.textContent = '正在提交…';
    form.setAttribute('aria-busy', 'true');
    back.hidden = true;

    try {
      const result = await send(form.action, fields);
      if (result === null || openVisit(result)) return;
      if (result.state === 'REJECTED') {
        const original = kind === 'reschedule' ? ' 原预约可从原就诊详情核对。' : '';
        showFeedback('本次' + operation + '未保存', result.message + original, {canReselect: true});
        resultFields = undefined;
        return;
      }
    } catch {
      // The command may have committed before the response was lost.
    } finally {
      form.removeAttribute('aria-busy');
    }
    query.textContent = '查询本次' + operation + '结果';
    showFeedback('本次' + operation + '结果暂未确认', '可以先查询这次提交是否已保存。', {canQuery: true});
  });

  query.addEventListener('click', async () => {
    if (!resultFields || query.disabled) return;
    query.disabled = true;
    message.textContent = '正在核对本次提交…';
    try {
      const result = await send(form.dataset.resultUrl, resultFields);
      if (result === null || openVisit(result)) return;
      if (result.state === 'REJECTED') {
        message.textContent = result.message;
        query.hidden = true;
        visitList.focus();
        resultFields = undefined;
        return;
      }
      message.textContent = '暂未查到本次提交的结果。你可以稍后再查，或查看已有预约。';
    } catch {
      message.textContent = '暂时无法连接。请恢复网络后再查询。';
    } finally {
      query.disabled = false;
    }
  });
})();
