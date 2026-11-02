/* Actual Page handlers, controlled transport; no official-runtime or phone claim. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function fixture(query={}){
 let definition;const calls=[],state={account_authenticated:true,account_name:'account-a',workspace_id:'ctx-a',subject_revision:1,read_only:false};
 const controls={fail:false,uncertain:false},wx={navigateTo:o=>calls.push({navigation:o.url}),openDocument:o=>{calls.push({open:o.filePath});o.success();}};
 const api={bootstrap:async()=>({...state}),downloadRecordCopy:async t=>{calls.push({download:t});return '/private-temp/verified-copy.pdf';},
 request:async(route,method='GET',data={})=>{
  calls.push({route,method,data:JSON.parse(JSON.stringify(data))});if(controls.fail)throw Error('当前领取范围失效');
  if(route==='record-copies/options/')return {clinic:1,clinics:[{id:1,name:'甲门店'},{id:2,name:'乙门店'}],visits:[{id:'11',label:'就诊11'}],packages:[{id:'',label:'最近版本'}],sections:[{id:'DOCUMENT',label:'病历'}]};
  if(route.endsWith('/preview/'))return {proposal_token:'signed-exact-copy',summary:[{label:'患者',value:'合成患者'}]};
  if(route==='record-copies/confirm/'){if(controls.uncertain)throw Error('结果尚未确认');return {id:3,ticket:'private-ticket'};}
  if(route==='record-copies/')return {rows:[{id:3,patient:'合成患者'}],page:1,pages:1};
  return {id:3,patient:'合成患者',history:[],items:[],state:'READY',can_pickup:true};
 }};
 const source=fs.readFileSync(path.resolve(__dirname,'../clients/wechat/miniprogram/pages/record-copies/index.js'),'utf8');
 vm.runInNewContext(source,{Page:p=>definition=p,wx,require:n=>n.endsWith('/api')?api:n.endsWith('/booking-intent')?{positive:v=>Number(v)>0&&Number.isSafeInteger(Number(v))}:{dateTime:x=>x,showError:(p,e)=>p.setData({busy:false,error:e.message})}});
 const page={...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(values){for(const [key,value] of Object.entries(values)){const parts=key.split('.');let target=this.data;for(const p of parts.slice(0,-1))target=target[p];target[parts.at(-1)]=value;}}};page.onLoad(query);
 return {page,calls,state,controls};
}
const action=value=>({currentTarget:{dataset:{action:value}}});
async function verify(){
 const details=[],test=async(name,fn)=>{await fn();details.push(name);};
 await test('guest sees no private copy request',async()=>{const d=fixture();d.state.account_authenticated=false;await d.page.onShow();assert.equal(d.calls.filter(c=>c.route).length,0);assert(d.calls[0].navigation.includes('login'));});
 await test('account change clears private application fields and previous rows',async()=>{const d=fixture();await d.page.onShow();d.page.setData({purpose:'PRIVATE_OLD',message:'PRIVATE_OLD'});d.state.account_name='account-b';d.controls.fail=true;await d.page.load();assert.equal(d.page.data.purpose,'');assert.equal(d.page.data.message,'');assert.equal(d.page.data.rows.length,0);});
 await test('application previews explicit visit and section choices',async()=>{const d=fixture({new:'1'});await d.page.onShow();d.page.visits({detail:{value:['11']}});d.page.setData({purpose:'个人复诊资料留存'});await d.page.prepare(action('SUBMIT'));const call=d.calls.find(c=>c.route==='record-copies/preview/');assert.equal(call.data.visits,'11');assert.equal(call.data.sections,'DOCUMENT');assert.equal(d.page.data.options.visits[0].checked,true);assert(d.page.data.preview);});
 await test('confirmation requires explicit checkbox and sends signed proposal only',async()=>{const d=fixture({id:'3'});await d.page.onShow();await d.page.prepare(action('CLAIM'));await d.page.confirm();assert(!d.calls.some(c=>c.route==='record-copies/confirm/'));d.page.consent({detail:{value:['yes']}});await d.page.confirm();const call=d.calls.find(c=>c.route==='record-copies/confirm/');assert.deepEqual(call.data,{proposal_token:'signed-exact-copy',confirmed:'on'});assert(d.calls.some(c=>c.download==='private-ticket'));assert(d.calls.some(c=>c.open));});
 await test('uncertain confirmation keeps identical signed effect for retry',async()=>{const d=fixture({id:'3'});await d.page.onShow();await d.page.prepare(action('CLAIM'));d.page.consent({detail:{value:['yes']}});d.controls.uncertain=true;await d.page.confirm();assert.equal(d.page.data.preview.proposal_token,'signed-exact-copy');assert(d.page.data.error);});
 await test('revoked read removes cached request before displaying error',async()=>{const d=fixture({id:'3'});await d.page.onShow();assert(d.page.data.detail);d.controls.fail=true;await d.page.load();assert.equal(d.page.data.detail,null);assert(d.page.data.error);});
 await test('read-only mode performs no new copy mutation',async()=>{const d=fixture({id:'3'});d.state.read_only=true;await d.page.onShow();await d.page.prepare(action('CLAIM'));assert(!d.calls.some(c=>c.method==='POST'));});
 return {passed:true,cases:details.length,details,scope:'Native copy Page handlers with mocked transport; official compilation, PDF viewer and phone remain separate'};
}
module.exports={verify};
