/* 18551: patient report notices and report-detail projection.
   Pure JS assertions over utils/report-notices.js — no Django, no WeChat runtime. */
const assert = require('node:assert/strict');
const path = require('node:path');

const root = path.resolve(__dirname, '../clients/wechat/miniprogram');
const {reportEntry, buildNotice, buildNoticeList, buildFollowup, dayLabel} =
  require(path.join(root, 'utils/report-notices.js'));

let checks = 0;
const ok = (value, message) => { assert.ok(value, message); checks++; };

// --- notice rows -----------------------------------------------------------
const corrected = buildNotice({id: 2, kind: 'CORRECTED', title: '检查报告已更新', project: '课程文本检查',
  clinic: '演示甲店', occurred_at: '2026-11-27T01:19:59.880Z', read_at: null, visit_id: 1, examination_id: 1, revision: 2});
ok(corrected.heading === '课程文本检查', 'project becomes the heading');
ok(corrected.showStatus === true, 'server title stays as the status pill when a project exists');
ok(corrected.statusLabel === '检查报告已更新', 'status text is the server title');
ok(corrected.tone === 'status-rescheduled', 'corrected keeps its own tone');
ok(corrected.readLabel === '未读' && corrected.unread === true, 'unread is explicit');
ok(corrected.occurredLabel === '2026-11-27 09:19', 'notice time is Beijing time');
ok(corrected.actionLabel === '查看第 2 版报告', 'the action names the announced version');
ok(corrected.url === '/pages/examination/index?visit=1&id=1&revision=2', 'the row opens its exact version');
ok(corrected.ariaLabel.includes('课程文本检查') && corrected.ariaLabel.includes('检查报告已更新') &&
  corrected.ariaLabel.includes('未读'), 'the row has one spoken summary');

const read = buildNotice({id: 6, kind: 'RELEASED', title: '检查报告已发布', project: '课程文本检查',
  clinic: '演示甲店', occurred_at: '2026-11-27T01:20:01.329Z', read_at: '2026-11-27T01:20:04.560Z',
  visit_id: 1, examination_id: 7, revision: 1});
ok(read.readLabel === '已读' && read.unread === false, 'a read row says so');
ok(read.readLabelFull === '已读 2026-11-27 09:20', 'the read time stays available in Beijing time');
ok(read.actionLabel === '查看第 1 版报告', 'the read row still opens its version');

const withdrawn = buildNotice({id: 11, kind: 'WITHDRAWN', title: '检查报告已撤回', project: '课程文本检查',
  clinic: '演示甲店', occurred_at: '2026-11-27T01:20:02.982Z', read_at: null, visit_id: 1, examination_id: 2, revision: null});
ok(withdrawn.canOpen === false && withdrawn.url === '', 'a withdrawn notice never opens a report');
ok(withdrawn.actionLabel === '联系门店', 'a withdrawn notice offers the clinic');
ok(withdrawn.contactUrl === '/pages/help/index?visit=1', 'contact stays on the original visit');
ok(withdrawn.visitUrl === '/pages/visit/index?id=1', 'the original visit remains reachable');
ok(withdrawn.tone === 'status-cancelled', 'withdrawn keeps the cancelled tone');

const legacy = buildNotice({id: 12, kind: 'RELEASED', title: '检查报告已发布', clinic: '演示甲店',
  occurred_at: '2026-11-27T01:20:01.329Z', read_at: null, visit_id: 1, examination_id: 5, revision: 1});
ok(legacy.heading === '检查报告已发布', 'a missing project falls back to the existing title');
ok(legacy.showStatus === false, 'the fallback title is not repeated as a pill');
ok(legacy.title === '检查报告已发布', 'the original title is preserved');

ok(buildNotice({id: 0, kind: 'RELEASED'}) === null, 'a row without a numeric id is dropped');
ok(!buildNotice({id: 19, kind: 'PENDING', visit_id: 4, examination_id: 3, revision: 1}).canOpen,
  'a revision alone does not open an unpublished notice');

const list = buildNoticeList({rows: [corrected, legacy, null], unread_count: 8, page: 1,
  has_previous: false, has_next: true});
ok(list.rows.length === 2, 'invalid rows are filtered without breaking the list');
ok(list.unreadCount === 8 && list.hasNext === true, 'pagination and the unread count pass through');
ok(buildNoticeList({}).unreadCount === null, 'a missing count stays unknown');
ok(reportEntry({report_unread_count: 0}).unread === 0, 'zero unread still keeps the entry');
ok(reportEntry({report_unread_count: 3}, {delegated: true}) === null, 'a delegate has no patient entry');
ok(reportEntry({}) === null, 'a missing capability hides the entry');

// --- follow-up decisions ---------------------------------------------------
const booked = buildFollowup({action: 'VIEW_APPOINTMENT', label: '查看复诊预约',
  message: '已保存复诊安排，可查看当前预约。', clinic_id: 1, clinic: '演示甲店', service_id: 1,
  service: '课程初诊检查', earliest_on: '2026-12-01', latest_on: '2026-12-01',
  appointment: {id: 2, visit_no: 'V-00000000000000000000000000000001',
    start: '2026-12-01T02:00:00Z', status: 'SCHEDULED', status_label: '已预约'}},
  {visitId: 1, examinationId: 7, revision: 1});
