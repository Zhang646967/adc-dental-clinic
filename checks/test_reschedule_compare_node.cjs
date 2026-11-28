/* 18553: reschedule comparison projection and the confirm page's two fact
   groups with a controlled transport. The server owns the facts; this check
   only proves they stay separate, readable and empty when omitted. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../clients/wechat/miniprogram');
const format = require(path.join(root, 'utils/format'));
const bookingIntent = require(path.join(root, 'utils/booking-intent'));
const subjectState = require(path.join(root, 'utils/subject-state'));
const reschedule = require(path.join(root, 'utils/reschedule'));
const textScale = require(path.join(root, 'utils/text-scale'));

let checks = 0;
const ok = (value, message) => { assert.ok(value, message); checks++; };

function confirmPage(review, { session = {} } = {}) {
  let definition;
  const state = { globalData: { review } };
  const api = {
    sessionInfo: () => session,
    showSubject() {},
    async request() { throw new Error('confirm load must not write'); }
  };
  const navigation = { navigateTo() {}, navigateBack() {}, reLaunch() {}, returnTo() {} };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'pages/confirm/index.js'), 'utf8'), {
    Page: d => { definition = d; },
    getApp: () => state,
    getCurrentPages: () => [],
    wx: {},
    require: key => key.endsWith('/api') ? api
      : key.endsWith('/navigation') ? navigation
      : key.endsWith('/booking-intent') ? bookingIntent
      : key.endsWith('/subject-state') ? subjectState
      : key.endsWith('/reschedule') ? reschedule
      : key.endsWith('/text-scale') ? textScale
      : key.endsWith('/format') ? format : null
  });
  return Object.assign({}, definition, {
    data: JSON.parse(JSON.stringify(definition.data)),
    setData(v) { Object.assign(this.data, v); },
    replaceGlobalReview(next) { state.globalData.review = next; }
  });
}

// --- candidate facts -------------------------------------------------------
const row = reschedule.candidate({id: '6:2026-12-01T02:30:00Z', slot: 6, clinic: '云庭口腔 · 江畔门诊',
  dentist: '演示医生1', dentist_id: 3, start: '2026-12-01T02:30:00Z', end: '2026-12-01T03:00:00Z',
  service: 2, service_name: '口腔检查与复查'});
ok(row.startLabel === '2026-12-01 10:30' && row.endLabel === '2026-12-01 11:00', 'candidate times are Beijing time');
ok(row.serviceLabel === '口腔检查与复查', 'candidate service_name is readable');
ok(row.durationLabel === '30 分钟' && row.durationMinutes === 30, 'candidate duration comes from its own slot');
const bare = reschedule.candidate({start: '2026-12-01T02:30:00Z', service: 2});
ok(bare.serviceLabel === '' && bare.endLabel === '' && bare.durationLabel === '',
  'an older row without a name or end leaves those facts empty');

// --- comparison keeps the two groups apart --------------------------------
const preview = {
  original: {id: 2, visit_no: 'V-17E6B35D0AB64F729096E252DFB2F48C', clinic: '云庭口腔 · 江畔门诊',
    dentist: '演示医生1', service: '口腔检查与复查', status_label: '已预约',
    start: '2026-11-30T01:00:00Z', end: '2026-11-30T01:30:00Z'},
  clinic: '云庭口腔 · 江畔门诊', dentist: '演示医生1', service_name: '口腔检查与复查',
  duration_minutes: 30, start: '2026-12-01T02:30:00Z', end: '2026-12-01T03:00:00Z',
  duration_changed: false, proposal_token: 'signed'
};
const facts = reschedule.comparison(preview);
ok(facts.original.visitNo === 'V-17E6B35D0AB64F729096E252DFB2F48C', 'the original keeps its full number');
ok(facts.original.startLabel === '2026-11-30 09:00' && facts.original.endLabel === '2026-11-30 09:30',
  'the original keeps its own arrival window');
ok(facts.proposed.startLabel === '2026-12-01 10:30' && facts.proposed.endLabel === '2026-12-01 11:00',
  'the proposal keeps its own window');
ok(facts.proposed.durationLabel === '30 分钟' && facts.proposed.serviceLabel === '口腔检查与复查',
  'the proposal keeps its own service and duration');
ok(facts.changedDay === true && facts.sameDay === false, 'a different day is visible as a change');

const changed = reschedule.comparison(Object.assign({}, preview, {duration_minutes: 45, duration_changed: true}));
ok(changed.proposed.durationLabel === '45 分钟' && changed.proposed.durationChanged === true,
  'a different duration follows the proposal, not the original');

const noName = reschedule.comparison(Object.assign({}, preview, {service_name: ''}));
ok(noName.proposed.serviceLabel === '', 'a missing new service name does not borrow the original service');

const noOriginal = reschedule.comparison({start: '2025-01-01T01:00:00Z', end: '2025-01-01T01:30:00Z'});
ok(noOriginal.original === null && noOriginal.proposed.startLabel === '2025-01-01 09:00',
  'a new booking without an original still shows the proposal');

const noStart = reschedule.comparison({original: preview.original, proposal_token: 'x'});
ok(noStart.original.visitNo === preview.original.visit_no && noStart.proposed === null,
  'an older preview without a proposed start keeps only the original');

// --- lineage roles ---------------------------------------------------------
const old = reschedule.lineage({id: 3, status: 'RESCHEDULED', successor: 4, predecessor: null});
ok(old.next === 4 && old.previous === null, 'a replaced appointment points only to its successor');
ok(old.title.includes('原预约') && old.note.includes('已改期'), 'the original explains its status');
const middle = reschedule.lineage({id: 4, status: 'RESCHEDULED', predecessor: 3, successor: 5});
ok(middle.previous === 3 && middle.next === 5 && middle.title.includes('再次改期'), 'an intermediate appointment links both ways');
const saved = reschedule.lineage({id: 5, status: 'SCHEDULED', predecessor: 4});
ok(saved.previous === 4 && saved.next === null && saved.title.includes('当前预约'), 'only the scheduled successor is current');
for (const status of ['CANCELLED','COMPLETED','CLOSED_NO_TREATMENT','NO_SHOW','CHECKED_IN',null]) {
  const last = reschedule.lineage({id: 5, status, predecessor: 4});
  ok(last.previous === 4 && !last.next && !last.title.includes('当前') && !last.note,
    'an appointment with status ' + status + ' keeps its history without giving an arrival instruction');
}
const past = reschedule.lineage({id: 5, status: 'SCHEDULED', needs_outcome_review: true, predecessor: 4});
ok(!past.title.includes('当前') && !past.note, 'past scheduled slots pending review do not give an arrival instruction');
ok(reschedule.lineage({id: 2}) === null, 'an unrelated appointment has no lineage card');
ok(reschedule.minutesBetween('bad', 'worse') === null, 'an invalid window has no duration');

// --- confirm page shows both groups ---------------------------------------
const baseReview = {kind: 'reschedule', subjectKey: 'self', workspaceKey: 'w1', subjectRevision: 1,
  path: 'visits/2/reschedule/confirm/', selection: {service: 2, clinic: 3, dentist: 3, day: '2026-12-01'},
  preview};
const page = confirmPage(baseReview, {session: {subject_key: 'self', workspace_id: 'w1', subject_revision: 1}});
page.onLoad();
ok(page.data.previewNote === '待确认，原预约仍保留', 'the confirmation still says the original remains');
ok(page.data.button === '确认改期' && page.data.title === '确认预约改期', 'the main action stays confirmation');
ok(page.data.comparison.original.visitNo === preview.original.visit_no, 'the page keeps the original number');
ok(page.data.comparison.proposed.durationLabel === '30 分钟', 'the page keeps the new duration');
ok(page.data.comparison.original.startLabel !== page.data.comparison.proposed.startLabel,
  'the page never reuses one window for the other');

const missing = confirmPage(Object.assign({}, baseReview, {preview: Object.assign({}, preview, {service_name: ''})}),
  {session: {subject_key: 'self', workspace_id: 'w1', subject_revision: 1}});
missing.onLoad();
ok(missing.data.comparison.proposed.serviceLabel === '', 'the page leaves a missing new service empty');

// The patient reads each date and unchanged service detail once.
const compact = page.data.comparison.summary;
ok(compact.originalTime === '2026-11-30 09:00–09:30' &&
  compact.proposedTime === '2026-12-01 10:30–11:00' && compact.sharedDay === '', 'different days keep both dates');
ok(compact.shared.map(f=>f.label).join() === '门店,服务' && !compact.originalOnly.length &&
  compact.proposedOnly[0].label === '医师' && compact.originalDentistDetail === preview.original.dentist,
  'same-name doctors without both IDs are shown separately, with the source doctor in details');
const doctors = (before,after) => reschedule.comparison({...preview,original:{...preview.original,dentist_id:before},
  dentist_id:after},true).summary;
ok(doctors(4,4).shared.some(row=>row.label==='医师') && !doctors(4,4).originalDentistDetail && !doctors(4,4).doctorChanged,
  'a shared name and shared stable clinician ID allow one combined fact');
ok(doctors(4,5).doctorChanged && doctors(4,5).originalOnly[0].label==='医师' &&
  doctors(4,5).proposedOnly[0].value===preview.dentist && !doctors(4,5).shared.some(row=>row.label==='医师'),
  'two different doctors sharing a name remain attributed to their own appointments');
ok(doctors(null,3).originalDentistDetail === preview.original.dentist && !doctors(null,3).doctorChanged,
  'one missing clinician ID does not manufacture continuity or a change');
const sameDay = reschedule.comparison({...preview, start:'2026-11-30T02:30:00Z', end:'2026-11-30T03:00:00Z'},true).summary;
ok(sameDay.sharedDay === '2026-11-30' && sameDay.originalTime === '09:00–09:30' && sameDay.proposedTime === '10:30–11:00',
  'the same Beijing date appears once above two clock ranges');
const overnight = reschedule.comparison({...preview, start:'2026-12-31T15:45:00Z', end:'2026-12-31T16:30:00Z'},true).summary;
ok(overnight.proposedTime === '2026-12-31 23:45 至 2027-01-01 00:30', 'a Beijing-midnight year change retains both dates');
const revised = reschedule.comparison({...preview, dentist:'另一位医师',service_name:'',duration_minutes:45,duration_changed:true},true).summary;
ok(revised.shared.length === 1 && revised.shared[0].label === '门店' &&
  revised.originalOnly.map(f=>f.label).join() === '医师,服务' && revised.proposedOnly.length === 1 &&
  revised.proposedOnly[0].value === '另一位医师', 'changed facts stay attached to their appointment and absent names remain absent');
ok(revised.durationChanged && revised.originalDuration === '30 分钟' && revised.proposedDuration === '45 分钟',
  'both known durations remain visible when the slot length changes');
const partial = reschedule.comparison({original:preview.original,end:preview.end},true).summary;
ok(partial.proposedTime === '至 2026-12-01 11:00' && partial.proposedOnly.length === 0, 'missing proposed start leaves only its own end');
ok(!page.data.detailsOpen,'number and reason start collapsed');
page.toggleRescheduleDetails();ok(page.data.detailsOpen,'the patient can expand the details');
page.onHide();ok(!page.data.detailsOpen,'leaving folds the details without submitting or clearing consent');
page.toggleRescheduleDetails();
page.replaceGlobalReview({...baseReview,preview:{...preview, proposal_token:'next'}});
page.onShow();
ok(!page.data.detailsOpen && !page.data.comparison && !page.data.review, 'a new proposal cannot restore older private details');
const session={subject_key:'self',workspace_id:'w1',subject_revision:1};
const switched=confirmPage(baseReview,{session});switched.onLoad();switched.toggleRescheduleDetails();session.subject_revision=2;switched.onShow();
ok(switched.data.subjectInvalid && !switched.data.detailsOpen && !switched.data.comparison && !switched.data.checked && !switched.sourceReview,
  'a changed identity clears the whole comparison and the disclosure');
const content=fs.readFileSync(path.join(root,'pages/confirm/index.wxml'),'utf8');
ok(content.includes('aria-expanded="{{detailsOpen}}"') && content.includes('bindtap="toggleRescheduleDetails"') &&
  content.includes('wx:if="{{detailsOpen}}"'), 'assistive technology receives the state of the dedicated disclosure');

module.exports = {passed: checks, total: checks, layer: 'Node JS reschedule projection and confirm page'};
if (require.main === module) console.log(JSON.stringify(module.exports));
