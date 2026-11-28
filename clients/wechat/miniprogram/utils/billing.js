/* Pure projection of the patient billing list and one invoice.
   The server owns every business value: version, amounts, cash state and the
   care outcome. This module only formats decimals, chooses the one balance a
   patient should read first and labels optional fields that an older backend
   may omit. */
const {dateTime} = require('./format');
const {positive} = require('./booking-intent');

function money(value) {
  if (value === null || value === undefined || value === '') return null;
  const text = String(value).trim();
  if (!/^-?\d+(?:\.\d{1,2})?$/.test(text)) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number.toFixed(2) : null;
}

function amountLabel(value) {
  const formatted = money(value);
  return formatted === null ? '金额暂不可读' : '¥ ' + formatted;
}

function count(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0;
}

/* One primary balance per bill: pay, refund, settled, or a zero cash gap that
   still has something to review. Unknown amounts never become zero. */
function balanceState(source) {
  if (!source || typeof source !== 'object') {
    return {kind: 'unknown', label: '余额暂不可读', tone: 'status-unknown', amount: null,
      note: '当前版本未能读取余额，请打开结算单核对。'};
  }
  const remaining = money(source.remaining);
  const refund = money(source.refund_due);
  const pendingRefunds = money(source.pending_refunds);
  const advanceExcess = money(source.advance_excess);
  const insurancePending = count(source.insurance_pending);
  const reviewPending = !!source.review_pending;
  if (remaining === null || refund === null) {
    return {kind: 'unknown', label: '余额暂不可读', tone: 'status-unknown', amount: null,
      note: '当前版本未能读取余额，请打开结算单核对。'};
  }
  const due = Number(remaining), back = Number(refund);
  if (due > 0) {
    return {kind: 'due', label: '尚需支付', tone: 'status-rescheduled', amount: remaining,
      note: reviewPending ? '有收退款待复核，当前应付按已确认记录显示。' : ''};
  }
  if (back > 0) {
    const pending = pendingRefunds !== null && Number(pendingRefunds) > 0;
    return {kind: 'refund', label: '应退余额', tone: 'status-arrived', amount: refund,
      note: pending ? '其中 ¥ ' + pendingRefunds + ' 的退款申请待复核，尚未记账。'
        : (reviewPending ? '有退款记录待复核，以门店复核后为准。' : '')};
  }
  if (insurancePending > 0) {
    return {kind: 'pending', label: '待处理', tone: 'status-rescheduled', amount: null,
      note: '现金差额为 ¥ 0.00，另有 ' + insurancePending + ' 笔医保原请求待处理。'};
  }
  if (advanceExcess !== null && Number(advanceExcess) > 0) {
    return {kind: 'pending', label: '待处理', tone: 'status-rescheduled', amount: null,
      note: '现金差额为 ¥ 0.00，预收抵扣超额 ¥ ' + advanceExcess + ' 待核对。'};
  }
  if (reviewPending) {
    return {kind: 'pending', label: '待处理', tone: 'status-rescheduled', amount: null,
      note: '现金差额为 ¥ 0.00，另有收退款事项待复核。'};
  }
  return {kind: 'settled', label: '已结清', tone: 'status-finished', amount: null, note: ''};
}

function billingRow(row) {
  if (!row || !positive(row.id)) return null;
  const state = balanceState(row);
  const version = positive(row.revision) ? Number(row.revision) : null;
  const invoiceNo = row.invoice_no || '';
  const clinic = row.clinic || '';
  const scheduledLabel = row.scheduled_start ? dateTime(row.scheduled_start) : '';
  return {
    id: row.id,
    visitId: positive(row.visit_id) ? Number(row.visit_id) : null,
    invoiceNo,
    clinic,
    scheduledLabel,
    publishedLabel: row.published_at ? dateTime(row.published_at) : '',
    revision: version,
    versionLabel: version ? '第 ' + version + ' 版' : '版本暂不可读',
    totalLabel: amountLabel(row.total),
    status: state,
    ariaLabel: [clinic, scheduledLabel && '就诊 ' + scheduledLabel, version ? '第 ' + version + ' 版' : '',
      state.amount ? state.label + ' ¥ ' + state.amount : state.label].filter(Boolean).join('，'),
    openLabel: '查看结算单与明细'
  };
}

function billingList(data) {
  const rows = Array.isArray(data && data.rows) ? data.rows.map(billingRow).filter(Boolean) : [];
  return {
    rows,
    page: positive(data && data.page) ? data.page : 1,
    pages: positive(data && data.pages) ? data.pages : 1,
    count: Number.isFinite(Number(data && data.count)) ? Number(data.count) : rows.length,
    hasPrevious: !!(data && data.previous),
    hasNext: !!(data && data.next)
  };
}

