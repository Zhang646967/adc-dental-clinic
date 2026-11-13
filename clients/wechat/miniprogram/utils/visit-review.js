/* Pure projection of GET /api/mini/v1/visits/<id>/ review data.
   The server owns every business value; this module only formats the Beijing
   timestamps and trims insignificant trailing zeros from quantities. */
const {dateTime} = require('./format');

function quantity(value) {
  return amount(value).replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '');
}

function amount(value) {
  return value === null || value === undefined ? '' : String(value);
}

function buildReview(visit, {delegated = false} = {}) {
  // Older backends omit review entirely; the original detail and invoice_id
  // entry remain available in that case.
  if (!visit || !visit.review) return null;
  const raw = visit.review;
  const care = delegated ? null : raw.care;
  const settlement = delegated ? null : raw.settlement;
  const followups = (delegated ? [] : raw.followups || []).map(item => {
    const booked = !!(item.appointment && item.appointment.id);
    return {
      id: item.id,
      service: item.service || '',
      label: item.label || '',
      status: item.status || '',
      rangeLabel: (item.earliest_on || item.latest_on) ? `${item.earliest_on || ''} 至 ${item.latest_on || ''}` : '',
      overdue: !!item.overdue,
      needsContact: item.status === 'WAITING' || item.status === 'REVIEW',
      appointment: booked ? {
        id: item.appointment.id,
        visitNo: item.appointment.visit_no || '',
        startLabel: dateTime(item.appointment.start),
        statusLabel: item.appointment.status_label || ''
      } : null
    };
  });

  return {
    attendedLabel: dateTime(raw.attended_at),
    completedLabel: delegated ? '' : dateTime(raw.completed_at),
    care: care ? {
      outcomeLabel: care.outcome_label || '',
      treatments: (care.treatments || []).map((row, index) => ({
        key: index,
        name: row.name || '',
        quantity: quantity(row.quantity),
        unit: row.unit || '',
        noCharge: row.kind === 'NO_CHARGE_STAGE'
      })),
      medications: (care.medications || []).map((row, index) => ({
        key: index,
        name: row.name || '',
        netQuantity: quantity(row.net_quantity),
        unit: row.unit || '',
        amount: amount(row.amount)
      }))
    } : null,
    settlement: settlement ? {
      invoiceId: settlement.invoice_id,
      invoiceNo: settlement.invoice_no || '',
      revision: settlement.revision,
      total: amount(settlement.total),
      remaining: amount(settlement.remaining),
      refundDue: amount(settlement.refund_due),
      reviewPending: !!settlement.review_pending
    } : null,
    followups
  };
}

module.exports = {buildReview};
