/* 18551: page-handler regression for the two report pages with a controlled
   transport. Verifies stale responses, missing fields and disclosure resets;
   it is not an IDE or WeChat-runtime execution. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../clients/wechat/miniprogram');
const format = require(path.join(root, 'utils/format'));
const subjectState = require(path.join(root, 'utils/subject-state'));
const bookingIntent = require(path.join(root, 'utils/booking-intent'));
const examinations = require(path.join(root, 'utils/examinations'));
const reportNotices = require(path.join(root, 'utils/report-notices'));

let checks = 0;
const ok = (value, message) => { assert.ok(value, message); checks++; };

function load(name, { session = {}, responses = [] } = {}) {
  let definition;
  const calls = [];
  const routes = [];
  const state = { globalData: { returnSource: null } };
  const api = {
    async bootstrap() { return session; },
    sessionInfo: () => session,
    showSubject: p => p.setData({ patientName: session.patient_name || '', patientCapacity: session.acting_capacity || '',
      patientDelegated: !!session.delegated }),
    async request(...args) {
      calls.push(args);
      const next = responses.shift();
      if (next instanceof Error) throw next;
      if (typeof next === 'function') return next();
      return next;
    }
  };
  const navigation = {
    navigateTo: o => routes.push(['navigateTo', o.url]),
    reLaunch: o => routes.push(['reLaunch', o.url]),
    redirectTo: o => routes.push(['redirectTo', o.url]),
    switchTab: o => routes.push(['switchTab', o.url]),
    returnTo: url => routes.push(['returnTo', url])
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'pages', name, 'index.js'), 'utf8'), {
    Page: d => { definition = d; },
    getApp: () => state,
    getCurrentPages: () => [],
    wx: {},
    require: key => key.endsWith('/api') ? api
      : key.endsWith('/navigation') ? navigation
      : key.endsWith('/subject-state') ? subjectState
      : key.endsWith('/booking-intent') ? bookingIntent
      : key.endsWith('/examinations') ? examinations
      : key.endsWith('/report-notices') ? reportNotices
      : key.endsWith('/format') ? format : null
  });
  return {
    page: Object.assign({}, definition, {
      data: JSON.parse(JSON.stringify(definition.data)),
      setData(v) { Object.assign(this.data, v); }
    }),
    calls, routes, state
  };
}

async function verify() {
  checks = 0;
  // --- report notices: missing project falls back to the server title ------
  const legacyRow = { id: 11, kind: 'WITHDRAWN', title: '检查报告已撤回', clinic: '演示甲店',
    occurred_at: '2026-11-27T01:20:02.982Z', read_at: null, visit_id: 1, examination_id: 2, revision: null };
  const list = load('report-notices', { session: { authenticated: true }, responses: [
    { rows: [legacyRow], unread_count: 1, page: 1, has_previous: false, has_next: false }
  ] });
  list.page.onLoad({});
  await list.page.onShow();
  ok(list.page.data.rows.length === 1, 'a legacy row still renders');
  ok(list.page.data.rows[0].heading === '检查报告已撤回', 'missing project falls back to the existing title');
  ok(list.page.data.rows[0].showStatus === false, 'the fallback title is not duplicated');
  ok(list.page.data.rows[0].canOpen === false && list.page.data.rows[0].actionLabel === '联系门店',
    'a withdrawn legacy row offers the clinic');
  ok(list.page.data.unreadCount === 1, 'the unread count is shown');

  // A late response from the first read never replaces the newer list.
  let release;
  const stale = load('report-notices', { session: { authenticated: true }, responses: [
    () => new Promise(resolve => { release = resolve; }),
    { rows: [], unread_count: 0, page: 1, has_previous: false, has_next: false }
  ] });
  stale.page.onLoad({});
  const first = stale.page.onShow();
  const second = stale.page.onShow();
  await second;
  release({ rows: [legacyRow], unread_count: 9, page: 1 });
  await first;
  ok(stale.page.data.rows.length === 0 && stale.page.data.unreadCount === 0,
    'a late notice response cannot restore older rows');

  // Missing fields never invent a count or a row.
  const empty = load('report-notices', { session: { authenticated: true }, responses: [{ rows: [] }] });
  empty.page.onLoad({});
  await empty.page.onShow();
  ok(empty.page.data.rows.length === 0 && empty.page.data.unreadCount === null,
    'a response without rows or count stays empty and unknown');

  // One explicit tap sends one write; an already-read row sends none.
  const read = load('report-notices', { session: { authenticated: true }, responses: [
    { rows: [{ ...legacyRow, kind: 'RELEASED', title: '检查报告已发布', revision: 1, examination_id: 5 }],
      unread_count: 1, page: 1 },
    { id: 11, read_at: '2026-11-27T02:00:00Z', unread_count: 0 }
  ] });
  read.page.onLoad({});
  await read.page.onShow();
  const evt = { currentTarget: { dataset: { index: 0 } } };
  await read.page.markRead(evt);
  await read.page.markRead(evt);
  ok(read.calls.filter(c => c[0] === 'report-notices/11/read/').length === 1, 'an explicit tap writes once');
  ok(read.page.data.rows[0].unread === false && read.page.data.unreadCount === 0, 'the row and count update locally');
  ok(read.page.data.rows[0].readLabel === '已读', 'the row now says it is read');

  // A read-only session exposes no acknowledgement action.
  const readOnly = load('report-notices', { session: { authenticated: true, read_only: true }, responses: [
    { rows: [{ ...legacyRow, kind: 'RELEASED', title: '检查报告已发布', revision: 1, examination_id: 5 }],
      unread_count: 1, page: 1 }
  ] });
  readOnly.page.onLoad({});
  await readOnly.page.onShow();
  await readOnly.page.markRead({ currentTarget: { dataset: { index: 0 } } });
  ok(readOnly.calls.length === 1, 'a read-only session performs no acknowledgement write');
  ok(readOnly.page.data.readOnly === true, 'the page knows it is read-only');

  // --- examination: disclosure and stale responses -------------------------
  const reportBody = '第一段。\n第二段，用于核对长正文与换行。';
  const detail = load('examination', { session: { authenticated: true }, responses: [
    { id: 1, number: 'EX-00000000000000000000000000000001', project: '课程文本检查', visit_id: 1,
      visit_no: 'V-00000000000000000000000000000002', revision: 2,
      performed_at: '2026-11-26T00:58:00Z', released_at: '2026-11-27T01:19:59.880Z', body: reportBody,
      followup: { action: 'NONE', label: '后续安排', message: '本报告供查阅。', clinic_id: 1, clinic: '演示甲店' } }
  ] });
  detail.page.onLoad({ visit: '1', id: '1', revision: '2' });
  await detail.page.onShow();
  ok(detail.page.data.report.body === reportBody, 'the full body is kept, not truncated');
  ok(detail.page.data.report.revision === 2, 'the current version is shown');
  ok(detail.page.data.infoOpen === false, 'identifiers start collapsed');
  ok(detail.calls[0][0] === 'visits/1/examinations/1/' && detail.calls[0][2].revision === 2,
    'the read asks for the announced version');
  detail.page.toggleInfo();
  ok(detail.page.data.infoOpen === true, 'the identifiers open on request');
  detail.page.onHide();
  ok(detail.page.data.report === null && detail.page.data.infoOpen === false,
    'leaving clears the report and the expansion');

  // A late response after leaving cannot repaint another report.
  let late;
  const raced = load('examination', { session: { authenticated: true }, responses: [
    () => new Promise(resolve => { late = resolve; })
  ] });
  raced.page.onLoad({ visit: '1', id: '7', revision: '1' });
  const pending = raced.page.onShow();
  raced.page.onHide();
  late({ id: 7, number: 'EX-00000000000000000000000000000003', project: '课程文本检查', revision: 1,
    body: '旧内容', followup: { action: 'VIEW_APPOINTMENT', appointment: { id: 2 } } });
  await pending;
  ok(raced.page.data.report === null && raced.page.data.followup === null,
    'a late report response cannot repaint a left page');

  // A 404 clears every previous value and keeps the arrival context.
  const rejected = load('examination', { session: { authenticated: true }, responses: [
    Object.assign(new Error('报告当前不可查看，请返回就诊核对'), { status: 404, requestId: 'req-404' })
  ] });
  rejected.page.onLoad({ visit: '1', id: '1', revision: '1' });
  await rejected.page.onShow();
  ok(rejected.page.data.report === null && rejected.page.data.followup === null, 'a rejected version shows no report');
  ok(rejected.page.data.infoOpen === false, 'a rejected version keeps identifiers collapsed');
  ok(rejected.page.data.error === '报告当前不可查看，请返回就诊核对', 'the rejection has its usual message');
  ok(rejected.page.data.requestId === 'req-404', 'the request id stays available');
  ok(rejected.page.data.hasVisit === true, 'the arrival visit stays available for the way back');

  return { passed: checks, total: checks, layer: 'Node JS page handlers with controlled transport' };
}

module.exports = { verify };
if (require.main === module) verify().then(r => console.log(JSON.stringify(r)))
  .catch(e => { console.error(e.message); process.exit(1); });
