/* Pure projection of the examinations array on GET visits/<id>/ and of the
   released report detail. The server owns state, version and body text; this
   module only decides whether a patient entry exists and formats Beijing time. */
const {dateTime} = require('./format');

function buildExaminations(visit, {delegated = false} = {}) {
  // A delegate sees the appointment only; an older backend omits the array.
  if (!visit || delegated || !Array.isArray(visit.examinations)) return [];
  return visit.examinations.map(row => {
    const published = row.state === 'PUBLISHED' &&
      row.revision !== null && row.revision !== undefined;
    return {
      id: row.id,
      number: row.number || '',
      project: row.project || '',
      state: row.state || '',
      label: row.label || '',
      revision: row.revision,
      revisionLabel: published ? `第 ${row.revision} 版` : '',
      releasedLabel: published ? dateTime(row.released_at) : '',
      canOpen: published
    };
  });
}

function buildReport(data) {
  if (!data || !data.id) return null;
  return {
    id: data.id,
    number: data.number || '',
    project: data.project || '',
    visitId: data.visit_id,
    visitNo: data.visit_no || '',
    revision: data.revision,
    performedLabel: dateTime(data.performed_at),
    releasedLabel: dateTime(data.released_at),
    body: data.body || ''
  };
}

module.exports = {buildExaminations, buildReport};
