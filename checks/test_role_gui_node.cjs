/* Node contract assertions for the 18550 patient list/detail shell.
   These check the source projections and the default page state; they do not
   render the WeChat runtime. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {record}=require('../clients/wechat/miniprogram/utils/visit-record');

let count=0;
const check=fn=>{fn();count+=1;};
const row=extra=>Object.assign({
  id:4,visit_no:'V-SYNTHETIC-EXAMPLE',clinic:'测试门店',dentist:'测试医师',
  start:'2026-11-25T02:30:00+00:00',end:'2026-11-25T03:00:00+00:00',status:'CLOSED_NO_TREATMENT',
  status_label:'无治疗关闭',service:'修复评估与复查',patient_request:'',needs_outcome_review:false
},extra||{});

check(()=>assert.equal(record(null),null));
check(()=>assert.equal(record({id:0}),null));

check(()=>{
  // One appointment slot reads as a single Beijing line.
  const r=record(row());
  assert.equal(r.whenLabel,'2026-11-25 10:30–11:00');
  assert.equal(r.startLabel,'2026-11-25 10:30');
  assert.equal(r.dateLabel,'2026-11-25');
  assert.equal(r.timeLabel,'10:30–11:00');
});

check(()=>{
  const r=record(row({end:'2026-11-26T02:30:00+00:00'}));
  assert.equal(r.whenLabel,'2026-11-25 10:30 至 2026-11-26 10:30');
});

check(()=>{
  // The four patient-facing kinds, not the raw workflow status.
  assert.equal(record(row({status:'SCHEDULED'})).kind,'upcoming');
  assert.equal(record(row({status:'CHECKED_IN'})).kind,'arrived');
  assert.equal(record(row({status:'COMPLETED'})).kind,'finished');
  assert.equal(record(row({status:'CLOSED_NO_TREATMENT'})).kind,'finished');
  assert.equal(record(row({status:'RESCHEDULED'})).kind,'rescheduled');
  assert.equal(record(row({status:'CANCELLED'})).kind,'cancelled');
  assert.equal(record(row({status:'SOMETHING_NEW'})).kind,'unknown');
});

check(()=>{
  const missed=record(row({status:'NO_SHOW',status_label:'未到诊'}));
  assert.equal(missed.actionLabel,'查看预约详情');
  assert.equal(missed.detailLabel,'预约编号与说明');
  assert.equal(missed.status_label,'未到诊');
});

check(()=>{
  const r=record(row({id:7,visit_no:'V-53FF',status:'CANCELLED'}));
  assert.equal(r.numberLabel,'#7 · V-53FF');
  assert.equal(r.note,'这次预约已取消。');
  assert.equal(r.actionLabel,'查看预约详情');
});

check(()=>{
  // Finished records open the result and bill for the patient, never for a delegate.
  assert.equal(record(row()).actionLabel,'查看就诊与结算');
  assert.equal(record(row(),{delegated:true}).actionLabel,'查看预约详情');
  assert.equal(record(row({status:'SCHEDULED'})).actionLabel,'查看预约详情');
});

check(()=>{
  const r=record(row({patient_request:'示例文字'}));
  assert.equal(r.hasRequest,true);
  assert.equal(record(row({patient_request:'x'}),{delegated:true}).hasRequest,false);
  assert.equal(r.open,false);
  assert.equal(r.detailLabel,'就诊编号与说明');
  assert.equal(record(row({status:'SCHEDULED'})).detailLabel,'预约编号与说明');
});

check(()=>{
  const r=record(row({id:9,visit_no:''}));
  assert.equal(r.numberLabel,'#9');
});

/* Load a page module with a capturing Page() so its initial data is visible. */
function pageData(relative){
  const file=path.resolve(__dirname,'../clients/wechat/miniprogram',relative);
  let captured=null;
  const previous=global.Page;
  global.Page=value=>{captured=value;};
  try{
    delete require.cache[require.resolve(file)];
    require(file);
  }finally{global.Page=previous;}
  assert.ok(captured&&captured.data,relative+' must register a Page with data');
  return captured.data;
}

check(()=>{
  // Both detail disclosures start closed and the labels stay explicit.
  const data=pageData('pages/visit/index.js');
  assert.equal(data.infoOpen,false);
  assert.equal(data.moneyOpen,false);
  assert.equal(data.infoOpenLabel,'展开就诊编号');
  assert.equal(data.moneyOpenLabel,'展开收款与退款明细');
});

check(()=>{
  const data=pageData('pages/discovery/index.js');
  assert.equal(data.moreOpen,false);
  assert.equal(data.reportEntry,null);
});

check(()=>{
  const data=pageData('pages/home/index.js');
  assert.equal(data.queue,'active');
  assert.ok(!('expanded' in data));
});

const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');

check(()=>{
  const wxml=read('pages/home/index.wxml');
  assert.match(wxml,/bindtap="toggleRow"[^>]*aria-expanded="\{\{item\.open\}\}"/);
  assert.match(wxml,/bindtap="open">\{\{item\.actionLabel\}\}/);
  assert.match(wxml,/暂无待到诊的预约/);
});

check(()=>{
  const wxml=read('pages/visit/index.wxml');
  assert.match(wxml,/bindtap="toggleInfo"[^>]*aria-expanded="\{\{infoOpen\}\}"/);
  assert.match(wxml,/bindtap="toggleMoney"[^>]*aria-expanded="\{\{moneyOpen\}\}"/);
  assert.match(wxml,/查看复诊预约/);
  assert.match(wxml,/查看历史预约/);
  assert.match(wxml,/联系原门店/);
  assert.match(wxml,/checkout-id/);
});

check(()=>{
  const wxml=read('pages/discovery/index.wxml');
  assert.match(wxml,/bindtap="toggleMore"[^>]*aria-expanded="\{\{moreOpen\}\}"/);
  assert.match(wxml,/更多服务与帮助/);
  assert.match(wxml,/wx:if="{{primary&&primary\.kind!=='BOOK'}}" class="shortcut" bindtap="book"/);
  assert.match(wxml,/到诊安排/);
});

module.exports={layer:'Node JS contract assertions (no Django/DB)',passed:count,total:count};
if(require.main===module)console.log(JSON.stringify(module.exports));
