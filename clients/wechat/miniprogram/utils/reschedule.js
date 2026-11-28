/* Pure projection of a reschedule: the retained original appointment and the
   proposed slot must be readable side by side, each with its own date, start,
   end, clinic, dentist and service. The server owns every value; this module
   only formats Beijing time and leaves a field empty when the response omits
   it instead of borrowing the other appointment's value. */
const {dateTime} = require('./format');
const {positive} = require('./booking-intent');

function minutesBetween(start, end) {
  const from = Date.parse(start), to = Date.parse(end);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return null;
  return Math.round((to - from) / 60000);
}

function durationLabel(minutes) {
  return positive(minutes) ? minutes + ' 分钟' : '';
}

/* A candidate row carries the service number in `service`, and an optional
   readable `service_name`. The duration is derived from that row's own start
   and end, never from the original appointment. */
function candidate(row) {
  if (!row || typeof row !== 'object') return null;
  const name = typeof row.service_name === 'string' ? row.service_name.trim() : '';
  const minutes = minutesBetween(row.start, row.end);
  return Object.assign({}, row, {
    startLabel: dateTime(row.start),
    endLabel: dateTime(row.end),
    serviceLabel: name,
    durationLabel: durationLabel(minutes),
    durationMinutes: minutes
  });
}

function originalFacts(original) {
  if (!original || typeof original !== 'object') return null;
  return {
    id: positive(original.id) ? Number(original.id) : null,
    visitNo: original.visit_no || '',
    clinic: original.clinic || '',
    dentist: original.dentist || '',
    dentistId: positive(original.dentist_id) ? Number(original.dentist_id) : null,
    serviceLabel: original.service || '',
    statusLabel: original.status_label || '',
    startLabel: dateTime(original.start),
    endLabel: dateTime(original.end),
    dayLabel: original.start ? dateTime(original.start).slice(0, 10) : ''
  };
}

function proposedFacts(preview, includePartial) {
  if (!preview || typeof preview !== 'object') return null;
  if (!preview.start && !(includePartial && (preview.end || preview.clinic || preview.dentist ||
      preview.service_name || positive(preview.duration_minutes)))) return null;
  const minutes = positive(preview.duration_minutes) ? Number(preview.duration_minutes)
    : minutesBetween(preview.start, preview.end);
  const name = typeof preview.service_name === 'string' ? preview.service_name.trim() : '';
  return {
    clinic: preview.clinic || '',
    dentist: preview.dentist || '',
    dentistId: positive(preview.dentist_id) ? Number(preview.dentist_id) : null,
    // An older response has no service_name; fall back only to a readable
    // service string, never to the original appointment's name.
    serviceLabel: name || (typeof preview.service === 'string' ? preview.service : ''),
    durationLabel: durationLabel(minutes),
    durationMinutes: minutes,
    durationChanged: !!preview.duration_changed,
    startLabel: dateTime(preview.start),
    endLabel: dateTime(preview.end),
    dayLabel: dateTime(preview.start).slice(0, 10)
  };
}

// Both endpoints are already in Beijing time. Repeat the date only when
// the interval crosses midnight, including across a year boundary.
function clockRange(facts, sharedDay) {
  if (!facts) return '';
  const start = facts.startLabel;
  const end = facts.endLabel;
  if (!start) return end ? '至 ' + end : '';
  const first = sharedDay ? start.slice(11) : start;
  if (!end) return first;
  return start.slice(0, 10) === end.slice(0, 10)
    ? first + '–' + end.slice(11) : first + ' 至 ' + end;
}

function reviewSummary(original, proposed, originalMinutes) {
  const sharedDay = original && proposed && original.dayLabel && original.dayLabel === proposed.dayLabel &&
    original.endLabel.startsWith(original.dayLabel) && proposed.endLabel.startsWith(proposed.dayLabel)
    ? original.dayLabel : '';
  const shared = [];
  const originalOnly = [];
  const proposedOnly = [];
  const doctorIdsKnown = !!(original && proposed && original.dentistId && proposed.dentistId);
  const doctorChanged = doctorIdsKnown && original.dentistId !== proposed.dentistId;
  let originalDentistDetail = '';
  for (const [field, label] of [['clinic', '门店'], ['dentist', '医师'], ['serviceLabel', '服务']]) {
    const before = original && original[field];
    const after = proposed && proposed[field];
    if (field === 'dentist' && before && before === after && !doctorIdsKnown) {
      // A matching display name alone does not establish the clinician's identity.
      proposedOnly.push({label, value: after});
      originalDentistDetail = before;
    } else if (before && before === after && !(field === 'dentist' && doctorChanged)) {
      shared.push({label, value: before});
    } else {
      if (before) originalOnly.push({label, value: before});
      if (after) proposedOnly.push({label, value: after});
    }
  }
  const changed = !!(proposed && (proposed.durationChanged ||
    (originalMinutes && proposed.durationMinutes && originalMinutes !== proposed.durationMinutes)));
  return {
    sharedDay,
    originalTime: clockRange(original, sharedDay),
    proposedTime: clockRange(proposed, sharedDay),
    shared, originalOnly, proposedOnly, doctorChanged, originalDentistDetail,
    durationChanged: changed,
    originalDuration: changed ? durationLabel(originalMinutes) : '',
    proposedDuration: proposed ? proposed.durationLabel : ''
  };
}

function comparison(preview, forRescheduleReview = false) {
  if (!preview || typeof preview !== 'object') return null;
  const original = originalFacts(preview.original);
  const proposed = proposedFacts(preview, forRescheduleReview);
  if (!original && !proposed) return null;
  return {
    original,
    proposed,
    summary: forRescheduleReview ? reviewSummary(original, proposed,
      original && minutesBetween(preview.original.start, preview.original.end)) : null,
    sameDay: !!(original && proposed && original.dayLabel === proposed.dayLabel),
    changedDay: !!(original && proposed && original.dayLabel !== proposed.dayLabel)
  };
}

function lineage(visit) {
  if (!visit) return null;
  const previous = positive(visit.predecessor) ? Number(visit.predecessor) : null;
  const next = positive(visit.successor) ? Number(visit.successor) : null;
  if (!previous && !next) return null;

  // A successor can itself be replaced, cancelled or completed.
  if (next) {
    return {
      previous, next,
      title: previous ? '本记录 · 再次改期前的预约' : '本记录 · 原预约',
      note: '这次预约已改期，可查看下一笔预约的时间和状态。'
    };
  }
  const upcoming = visit.status === 'SCHEDULED' && !visit.needs_outcome_review;
  return {
    previous, next,
    title: upcoming ? '本记录 · 改期后的当前预约' : '本记录 · 改期后的预约',
    note: upcoming ? '到诊时间以本记录为准。' : ''
  };
}

module.exports = {candidate, comparison, lineage, minutesBetween, durationLabel};