function lines(rows, kind) {
  return (Array.isArray(rows) ? rows : []).map((row, index) => ({
    key: index,
    kind,
    name: row.name_snapshot || '',
    quantity: row.quantity === null || row.quantity === undefined ? '' : String(row.quantity),
    unit: row.unit_snapshot || '',
    unitPriceLabel: amountLabel(row.unit_price),
    amountLabel: amountLabel(row.line_amount),
    noCharge: kind === 'stage'
  }));
}

function invoiceView(invoice) {
  if (!invoice || typeof invoice !== 'object') return null;
  const cash = invoice.cash_balance && typeof invoice.cash_balance === 'object' ? invoice.cash_balance : null;
  const revision = positive(invoice.revision) ? Number(invoice.revision) : null;
  const balanceRevision = cash && positive(cash.current_revision) ? Number(cash.current_revision) : revision;
  const state = balanceState(cash ? Object.assign({}, cash, {review_pending: cash.review_pending}) : null);
  const treatment = lines(invoice.treatment_lines || invoice.lines, 'treatment');
  const medication = lines(invoice.medication_lines, 'medication');
  const stages = lines(invoice.no_charge_stages, 'stage');
  const outcome = String(invoice.outcome || '').toUpperCase();
  let special = null;
  if (outcome === 'NO_TREATMENT') {
    special = {kind: 'no-treatment', text: '本次未治疗，无治疗收费。'};
  } else if (outcome === 'PHARMACY_ONLY') {
    special = {kind: 'pharmacy', text: '本次仅发退药，费用按实际发出减退回计算，未发生治疗收费。'};
  } else if (stages.length && !treatment.length) {
    special = {kind: 'staged', text: '本次为阶段治疗，按约定本次不另计费。'};
  }
  const pendingRefunds = cash ? money(cash.pending_refunds) : null;
  const insurancePending = cash ? count(cash.insurance_pending) : 0;
  const advanceExcess = cash ? money(cash.advance_excess) : null;
  const notes = [];
  if (pendingRefunds !== null && Number(pendingRefunds) > 0) {
    notes.push({key: 'pending-refund', text: '待复核退款 ¥ ' + pendingRefunds + '，尚未计入已记账退款。'});
  }
  if (cash && cash.pending) notes.push({key: 'pending-cash', text: '有 ' + count(cash.pending) + ' 笔收退款请求待复核，尚未计入已记账金额。'});
  if (insurancePending) notes.push({key: 'insurance', text: '有 ' + insurancePending + ' 笔医保原请求待处理，非现金承担不代表资金到账。'});
  if (advanceExcess !== null && Number(advanceExcess) > 0) {
    notes.push({key: 'advance', text: '预收抵扣超额 ¥ ' + advanceExcess + '，请联系原门店核对。'});
  }
  return {
    revision,
    revisionLabel: revision ? '第 ' + revision + ' 版' : '版本暂不可读',
    current: !!invoice.is_current,
    invoiceNo: invoice.invoice_no || '',
    publishedLabel: invoice.published_at ? dateTime(invoice.published_at) : '',
    totalLabel: amountLabel(invoice.total),
    treatment,
    medication,
    stages,
    hasFeeLines: !!(treatment.length || medication.length),
    special,
    emptyFeeText: !special && !treatment.length && !medication.length && !stages.length
      ? '本版没有收费项目，请结合就诊结果核对。' : '',
    balanceRevision,
    balanceLabel: balanceRevision ? '第 ' + balanceRevision + ' 版余额' : '当前余额',
    staleBalance: !!(balanceRevision && revision && balanceRevision !== revision),
    staleBalanceText: balanceRevision && revision && balanceRevision !== revision
      ? '以下余额对应当前第 ' + balanceRevision + ' 版，不是所选历史版本的费用。' : '',
    state,
    notes,
    cash: cash ? {
      billed: amountLabel(cash.billed),
      remaining: amountLabel(cash.remaining),
      refundDue: amountLabel(cash.refund_due),
      receipts: amountLabel(cash.receipts),
      refunds: amountLabel(cash.refunds),
      netReceived: amountLabel(cash.net_received),
      advanceApplied: amountLabel(cash.advance_applied),
      insuranceFund: amountLabel(cash.insurance_fund),
      insurancePersonal: amountLabel(cash.insurance_personal_account),
      patientResponsibility: amountLabel(cash.patient_responsibility),
      pendingRefunds: pendingRefunds === null ? '金额暂不可读' : '¥ ' + pendingRefunds,
      advanceExcess: advanceExcess === null ? '金额暂不可读' : '¥ ' + advanceExcess
    } : null,
    cashOpenLabel: '查看已记账收退款与分担明细',
    cashCloseLabel: '收起收款与退款明细'
  };
}

function versionOptions(invoice) {
  return (Array.isArray(invoice && invoice.revisions) ? invoice.revisions : []).map(row => ({
    revision: row.revision_no,
    label: '第 ' + row.revision_no + ' 版 · ' + (row.published_at ? dateTime(row.published_at) : '发布时间暂不可读')
  }));
}

module.exports = {money, amountLabel, balanceState, billingRow, billingList, invoiceView, versionOptions};
