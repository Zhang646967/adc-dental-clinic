/* Pure projection of review.return_sources on GET visits/<id>/.
   The server owns the link, the report state and every business value. This
   module only decides which navigation entries may exist for this patient and
   formats the fixed action text. No clinical field is copied to the patient. */
const {positive} = require('./booking-intent');

function text(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function reportAction(project, revision) {
  const version = `第 ${revision} 版`;
  return project ? `查看${project} · ${version}` : `查看检查报告 · ${version}`;
}

function buildReturnSources(visit, {delegated = false} = {}) {
  // A delegate reads the appointment only; an older backend omits the array.
  if (!visit || delegated) return [];
  const review = visit.review;
  if (!review || !Array.isArray(review.return_sources)) return [];

  const rows = [];
  review.return_sources.forEach((raw, index) => {
    if (!raw || typeof raw !== 'object') return;
    const sourceId = positive(raw.source_visit_id) ? Number(raw.source_visit_id) : null;
    // Unknown states never become a link, a report entry or a contact action.
    const state = raw.state === 'CURRENT' || raw.state === 'CONTACT' ? raw.state : '';
    if (!sourceId || !state) return;

    const report = raw.report && typeof raw.report === 'object' ? raw.report : null;
    const reportId = report && positive(report.id) ? Number(report.id) : null;
    const revision = report && positive(report.revision) ? Number(report.revision) : null;
    const number = report ? text(report.number) : '';
    const project = report ? text(report.project) : '';
    // A changed source (CONTACT) never keeps a readable old report, and an
    // entry without its own number or version is not enough to open one.
    const openable = state === 'CURRENT' && !!reportId && !!revision && !!number;
    const sourceNo = text(raw.source_visit_no);

    rows.push({
      key: `${sourceId}-${index}`,
      sourceVisitId: sourceId,
      sourceNo,
      sourceLabel: sourceNo || `#${sourceId}`,
      service: text(raw.service) || '复诊来源',
      label: text(raw.label),
      canOpenSource: true,
      canContact: state === 'CONTACT',
      report: openable ? {
        id: reportId,
        revision,
        number,
        project,
        actionLabel: reportAction(project, revision)
      } : null
    });
  });
  return rows;
}

module.exports = {buildReturnSources};
