/* Patient navigation and native invoice handlers; real IDE/device evidence is separate. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
async function verify(){
  let count=0;const app={globalData:{}},routes=[];
  global.getApp=()=>app;global.wx={switchTab:o=>routes.push({method:'switchTab',...o}),navigateTo:o=>routes.push({method:'navigateTo',...o}),redirectTo:o=>routes.push({method:'redirectTo',...o}),reLaunch:o=>routes.push({method:'reLaunch',...o})};
  const navigation=require(path.join(root,'utils/navigation'));
  for(const name of ['discovery','services','home','account'])navigation.navigateTo({url:'/pages/'+name+'/index'});
  assert(routes.every(r=>r.method==='switchTab'));count++;
  navigation.reLaunch({url:'/pages/services/index?clinic=12&category=RESTORATION&patient_name=PRIVATE&next=https://example.invalid'});
  const selected=navigation.consume('/pages/services/index');assert.deepEqual(selected,{clinic:'12',category:'RESTORATION'});count++;
  assert.equal(navigation.consume('/pages/services/index'),null);count++;
  navigation.navigateTo({url:'/pages/dentist/index?id=7'});assert.equal(routes.at(-1).method,'navigateTo');count++;
  app.globalData.tabNavigation={path:'/pages/services/index',values:{clinic:3},expires:Date.now()-1};assert.equal(navigation.consume('/pages/services/index'),null);count++;
  const intent=require(path.join(root,'utils/booking-intent'));
  intent.remember(app,11,3,7,'2026-10-29');assert.equal(intent.destination(app,{subject_required:true}),'/pages/patients/index');
  assert.equal(intent.destination(app,{authenticated:true}),'/pages/booking/index?service=11&clinic=3&dentist=7&day=2026-10-29');count++;
  intent.remember(app,12,4,null,null,'CHILDREN');assert.equal(intent.destination(app,{authenticated:true,delegated:false}),'/pages/patients/index');assert(app.globalData.bookingIntent);count++;
  assert.equal(intent.destination(app,{authenticated:true,delegated:true,guardian:true}),'/pages/booking/index?service=12&clinic=4');count++;
  function page(name,{responses=[],session={}}={}){
    let definition;const calls=[];const state={globalData:{}};
    const api={async bootstrap(){return session;},sessionInfo:()=>session,showSubject:()=>{},async request(...args){calls.push(args);const r=responses.shift();if(r instanceof Error)throw r;return r;}};
    vm.runInNewContext(fs.readFileSync(path.join(root,'pages',name,'index.js'),'utf8'),{
      Page:d=>definition=d,getApp:()=>state,wx:global.wx,require:key=>key.endsWith('/api')?api:key.endsWith('/navigation')?navigation:
        key.endsWith('/booking-intent')?intent:key.endsWith('/format')?{dateTime:x=>x,showError:(p,e)=>p.setData({busy:false,error:e.message})}:null});
    return {p:{...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(v){Object.assign(this.data,v);}},calls};
  }
  const invoice=()=>({invoice_no:'SYNTHETIC-BILL',revision:2,total:'99.99',is_current:true,published_at:'2026-10-28',revisions:[{revision_no:2,published_at:'2026-10-28'},{revision_no:1,published_at:'2026-10-27'}],lines:[],cash_balance:{current_revision:2,remaining:'9.99'}});
  let d=page('invoice',{responses:[invoice()]});d.p.onLoad({id:5});await d.p.onShow();assert.equal(d.calls[0][0],'invoices/5/');assert.equal(d.p.data.invoice.total,'99.99');count++;
  d=page('invoice',{responses:[invoice(),{...invoice(),revision:1,total:'199.98',is_current:false}]});d.p.onLoad({id:5});await d.p.onShow();await d.p.version({detail:{value:1}});await new Promise(r=>setImmediate(r));assert.equal(d.calls[1][2].revision,1);assert.equal(d.p.data.invoice.total,'199.98');assert.equal(d.p.data.invoice.cash_balance.current_revision,2);count++;
  assert(d.calls.every(c=>c[1]==='GET'));count++;
  d=page('invoice');d.p.onLoad({id:'../account'});await d.p.onShow();assert.equal(d.calls.length,0);assert(d.p.data.error);count++;
  d=page('invoice',{responses:[Error('当前身份不可查看本人账单')]});d.p.data.invoice=invoice();d.p.onLoad({id:5});await d.p.onShow();assert.equal(d.p.data.invoice,null);assert(d.p.data.error);count++;
  d=page('home',{session:{authenticated:false,account_authenticated:false}});d.p.data.rows=[{patient:'OLD_PRIVATE'}];await d.p.onShow();assert.equal(d.p.data.guest,true);assert.equal(d.calls.length,0);assert.equal(d.p.data.rows.length,0);count++;
  d=page('account',{session:{account_authenticated:false}});await d.p.onShow();assert.equal(d.p.data.guest,true);assert.equal(d.p.data.profile,null);count++;
  d.p.setData({newPassword:'SECRET',repeatPassword:'SECRET',smsCode:'SECRET',unlinkPassword:'SECRET'});d.p.onHide();assert.equal(d.p.data.newPassword,'');assert.equal(d.p.data.smsCode,'');count++;
  return {passed:true,cases:count,scope:'actual tab routing and patient Page handlers with controlled transport; not IDE/device acceptance'};
}
module.exports={verify};
if(require.main===module)verify().then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e.stack);process.exitCode=1;});
