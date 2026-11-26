/* Pure projection of a visit list row and the detail header.
   The server owns every status, time and permission; this module only groups
   the status into the four patient-facing kinds (预约、到诊、已结束、已改期),
   formats Beijing time and decides which action label the row carries. */
const {dateTime} = require('./format');
const {positive} = require('./booking-intent');

const KINDS = {
  SCHEDULED: {kind: 'upcoming', note: ''},
  CHECKED_IN: {kind: 'arrived', note: '前台已登记到诊，接诊进度以现场指引为准。'},
  COMPLETED: {kind: 'finished', note: '这次就诊已结束。'},
  CLOSED_NO_TREATMENT: {kind: 'finished', note: '这次就诊已结束。'},
  NO_SHOW: {kind: 'missed', note: '这次预约未到诊。'},
  RESCHEDULED: {kind: 'rescheduled', note: '原预约已改期替代，请按有效预约到诊。'},
  CANCELLED: {kind: 'cancelled', note: '这次预约已取消。'}
};
const FALLBACK = {kind: 'unknown', note: ''};

function record(visit, {delegated = false} = {}) {
  if (!visit || !positive(visit.id)) return null;
  const start = dateTime(visit.start);
  const end = dateTime(visit.end);
  const meta = KINDS[visit.status] || FALLBACK;
  const finished = meta.kind === 'finished';
  // A same-day slot reads as one line; a cross-day one keeps both dates.
  const whenLabel = start.slice(0, 10) === end.slice(0, 10)
    ? `${start}–${end.slice(11)}`
    : `${start} 至 ${end}`;
  return Object.assign({}, visit, {
    kind: meta.kind,
    note: meta.note,
    startLabel: start,
    endLabel: end,
    whenLabel,
    dateLabel: start.slice(0, 10),
    timeLabel: `${start.slice(11)}–${end.slice(11)}`,
    visitNo: visit.visit_no || '',
    // The detail page shows the id and the full number together; the list
    // keeps them in the disclosure so a long number never crowds the row.
    numberLabel: visit.visit_no ? `#${visit.id} · ${visit.visit_no}` : `#${visit.id}`,
    finished,
    // Mirrors the patient web: a finished record opens its result and bill.
    actionLabel: finished && !delegated ? '查看就诊与结算' : '查看预约详情',
    detailLabel: finished ? '就诊编号与说明' : '预约编号与说明',
    hasRequest: !delegated && !!visit.patient_request,
    open: false
  });
}

module.exports = {record, KINDS};
