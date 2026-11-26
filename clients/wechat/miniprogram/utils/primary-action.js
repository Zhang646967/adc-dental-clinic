/* Map the server's single primary action onto an existing page.
   The server decides which action wins; this module only formats labels and
   assembles a local path from the kind plus the official id. */
const {arrangement, dateTime} = require('./format');

const SPEC = {
  CHECKED_IN: {label: '正在就诊', hint: '查看正在就诊的预约', target: 'visit', action: '查看就诊安排'},
  CONFIRM_OFFER: {label: '待确认邀约', hint: '时段为限时保留，请先核对截止时间。', target: 'offer', action: '查看并决定'},
  UPCOMING_VISIT: {label: '下一次就诊', hint: '打开安排与到诊提示。', target: 'visit', action: '查看安排与到诊提示'},
  CONTACT_CLINIC: {label: '请联系门店核实', hint: '请与门店前台核对这次办理结果。', target: 'contact', action: '查看门店联系方式'},
  WAITLIST: {label: '候补进度', hint: '查看等待、确认和成约结果。', target: 'waitlist', action: '查看候补进度'},
  REPORT_FOLLOWUP: {label: '复诊待安排', hint: '查看检查报告与复诊建议。', target: 'report', action: '查看报告与复诊'},
  VISIT_FOLLOWUP: {label: '复诊时间待安排', hint: '查看这次就诊的建议复诊安排。', target: 'followup', action: '查看下次安排'},
  BOOK: {label: '预约就诊', hint: '从服务目录选择门店、服务与时段。', target: 'book', action: '预约就诊'}
};

const REVIEW_HINT = '请联系门店核实';

function id(value) {
  const n = Number(value);
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

function primaryAction(overview) {
  const raw = overview && overview.primary_action;
  if (!raw || !raw.kind || !SPEC[raw.kind]) return null;
  const spec = SPEC[raw.kind];
  const visit = raw.visit ? arrangement(raw.visit) : null;
  const offer = raw.offer ? Object.assign({}, raw.offer, {expiresLabel: dateTime(raw.offer.expires_at)}) : null;

  let url = '';
  if (spec.target === 'visit') {
    if (!visit || !id(visit.id)) return null;
    url = `/pages/visit/index?id=${id(visit.id)}`;
  } else if (spec.target === 'offer') {
    if (!offer || !id(offer.id)) return null;
    url = `/pages/offer/index?id=${id(offer.id)}`;
  } else if (spec.target === 'contact') {
    if (!visit || !id(visit.id)) return null;
    url = `/pages/help/index?visit=${id(visit.id)}`;
  } else if (spec.target === 'waitlist') {
    url = '/pages/waitlist/index';
  } else if (spec.target === 'book') {
    url = '/pages/services/index';
  } else if (spec.target === 'report') {
    const report = raw.report;
    if (!report || ![report.visit_id, report.id, report.revision].every(value => Number.isSafeInteger(value) && value > 0)) return null;
    url = `/pages/examination/index?visit=${report.visit_id}&id=${report.id}&revision=${report.revision}`;
  } else if (spec.target === 'followup') {
    // Only the two numeric ids are trusted; no server-supplied URL is opened.
    const followup = raw.followup;
    const visitId = followup && id(followup.visit_id);
    const instructionId = followup && id(followup.instruction_id);
    if (!visitId || !instructionId) return null;
    url = `/pages/visit/index?id=${visitId}&instruction=${instructionId}`;
  } else {
    return null;
  }

  // A visit flagged for outcome review keeps its business status; only the
  // wording changes so the patient knows to confirm with the clinic.
  const review = !!(visit && visit.needs_outcome_review);
  const timeLabel = visit ? visit.startLabel : '';
  const detail = visit ? `${visit.clinic} · ${visit.dentist}` : '';
  const serviceLine = visit ? `${visit.service} · ${visit.status_label}` : '';
  const deadline = offer && offer.expires_at ? `请在 ${offer.expiresLabel} 前确认（北京时间）` : '';
  const copy = (spec.target === 'report' || spec.target === 'followup') ? raw : {};

  return {
    kind: raw.kind,
    label: review ? REVIEW_HINT : copy.label || spec.label,
    hint: review ? '预约状态仍以门店核实为准。' : copy.hint || spec.hint,
    actionLabel: review ? '查看门店联系方式' : copy.button || spec.action,
    url,
    review,
    timeLabel,
    detail,
    serviceLine,
    deadline,
    offerId: offer ? id(offer.id) : null,
    visitId: visit ? id(visit.id) : null,
    visitNo: visit ? (visit.visit_no || '') : ''
  };
}

module.exports = {primaryAction, REVIEW_HINT, KINDS: Object.keys(SPEC)};
