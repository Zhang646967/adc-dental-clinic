// Real Chrome role/write smoke checks. Full A/B cloud acceptance remains separate.
// Credentials, cookies and workspace tokens stay in private local files.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const bundle = path.resolve(process.argv[2] || '');
const scope = process.argv[3];
const plan = JSON.parse(fs.readFileSync(path.join(bundle, 'plan.json'), 'utf8'));
if (plan.mode !== 'direct_tls' || plan.access_mode !== 'course-writable' || plan.read_only ||
    !['origin', 'public'].includes(scope)) throw new Error('Separate writable course bundle required.');
const local = scope === 'origin';
if (local && (plan.bind_ip !== '127.0.0.1' || [80, 443].some(p => plan.ports.includes(p))))
  throw new Error('Local browser rehearsal requires separate loopback ports.');
if (!local && (plan.ports[0] !== 80 || plan.ports[1] !== 443))
  throw new Error('Public browser checks require ordinary HTTPS ports.');
const privateDir = path.join(bundle, 'private');
const credentials = {};
for (const line of fs.readFileSync(path.join(privateDir, 'demo-credentials.txt'), 'utf8').split('\n')) {
  const fields = line.split('|').map(s => s.trim());
  if (fields.length === 3 && /^LOCAL/.test(fields[0])) credentials[fields[1]] = fields[2];
}
const base = 'https://' + plan.host + (local ? ':' + plan.ports[1] : '');
const args = [];
if (local) {
  const certificate = new crypto.X509Certificate(fs.readFileSync(path.join(bundle, 'tls/fullchain.pem')));
  const pin = crypto.createHash('sha256').update(certificate.publicKey.export({type: 'spki', format: 'der'})).digest('base64');
  args.push('--host-resolver-rules=MAP ' + plan.host + ' 127.0.0.1', '--no-proxy-server',
            '--ignore-certificate-errors-spki-list=' + pin);
}
const report = {scope: local ? 'isolated origin Chrome rehearsal with pinned local certificate' : 'public Chrome smoke',
                project: plan.project, source_commit: plan.requested_source_commit,
                checks: [], page_errors: 0, full_business_routes_accepted: false,
                course_online_readiness: 'NOT_GRANTED_BY_SMOKE_ALONE'};
function check(name, value) {
  report.checks.push({check: name, passed: Boolean(value)});
  if (!value) throw new Error('Browser check failed: ' + name);
}
let browser;
(async () => {
  browser = await chromium.launch({channel: 'chrome', headless: true, args});
  report.browser_version = browser.version();
  for (const [username, route, clinic, patient] of [
    ['front_a', '/frontdesk/', '1', false], ['front_b', '/frontdesk/', '2', false],
    ['manager_a', '/manager/', '1', false], ['doctor_a', '/doctor/', null, false],
    ['hq_demo', '/headquarters/', null, false], ['finance_demo', '/financial-workspace/', null, false],
    ['tech_demo', '/technical/', null, false], ['patient_demo_a', '/portal/', null, true],
    ['multi_demo', '/manager/', '1', false],
  ]) {
    const context = await browser.newContext({viewport: {width: 1280, height: 900}});
    const page = await context.newPage();
    page.on('pageerror', () => report.page_errors++);
    const login = patient ? '/portal/login/' : '/accounts/login/';
    const response = await page.goto(base + login);
    check(username + ' login page', response.status() === 200);
    await page.locator('input[name=username]').fill(username);
    await page.locator('input[name=password]').fill(credentials[username]);
    await page.locator('form:has(input[name=username]) button[type=submit]').click();
    await page.waitForURL(url => !url.pathname.endsWith('/login/'));
    if (username === 'multi_demo') {
      check('Explicit role selection', new URL(page.url()).pathname === '/workspace/select-role/');
      await page.locator('form:has(input[name=role][value="MANAGER"]) button[type=submit]').click();
      await page.waitForURL(base + route);
    }
    if (clinic) {
      await page.locator('form:has(input[name=clinic][value="' + clinic + '"]) button[type=submit]').click();
      await page.waitForURL(base + route);
    }
    check(username + ' scoped workspace', new URL(page.url()).pathname === route);
    check(username + ' secure session', (await context.cookies()).some(c => c.name === 'sessionid' && c.secure && c.httpOnly));
    if (username === 'front_a') {
      await page.goto(base + '/patients/new/');
      check('Business save is available', await page.locator('main button[type=submit]').isEnabled());
      await page.locator('[name=clinic]').selectOption('1');
      const suffix = crypto.randomBytes(6).toString('hex');
      for (const [name, value] of Object.entries({
        name: 'COURSE-BROWSER-' + suffix, date_of_birth: '2000-01-01',
        billing_address: 'Synthetic course address', phone: '000-DEMO', email: 'browser@example.invalid',
        emergency_name: 'Synthetic contact', emergency_phone: '000-DEMO',
      })) await page.locator('[name=' + name + ']').fill(value);
      await page.locator('[name=allergy_status]').selectOption('UNKNOWN');
      await page.locator('main button[type=submit]').click();
      await page.waitForURL(url => /^\/patients\/[0-9]+\/$/.test(url.pathname));
      check('Real Chrome patient write persisted visibly', (await page.locator('main').innerText()).includes('COURSE-BROWSER-' + suffix));
      await page.setViewportSize({width: 390, height: 844});
      await page.locator('button.mode-toggle').click();
      check('390px large text fits', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    }
    if (username === 'doctor_a') {
      const denied = await page.goto(base + '/finance/');
      check('Doctor cannot inherit finance access', denied.status() === 403);
    }
    await context.close();
    // Deliberately paced setup; never retry rejected authentication.
    await new Promise(resolve => setTimeout(resolve, 6100));
  }
  check('No frontend execution errors', report.page_errors === 0);
  report.all_checks_passed = report.checks.every(c => c.passed);
})().catch(() => {
  report.all_checks_passed = false;
  report.failure = 'Browser smoke stopped; inspect the last named private check.';
  process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close();
  fs.writeFileSync(path.join(privateDir, 'course-browser.json'), JSON.stringify(report, null, 2) + '\n', {mode: 0o600});
  console.log(JSON.stringify({all_checks_passed: report.all_checks_passed, checks: report.checks.length}));
});
