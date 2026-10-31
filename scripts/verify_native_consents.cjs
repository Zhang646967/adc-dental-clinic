/* Native Page execution with controlled transport; official-tool checks separate. */
const assert=require('node:assert/strict');
const {page}=require('./verify_native_services.cjs');
const session={authenticated:true,subject_key:'self',subject_revision:1,workspace_id:'own',patient_name:'合成本人'};
const medical={step:16,plan:8,version:2,revision:1,recorded_at:'2026-10-30T08:00:00Z',events:[],versions:[],can_agree:true};
async function verify(){
 const cases=[];const test=async(name,run)=>{await run();cases.push(name);};
 await test('invalid link never reads medical content',async()=>{const d=page('consent',{session});d.p.onLoad({step:'../'});await d.p.onShow();assert.equal(d.calls.length,0);assert(d.p.data.error);});
 await test('appointment delegate never loads medical consent',async()=>{const d=page('consent',{session:{...session,delegated:true}});d.p.onLoad({step:'16'});await d.p.onShow();assert.equal(d.calls.length,0);assert.equal(d.p.data.medical,null);});
 await test('self preview binds exact version and edited text clears it',async()=>{
  const d=page('consent',{session,request:async(r,m,v)=>m==='POST'?{proposal_token:'signed',values:v}:medical});d.p.onLoad({step:'16'});await d.p.onShow();d.p.input({detail:{value:'具体疑问'}});await d.p.preview();assert.equal(d.calls.at(-1).data.version,2);assert.equal(d.p.data.preview.values.text,'具体疑问');d.p.input({detail:{value:'更正疑问'}});assert.equal(d.p.data.preview,null);
 });
 await test('uncertain confirmation retries same signed effect',async()=>{
  let count=0;const d=page('consent',{session,request:async(r,m,v)=>{if(r.endsWith('/preview/'))return {proposal_token:'same',values:{text:'患者疑问'}};if(r.endsWith('/confirm/')){if(!count++){const e=new Error('结果未确认');e.code='NETWORK_UNCONFIRMED';throw e;}return {event:4,replayed:true};}return medical;}});
  d.p.onLoad({step:'16'});await d.p.onShow();await d.p.preview();d.p.checked({detail:{value:['yes']}});await d.p.confirm();assert(d.p.data.uncertain);d.p.input({detail:{value:'不能替换未确认请求'}});await d.p.confirm();const sent=d.calls.filter(c=>c.route.endsWith('/confirm/'));assert.deepEqual(sent[0].data,sent[1].data);assert(!d.p.data.uncertain);
 });
 await test('patient switch clears all clinical data',async()=>{
  const d=page('consent',{session,request:async()=>medical});d.p.onLoad({step:'16'});await d.p.onShow();d.session.subject_key='grant:8';d.session.delegated=true;await d.p.preview();assert.equal(d.p.data.medical,null);assert.equal(d.calls.length,1);
 });
 await test('read-only session cannot submit any decision',async()=>{const d=page('consent',{session:{...session,read_only:true},request:async()=>medical});d.p.onLoad({step:'16'});await d.p.onShow();await d.p.preview();assert.equal(d.calls.length,1);assert.equal(d.p.data.preview,null);});
 return {passed:true,cases:cases.length,case_names:cases,scope:'Actual Page handlers, controlled transport; not official WeChat runtime'};
}
module.exports={verify};
