/* Node contract assertions for the visit checkout projection. */
const assert=require('node:assert/strict');
const {buildReview}=require('../clients/wechat/miniprogram/utils/visit-review');

let count=0;
const check=fn=>{fn();count+=1;};
const visit=review=>({status:'COMPLETED',review});
const base={
  attended_at:'2026-11-24T01:00:00Z',completed_at:'2026-11-24T01:05:00Z',settlement_state:'PUBLISHED',
  care:{outcome:'TREATED',outcome_label:'有治疗',treatments:[],medications:[]},
  settlement:{invoice_id:1,invoice_no:'I-1',revision:1,total:'300',review_pending:false,receipts:'100',
    refunds:'0',net_received:'100',advance_applied:'50',insurance_fund:'60',insurance_personal_account:'20',
    remaining:'150',refund_due:'0',pending_refunds:'0'},
  followups:[],return_sources:[]
};

check(()=>assert.equal(buildReview({}),null));
check(()=>assert.equal(buildReview({review:null}),null));
check(()=>{
  const r=buildReview(visit(base));
  assert.equal(r.settlementState,'PUBLISHED');
  assert.equal(r.settlement.total,'300.00');
  assert.equal(r.settlement.receipts,'100.00');
  assert.equal(r.settlement.refunds,'0.00');
  assert.equal(r.settlement.advanceApplied,'50.00');
  assert.equal(r.settlement.insuranceFund,'60.00');
  assert.equal(r.settlement.insurancePersonalAccount,'20.00');
  assert.deepEqual(r.headline,{kind:'due',label:'尚需支付',amount:'150.00'});
});
check(()=>{
  const r=buildReview(visit({...base,settlement:{...base.settlement,remaining:'0',refund_due:'40',pending_refunds:'40',refunds:'0'}}));
  assert.deepEqual(r.headline,{kind:'refund',label:'应退余额',amount:'40.00'});
  assert.equal(r.settlement.pendingRefundDue,'40.00');
});
check(()=>{
  const r=buildReview(visit({...base,settlement:{...base.settlement,remaining:'0.00',refund_due:'0.00'}}));
  assert.deepEqual(r.headline,{kind:'settled',label:'已结清',amount:''});
});
check(()=>{
  // A published zero bill is different from an unpublished one.
  const r=buildReview(visit({...base,settlement:{...base.settlement,total:'0.00',receipts:'0.00',refunds:'0.00',
    net_received:'0.00',advance_applied:'0.00',insurance_fund:'0.00',insurance_personal_account:'0.00',
    remaining:'0.00',refund_due:'0.00',pending_refunds:'0.00'}}));
  assert.equal(r.settlementState,'PUBLISHED');
  assert.equal(r.settlement.total,'0.00');
  assert.equal(r.headline.label,'已结清');
});
check(()=>{
  const r=buildReview(visit({attended_at:'2026-11-24T05:30:00Z',completed_at:null,settlement_state:'AWAITING_PUBLICATION',
    care:null,settlement:null,followups:[],return_sources:[]}));
  assert.equal(r.showCheckout,true);
  assert.equal(r.settlementState,'AWAITING_PUBLICATION');
  assert.equal(r.settlement,null);
  assert.equal(r.headline,null);
});
check(()=>{
  // Older backend: settlement exists, new fields absent.
  const r=buildReview(visit({...base,settlement_state:null,settlement:{invoice_id:2,invoice_no:'I-2',revision:1,
    total:'80',remaining:'20',refund_due:'0',review_pending:true}}));
  assert.equal(r.settlementState,'PUBLISHED');
  assert.equal(r.settlement.total,'80.00');
  assert.equal(r.settlement.receipts,'');
  assert.equal(r.settlement.advanceApplied,'');
  assert.equal(r.headline.label,'尚需支付');
});
check(()=>{
  // An older completed response without a settlement is still "not published",
  // never a broken published bill.
  const r=buildReview(visit({...base,settlement_state:null,settlement:null,care:null}));
  assert.equal(r.settlementState,'AWAITING_PUBLICATION');
  assert.equal(r.settlement,null);
});
check(()=>{
  // Zero-valued optional items are not itemised; the server only sends them
  // when they actually apply.
  const r=buildReview(visit({...base,settlement:{...base.settlement,advance_applied:'0.00',
    insurance_fund:'0.00',insurance_personal_account:'0.00',pending_refunds:'0'}}));
  assert.equal(r.settlement.advanceApplied,'');
  assert.equal(r.settlement.insuranceFund,'');
  assert.equal(r.settlement.insurancePersonalAccount,'');
  assert.equal(r.settlement.pendingRefundDue,'');
});
check(()=>{
  const r=buildReview(visit(base),{delegated:true});
  assert.equal(r.care,null);
  assert.equal(r.settlement,null);
  assert.equal(r.settlementState,null);
  assert.equal(r.showCheckout,false);
  assert.deepEqual(r.followups,[]);
});
check(()=>{
  const r=buildReview(visit({...base,followups:[{id:1,service:'修复',label:'已安排复诊',status:'BOOKED',
    earliest_on:'2026-11-27',latest_on:'2026-12-02',overdue:false,action:'VIEW_APPOINTMENT',
    active_appointment:{id:3,visit_no:'V-3',start:'2026-11-27T02:00:00Z',status:'SCHEDULED',
      status_label:'已预约',clinic:'云庭口腔 · 江畔门诊'},
    historical_appointment:{id:2,visit_no:'V-2',start:'2026-11-27T01:00:00Z',status:'RESCHEDULED',
      status_label:'已改期替代',clinic:'云庭口腔 · 江畔门诊'},booking_source:null}]}));
  const [row]=r.followups;
  assert.equal(row.active.id,3);
  assert.equal(row.active.startLabel,'2026-11-27 10:00');
  assert.equal(row.historical.id,2);
  assert.equal(row.historical.status,'RESCHEDULED');
  assert.equal(row.showActive,true);
  assert.equal(row.canContact,false);
  assert.equal(row.canBook,false);
});
check(()=>{
  // The old appointment field must never be promoted to the next appointment.
  const r=buildReview(visit({...base,followups:[{id:1,label:'旧字段',status:'WAITING',action:'CONTACT',
    appointment:{id:9,visit_no:'V-9',start:'2026-11-30T04:00:00Z',status:'SCHEDULED',status_label:'已预约'}}]}));
  const [row]=r.followups;
  assert.equal(row.active,null);
  assert.equal(row.showActive,false);
  assert.equal(row.canContact,true);
});
check(()=>{
  const r=buildReview(visit({...base,followups:[{id:2,label:'尚未预约',status:'WAITING',action:'BOOK',
    earliest_on:'2026-11-27',latest_on:'2026-12-02',booking_source:{clinic:1,service:1,followup_visit:4,
      followup_examination:1,followup_revision:1}}]}));
  const [row]=r.followups;
  assert.equal(row.canBook,true);
  assert.equal(row.bookingUrl,'/pages/booking/index?clinic=1&service=1&followup_visit=4&followup_examination=1&followup_revision=1');
});
check(()=>{
  const r=buildReview(visit({...base,followups:[{id:2,label:'尚未预约',action:'BOOK',
    booking_source:{clinic:1,service:1,followup_visit:4,followup_examination:0,followup_revision:1}}]}));
  assert.equal(r.followups[0].canBook,false);
  assert.equal(r.followups[0].bookingUrl,'');
});
check(()=>{
  // A changed basis keeps the retained active appointment and the store entry.
  const r=buildReview(visit({...base,followups:[{id:5,label:'待门店核对',status:'REVIEW',action:'CONTACT',
    active_appointment:{id:9,visit_no:'V-9',start:'2026-11-30T04:00:00Z',status:'SCHEDULED',status_label:'已预约'},
    historical_appointment:null,booking_source:null}]}));
  const [row]=r.followups;
  assert.equal(row.canContact,true);
  assert.equal(row.showActive,true);
  assert.equal(row.active.id,9);
});
check(()=>{
  // A cancelled appointment without a successor only appears as history.
  const r=buildReview(visit({...base,followups:[{id:3,label:'待重新安排',status:'WAITING',action:'CONTACT',
    active_appointment:null,historical_appointment:{id:10,visit_no:'V-10',start:'2026-11-27T03:00:00Z',
      status:'CANCELLED',status_label:'已取消',clinic:'云庭口腔 · 江畔门诊'}}]}));
  const [row]=r.followups;
  assert.equal(row.active,null);
  assert.equal(row.showActive,false);
  assert.equal(row.historical.status,'CANCELLED');
  assert.equal(row.historical.statusLabel,'已取消');
});
check(()=>{
  const r=buildReview(visit({...base,followups:[{id:6,label:'查阅记录',status:'REVIEW',action:'NONE',
    active_appointment:{id:9,visit_no:'V-9',start:'2026-11-30T04:00:00Z',status:'SCHEDULED',status_label:'已预约'},
    historical_appointment:{id:10,visit_no:'V-10',start:'2026-11-27T03:00:00Z',status:'CANCELLED',status_label:'已取消'}}]}));
  const [row]=r.followups;
  assert.equal(row.showActive,false);
  assert.equal(row.canContact,false);
  assert.equal(row.canBook,false);
  assert.equal(row.historical.id,10);
});
check(()=>{
  const r=buildReview(visit({...base,followups:[{id:1,action:'SOMETHING_ELSE',active_appointment:null}]}));
  assert.equal(r.followups[0].action,'NONE');
});
check(()=>assert.deepEqual(buildReview(visit({...base,followups:[{id:0,action:'CONTACT'},{label:'x'},null]})).followups,[]));
check(()=>{
  const r=buildReview(visit({...base,followups:[],care:null}));
  assert.deepEqual(r.followups,[]);
  assert.equal(r.showCheckout,true);
});
check(()=>{
  // Clinical and internal fields never enter this projection.
  const r=buildReview(visit({...base,allergies:['合成材料甲'],plan_goal:'内部目标',
    followups:[{id:1,label:'待门店核对',action:'CONTACT',tooth:'16 牙',record_revision:2}]}));
  const text=JSON.stringify(r);
  for(const secret of ['合成材料甲','内部目标','16 牙','record_revision'])assert(!text.includes(secret));
});
check(()=>{
  // A scheduled visit with no checkout state keeps the original detail.
  const r=buildReview({status:'SCHEDULED',review:{attended_at:null,completed_at:null,settlement_state:null,
    care:null,settlement:null,followups:[],return_sources:[]}});
  assert.equal(r.showCheckout,false);
  assert.equal(r.settlement,null);
});
console.log(JSON.stringify({layer:'Node JS contract assertions (no Django/DB)',passed:count,total:count}));