ok(booked.action === 'VIEW_APPOINTMENT' && booked.canBook === false, 'a booked follow-up is not a booking action');
ok(booked.appointment.startLabel === '2026-12-01 10:00', 'the appointment keeps Beijing time');
ok(booked.appointment.statusLabel === '已预约' && booked.appointment.historical === false, 'current status passes through');
ok(booked.appointment.visitNo === 'V-00000000000000000000000000000001', 'the appointment number is exact');
ok(booked.appointmentLabel === '查看复诊预约' && booked.appointmentUrl === '/pages/visit/index?id=2',
  'the appointment entry names and targets the visit');
ok(booked.windowLabel === '2026-12-01', 'the suggested window stays separate from the booked time');

const rescheduled = buildFollowup({action: 'VIEW_APPOINTMENT', label: '查看复诊预约',
  message: '已保存复诊安排，可查看当前预约。', clinic_id: 1, clinic: '演示甲店', service_id: 1,
  service: '课程初诊检查', earliest_on: '2026-12-02', latest_on: '2026-12-02',
  appointment: {id: 3, visit_no: 'V-00000000000000000000000000000002',
    start: '2026-12-02T02:00:00Z', status: 'RESCHEDULED', status_label: '已改期替代'}},
  {visitId: 1, examinationId: 8, revision: 1});
ok(rescheduled.appointment.statusLabel === '已改期替代', 'a rescheduled predecessor keeps its exact state');
ok(rescheduled.appointment.historical === true, 'a historical appointment is marked as such');
ok(rescheduled.appointmentLabel === '查看历史预约', 'the link identifies the previous visit');
for (const status of ['CANCELLED', 'COMPLETED', 'CLOSED_NO_TREATMENT', 'NO_SHOW']) {
  const ended = buildFollowup({action: 'CONTACT', appointment: {id: 8, status}});
  ok(ended.appointment.historical && ended.appointmentLabel === '查看历史预约',
    'an ended visit remains history when the older server supplies only its status');
}

const available = buildFollowup({action: 'BOOK', label: '按建议日期预约复诊',
  message: '可在建议日期内选择有号时段。', clinic_id: 1, clinic: '演示甲店', service_id: 1,
  service: '课程初诊检查', earliest_on: '2026-11-29', latest_on: '2026-11-29'},
  {visitId: 1, examinationId: 4, revision: 1});
ok(available.canBook === true, 'a windowed report keeps the booking entry');
ok(available.bookingUrl === '/pages/booking/index?followup_visit=1&followup_examination=4&followup_revision=1',
  'the booking entry carries the exact report version');
ok(available.bookLabel === '查看可约时段', 'the booking entry names what it shows');
ok(available.windowLabel === '2026-11-29', 'a single-day window reads once');

const incomplete = buildFollowup({action: 'BOOK', label: '按建议日期预约复诊', clinic_id: 1,
  service_id: 1, earliest_on: '2026-11-29', latest_on: '2026-11-29'}, {visitId: 1});
ok(incomplete.action === 'CONTACT' && incomplete.canBook === false, 'an unbound BOOK degrades to contact');
ok(incomplete.message.length > 0 && incomplete.showContact === true, 'the degradation explains itself and offers the clinic');

const contact = buildFollowup({action: 'CONTACT', label: '联系原门店',
  message: '请联系原门店核对本报告的后续安排。', clinic_id: 1, clinic: '演示甲店'},
  {visitId: 1, examinationId: 9, revision: 1});
ok(contact.showContact === true && contact.contactLabel === '联系原门店', 'contact goes to the original clinic');
ok(contact.contactUrl === '/pages/help/index?visit=1', 'contact keeps the visit context');

const none = buildFollowup({action: 'NONE', label: '后续安排', message: '本报告供查阅。',
  clinic_id: 1, clinic: '演示甲店'}, {visitId: 1, examinationId: 1, revision: 2});
ok(none.action === 'NONE' && none.conclusionLabel === '后续安排', 'a read-only conclusion stays readable');
ok(none.message === '本报告供查阅。', 'the server conclusion text passes through');
ok(none.canBook === false && none.showContact === false && none.appointment === null, 'NONE offers no action');

const bookedMissing = buildFollowup({action: 'VIEW_APPOINTMENT', message: '', clinic_id: 1},
  {visitId: 1, examinationId: 7, revision: 1});
ok(bookedMissing.action === 'CONTACT' && bookedMissing.showContact === true,
  'a missing appointment degrades to contact instead of an empty claim');

ok(dayLabel('2026-11-29') === '2026-11-29', 'a date-only window is not shifted');
ok(dayLabel('2026-11-29T16:00:00Z') === '2026-11-30', 'a timestamp converts to the Beijing day');

module.exports = {passed: checks, total: checks, layer: 'Node JS contract assertions (no Django/DB)'};
if (require.main === module) console.log(JSON.stringify(module.exports));
