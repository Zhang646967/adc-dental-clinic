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
  const scrolls = [];
  const state = { globalData: { returnSource: null } };
  // The page computes the absolute offset from the viewport and the row box.
  const wx = {
    nextTick: fn => fn(),
    pageScrollTo: options => scrolls.push(options),
    createSelectorQuery: () => {
      const query = {
        selectViewport() { return query; },
        select() { return query; },
        scrollOffset() { return query; },
        boundingClientRect() { return query; },
        exec(callback) { callback([{ scrollTop: 120 }, { top: 300 }]); }
      };
      return query;
    }
  };
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
    wx,
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
    calls, routes, scrolls, state
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

  // --- report notices: the row that opened a report stays the anchor --------
  const auth = { authenticated: true, subject_key: 'self', workspace_id: 'w1', subject_revision: 1 };
  const notice = (id, extra = {}) => ({ id, kind: 'RELEASED', title: '检查报告已发布',
    project: '课程文本检查', clinic: '演示甲店', occurred_at: '2026-11-27T01:20:00Z',
    read_at: null, visit_id: 1, examination_id: id, revision: 1, ...extra });
  const pageOf = (rows, number = 1, hasNext = false, hasPrevious = false) =>
    ({ rows, unread_count: 8, page: number, has_next: hasNext, has_previous: hasPrevious });
  const tapAt = i => ({ currentTarget: { dataset: { index: i } } });

  // First entry never invents a position.
  const firstEntry = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)])] });
  firstEntry.page.onLoad({});
  await firstEntry.page.onShow();
  ok(firstEntry.scrolls.length === 0 && firstEntry.page.data.focusId === null, 'first entry keeps the normal start');

  // Opening a row remembers its id and action; the back gesture re-reads and
  // scrolls to that same row, not to the first one.
  const same = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11), notice(2)]), pageOf([notice(11), notice(2)])] });
  same.page.onLoad({});
  await same.page.onShow();
  same.page.open(tapAt(1));
  ok(same.routes.at(-1)[1] === '/pages/examination/index?visit=1&id=2&revision=1', 'the row opens its exact report');
  await same.page.onHide();
  await same.page.onShow();
  ok(same.page.data.focusId === 2, 'return focuses the notice that opened the report');
  ok(same.scrolls.length === 1 && same.scrolls[0].scrollTop === 404,
    'the page restores the reading position of that row');
  ok(same.page.data.rows[1].actionLabel === '查看第 1 版报告', 'the row still carries its action after the re-read');
  ok(same.page.data.unreadCount === 8, 'the unread count is unchanged');

  // A second back gesture does not reuse the consumed anchor.
  await same.page.onHide();
  await same.page.onShow();
  ok(same.page.data.focusId === null && same.scrolls.length === 1, 'the anchor is consumed by one return');

  // Sorting moved the row to the second page: the current list is searched.
  const moved = load('report-notices', { session: { ...auth }, responses: [
    pageOf([notice(11)], 1, true), pageOf([notice(12)], 1, true), pageOf([notice(11)], 2, false, true)
  ] });
  moved.page.onLoad({});
  await moved.page.onShow();
  moved.page.open(tapAt(0));
  await moved.page.onHide();
  await moved.page.onShow();
  ok(moved.calls.some(c => c[0] === 'report-notices/' && c[2] && c[2].page === 2), 'a moved row is looked up on the next page');
  ok(moved.page.data.focusId === 11 && moved.page.data.page === 2, 'the moved row is shown and focused');
  ok(moved.scrolls.length === 1, 'the moved row is scrolled into view');

  // The row disappeared: fall back to the current first page without a jump.
  const gone = load('report-notices', { session: { ...auth }, responses: [
    pageOf([notice(11)], 1, true), pageOf([notice(12)], 1, true), pageOf([notice(13)], 2, false, true)
  ] });
  gone.page.onLoad({});
  await gone.page.onShow();
  gone.page.open(tapAt(0));
  await gone.page.onHide();
  await gone.page.onShow();
  ok(gone.page.data.focusId === null && gone.scrolls.length === 0, 'a missing row returns to the valid list');
  ok(gone.page.data.page === 1 && gone.page.data.rows.length === 1, 'the fallback list is the current first page');

  // Another patient or workspace must not inherit the anchor.
  const switched = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)]), pageOf([notice(11)])] });
  switched.page.onLoad({});
  await switched.page.onShow();
  switched.page.open(tapAt(0));
  switched.page.returnTarget.context.subjectKey = 'grant:1';
  await switched.page.onHide();
  await switched.page.onShow();
  ok(switched.page.data.focusId === null && switched.scrolls.length === 0, 'a changed subject drops the old anchor');

  // A workspace change or a signed-out session drops the anchor as well.
  const workspace = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)]), pageOf([notice(11)])] });
  workspace.page.onLoad({});
  await workspace.page.onShow();
  workspace.page.open(tapAt(0));
  workspace.page.returnTarget.context.workspaceId = 'w2';
  await workspace.page.onHide();
  await workspace.page.onShow();
  ok(workspace.page.data.focusId === null && workspace.scrolls.length === 0, 'a changed workspace drops the old anchor');

  const revised = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)]), pageOf([notice(11)])] });
  revised.page.onLoad({});
  await revised.page.onShow();
  revised.page.open(tapAt(0));
  revised.page.returnTarget.context.revision = 2;
  await revised.page.onHide();
  await revised.page.onShow();
  ok(revised.page.data.focusId === null && revised.scrolls.length === 0, 'a changed subject revision drops the old anchor');


  // Expired anchors and unloads never apply later.
  const expired = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)]), pageOf([notice(11)])] });
  expired.page.onLoad({});
  await expired.page.onShow();
  expired.page.open(tapAt(0));
  expired.page.returnTarget.expires = Date.now() - 1;
  await expired.page.onHide();
  await expired.page.onShow();
  ok(expired.page.data.focusId === null && expired.scrolls.length === 0, 'an expired anchor is ignored');

  const unloaded = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)]), pageOf([notice(11)])] });
  unloaded.page.onLoad({});
  await unloaded.page.onShow();
  unloaded.page.open(tapAt(0));
  unloaded.page.onUnload();
  await unloaded.page.onShow();
  ok(unloaded.page.data.focusId === null && unloaded.scrolls.length === 0, 're-entering after unload starts fresh');

  // Contact and the original visit set their own anchor action.
  const contactAnchor = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11, { kind: 'WITHDRAWN', revision: null })]), pageOf([notice(11, { kind: 'WITHDRAWN', revision: null })])] });
  contactAnchor.page.onLoad({});
  await contactAnchor.page.onShow();
  contactAnchor.page.contact(tapAt(0));
  ok(contactAnchor.page.returnTarget.action === 'contact' && contactAnchor.routes.at(-1)[1] === '/pages/help/index?visit=1',
    'contact keeps both its destination and its action');
  await contactAnchor.page.onHide();
  await contactAnchor.page.onShow();
  ok(contactAnchor.page.data.focusId === 11, 'returning from contact focuses the withdrawn row');

  const visitAnchor = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)]), pageOf([notice(11)])] });
  visitAnchor.page.onLoad({});
  await visitAnchor.page.onShow();
  visitAnchor.page.rememberVisit(tapAt(0));
  ok(visitAnchor.page.returnTarget.action === 'visit', 'the original-visit link sets its own action');
  await visitAnchor.page.onHide();
  await visitAnchor.page.onShow();
  ok(visitAnchor.page.data.focusId === 11, 'returning from the original visit focuses the same row');

  // A refresh that the server rejects must not restore an old position.
  const rejectedReturn = load('report-notices', { session: { ...auth }, responses: [
    pageOf([notice(11)]), Object.assign(new Error('检查报告与提醒仅限患者本人查看。'), { status: 403, code: 'REPORT_SELF_REQUIRED' })
  ] });
  rejectedReturn.page.onLoad({});
  await rejectedReturn.page.onShow();
  rejectedReturn.page.open(tapAt(0));
  await rejectedReturn.page.onHide();
  await rejectedReturn.page.onShow();
  ok(rejectedReturn.page.data.focusId === null && rejectedReturn.scrolls.length === 0, 'a rejected refresh keeps no anchor');
  ok(rejectedReturn.page.data.selfOnly === true, 'the rejection still shows its own path');

  // Acknowledge is not navigation and must not create an anchor.
  const ack = load('report-notices', { session: { ...auth }, responses: [pageOf([notice(11)]), { id: 11, read_at: '2026-11-27T02:00:00Z', unread_count: 7 }] });
  ack.page.onLoad({});
  await ack.page.onShow();
  await ack.page.markRead(tapAt(0));
  ok(ack.page.returnTarget === null, 'marking a row read creates no return anchor');

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
