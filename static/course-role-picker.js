(() => {
  const panel = document.querySelector('[data-course-role-picker]');
  const form = document.querySelector('#login-form');
  if (!panel || !form) return;

  const endpoint = panel.dataset.endpoint;
  const storageKey = 'adc-course-invite:' + endpoint;
  const supplied = new URLSearchParams(location.hash.slice(1)).get('course');
  const invitePattern = /^[A-Za-z0-9_-]{43}$/;
  let invite = supplied;
  try {
    if (supplied && invitePattern.test(supplied)) sessionStorage.setItem(storageKey, supplied);
    if (supplied === null) invite = sessionStorage.getItem(storageKey);
  } catch (_) {
    // The current invitation still works when the browser blocks storage.
  }
  if (supplied !== null) history.replaceState(null, '', location.pathname + location.search);
  if (!invitePattern.test(invite || '')) return;

  const choices = panel.querySelector('[data-course-role-options]');
  const message = panel.querySelector('[data-course-role-message]');
  const username = form.elements.username;
  const password = form.elements.password;
  const submit = form.querySelector('button[type=submit]');
  const csrf = form.elements.csrfmiddlewaretoken.value;
  let filling = false;

  async function request(role) {
    const response = await fetch(endpoint, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'X-CSRFToken': csrf, Accept: 'application/json'},
      body: new URLSearchParams(role ? {invite, role} : {invite}),
    });
    const body = await response.json();
    if (!response.ok || !body.ok) {
      if (body.code === 'COURSE_UNAVAILABLE' && !role) {
        try { sessionStorage.removeItem(storageKey); } catch (_) { /* optional storage */ }
      }
      throw new Error(body.code === 'COURSE_UNAVAILABLE'
        ? '此体验账号暂不可用。你可以手动登录。'
        : '暂时无法读取体验账号。你可以手动登录。');
    }
    return body.data;
  }

  async function select(button, role) {
    if (filling) return;
    filling = true;
    message.textContent = '正在填入体验账号…';
    username.value = '';
    password.value = '';
    const buttons = [...choices.querySelectorAll('button')];
    buttons.forEach(item => { item.disabled = true; item.setAttribute('aria-pressed', 'false'); });
    username.disabled = password.disabled = submit.disabled = true;
    try {
      const fields = await request(role);
      username.value = fields.username;
      password.value = fields.password;
      const details = form.closest('details');
      if (details) details.open = true;
      button.setAttribute('aria-pressed', 'true');
      message.textContent = '已填好账号和密码。请点击登录。';
    } catch (error) {
      message.textContent = error.message;
    } finally {
      filling = false;
      username.disabled = password.disabled = submit.disabled = false;
      buttons.forEach(item => { item.disabled = false; });
    }
  }

  form.addEventListener('submit', event => { if (filling) event.preventDefault(); });
  request().then(data => {
    for (const choice of data.roles) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'button secondary';
      button.textContent = choice.label;
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => select(button, choice.id));
      choices.append(button);
    }
    panel.hidden = data.roles.length === 0;
  }).catch(error => {
    // A regular visitor or expired link can still use the standard login form.
    panel.hidden = false;
    message.textContent = error.message;
  });
})();
