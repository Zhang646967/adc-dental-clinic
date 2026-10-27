/* Actual Page handlers, simulated transport/consent. HTTP and WeChat are separate. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram'),intent=require(path.join(root,'utils/booking-intent'));
const plain=x=>JSON.parse(JSON.stringify(x)),pending={authenticated:false,account_authenticated:true,account_name:'synthetic-account',workspace_id:'account-a',subject_revision:0,read_only:false,identity_provider:'local'};
const profile={account_name:'synthetic-account',enrollment_required:true,password_ready:false,phone:null,identities:[{id:5,revision:1,provider:'LOCAL'}],cases:[]};
function page(name,options={}){
 let definition;const calls=[],navigation=[],session={...pending,...options.session},state={globalData:{review:null,bookingIntent:null}};
 const wx={...Object.fromEntries(['navigateTo','reLaunch','redirectTo'].map(m=>[m,o=>navigation.push({method:m,...o})])),showModal:o=>o.success({confirm:options.consent!==false}),login:o=>options.wechatError?o.fail():o.success({code:'provider-one-use-code'})};
 const api={bootstrap:async()=>session,sessionInfo:()=>session,signOut:async()=>{},localSignIn:async(code,username,password,confirmed)=>{
  calls.push({route:'account/local-login/',data:{code,username,password,confirmed}});if(options.loginError)throw options.loginError;return session;
 },request:async(route,method='GET',data)=>{calls.push({route,method,data});if(options.request)return options.request(route,method,data);if(route==='account/')return plain(profile);if(route==='discovery/')return {clinics:[{id:1,name:'合成长沙一店'},{id:2,name:'合成长沙二店'}]};throw Error('Unexpected '+route);}};
 const format={exports:{}};vm.runInNewContext(fs.readFileSync(path.join(root,'utils/format.js'),'utf8'),{module:format,wx});
 vm.runInNewContext(fs.readFileSync(path.join(root,'pages',name,'index.js'),'utf8'),{Page:p=>definition=p,wx,getApp:()=>state,require:n=>n.endsWith('/navigation')?{navigateTo:wx.navigateTo,reLaunch:wx.reLaunch,redirectTo:wx.redirectTo,consume:()=>null}:n.endsWith('/api')?api:n.endsWith('/format')?format.exports:intent});
 const p={...definition,data:plain(definition.data),setData:v=>Object.assign(p.data,v)};
 return {p,session,calls,navigation,state};
}
const input=(field,value)=>({currentTarget:{dataset:{field}},detail:{value}});
async function verify(){
 const details=[];const test=async(n,f)=>{await f();details.push(n);};
 await test('pending login preserves service intent while opening enrollment account',async()=>{
  const d=page('login');intent.remember(d.state,22,2);await d.p.onLoad();assert.equal(d.navigation[0].url,'/pages/account/index');assert.equal(d.state.globalData.bookingIntent.service,22);
 });
 await test('local login requires consent and clears credential/password on failure',async()=>{
  const d=page('login',{session:{account_authenticated:false},loginError:new Error('核对未通过')});d.p.setData({localCode:'private-code',password:'private-password'});
  await d.p.localLogin();assert.equal(d.calls.length,0);d.p.consent({detail:{value:['agree']}});await d.p.localLogin();assert.equal(d.calls.length,1);assert.equal(d.p.data.localCode,'');assert.equal(d.p.data.password,'');
 });
 await test('profile refresh failure clears previously displayed private account',async()=>{
  let failed=false;const d=page('account',{request:async()=>{if(failed)throw Error('授权已变化');return plain(profile);}});
  await d.p.onShow();assert(d.p.data.profile);failed=true;await d.p.load();assert.equal(d.p.data.profile,null);
 });
 await test('account switch clears private input before displaying another profile',async()=>{
  const d=page('account');await d.p.onShow();d.p.setData({phoneCode:'prior-code',newPassword:'prior-secret',unlinkPassword:'prior-secret'});d.session.workspace_id='account-b';await d.p.onShow();
  assert.equal(d.p.data.phoneCode,'');assert.equal(d.p.data.newPassword,'');assert.equal(d.p.data.unlinkPassword,'');
 });
 await test('phone refusal sends no mutation',async()=>{
  const d=page('account',{consent:false});d.p.setData({phoneCode:'code'});await d.p.phone();assert.equal(d.calls.length,0);
 });
 await test('phone confirmation sends only own one-use proof and clears input',async()=>{
  const d=page('account',{request:async()=>plain(profile)});d.p.setData({phoneCode:'proof'});await d.p.phone();assert.deepEqual(plain(d.calls[0].data),{code:'proof',confirmed:'on'});assert.equal(d.p.data.phoneCode,'');
 });
 await test('password setup uses fresh credential and removes both private passwords',async()=>{
  const d=page('account',{request:async()=>plain(profile)});d.p.setData({loginCode:'fresh',newPassword:'new-private',repeatPassword:'new-private'});await d.p.password();assert.equal(d.calls[0].route,'account/password/');assert.equal(d.p.data.loginCode,'');assert.equal(d.p.data.newPassword,'');assert.equal(d.p.data.repeatPassword,'');
 });
 await test('explicit activation resumes exact service only after returned patient authority',async()=>{
  const d=page('account',{request:async()=>({...pending,authenticated:true})});intent.remember(d.state,22,2);await d.p.activate();assert.equal(d.calls[0].route,'account/activate/');assert.equal(d.navigation[0].url,'/pages/booking/index?service=22&clinic=2');assert.equal(d.state.globalData.bookingIntent,null);
 });
 await test('new enrollment preserves selected non-first clinic and edits invalidate preview',async()=>{
  const d=page('enrollment',{request:async r=>r==='discovery/'?{clinics:[{id:1,name:'一店'},{id:2,name:'二店'}]}:{proposal_token:'signed-original',rows:[]}});intent.remember(d.state,22,2);d.p.onLoad({});await d.p.onShow();
  d.p.field(input('name','合成本人'));await d.p.preview();assert.equal(d.calls.at(-1).data.clinic,2);assert(d.p.data.preview);d.p.field(input('phone','00000000000'));assert.equal(d.p.data.preview,null);
 });
 await test('invalid enrollment case link never becomes a new application',async()=>{
  const d=page('enrollment');d.p.onLoad({case:'../1'});await d.p.onShow();assert.equal(d.calls.length,0);assert.equal(d.p.data.invalidLink,true);
 });
 await test('account change clears existing enrollment draft and signed preview',async()=>{
  const d=page('enrollment');d.p.onLoad({});await d.p.onShow();d.p.field(input('name','PRIVATE_OLD_NAME'));d.p.setData({preview:{proposal_token:'old-account'},patientMessage:'private-message'});d.session.workspace_id='account-b';await d.p.onShow();
  assert.equal(d.p.data.form.name,'');assert.equal(d.p.data.preview,null);assert.equal(d.p.data.patientMessage,'');assert.equal(d.p.data.clinics.length,0);
 });
 await test('uncertain enrollment retry retains identical signed operation and freezes edits',async()=>{
  let count=0;const d=page('enrollment',{request:async r=>{
   if(r.endsWith('/confirm/')){count++;if(count===1){const e=new Error('结果尚未确认');e.code='NETWORK_UNCONFIRMED';throw e;}return {repeated:true};}return {};
  }});d.p.setData({preview:{proposal_token:'one-signed-operation'}});await d.p.confirm();assert.equal(d.p.data.uncertain,true);d.p.field(input('name','must not change'));d.p.revise();assert(d.p.data.preview);assert.equal(d.p.data.form.name,'');await d.p.confirm();
  assert.deepEqual(plain(d.calls[0].data),plain(d.calls[1].data));assert.equal(d.p.data.uncertain,false);assert.equal(d.navigation[0].url,'/pages/account/index');
 });
 await test('read-only clients cannot issue account mutations or enrollment submission',async()=>{
  const a=page('account');a.p.setData({readOnly:true,phoneCode:'proof',loginCode:'code',newPassword:'secret',repeatPassword:'secret',unlinkPassword:'secret'});await a.p.phone();await a.p.password();await a.p.unlink({currentTarget:{dataset:{id:5,revision:1}}});assert.equal(a.calls.length,0);
  const e=page('enrollment');e.p.setData({readOnly:true,preview:{proposal_token:'old'}});await e.p.preview();await e.p.confirm();assert.equal(e.calls.length,0);
 });
 await test('unlink submits own selected identity/version without patient fields',async()=>{
  const d=page('account',{request:async()=>plain(profile)});d.p.setData({unlinkPassword:'private-fallback'});await d.p.unlink({currentTarget:{dataset:{id:5,revision:2}}});assert.deepEqual(plain(d.calls[0].data),{identity:5,revision:2,password:'private-fallback',confirmed:'on'});assert.equal(d.p.data.unlinkPassword,'');
 });
 await test('WeChat login requires consent and sends only platform code with explicit old-account fields',async()=>{
  const d=page('login',{session:{account_authenticated:false},request:async()=>plain(pending)});await d.p.wechatLogin();assert.equal(d.calls.length,0);
  d.p.setData({authConfirmed:true});await d.p.wechatLogin();assert.equal(d.calls[0].route,'auth/wechat/');assert.deepEqual(plain(d.calls[0].data),{code:'provider-one-use-code',confirmed:'on',username:'',password:''});assert.equal(d.navigation[0].url,'/pages/account/index');
 });
 await test('WeChat platform refusal cannot create an ADC login',async()=>{
  const d=page('login',{wechatError:true});d.p.setData({authConfirmed:true});await d.p.wechatLogin();assert.equal(d.calls.length,0);assert(d.p.data.error);assert.equal(d.p.data.busy,false);
 });
 await test('SMS test source is labelled and confirmation uses returned challenge',async()=>{
  const d=page('login',{request:async route=>route.endsWith('/send/')?{challenge:'one-challenge',demo:true,test_code:'123456'}:plain(pending)});
  d.p.setData({phone:'00000000110',authConfirmed:true});await d.p.sendSms();assert(d.p.data.smsNotice.includes('未发送短信'));d.p.setData({smsCode:'123456'});await d.p.smsLogin();
  assert.deepEqual(plain(d.calls[1].data),{phone:'00000000110',challenge:'one-challenge',code:'123456',confirmed:'on'});assert.equal(d.p.data.smsCode,'');assert.equal(d.p.data.smsNotice,'');
 });
 await test('Real SMS send acknowledgement never displays an invented test code',async()=>{
  const d=page('login',{request:async()=>({challenge:'one-challenge',demo:false})});d.p.setData({phone:'13800000000',authConfirmed:true});await d.p.sendSms();assert(d.p.data.smsNotice.includes('提交发送'));assert(!d.p.data.smsNotice.includes('undefined'));assert.equal(d.p.data.smsCode,'');
 });
 await test('Current account WeChat binding keeps the own-account endpoint',async()=>{
  const d=page('account',{request:async()=>plain(profile)});await d.p.bindWechat();assert.equal(d.calls[0].route,'account/wechat/bind/');assert.deepEqual(plain(d.calls[0].data),{code:'provider-one-use-code',confirmed:'on'});
 });
 await test('Phone denial does nothing and phone approval sends only the one-use provider code',async()=>{
  const d=page('account',{request:async()=>plain(profile)});await d.p.wechatPhone({detail:{}});assert.equal(d.calls.length,0);await d.p.wechatPhone({detail:{code:'one-use-phone-code'}});assert.equal(d.calls[0].route,'account/phone/wechat/');assert.deepEqual(plain(d.calls[0].data),{code:'one-use-phone-code',confirmed:'on'});
 });
 await test('Account switch clears SMS challenge and contact inputs',async()=>{
  const d=page('account');await d.p.onShow();d.p.setData({smsPhone:'13800000000',smsCode:'123456',smsChallenge:'old',smsNotice:'old code'});d.session.workspace_id='account-b';await d.p.onShow();for(const key of ['smsPhone','smsCode','smsChallenge','smsNotice'])assert.equal(d.p.data[key],'');
 });
 await test('Read-only clients cannot bind WeChat or send/confirm phone SMS',async()=>{
  const d=page('account');d.p.setData({readOnly:true});await d.p.bindWechat();await d.p.wechatPhone({detail:{code:'one-use-code'}});await d.p.sendPhoneSms();await d.p.bindPhoneSms();assert.equal(d.calls.length,0);
 });
 return {passed:true,cases:details.length,details,scope:'actual Page handlers with mocked transport/consent; not HTTP, official compilation or WeChat runtime'};
}
module.exports={verify};
