/* Appointment details: verify the ordinary page lifecycle and the entry/cancel
   controls independently of the later booking confirmation screen. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const pageDir = path.join(__dirname, '../clients/wechat/miniprogram/pages/visit');
const source = fs.readFileSync(path.join(pageDir, 'index.js'), 'utf8');
const markup = fs.readFileSync(path.join(pageDir, 'index.wxml'), 'utf8');
const original = {id: 2, status: 'SCHEDULED', can_change: true, visit_no: 'V-2', clinic: '门诊甲',
  start: '2026-11-30T01:00:00Z', end: '2026-11-30T01:30:00Z', phone: '门店前台号码', patient_request: '预约时填写的需求'};

function open(session, results, id = '2') {
  const calls = [], routes = [];
  let definition;
  const api = {sessionInfo: () => session, showSubject() {}, async request(...args) {
    calls.push(args); const next = results.shift(); if (next instanceof Error) throw next; return next;
  }};
  vm.runInNewContext(source, {
    Page: value => { definition = value; }, getApp: () => ({globalData: {}}), wx: {},
    require(key) {
      if (key.endsWith('/api')) return api;
      if (key.endsWith('/navigation')) return {navigateTo: ({url}) => routes.push(url)};
      return require(path.join(pageDir, key));
    }
  });
  const page = {...definition, data: {...definition.data}, setData(patch) {Object.assign(this.data, patch);}};
  page.onLoad({id});
  return {page, calls, routes};
}

async function verify() {
  const summary = markup.slice(markup.indexOf('class="card visit-summary"'), markup.indexOf('wx:if="{{lineage}}"'));
  assert.equal(markup.match(/bindtap="reschedule"/g).length, 1);
  assert(summary.indexOf('record.whenLabel') < summary.indexOf('visit.clinic'));
  assert(summary.indexOf('visit.address') < summary.indexOf('bindtap="reschedule"'));
  assert(summary.indexOf('bindtap="reschedule"') < summary.indexOf('bindtap="toggleInfo"'));
  assert(summary.includes('wx:if="{{reviewView && reviewView.attendedLabel}}"'));
  assert(!summary.includes('尚未登记'));
  assert(summary.includes('wx:if="{{visit.needs_outcome_review}}"'));

  let unlock;
  const fresh = open({}, [new Promise(resolve => { unlock = resolve; })]);
  const read = fresh.page.onShow();
  assert.equal(fresh.page.data.busy, true);
  fresh.page.reschedule(); fresh.page.cancel();
  assert.deepEqual(fresh.routes, []);
  assert.equal(fresh.page.data.cancelOpen, false);
  unlock(original); await read;
  assert.equal(fresh.page.data.busy, false);
  assert.equal(fresh.page.data.infoOpen, false);
  assert.equal(fresh.page.data.infoOpenLabel, '展开预约编号、门店电话、就诊需求');
  fresh.page.toggleInfo(); fresh.page.cancel();
  assert.equal(fresh.page.data.infoOpen, true);
  assert.equal(fresh.page.data.cancelOpen, true);
  fresh.page.cancel(); fresh.page.reschedule();
  assert.deepEqual(fresh.routes, ['/pages/booking/index?visit=2']);
  assert.deepEqual(fresh.calls.map(args => args[0]), ['visits/2/']);

  const proxy = open({read_only: true, delegated: true}, [{...original, phone: ''}]);
  await proxy.page.onShow();
  assert.equal(proxy.page.data.infoOpenLabel, '展开预约编号');
  proxy.page.reschedule(); proxy.page.cancel();
  assert.deepEqual(proxy.routes, []); assert.equal(proxy.page.data.cancelOpen, false);

  for (const status of [404, 503]) {
    const outcome = open({}, [Object.assign(Error('无法读取预约'), {status})]);
    await outcome.page.onShow();
    assert.equal(outcome.page.data.busy, false); assert.equal(outcome.page.data.visit, null);
    assert.equal(outcome.page.data.canRetry, status === 503);
    outcome.page.reschedule(); assert.deepEqual(outcome.routes, []);
  }
  const invalid = open({}, [], 'bad'); await invalid.page.onShow();
  assert.equal(invalid.page.data.canRetry, false); assert.deepEqual(invalid.calls, []);
  return {passed: true, layer: 'appointment detail Page handlers and template order'};
}
module.exports = verify;
if (require.main === module) verify().then(console.log).catch(error => { console.error(error); process.exitCode = 1; });
