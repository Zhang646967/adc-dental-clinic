// Real Chromium against the explicitly prepared public synthetic Mac demo.
// Credentials, cookies and workspace tokens are read privately and never output.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const bundle = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(path.join(bundle, 'plan.json'), 'utf8'));
if (plan.mode !== 'mac_tunnel' || !plan.read_only || !/^[a-z0-9-]+\.trycloudflare\.com$/.test(plan.host)) {
  throw new Error('Explicit read-only Mac demo bundle required.');
}
const base = 'https://' + plan.host;
const privateDir = path.join(bundle, 'private');
const credentials = {};
for (const line of fs.readFileSync(path.join(privateDir, 'demo-credentials.txt'), 'utf8').split('\n')) {
  const fields = line.split('|').map(x => x.trim());
  if (fields.length === 3 && /^LOCAL/.test(fields[0])) credentials[fields[1]] = fields[2];
}
const report = {scope: 'Real public Chromium, synthetic read-only course demo; bounded checks',
  host: plan.host, checks: [], page_errors: 0, public_release_approved: false};
function check(name, passed) {
  report.checks.push({check: name, passed: Boolean(passed)});
  if (!passed) throw new Error('Browser check failed: ' + name);
}
let browser;
(async () => {
  // Installed Chrome with a new temporary profile; no existing user profile.
  browser = await chromium.launch({channel: 'chrome', headless: true});
  report.browser_version = browser.version();
  for (const [user, route, clinic, patient] of [
    ['front_a', '/frontdesk/', '1', false], ['front_b', '/frontdesk/', '2', false],
    ['manager_a', '/manager/', '1', false], ['doctor_a', '/doctor/', null, false],
    ['hq_demo', '/headquarters/', null, false], ['finance_demo', '/financial-workspace/', null, false],
    ['tech_demo', '/technical/', null, false], ['patient_demo_a', '/portal/', null, true],
    ['multi_demo', '/manager/', '1', false],
  ]) {
    if (!credentials[user]) throw new Error('Missing private seeded account: ' + user);
    const context = await browser.newContext({viewport: {width: 1280, height: 900}});
    const page = await context.newPage();
    page.on('pageerror', () => report.page_errors++);
    const loginPath = patient ? '/portal/login/' : '/accounts/login/';
    const response = await page.goto(base + loginPath, {waitUntil: 'networkidle'});
    check(user + ' public login GET', response.status() === 200);
    await page.locator('input[name=username]').fill(user);
    await page.locator('input[name=password]').fill(credentials[user]);
    await Promise.all([
      page.waitForURL(url => url.origin === base && !url.pathname.endsWith('/login/')),
      page.locator('form:has(input[name=username]) button[type=submit]').click(),
    ]);
    if (user === 'multi_demo') {
      check('Multi-role account requires explicit role selection', new URL(page.url()).pathname === '/workspace/select-role/');
      await page.locator('form:has(input[name=role][value="MANAGER"]) button[type=submit]').click();
      await page.waitForURL(base + route);
    }
    if (clinic) {
      await page.locator(`form:has(input[name=clinic][value="${clinic}"]) button[type=submit]`).click();
      await page.waitForURL(base + route);
    }
    await page.waitForLoadState('networkidle');
    check(user + ' authorized workspace route', new URL(page.url()).pathname === route);
    const cookies = await context.cookies(base);
    check(user + ' secure authenticated session', cookies.some(c => c.name === 'sessionid' && c.secure && c.httpOnly));
    check(user + ' read-only notice', (await page.locator('body').innerText()).includes('只读'));
    if (user === 'front_a') {
      const refusal = await page.evaluate(async () => {
        const csrf = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=').slice(1).join('=');
        const token = document.querySelector('meta[name=adc-workspace]').content;
        const response = await fetch('/patients/new/', {method: 'POST',
          headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded'},
          body: new URLSearchParams({workspace_token: token, name: 'Synthetic rejected read-only attempt'})});
        return {status: response.status, readonly: (await response.text()).includes('只读')};
      });
      check('Authenticated signed business POST refused by read-only policy', refusal.status === 403 && refusal.readonly);
      await page.setViewportSize({width: 390, height: 844});
      await page.locator('button.mode-toggle').click();
      check('390px large-text workspace fits viewport', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({path: path.join(privateDir, 'frontdesk-390-readonly.png'), fullPage: true});
    }
    if (user === 'doctor_a') {
      const denied = await page.goto(base + '/finance/', {waitUntil: 'networkidle'});
      check('Doctor cannot inherit finance permission', denied.status() === 403 && await page.locator('h1').count() === 1);
    }
    if (patient) {
      const refusal = await page.evaluate(async () => {
        const csrf = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=').slice(1).join('=');
        const response = await fetch('/portal/book/confirm/', {method: 'POST',
          headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded'},
          body: new URLSearchParams({slot: '1'})});
        return {status: response.status, readonly: (await response.text()).includes('只读')};
      });
      // Portal booking uses its existing 409 no-write conflict page.
      check('Patient booking POST refused in read-only demo', refusal.status === 409 && refusal.readonly);
    }
    await context.close();
  }
  const csrfContext = await browser.newContext();
  await csrfContext.request.get(base + '/accounts/login/');
  const rejected = await csrfContext.request.post(base + '/accounts/login/', {
    headers: {Origin: base, Referer: base + '/accounts/login/'},
    form: {username: 'front_a', password: credentials.front_a},
  });
  check('Login POST without CSRF token refused', rejected.status() === 403);
  await csrfContext.close();
  check('No frontend execution errors during tested flows', report.page_errors === 0);
  report.all_checks_passed = report.checks.every(x => x.passed);
})().catch(error => {
  report.all_checks_passed = false;
  report.failure = error.message.replace(/https:\/\/[^\s]+/g, '[demo URL]');
  process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close();
  fs.writeFileSync(path.join(privateDir, 'browser-checks.json'), JSON.stringify(report, null, 2) + '\n', {mode: 0o600});
  console.log(JSON.stringify({all_checks_passed: report.all_checks_passed,
    checks: report.checks.length, failure: report.failure || null}));
});
