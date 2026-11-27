// Real form submission with local test responses. Run with Playwright and Chrome or WebKit.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium, webkit } = require('playwright');

const script = path.join(__dirname, '..', 'static', 'patient-booking-confirm.js');
const origin = 'http://clinic.test';
const savedPath = '/portal/visits/41/';

async function verify(browser, { kind, pagePath, action }) {
  const page = await browser.newPage();
  try {
    const posts = [];
    const postedTo = new URL(action || pagePath, origin).href;
    const input = kind === 'reschedule'
      ? '<input type="hidden" name="action" value="confirm"><input name="proposal_token" value="fixture">'
      : '<input name="token" value="fixture">';
    const form = '<!doctype html><meta charset="utf-8"><form method="post" data-booking-confirmation="' + kind + '"' +
      (action ? ' action="' + action + '"' : '') + '>' + input +
      '<button type="submit">确认</button><a data-confirm-back>返回</a></form>' +
      '<section data-booking-feedback hidden><h2 data-feedback-title></h2><p data-feedback-message></p>' +
      '<button data-query-booking hidden></button><a data-reselect-booking></a><a data-visit-list></a></section>';
    await page.route('**/*', async route => {
      const request = route.request();
      assert.equal(new URL(request.url()).origin, origin);
      if (request.method() === 'POST') {
        const fields = await new Response(request.postDataBuffer(), { headers: request.headers() }).formData();
        posts.push({ url: request.url(), operation: fields.get('action') });
        await route.fulfill({ json: { state: 'SAVED', url: savedPath } });
      } else {
        await route.fulfill({ contentType: 'text/html; charset=utf-8', body: request.url().endsWith(savedPath) ? '已预约' : form });
      }
    });
    await page.goto(origin + pagePath);
    await page.addScriptTag({ path: script });
    await Promise.all([
      page.waitForURL(origin + savedPath),
      page.getByRole('button', { name: '确认' }).click(),
    ]);
    assert.deepEqual(posts, [{ url: postedTo, operation: kind === 'reschedule' ? 'confirm' : null }]);
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = process.argv[2] === 'webkit' ? await webkit.launch() : await chromium.launch({ channel: 'chrome' });
  try {
    await verify(browser, { kind: 'reschedule', pagePath: '/portal/visits/9/reschedule/?day=2026-11-30' });
    await verify(browser, { kind: 'booking', pagePath: '/portal/book/confirm/' });
    await verify(browser, { kind: 'reschedule', pagePath: '/preview/', action: '/portal/visits/9/reschedule/' });
    console.log('Passed 3 booking and reschedule form submission cases.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
