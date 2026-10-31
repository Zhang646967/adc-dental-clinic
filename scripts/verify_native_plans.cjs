/* Page handlers with a mocked API; real backend/browser acceptance is separate. */
const assert=require('node:assert/strict');
const {page}=require('./verify_native_services.cjs');
const plain=x=>JSON.parse(JSON.stringify(x));
const plan={id:8,clinic:'合成门店',version:1,is_current:true,summary:'已讨论方案',discussion_note:'仍由本人核对具体步骤',recorded_at:'2026-10-24T08:00:00Z',versions:[1],instructions:[],
 steps:[{id:16,sequence:1,description:'合成步骤',goal:'明确目标',treatment:'合成项目',unit:'颗次',service:{id:4,name:'复查'},tooth:16,surface:'MO',estimated_quantity:'1',estimated_unit_price:null,estimate_amount:null,
  estimate_note:'费用仍待评估',alternative_group:'A',charge_basis:'ON_COMPLETION',charge_basis_label:'分次步骤完成时计费',decision:null,completed:false,actual_history:[{id:1,observed_at:'2026-10-24T08:00:00Z',progress_label:'尚待继续',mode_label:'本阶段不另计费',state:'ACTIVE',state_label:'有效'}]}]};
const session={authenticated:true,delegated:false,workspace_id:'plan-ctx',subject_key:'self',subject_revision:1};
const click=id=>({currentTarget:{dataset:{id}}});
async function verify(){
 const cases=[];const test=async(name,fn)=>{await fn();cases.push(name);};
 await test('self plan list opens its exact typed plan',async()=>{
  const {p,navigation}=page('plans',{session,request:async()=>({rows:[{id:8,clinic:'合成门店',version:1,summary:'方案',recorded_at:plan.recorded_at}],page:1,pages:1})});
  await p.onShow();assert.equal(p.data.rows.length,1);p.open(click(8));assert.equal(navigation[0].url,'/pages/plan/index?id=8');
 });
 await test('delegated subject never loads clinical plans',async()=>{
  for(const name of ['plans','plan']){
   const {p,calls}=page(name,{session:{...session,delegated:true}});if(p.onLoad)p.onLoad({id:'8'});await p.onShow();assert.equal(calls.length,0);assert.match(p.data.error,/预约代办/);
  }
 });
 await test('invalid plan link never sends a path request',async()=>{
  const {p,calls}=page('plan',{session});p.onLoad({id:'../visits'});await p.onShow();assert.equal(calls.length,0);assert.match(p.data.error,/链接已失效/);
 });
 await test('unknown estimate and partial actual progress remain distinct',async()=>{
  const {p}=page('plan',{session,request:async()=>plain(plan)});p.onLoad({id:'8'});await p.onShow();assert.equal(p.data.plan.steps[0].estimate_amount,null);
  assert.equal(p.data.plan.steps[0].completed,false);assert.equal(p.data.plan.steps[0].actual_history[0].mode_label,'本阶段不另计费');
 });
 await test('exact-version treatment explanation remains read-only and old versions can be revisited',async()=>{
  const value=plain(plan);value.steps[0].disclosure={available:true,state:'PREPARED',label:'治疗说明已准备，待沟通核对',prepared_at:'2026-10-24T08:00:00Z',prepared_by_name:'课程医师',fields:[{key:'risks',label:'主要风险',value:'PRIVATE_VERSION_ONE_RISK'}]};
  const {p,calls}=page('plan',{session,request:async(route)=>route.includes('?revision=1')?{...plain(value),is_current:false}:plain(value)});
  p.onLoad({id:'8'});await p.onShow();assert.equal(p.data.plan.steps[0].disclosure.fields[0].value,'PRIVATE_VERSION_ONE_RISK');assert(p.data.plan.steps[0].disclosureTimeLabel);
  await p.version({currentTarget:{dataset:{revision:'1'}}});assert.equal(p.data.plan.is_current,false);assert.equal(p.data.plan.steps[0].disclosure.fields[0].value,'PRIVATE_VERSION_ONE_RISK');assert(calls.every(c=>!c.method||c.method==='GET'));
 });
 await test('decision preview binds exact plan step and edited values clear confirmation',async()=>{
  const {p,calls}=page('plan',{session,request:async(route,method,data)=>route.startsWith('plans/8/steps/')?{proposal_token:'signed-1',plan:8,step:16,version:1,description:'合成步骤',values:data}:plain(plan)});
  p.onLoad({id:'8'});await p.onShow();p.choose(click(16));p.pick({detail:{value:'1'}});p.input({detail:{value:'稍后继续讨论'}});await p.preview();
  assert.equal(calls.at(-1).route,'plans/8/steps/16/decision/preview/');assert.equal(calls.at(-1).data.decision,'DEFERRED');assert(p.data.preview);
  p.input({detail:{value:'调整后续讨论说明'}});assert.equal(p.data.preview,null);assert.equal(p.data.checked,false);
 });
 await test('unconfirmed network retry uses the original signed operation',async()=>{
  let confirmations=0;
  const {p,calls}=page('plan',{session,request:async(route,method,data)=>{
   if(route.endsWith('/preview/'))return {proposal_token:'signed-retry',plan:8,step:16,version:1,description:'合成步骤',values:{decision:'ACCEPTED',note:''}};
   if(route.endsWith('/confirm/')){confirmations++;if(confirmations===1){const e=new Error('结果尚未确认');e.code='NETWORK_UNCONFIRMED';throw e;}return {replayed:true};}
   return plain(plan);
  }});
  p.onLoad({id:'8'});await p.onShow();p.choose(click(16));await p.preview();p.checked({detail:{value:['yes']}});await p.confirm();assert.equal(p.data.uncertain,true);
  p.pick({detail:{value:'2'}});p.input({detail:{value:'不得改变未确认提交'}});assert.equal(p.data.stateIndex,0);assert.equal(p.data.note,'');await p.confirm();
  const sent=calls.filter(c=>c.route.endsWith('/confirm/'));assert.equal(sent.length,2);assert.deepEqual(plain(sent[0].data),plain(sent[1].data));assert.equal(p.data.preview,null);assert.equal(p.data.uncertain,false);
 });
 await test('subject switch clears clinical values before any decision submission',async()=>{
  const d=page('plan',{session,request:async()=>plain(plan)});d.p.onLoad({id:'8'});await d.p.onShow();d.p.choose(click(16));d.p.input({detail:{value:'PRIVATE_UNSAVED_NOTE'}});
  d.session.subject_revision=2;d.session.subject_key='grant:9';d.session.delegated=true;const before=d.calls.length;await d.p.preview();assert.equal(d.calls.length,before);assert.equal(d.p.data.plan,null);assert.equal(d.p.data.note,'');
 });
 await test('read-only and retained historical versions cannot start a decision',async()=>{
  const d=page('plan',{session:{...session,read_only:true},request:async()=>plain(plan)});d.p.onLoad({id:'8'});await d.p.onShow();d.p.choose(click(16));assert.equal(d.p.data.selected,null);
  const h=page('plan',{session,request:async()=>({...plain(plan),is_current:false})});h.p.onLoad({id:'8'});await h.p.onShow();h.p.choose(click(16));assert.equal(h.p.data.selected,null);
 });
 await test('server conflict preserves entered discussion and removes stale confirmation',async()=>{
  const {p}=page('plan',{session,request:async(route)=>{
   if(route.endsWith('/preview/'))return {proposal_token:'old-version',plan:8,step:16,version:1,description:'步骤',values:{decision:'DEFERRED',note:'PRIVATE_RETAINED_NOTE'}};
   if(route.endsWith('/confirm/')){const e=new Error('方案已有新版本');e.code='BUSINESS_CONFLICT';throw e;}return plain(plan);
  }});
  p.onLoad({id:'8'});await p.onShow();p.choose(click(16));p.input({detail:{value:'PRIVATE_RETAINED_NOTE'}});await p.preview();p.checked({detail:{value:['yes']}});await p.confirm();
  assert.equal(p.data.note,'PRIVATE_RETAINED_NOTE');assert.equal(p.data.preview,null);assert.equal(p.data.uncertain,false);
 });
 return {passed:true,cases:cases.length,scope:'mocked API Page handlers; not WeChat runtime',details:cases};
}
module.exports={verify};
