/* 18552: billing list and invoice projection plus page handlers with a
   controlled transport. Verifies one primary balance, version/balance clarity,
   stale responses, missing optional fields and return routing. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../clients/wechat/miniprogram');
const format = require(path.join(root, 'utils/format'));
const bookingIntent = require(path.join(root, 'utils/booking-intent'));
const billing = require(path.join(root, 'utils/billing'));

let checks = 0;
const ok = (value, message) => { assert.ok(value, message); checks++; };

function load(name, { session = {}, responses = [], pages = [] } = {}) {
  let definition;
  const calls = [];
  const routes = [];
  const api = {
    async request(...args) {
      calls.push(args);
      const next = responses.shift();
      if (next instanceof Error) throw next;
      if (typeof next === 'function') return next();
      return next;
    },
    sessionInfo: () => session
  };
  const navigation = {
    navigateTo: o => routes.push(['navigateTo', o.url]),
    returnTo: url => routes.push(['returnTo', url]),
    reLaunch: o => routes.push(['reLaunch', o.url]),
    redirectTo: o => routes.push(['redirectTo', o.url]),
    switchTab: o => routes.push(['switchTab', o.url])
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'pages', name, 'index.js'), 'utf8'), {
    Page: d => { definition = d; },
    getApp: () => ({ globalData: {} }),
    getCurrentPages: () => pages,
    wx: {},
    require: key => key.endsWith('/api') ? api
      : key.endsWith('/navigation') ? navigation
      : key.endsWith('/booking-intent') ? bookingIntent
      : key.endsWith('/billing') ? billing
      : key.endsWith('/format') ? format : null
  });
  return {
    page: Object.assign({}, definition, {
      data: JSON.parse(JSON.stringify(definition.data)),
      setData(v) { Object.assign(this.data, v); }
    }),
    calls, routes
  };
}

async function verify() {
  checks = 0;
  // --- money and one primary balance ---------------------------------------
  ok(billing.money('100.00') === '100.00', 'a decimal passes through');
  ok(billing.money('0') === '0.00', 'a whole number keeps two decimals');
  ok(billing.money('') === null && billing.money('abc') === null && billing.money(null) === null,
    'unknown amounts never become zero');
  ok(billing.amountLabel('37.5') === '¥ 37.50', 'an amount is formatted for reading');
  ok(billing.amountLabel('12.505') === '金额暂不可读', 'a malformed amount stays unknown');

  const due = billing.balanceState({remaining: '150.00', refund_due: '0.00'});
  ok(due.kind === 'due' && due.amount === '150.00', 'a positive remainder is the one balance');
  const refund = billing.balanceState({remaining: '0.00', refund_due: '40.00', pending_refunds: '40.00', review_pending: true});
  ok(refund.kind === 'refund' && refund.amount === '40.00', 'a refundable balance is shown as refund');
  ok(refund.note.includes('40.00') && refund.note.includes('待复核'), 'a pending refund is called out separately');
  const settled = billing.balanceState({remaining: '0.00', refund_due: '0.00'});
  ok(settled.kind === 'settled' && settled.amount === null, 'zero and nothing pending is settled');
  const insured = billing.balanceState({remaining: '0.00', refund_due: '0.00', insurance_pending: 1, review_pending: true});
  ok(insured.kind === 'pending' && insured.note.includes('医保'), 'a zero cash gap with insurance review is still pending');
  const excess = billing.balanceState({remaining: '0.00', refund_due: '0.00', advance_excess: '20.00'});
  ok(excess.kind === 'pending' && excess.note.includes('20.00'), 'an advance excess is still pending');
  const unknown = billing.balanceState({remaining: null, refund_due: '0.00'});
  ok(unknown.kind === 'unknown' && unknown.amount === null, 'an unreadable remainder stays unknown');

  // --- list rows ------------------------------------------------------------
  const rowA = billing.billingRow({id: 1, invoice_no: 'I-D08DF39EA0C04F5B88B15DD1963B6D6B', visit_id: 1,
    clinic: '云庭口腔 · 江畔门诊', scheduled_start: '2026-11-26T01:00:00Z', published_at: '2026-11-26T01:05:00Z',
    revision: 1, total: '100.00', remaining: '0.00', refund_due: '0.00', advance_excess: '0.00',
    insurance_pending: 0, review_pending: false});
  ok(rowA.versionLabel === '第 1 版' && rowA.status.kind === 'settled', 'a settled row reads settled');
  ok(rowA.scheduledLabel === '2026-11-26 09:00', 'the visit time is Beijing time');
  ok(rowA.visitId === 1 && rowA.openLabel === '查看结算单与明细', 'the row keeps its visit and names the action');
  ok(rowA.ariaLabel.includes('已结清') && rowA.ariaLabel.includes('第 1 版'), 'the row has one spoken summary');
  const rows = billing.billingList({rows: [rowA], page: 2, pages: 2, count: 11, previous: 1, next: null});
  ok(rows.rows.length === 1 && rows.page === 2 && rows.hasPrevious === true && rows.hasNext === false,
    'pagination and count pass through');

  // --- invoice view: current and historical versions ------------------------
  const cPending = {
    invoice_no: 'I-AEADB617D5F14AAD836104AD24A2E2F5', revision: 2, is_current: true,
    published_at: '2026-11-26T02:05:00Z', total: '160.00', outcome: 'TREATED',
    treatment_lines: [{name_snapshot: '修复评估与阶段处置', unit_snapshot: '次', quantity: '2.000', unit_price: '80.00', line_amount: '160.00'}],
    medication_lines: [], no_charge_stages: [],
    cash_balance: {billed: '160.00', remaining: '0.00', refund_due: '40.00', receipts: '200.00', refunds: '0.00',
      net_received: '200.00', advance_applied: '0.00', advance_excess: '0.00', insurance_fund: '0.00',
      insurance_personal_account: '0.00', patient_responsibility: '160.00', pending_refunds: '40.00',
      insurance_pending: 0, pending: 1, current_revision: 2},
    revisions: [{revision_no: 2, published_at: '2026-11-26T02:05:00Z'}, {revision_no: 1, published_at: '2026-11-26T02:05:00Z'}]
  };
  const current = billing.invoiceView(cPending);
  ok(current.revision === 2 && current.totalLabel === '¥ 160.00', 'the selected version total is shown');
  ok(current.state.kind === 'refund' && current.state.amount === '40.00', 'the current refund is the one balance');
  ok(current.balanceRevision === 2 && current.balanceLabel === '第 2 版余额', 'the balance names its own version');
  ok(current.staleBalance === false, 'a current version does not warn about a stale balance');
  ok(current.notes.some(n => n.key === 'pending-refund'), 'a pending refund is a separate note');
  ok(current.notes.some(n => n.key === 'pending-cash'), 'a pending cash request is a separate note');
  ok(current.treatment[0].quantity === '2.000' && current.medication.length === 0, 'version lines pass through');
  ok(current.cash.refunds === '¥ 0.00' && current.cash.pendingRefunds === '¥ 40.00',
    'posted refunds and pending refunds stay separate');

  const historical = billing.invoiceView(Object.assign({}, cPending, {revision: 1, is_current: false, total: '200.00',
    treatment_lines: [{name_snapshot: '修复评估与阶段处置', unit_snapshot: '次', quantity: '2.000', unit_price: '100.00', line_amount: '200.00'}]}));
  ok(historical.revision === 1 && historical.totalLabel === '¥ 200.00', 'a historical version keeps its own total');
  ok(historical.balanceRevision === 2 && historical.staleBalance === true,
    'the current balance is labelled with its own version when reading history');
  ok(historical.state.amount === '40.00', 'the current balance does not follow the historical version');

  const drug = billing.invoiceView({revision: 2, is_current: true, total: '37.50', outcome: 'PHARMACY_ONLY',
    treatment_lines: [], medication_lines: [{name_snapshot: '合成目录条目甲', unit_snapshot: '演练片', quantity: 3, unit_price: '12.50', line_amount: '37.50'}],
    no_charge_stages: [], cash_balance: {billed: '37.50', remaining: '0.00', refund_due: '0.00', receipts: '50.00',
      refunds: '12.50', net_received: '37.50', pending_refunds: '0.00', current_revision: 2}});
  ok(drug.special && drug.special.kind === 'pharmacy', 'pharmacy-only care explains itself');
  ok(drug.emptyFeeText === '' && drug.medication.length === 1, 'medication lines are not treated as empty');
  const zero = billing.invoiceView({revision: 1, is_current: true, total: '0.00', outcome: 'TREATED',
    treatment_lines: [], medication_lines: [], no_charge_stages: [{name_snapshot: '修复评估与阶段处置', unit_snapshot: '次', quantity: '1.000'}],
    cash_balance: {billed: '0.00', remaining: '0.00', refund_due: '0.00', pending_refunds: '0.00', current_revision: 1}});
  ok(zero.special && zero.special.kind === 'staged' && zero.stages.length === 1, 'a staged treatment explains the zero charge');
  const none = billing.invoiceView({revision: 1, is_current: true, total: '0.00', outcome: 'NO_TREATMENT',
    treatment_lines: [], medication_lines: [], no_charge_stages: [],
    cash_balance: {billed: '0.00', remaining: '0.00', refund_due: '0.00', pending_refunds: '0.00', current_revision: 1}});
  ok(none.special && none.special.kind === 'no-treatment', 'no treatment explains itself');
  ok(none.emptyFeeText === '', 'no treatment uses its own explanation, not a generic empty line');
  const legacy = billing.invoiceView({revision: 1, is_current: true, total: '100.00', revisions: []});
  ok(legacy.state.kind === 'unknown' && legacy.cash === null, 'an older response without a balance stays unknown');
  const unknownMoney = billing.invoiceView({revision: 1, total: 'abc', cash_balance: {remaining: 'abc', refund_due: '0.00'}});
  ok(unknownMoney.totalLabel === '金额暂不可读' && unknownMoney.state.kind === 'unknown', 'unreadable amounts stay unknown');
  ok(billing.versionOptions(cPending).length === 2 && billing.versionOptions(cPending)[0].revision === 2,
    'the published history keeps server order');

  // --- billing page handlers ------------------------------------------------
  const pageOne = {rows: [{id: 1, invoice_no: 'I-1', visit_id: 1, clinic: '演示甲店', scheduled_start: '2026-11-26T01:00:00Z',
    revision: 1, total: '100.00', remaining: '0.00', refund_due: '0.00'}], page: 1, pages: 2, count: 11, next: 2};
  const list = load('billing', { responses: [pageOne] });
  list.page.onLoad({});
  await list.page.onShow();
  ok(list.calls[0][0] === 'billing/' && list.calls[0][2].page === 1, 'the list reads its page');
  ok(list.page.data.rows.length === 1 && list.page.data.hasNext === true, 'the list keeps the server page state');
  list.page.open({currentTarget: {dataset: {index: 0}}});
  ok(list.routes.at(-1)[1] === '/pages/invoice/index?id=1&visit=1&from=billing&page=1',
    'opening a bill keeps its page and visit');

  list.page.data.busy = true;
  await list.page.turn({currentTarget: {dataset: {step: 1}}});
  ok(list.calls.length === 1, 'a busy list ignores a second page turn');
  list.page.data.busy = false;
  list.page.onHide();
  ok(list.page.data.rows.length === 0 && list.page.page === 1, 'leaving clears the rows but keeps the page');

  let release;
  const late = load('billing', { responses: [() => new Promise(r => { release = r; }), Object.assign({}, pageOne, {page: 2, rows: []})] });
  late.page.onLoad({});
  const staleRead = late.page.onShow();
  const freshRead = late.page.load(2);
  await freshRead;
  release(pageOne);
  await staleRead;
  ok(late.page.data.page === 2 && late.page.data.rows.length === 0, 'a late list response cannot restore an older page');

  const failed = load('billing', { responses: [Object.assign(new Error('当前授权已失效'), {status: 403})] });
  failed.page.onLoad({});
  await failed.page.onShow();
  ok(failed.page.data.rows.length === 0 && failed.page.data.error, 'a denied list keeps no old row');

  // --- invoice page handlers ------------------------------------------------
  const invoiceData = {id: 3, invoice_no: 'I-AEADB617D5F14AAD836104AD24A2E2F5', revision: 2, is_current: true,
    published_at: '2026-11-26T02:05:00Z', total: '160.00', outcome: 'TREATED',
    treatment_lines: [{name_snapshot: '处置', unit_snapshot: '次', quantity: '2.000', unit_price: '80.00', line_amount: '160.00'}],
    medication_lines: [], no_charge_stages: [],
    cash_balance: {billed: '160.00', remaining: '0.00', refund_due: '40.00', pending_refunds: '40.00', current_revision: 2},
    revisions: [{revision_no: 2, published_at: '2026-11-26T02:05:00Z'}, {revision_no: 1, published_at: '2026-11-26T02:05:00Z'}],
    cash_activity: {receipts: '200.00', refunds: '0.00', entries: [{id: 4, label: '收款', amount: '200.00', occurred_on: '2026-11-26', status: '已记账', posted_at: '2026-11-26T02:05:00Z'}], count: 1, page: 1, pages: 1, previous: null, next: null}};
  const detail = load('invoice', { responses: [invoiceData] });
  detail.page.onLoad({id: '3', visit: '5', from: 'billing', page: '2'});
  await detail.page.onShow();
  ok(detail.calls[0][0] === 'invoices/3/' && detail.calls[0][2].cash_page === 1, 'the current version is read first');
  ok(detail.page.data.view.state.amount === '40.00', 'the invoice shows its one balance');
  ok(detail.page.data.cashOpen === false, 'cash details start collapsed');
  detail.page.toggleCash();
  ok(detail.page.data.cashOpen === true, 'cash details open on request');
  detail.page.version({detail: {value: 1}});
  ok(detail.calls.at(-1)[2].revision === 1 && detail.calls.at(-1)[2].cash_page === 1,
    'a version switch resets the cash page and asks for that version');
  ok(detail.page.data.cashOpen === false, 'a version switch closes the old detail');
  detail.page.onHide();
  ok(detail.page.data.invoice === null && detail.page.data.view === null && detail.page.data.cashOpen === false,
    'leaving clears the bill and its expansion');

  let lateBill;
  const raced = load('invoice', { responses: [() => new Promise(r => { lateBill = r; }), invoiceData] });
  raced.page.onLoad({id: '3'});
  const firstBill = raced.page.onShow();
  const secondBill = raced.page.load();
  await secondBill;
  lateBill(Object.assign({}, invoiceData, {revision: 1, total: '200.00'}));
  await firstBill;
  ok(raced.page.data.view.revision === 2 && raced.page.data.view.totalLabel === '¥ 160.00',
    'a late invoice response cannot replace the newer version');

  const fromBilling = [{route: 'pages/billing/index', options: {}}, {route: 'pages/invoice/index', options: {}}];
  const routed = load('invoice', { responses: [invoiceData], pages: fromBilling });
  routed.page.onLoad({id: '3', from: 'billing', page: '2'});
  await routed.page.onShow();
  routed.page.back();
  ok(routed.routes.at(-1)[0] === 'returnTo' && routed.routes.at(-1)[1] === '/pages/billing/index',
    'the bill returns to the existing list so its page stays');

  const direct = load('invoice', { responses: [invoiceData], pages: [{route: 'pages/home/index', options: {}}, {route: 'pages/invoice/index', options: {}}] });
  direct.page.onLoad({id: '3', from: 'billing', page: '2'});
  await direct.page.onShow();
  direct.page.back();
  ok(direct.routes.at(-1)[1] === '/pages/billing/index?page=2', 'a direct bill rebuilds the list at its page');

  const fromVisit = load('invoice', { responses: [invoiceData], pages: [{route: 'pages/visit/index', options: {id: '5'}}, {route: 'pages/invoice/index', options: {}}] });
  fromVisit.page.onLoad({id: '3', visit: '5'});
  await fromVisit.page.onShow();
  fromVisit.page.back();
  ok(fromVisit.routes.at(-1)[1] === '/pages/visit/index?id=5', 'a bill opened from a visit returns to that visit');

  return { passed: checks, total: checks, layer: 'Node JS billing projection and page handlers' };
}

module.exports = { verify };
if (require.main === module) verify().then(r => console.log(JSON.stringify(r)))
  .catch(e => { console.error(e.message); process.exit(1); });
