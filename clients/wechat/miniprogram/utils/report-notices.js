/* Pure projection of the patient report notices, the home entry capability and
   the follow-up block on a released report. The server owns notice state, the
   exact report version and the follow-up decision; this module only decides
   which entry a row exposes and formats Beijing time. */
const {dateTime} = require('./format');
const {positive} = require('./booking-intent');

const KIND_LABELS = {RELEASED: '报告已发布', CORRECTED: '报告已更新', WITHDRAWN: '报告已撤回'};
const KIND_TONES = {RELEASED: 'status-upcoming', CORRECTED: 'status-rescheduled', WITHDRAWN: 'status-cancelled'};
const ACTIONS = ['BOOK', 'VIEW_APPOINTMENT', 'CONTACT', 'NONE'];

function dayLabel(value) {
  if (!value) return '';
  const text = String(value);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : dateTime(text).slice(0, 10);
}

/* The home entry exists only for the patient themself and only when the
   overview actually carries the capability. A missing or null count hides it;
   zero still opens the list. */
function reportEntry(overview, {delegated = false} = {}) {
  if (delegated || !overview || typeof overview !== 'object') return null;
  const count = overview.report_unread_count;
  if (!Number.isInteger(count) || count < 0) return null;
  return {unread: count};
}

function buildNotice(row) {
  if (!row || !positive(row.id)) return null;
  const kind = String(row.kind || '').toUpperCase();
  const withdrawn = kind === 'WITHDRAWN';
  const visitId = positive(row.visit_id) ? row.visit_id : null;
  const examinationId = positive(row.examination_id) ? row.examination_id : null;
  const revision = positive(row.revision) ? row.revision : null;
  // A released or corrected notice opens the exact version it announced.
  // Without a version the row falls back to the original visit instead of
  // silently opening whatever version happens to be current.
  const canOpen = (kind === 'RELEASED' || kind === 'CORRECTED') && !!visitId && !!examinationId && !!revision;
  const unread = !row.read_at;
  // The clinic keeps the notice's own project name; an older backend omits it,
  // so the row falls back to the existing server title instead of inventing one.
  const project = typeof row.project === 'string' ? row.project.trim() : '';
  const statusLabel = row.title || KIND_LABELS[kind] || '报告提醒';
  const heading = project || statusLabel;
  // With a project the server title becomes the status pill; without one the
  // heading already is that title, so the pill would repeat it.
  const showStatus = !!project && project !== statusLabel;
  const clinic = row.clinic || '';
  const occurredLabel = dateTime(row.occurred_at);
  const readLabel = unread ? '未读' : '已读';
  const actionLabel = canOpen ? `查看第 ${revision} 版报告` : '联系门店';
  return {
    id: row.id,
    kind,
    kindLabel: KIND_LABELS[kind] || '报告提醒',
    tone: KIND_TONES[kind] || 'status-finished',
    project,
    heading,
    statusLabel,
    showStatus,
    title: row.title || KIND_LABELS[kind] || '检查报告提醒',
    clinic,
    occurredLabel,
    unread,
    readLabel,
    readAt: row.read_at || null,
    readLabelFull: unread ? '未读' : '已读' + (row.read_at ? ' ' + dateTime(row.read_at) : ''),
    withdrawn,
    canOpen,
    visitId,
    examinationId,
    revision,
    actionLabel,
    // One spoken summary per row: project, server status, read state, clinic
    // and Beijing time. Buttons name their own action separately.
    ariaLabel: [heading, showStatus ? statusLabel : '', readLabel, clinic, occurredLabel && occurredLabel + '（北京时间）']
      .filter(Boolean).join('，'),
    url: canOpen ? `/pages/examination/index?visit=${visitId}&id=${examinationId}&revision=${revision}` : '',
    visitUrl: visitId ? `/pages/visit/index?id=${visitId}` : '',
    contactUrl: visitId ? `/pages/help/index?visit=${visitId}` : '/pages/help/index'
  };
}

