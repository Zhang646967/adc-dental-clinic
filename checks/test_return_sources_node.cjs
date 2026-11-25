/* Node contract assertions for the visit-page return-source projection. */
const assert=require('node:assert/strict');
const {buildReturnSources}=require('../clients/wechat/miniprogram/utils/return-sources');
let count=0;
const check=(fn)=>{fn();count+=1;};
const visit=rows=>({review:{return_sources:rows}});
const current={source_visit_id:1,source_visit_no:'V-6AFEEB3A5F494A7E8D559331149B5BDF',service:'修复评估与复查',
  state:'CURRENT',label:'已关联原就诊',report:{id:1,number:'EX-793A517E077E408C862F57BF22B05032',
  project:'口腔影像复查报告',revision:2}};
const contact={source_visit_id:1,source_visit_no:'V-6AFEEB3A5F494A7E8D559331149B5BDF',service:'修复评估与复查',
  state:'CONTACT',label:'复诊依据有变化，请联系原门店核对。',report:null};

check(()=>assert.deepEqual(buildReturnSources({}),[]));
check(()=>assert.deepEqual(buildReturnSources({review:{}}),[]));
check(()=>assert.deepEqual(buildReturnSources({review:{return_sources:[]}}),[]));
check(()=>assert.deepEqual(buildReturnSources({review:{return_sources:{length:1}}}),[]));
check(()=>assert.deepEqual(buildReturnSources(visit([current]),{delegated:true}),[]));

check(()=>{
  const [row]=buildReturnSources(visit([current]));
  assert.equal(row.sourceVisitId,1);
  assert.equal(row.sourceLabel,current.source_visit_no);
  assert.equal(row.service,'修复评估与复查');
  assert.equal(row.canOpenSource,true);
  assert.equal(row.canContact,false);
  assert.deepEqual(row.report,{id:1,revision:2,number:current.report.number,
    project:'口腔影像复查报告',actionLabel:'查看口腔影像复查报告 · 第 2 版'});
});
check(()=>{
  const [row]=buildReturnSources(visit([{...current,report:null}]));
  assert.equal(row.report,null);
  assert.equal(row.canOpenSource,true);
});
check(()=>{
  const [row]=buildReturnSources(visit([contact]));
  assert.equal(row.report,null);
  assert.equal(row.canContact,true);
  assert.equal(row.label,'复诊依据有变化，请联系原门店核对。');
});
check(()=>{
  // A changed source never keeps an old readable report, even if one is sent.
  const [row]=buildReturnSources(visit([{...contact,report:current.report}]));
  assert.equal(row.report,null);
});
check(()=>assert.deepEqual(buildReturnSources(visit([{...current,state:'STALE'}])),[]));
check(()=>assert.deepEqual(buildReturnSources(visit([{...current,source_visit_id:0}])),[]));
check(()=>assert.deepEqual(buildReturnSources(visit([{...current,source_visit_id:'1x'}])),[]));
check(()=>{
  const [row]=buildReturnSources(visit([{...current,report:{...current.report,revision:0}}]));
  assert.equal(row.report,null);
});
check(()=>{
  const [row]=buildReturnSources(visit([{...current,report:{...current.report,revision:'2'}}]));
  assert.equal(row.report.revision,2);
});
check(()=>{
  const [row]=buildReturnSources(visit([{...current,report:{...current.report,number:''}}]));
  assert.equal(row.report,null);
});
check(()=>{
  const [row]=buildReturnSources(visit([{...current,report:{id:1,revision:3,number:'EX-3'}}]));
  assert.equal(row.report.actionLabel,'查看检查报告 · 第 3 版');
});
check(()=>{
  const second={...current,source_visit_id:20,source_visit_no:'V-SECOND',service:'牙周复查',
    report:{...current.report,id:9,number:'EX-SECOND',project:'复查',revision:1}};
  const rows=buildReturnSources(visit([current,second]));
  assert.equal(rows.length,2);
  assert.deepEqual(rows.map(row=>row.service),['修复评估与复查','牙周复查']);
  assert.deepEqual(rows.map(row=>row.report.actionLabel),['查看口腔影像复查报告 · 第 2 版','查看复查 · 第 1 版']);
  assert.notEqual(rows[0].key,rows[1].key);
  assert.deepEqual(rows.map(row=>row.sourceVisitId),[1,20]);
});
check(()=>assert.deepEqual(buildReturnSources(visit([null,current,'x'])).length,1));
check(()=>{
  // Internal chairside facts must not be copied into the patient projection.
  const rows=buildReturnSources(visit([{...current,record_revision:2,latest_record:3,
    location:'16 牙 · 近中面',findings:['16 牙 · 既往处置'],allergy:'合成材料甲',
    report:{...current.report,body:'内部检查摘要'}}]));
  const serialized=JSON.stringify(rows);
  for(const secret of ['record_revision','latest_record','16 牙','合成材料甲','内部检查摘要'])assert(!serialized.includes(secret));
});
check(()=>{
  const [row]=buildReturnSources(visit([{...current,source_visit_no:'',service:''}]));
  assert.equal(row.sourceLabel,'#1');
  assert.equal(row.service,'复诊来源');
});
module.exports={layer:'Node JS contract assertions (no Django/DB)',passed:count,total:count};
if(require.main===module)console.log(JSON.stringify(module.exports));
