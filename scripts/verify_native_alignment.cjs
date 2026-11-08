/* Patient navigation and native invoice handlers; real IDE/device evidence is separate. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
const patientAction=require(path.join(root,'utils/primary-action'));
const subjectState=require(path.join(root,'utils/subject-state'));
const format=require(path.join(root,'utils/format'));
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
  global.wx.navigateBack=o=>routes.push({method:'navigateBack',...o});
  global.getCurrentPages=()=>[{route:'pages/medical-authorizations/index',options:{id:'3'}},{route:'pages/plan/index',options:{id:'7'}}];
  navigation.returnTo('/pages/medical-authorizations/index?id=3');
  assert.equal(routes.at(-1).method,'navigateBack');count++;
  navigation.returnTo('/pages/medical-authorizations/index');
  assert.equal(routes.at(-1).method,'redirectTo');
  assert.equal(routes.at(-1).url,'/pages/medical-authorizations/index');count++;
  navigation.returnTo('/pages/home/index?queue=history');
  assert.equal(routes.at(-1).method,'switchTab');
  assert.equal(navigation.consume('/pages/home/index').queue,'history');count++;
  const intent=require(path.join(root,'utils/booking-intent'));
  intent.remember(app,11,3,7,'2026-10-29');assert.equal(intent.destination(app,{subject_required:true}),'/pages/patients/index');
  assert.equal(intent.destination(app,{authenticated:true}),'/pages/booking/index?service=11&clinic=3&dentist=7&day=2026-10-29');count++;
  intent.remember(app,12,4,null,null,'CHILDREN');assert.equal(intent.destination(app,{authenticated:true,delegated:false}),'/pages/patients/index');assert(app.globalData.bookingIntent);count++;
  assert.equal(intent.destination(app,{authenticated:true,delegated:true,guardian:true}),'/pages/booking/index?service=12&clinic=4');count++;
  function page(name,{responses=[],session={},freshSession=session,bootstrapError=null,review=null}={}){
    let definition;const calls=[];const state={globalData:{review}};
    const api={async bootstrap(){if(bootstrapError)throw bootstrapError;return freshSession;},sessionInfo:()=>session,
      showSubject:p=>p.setData({patientName:session.patient_name||'',patientCapacity:session.acting_capacity||'',patientDelegated:!!session.delegated}),
      async request(...args){calls.push(args);const r=responses.shift();if(r instanceof Error)throw r;return r;}};
    vm.runInNewContext(fs.readFileSync(path.join(root,'pages',name,'index.js'),'utf8'),{
      Page:d=>definition=d,getApp:()=>state,wx:global.wx,require:key=>key.endsWith('/api')?api:key.endsWith('/navigation')?navigation:
        key.endsWith('/booking-intent')?intent:key.endsWith('/primary-action')?patientAction:
        key.endsWith('/subject-state')?subjectState:key.endsWith('/format')?format:null});
    return {p:{...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(v){Object.assign(this.data,v);}},calls,state};
  }
  const invoice=()=>({invoice_no:'SYNTHETIC-BILL',revision:2,total:'99.99',is_current:true,published_at:'2026-10-28',revisions:[{revision_no:2,published_at:'2026-10-28'},{revision_no:1,published_at:'2026-10-27'}],lines:[],cash_balance:{current_revision:2,remaining:'9.99'}});
  let d=page('invoice',{responses:[invoice()]});d.p.onLoad({id:5});await d.p.onShow();assert.equal(d.calls[0][0],'invoices/5/');assert.equal(d.p.data.invoice.total,'99.99');count++;
  assert.deepEqual(Array.from(d.p.data.invoice.treatment_lines),[]);
  assert.deepEqual(Array.from(d.p.data.invoice.medication_lines),[]);count++;
  const drug={name_snapshot:'合成目录条目',quantity:3,unit_price:'12.50',line_amount:'37.50'};
  d=page('invoice',{responses:[{...invoice(),lines:[{...drug,name_snapshot:'药费 · 合成目录条目'}],
    treatment_lines:[],medication_lines:[drug]}]});
  d.p.onLoad({id:5});await d.p.onShow();
  assert.equal(d.p.data.invoice.treatment_lines.length,0);
  assert.equal(d.p.data.invoice.medication_lines[0].line_amount,'37.50');count++;
  d=page('invoice',{responses:[invoice(),{...invoice(),revision:1,total:'199.98',is_current:false}]});d.p.onLoad({id:5});await d.p.onShow();await d.p.version({detail:{value:1}});await new Promise(r=>setImmediate(r));assert.equal(d.calls[1][2].revision,1);assert.equal(d.p.data.invoice.total,'199.98');assert.equal(d.p.data.invoice.cash_balance.current_revision,2);count++;
  assert(d.calls.every(c=>c[1]==='GET'));count++;
  d=page('invoice');d.p.onLoad({id:'../account'});await d.p.onShow();assert.equal(d.calls.length,0);assert(d.p.data.error);count++;
  d=page('invoice',{responses:[Error('当前身份不可查看本人账单')]});d.p.data.invoice=invoice();d.p.onLoad({id:5});await d.p.onShow();assert.equal(d.p.data.invoice,null);assert(d.p.data.error);count++;
  d=page('invoice',{responses:[{...invoice(),revision:1,is_current:false}]});
  d.p.onLoad({id:5,revision:1});await d.p.onShow();d.p.back();
  d=page('home',{session:{authenticated:true,account_authenticated:true},responses:[{rows:[],page:1,pages:1},{}]});
  d.p.setData({queue:'active',page:4});
  await d.p.onShow();
  assert.deepEqual({...d.calls[0][2]},{queue:'history',page:1});count++;
  d=page('home',{session:{authenticated:false,account_authenticated:false}});d.p.data.rows=[{patient:'OLD_PRIVATE'}];await d.p.onShow();assert.equal(d.p.data.guest,true);assert.equal(d.calls.length,0);assert.equal(d.p.data.rows.length,0);count++;
  const primary=patientAction.primaryAction;
  const action=(kind,visit=null,offer=null)=>primary({primary_action:{kind,visit,offer}});
  const visit={id:12,clinic:'合成门店',dentist:'合成医师',service:'初诊',status_label:'已预约',start:'2026-11-05T06:00:00Z'};
  assert.equal(action('CHECKED_IN',visit).url,'/pages/visit/index?id=12');count++;
  assert.equal(action('UPCOMING_VISIT',visit).timeLabel,'2026-11-05 14:00');count++;
  const review=action('CONTACT_CLINIC',{...visit,needs_outcome_review:true});
  assert.equal(review.url,'/pages/help/index?visit=12');assert(review.serviceLine.endsWith('已预约'));count++;
  const offer=action('CONFIRM_OFFER',null,{id:4,expires_at:'2026-11-05T02:45:00Z'});
  assert.equal(offer.url,'/pages/offer/index?id=4');assert(offer.deadline.includes('2026-11-05 10:45'));count++;
  assert.equal(action('WAITLIST').url,'/pages/waitlist/index');assert.equal(action('BOOK').url,'/pages/services/index');count++;
  assert.equal(primary({next_visit:visit}),null);assert.equal(action('UNKNOWN'),null);
  assert.equal(action('UPCOMING_VISIT',{...visit,id:'12&next=elsewhere'}),null);assert.equal(action('CONFIRM_OFFER'),null);count++;
  for(const [status,code] of [[403,'ACCESS_DENIED'],[409,'SUBJECT_REQUIRED'],[409,'SUBJECT_CHANGED'],[409,'WORKSPACE_CHANGED']]){
    const denied=Object.assign(Error('当前就诊人或授权已变化'),{status,code});
    d=page('home',{session:{authenticated:true},responses:[denied,denied]});
    d.p.setData({rows:[visit],overview:{next_visit:visit},primary:action('UPCOMING_VISIT',visit)});
    await d.p.load();
    assert.equal(d.p.data.rows.length,0,`${code}: refresh must clear previous appointments`);
    assert.equal(d.p.data.overview,null,`${code}: refresh must clear the previous summary`);
    assert.equal(d.p.data.primary,null,`${code}: refresh must remove the previous primary action`);count++;
  }
  const priorSubject={authenticated:true,account_authenticated:true,patient_name:'OLD_SYNTHETIC_SUBJECT',acting_capacity:'预约代办',delegated:true};
  for(const entry of ['load','onShow']){
    for(const [status,code] of [[403,'ACCESS_DENIED'],[409,'SUBJECT_REQUIRED'],[409,'SUBJECT_CHANGED'],[409,'WORKSPACE_CHANGED'],[401,'LOGIN_REQUIRED']]){
      const denied=Object.assign(Error('就诊范围已变化'),{status,code,requestId:'SYNTHETIC-QUERY'});
      d=page('home',{session:priorSubject,responses:[denied,denied],bootstrapError:denied});
      d.p.setData({patientName:priorSubject.patient_name,patientCapacity:priorSubject.acting_capacity,patientDelegated:true,
        patient:priorSubject.patient_name,rows:[visit],overview:{next_visit:visit},primary:action('UPCOMING_VISIT',visit)});
      await d.p[entry]();
      assert.equal(d.p.data.patientName,'',`${entry}/${code}: old patient name remains`);
      assert.equal(d.p.data.patientCapacity,'',`${entry}/${code}: old acting capacity remains`);
      assert.equal(d.p.data.patientDelegated,false);
      assert.equal(d.p.data.patient,'');assert.equal(d.p.data.rows.length,0);
      assert.equal(d.p.data.overview,null);assert.equal(d.p.data.primary,null);
      assert.equal(d.p.data.requestId,'SYNTHETIC-QUERY');assert.equal(d.p.data.busy,false);
      if(status===401)assert.equal(routes.at(-1).url,'/pages/login/index');
      else if(code==='SUBJECT_REQUIRED')assert.equal(routes.at(-1).url,'/pages/patients/index');
      else assert.equal(d.p.data.subjectInvalid,true);
      count++;
    }
  }
  const confirmSession={...priorSubject,subject_key:'grant:1',workspace_id:'SYNTHETIC-WORKSPACE',subject_revision:4};
  const confirmReview={
    subjectKey:confirmSession.subject_key,workspaceKey:confirmSession.workspace_id,subjectRevision:confirmSession.subject_revision,
    kind:'booking',path:'booking/confirm/',preview:{proposal_token:'SYNTHETIC-PROPOSAL',patient_request:'OLD_SYNTHETIC_REQUEST'}
  };
  const deniedConfirmations=[
    {status:409,code:'WORKSPACE_CHANGED',freshSession:{authenticated:false,account_authenticated:true},url:'/pages/account/index'},
    {status:409,code:'SUBJECT_REQUIRED',freshSession:{authenticated:true,account_authenticated:true,subject_required:true},url:'/pages/patients/index'},
    {status:403,code:'ACCESS_DENIED',freshSession:{authenticated:true,account_authenticated:true},url:'/pages/patients/index'},
    {status:401,code:'LOGIN_REQUIRED',freshSession:{authenticated:false,account_authenticated:false},url:'/pages/login/index'}
  ];
  for(const {status,code,freshSession,url} of deniedConfirmations){
    const denied=Object.assign(Error('当前就诊人或授权已变化'),{status,code,requestId:'SYNTHETIC-CONFIRM-QUERY'});
    d=page('confirm',{session:confirmSession,freshSession,review:confirmReview,responses:[denied]});
    d.p.onLoad();
    d.p.checked({detail:{value:['yes']}});
    const routeCount=routes.length;
    await d.p.submit();
    assert.equal(d.state.globalData.review,null,code);
    assert.equal(d.p.data.review,null,code);
    assert.equal(d.p.data.patientName,'',code);
    assert.equal(d.p.data.patientCapacity,'',code);
    assert.equal(d.p.data.patientDelegated,false,code);
    assert.equal(d.p.data.checked,false,code);
    assert.equal(d.p.data.subjectInvalid,true,code);
    assert.equal(d.p.data.requestId,'SYNTHETIC-CONFIRM-QUERY',code);
    assert.equal(routes.length,routeCount,code);
    await d.p.submit();
    assert.equal(d.calls.length,1,code);
    await d.p.recoverSubject();
    assert.equal(routes.at(-1).url,url,code);count++;
  }
  const expired=Object.assign(Error('会话已失效'),{status:401,code:'LOGIN_REQUIRED',requestId:'SYNTHETIC-ORIGINAL-QUERY'});
  d=page('confirm',{session:confirmSession,review:confirmReview,responses:[expired],bootstrapError:Error('网络不可用')});
  d.p.onLoad();d.p.checked({detail:{value:['yes']}});await d.p.submit();
  const routeCount=routes.length;
  await d.p.recoverSubject();
  assert.equal(d.p.data.requestId,'SYNTHETIC-ORIGINAL-QUERY');
  assert.equal(d.p.data.error,'网络不可用');
  assert.equal(d.p.data.busy,false);
  assert.equal(routes.length,routeCount);count++;
  const occupied=Object.assign(Error('所选时段已占用'),{status:409,code:'BUSINESS_CONFLICT'});
  d=page('confirm',{session:confirmSession,review:confirmReview,responses:[occupied]});
  d.p.onLoad();d.p.checked({detail:{value:['yes']}});await d.p.submit();
  assert.equal(d.p.data.subjectInvalid,false);
  assert.equal(d.p.data.review.preview.proposal_token,'SYNTHETIC-PROPOSAL');count++;
  d=page('account',{session:{account_authenticated:false}});await d.p.onShow();assert.equal(d.p.data.guest,true);assert.equal(d.p.data.profile,null);count++;
  d.p.setData({newPassword:'SECRET',repeatPassword:'SECRET',smsCode:'SECRET',unlinkPassword:'SECRET'});d.p.onHide();assert.equal(d.p.data.newPassword,'');assert.equal(d.p.data.smsCode,'');count++;
  return {passed:true,cases:count,scope:'actual tab routing and patient Page handlers with controlled transport; not IDE/device acceptance'};
}
module.exports={verify};
if(require.main===module)verify().then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e.stack);process.exitCode=1;});
