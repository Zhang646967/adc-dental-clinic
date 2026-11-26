/* Node contract assertions for the recall primary action and visit focus. */
const assert=require('node:assert/strict');
const {primaryAction}=require('../clients/wechat/miniprogram/utils/primary-action');
const {buildReview}=require('../clients/wechat/miniprogram/utils/visit-review');

let count=0;
const check=fn=>{fn();count+=1;};
const overview=followup=>({primary_action:{kind:'VISIT_FOLLOWUP',label:'复诊时间待安排',button:'查看下次安排',
  hint:'建议日期已过，您尚未预约。可联系云庭口腔 · 江畔门诊核对时间。',visit:null,offer:null,followup}});
const visit=review=>({status:'COMPLETED',review});
const base={attended_at:'2026-11-25T01:00:00Z',completed_at:'2026-11-25T01:05:00Z',settlement_state:'PUBLISHED',
  care:null,settlement:null,followups:[],return_sources:[]};

check(()=>{
  const r=primaryAction(overview({visit_id:1,instruction_id:1}));
  assert.equal(r.kind,'VISIT_FOLLOWUP');
  assert.equal(r.url,'/pages/visit/index?id=1&instruction=1');
  assert.equal(r.label,'复诊时间待安排');
  assert.equal(r.actionLabel,'查看下次安排');
  assert.equal(r.hint,'建议日期已过，您尚未预约。可联系云庭口腔 · 江畔门诊核对时间。');
});
check(()=>{
  // A server-supplied URL is never used; only the two numeric ids are read.
  const raw=overview({visit_id:1,instruction_id:2});
  raw.primary_action.url='https://example.invalid/private';
  const r=primaryAction(raw);
  assert.equal(r.url,'/pages/visit/index?id=1&instruction=2');
});
check(()=>assert.equal(primaryAction({}),null));
check(()=>assert.equal(primaryAction({primary_action:{kind:'VISIT_FOLLOWUP'}}),null));
check(()=>{
  const r=primaryAction({primary_action:{kind:'UPCOMING_VISIT',label:'下一次就诊',button:'查看到诊安排',
    hint:'核对时间和门店。',visit:{id:6,visit_no:'V-E81063EB831F4A67997AB9A5430BF899',
      start:'2026-11-28T02:00:00Z',end:'2026-11-28T02:30:00Z',status:'SCHEDULED',status_label:'已预约',
      clinic:'云庭口腔 · 江畔门诊',dentist:'演示医生1',service:'修复评估与复查'},offer:null}});
  assert.equal(r.url,'/pages/visit/index?id=6');
  assert.equal(r.visitNo,'V-E81063EB831F4A67997AB9A5430BF899');
  assert.equal(r.timeLabel,'2026-11-28 10:00');
});
check(()=>assert.equal(primaryAction(overview(null)),null));
check(()=>assert.equal(primaryAction(overview({visit_id:1})),null));
check(()=>assert.equal(primaryAction(overview({visit_id:0,instruction_id:1})),null));
check(()=>assert.equal(primaryAction(overview({visit_id:'x',instruction_id:1})),null));
check(()=>assert.equal(primaryAction(overview({visit_id:1,instruction_id:'1 OR 1=1'})),null));
check(()=>{
  const report={kind:'REPORT_FOLLOWUP',label:'复诊待安排',button:'查看报告与复诊',hint:'查看报告',
    visit:null,offer:null,report:{visit_id:9,id:3,revision:2}};
  const r=primaryAction({primary_action:report});
  assert.equal(r.url,'/pages/examination/index?visit=9&id=3&revision=2');
  assert.equal(r.label,'复诊待安排');
});
check(()=>{
  const rows=[
    {id:1,service:'修复评估与复查',label:'尚未预约',status:'WAITING',action:'CONTACT',
      earliest_on:'2026-11-25',latest_on:'2026-11-25',overdue:true,message:'需要继续安排时，可联系原门店。'},
    {id:2,service:'修复评估与复查',label:'尚未预约',status:'WAITING',action:'CONTACT',
      earliest_on:'2026-11-25',latest_on:'2026-11-26',overdue:false,message:''}
  ];
  const r=buildReview(visit({...base,followups:rows}),{instruction:1});
  assert.equal(r.followups.length,2);
  assert.equal(r.followups[0].selected,true);
  assert.equal(r.followups[1].selected,false);
  assert.equal(r.followups[0].message,'需要继续安排时，可联系原门店。');
});
check(()=>{
  const rows=[{id:5,service:'修复评估与复查',label:'复诊安排已暂缓',status:'REVIEW',action:'CONTACT',
    earliest_on:'2026-11-25',latest_on:'2026-11-26',overdue:false,message:'需要继续安排时，可联系原门店。'}];
  const r=buildReview(visit({...base,followups:rows}),{instruction:6});
  assert.equal(r.followups[0].selected,false);
  assert.equal(r.followups[0].label,'复诊安排已暂缓');
  assert.equal(r.followups[0].canContact,true);
});
check(()=>{
  const rows=[{id:1,action:'CONTACT',overdue:false}];
  assert.equal(buildReview(visit({...base,followups:rows}),{instruction:null}).followups[0].selected,false);
  assert.equal(buildReview(visit({...base,followups:rows}),{delegated:true,instruction:1}).followups.length,0);
});
check(()=>{
  const rows=[{id:6,service:'修复',label:'已安排复诊',status:'BOOKED',action:'VIEW_APPOINTMENT',
    earliest_on:'2026-11-28',latest_on:'2026-12-03',
    active_appointment:{id:6,visit_no:'V-ACTIVE',start:'2026-11-28T02:00:00Z',status:'SCHEDULED',status_label:'已预约',clinic:'云庭'},
    historical_appointment:{id:5,visit_no:'V-OLD',start:'2026-11-28T01:00:00Z',status:'RESCHEDULED',status_label:'已改期替代',clinic:'云庭'}}];
  const r=buildReview(visit({...base,followups:rows}));
  const row=r.followups[0];
  assert.equal(row.active.visitNo,'V-ACTIVE');
  assert.equal(row.historical.visitNo,'V-OLD');
  assert.equal(row.showActive,true);
  assert.equal(row.canContact,false);
});
check(()=>{
  // Legacy shape without the new fields still exposes a contact entry and a
  // linked record without promoting it to the next appointment.
  const rows=[{id:8,service:'修复',label:'待重新安排',status:'WAITING',
    appointment:{id:7,visit_no:'V-CANCELLED',start:'2026-11-28T03:00:00Z',status:'CANCELLED',status_label:'已取消',clinic:'云庭'}}];
  const r=buildReview(visit({...base,followups:rows}));
  const row=r.followups[0];
  assert.equal(row.action,'CONTACT');
  assert.equal(row.active,null);
  assert.equal(row.historical.status,'CANCELLED');
  assert.equal(row.canContact,true);
});
module.exports={layer:'Node JS contract assertions (no Django/DB)',passed:count,total:count};
if(require.main===module)console.log(JSON.stringify(module.exports));
