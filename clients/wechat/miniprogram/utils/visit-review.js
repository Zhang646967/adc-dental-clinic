/* Pure projection of GET /api/mini/v1/visits/<id>/ review data.
   The server owns every business value; this module only formats the Beijing
   timestamps, trims insignificant trailing zeros from quantities and keeps
   amounts at two decimals. No clinical or internal field is added here. */
const {dateTime} = require('./format');
const {positive} = require('./booking-intent');

function quantity(value) {
  return amount(value).replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '');
}

function amount(value) {
  return value === null || value === undefined ? '' : String(value);
}

function money(value) {
  if (value === null || value === undefined || value === '') return '';
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : String(value);
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function appointment(row) {
  if (!row || !positive(row.id)) return null;
  return {
    id: Number(row.id),
    visitNo: row.visit_no || '',
    startLabel: dateTime(row.start),
    status: row.status || '',
    statusLabel: row.status_label || '',
    clinic: row.clinic || ''
  };
}

/* The server passes these five values through booking_source. The existing
   report-bound flow still rechecks the report version before any preview. */
function bookingUrl(source) {
  if (!source || typeof source !== 'object') return '';
  const keys = ['clinic', 'service', 'followup_visit', 'followup_examination', 'followup_revision'];
  if (!keys.every(key => positive(source[key]))) return '';
  return `/pages/booking/index?clinic=${source.clinic}&service=${source.service}`
    + `&followup_visit=${source.followup_visit}&followup_examination=${source.followup_examination}`
    + `&followup_revision=${source.followup_revision}`;
}

/* An instruction owns its own active/history pair. The old `appointment`
   field is deliberately ignored: only active_appointment is a valid next
   appointment, and a cancelled or rescheduled row stays history. */
function followup(item) {
  if (!item || !positive(item.id)) return null;
  const rawAction = String(item.action || '').toUpperCase();
  const action = ['VIEW_APPOINTMENT', 'BOOK', 'CONTACT', 'NONE'].includes(rawAction) ? rawAction : 'NONE';
  const active = appointment(item.active_appointment);
  const historical = appointment(item.historical_appointment);
  const url = action === 'BOOK' ? bookingUrl(item.booking_source) : '';
  const showActive = (action === 'VIEW_APPOINTMENT' || action === 'CONTACT') && !!active;
  return {
    key: Number(item.id),
    id: Number(item.id),
    service: item.service || '',
    label: item.label || '',
    status: item.status || '',
    action,
    rangeLabel: (item.earliest_on || item.latest_on)
      ? `${item.earliest_on || ''} 至 ${item.latest_on || ''}` : '',
    overdue: !!item.overdue,
    active,
    historical,
    showActive,
    canOpenActive: showActive,
    canBook: !!url,
    bookingUrl: url,
    canContact: action === 'CONTACT'
  };
}

function buildReview(visit, {delegated = false} = {}) {
  // Older backends omit review entirely; the original detail and invoice_id
  // entry remain available in that case.
  if (!visit || !visit.review) return null;
  const raw = visit.review;
  const care = delegated ? null : raw.care;
  const settlement = delegated ? null : raw.settlement;
  const state = delegated ? null : (
    raw.settlement_state === 'PUBLISHED' || raw.settlement_state === 'AWAITING_PUBLICATION'
      ? raw.settlement_state
      : (settlement ? 'PUBLISHED' : (raw.completed_at ? 'AWAITING_PUBLICATION' : null)));
  const instructions = (delegated ? [] : (Array.isArray(raw.followups) ? raw.followups : []))
    .map(followup).filter(Boolean);

  const settlementView = settlement ? {
    invoiceId: positive(settlement.invoice_id) ? Number(settlement.invoice_id) : null,
    invoiceNo: settlement.invoice_no || '',
    revision: settlement.revision,
    total: money(settlement.total),
    remaining: money(settlement.remaining),
    refundDue: money(settlement.refund_due),
    reviewPending: !!settlement.review_pending,
    receipts: money(settlement.receipts),
    refunds: money(settlement.refunds),
    netReceived: money(settlement.net_received),
    advanceApplied: number(settlement.advance_applied) > 0 ? money(settlement.advance_applied) : '',
    insuranceFund: number(settlement.insurance_fund) > 0 ? money(settlement.insurance_fund) : '',
    insurancePersonalAccount: number(settlement.insurance_personal_account) > 0
      ? money(settlement.insurance_personal_account) : '',
    pendingRefunds: money(settlement.pending_refunds),
    pendingRefundDue: number(settlement.pending_refunds) > 0 ? money(settlement.pending_refunds) : ''
  } : null;

  const headline = settlementView ? (
    number(settlementView.remaining) > 0
      ? {kind: 'due', label: '尚需支付', amount: settlementView.remaining}
      : number(settlementView.refundDue) > 0
        ? {kind: 'refund', label: '应退余额', amount: settlementView.refundDue}
        : {kind: 'settled', label: '已结清', amount: ''}
  ) : null;

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
    settlementState: state,
    settlement: settlementView,
    settlementUnavailable: state === 'PUBLISHED' && !settlementView,
    headline,
    // A completed or attended visit owns the checkout block; scheduled visits
    // keep their original detail without inventing money or instructions.
    showCheckout: !delegated && (!!raw.completed_at || state !== null),
    followups: instructions
  };
}

module.exports = {buildReview};