function buildNoticeList(data) {
  const rows = Array.isArray(data && data.rows) ? data.rows.map(buildNotice).filter(Boolean) : [];
  const count = data && data.unread_count;
  return {
    rows,
    unreadCount: Number.isInteger(count) && count >= 0 ? count : null,
    page: positive(data && data.page) ? data.page : 1,
    hasPrevious: !!(data && data.has_previous),
    hasNext: !!(data && data.has_next)
  };
}

/* Follow-up actions are authoritative on the server. BOOK needs the exact
   report version that produced the decision, so a missing parameter degrades
   to the clinic contact path rather than opening an unbound booking flow. */
function buildFollowup(followup, {visitId = null, examinationId = null, revision = null} = {}) {
  if (!followup || typeof followup !== 'object') return null;
  let action = String(followup.action || '').toUpperCase();
  if (ACTIONS.indexOf(action) < 0) return null;
  const appointment = followup.appointment && positive(followup.appointment.id) ? {
    id: followup.appointment.id,
    visitNo: followup.appointment.visit_no || '',
    startLabel: dateTime(followup.appointment.start),
    status: followup.appointment.status || '',
    statusLabel: followup.appointment.status_label || '',
    // A cancelled or rescheduled predecessor keeps the server's own state so a
    // historical record is never presented as the current appointment.
    historical: typeof followup.appointment.historical === 'boolean' ? followup.appointment.historical
      : ['CANCELLED', 'RESCHEDULED', 'COMPLETED', 'CLOSED_NO_TREATMENT', 'NO_SHOW'].includes(followup.appointment.status)
  } : null;
  const canBook = action === 'BOOK' && positive(followup.clinic_id) && positive(followup.service_id) &&
    positive(visitId) && positive(examinationId) && positive(revision);
  const firstDay = dayLabel(followup.first_day || followup.earliest_on);
  const lastDay = dayLabel(followup.last_day || followup.latest_on);
  const earliest = dayLabel(followup.earliest_on) || firstDay;
  const latest = dayLabel(followup.latest_on) || lastDay;
  let message = followup.message || '';
  if (action === 'BOOK' && !canBook) {
    action = 'CONTACT';
    message = message || '当前报告暂不支持自助预约复诊，请联系原门店或返回原就诊核对。';
  }
  if (action === 'VIEW_APPOINTMENT' && !appointment) {
    action = 'CONTACT';
    message = message || '复诊预约暂不可查看，请联系原门店核对。';
  }
  const conclusionLabel = followup.label || (action === 'NONE' ? '后续安排' : '');
  return {
    action,
    label: followup.label || '',
    conclusionLabel,
    message,
    clinic: followup.clinic || '',
    service: followup.service || '',
    clinicId: positive(followup.clinic_id) ? followup.clinic_id : null,
    serviceId: positive(followup.service_id) ? followup.service_id : null,
    firstDay,
    lastDay,
    // A one-day window is a date, not a range.
    windowLabel: earliest && latest ? (earliest === latest ? earliest : `${earliest} 至 ${latest}`) : (earliest || latest),
    appointment,
    canBook,
    showContact: action === 'CONTACT',
    bookingUrl: canBook ? `/pages/booking/index?followup_visit=${visitId}&followup_examination=${examinationId}&followup_revision=${revision}` : '',
    appointmentUrl: appointment ? `/pages/visit/index?id=${appointment.id}` : '',
    contactUrl: positive(visitId) ? `/pages/help/index?visit=${visitId}` : '/pages/help/index',
    // The server caption names the next step; the buttons below use it too so
    // the visible text and the spoken action never diverge.
    bookLabel: '查看可约时段',
    appointmentLabel: appointment && appointment.historical ? '查看历史预约' : '查看复诊预约',
    contactLabel: '联系原门店'
  };
}

module.exports = {reportEntry, buildNotice, buildNoticeList, buildFollowup, dayLabel};
