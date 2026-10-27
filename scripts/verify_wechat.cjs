/* Native JavaScript checks. They verify source/transport, not the WeChat runtime. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
const app=JSON.parse(fs.readFileSync(path.join(root,'app.json')));
let checks=0;
const css=fs.readFileSync(path.join(root,'app.wxss'),'utf8').replace(/\/\*[\s\S]*?\*\//g,'');
for(const selector of css.matchAll(/(?:^|})\s*([^{}]+)\{/g)) {
  assert(!selector[1].includes('*'),'WeChat WXSS rejects universal selectors; use class or descendant selectors.');
}
checks++;
for(const page of app.pages){
  for(const ext of ['.js','.wxml']){assert(fs.existsSync(path.join(root,page+ext)));checks++;}
  const source=fs.readFileSync(path.join(root,page+'.js'),'utf8');new vm.Script(source,{filename:page});checks++;
  const markup=fs.readFileSync(path.join(root,page+'.wxml'),'utf8');
  for(const match of markup.matchAll(/bind(?:tap|input|change|confirm)="([A-Za-z]\w*)"/g)){
    assert(new RegExp('(?:async\\s+)?'+match[1]+'\\s*\\(').test(source),page+' missing '+match[1]);checks++;
  }
}
const {dateTime}=require(path.join(root,'utils/format'));
assert.equal(dateTime('2026-10-20T16:15:00Z'),'2026-10-21 00:15');checks++;
let last;
const appState={globalData:{review:{sensitive:'not persisted'}}};
global.getApp=()=>appState;
global.wx={request(options){last=options;},setStorage(){throw Error('session must stay in memory');}};
const api=require(path.join(root,'utils/api'));
const success=(data,cookies=[])=>last.success({statusCode:200,cookies,data:{ok:true,data}});
(async()=>{
  let p=api.bootstrap();assert.equal(last.method,'GET');success({csrf_token:'masked_csrf',authenticated:false},['csrftoken=secret; Path=/']);await p;checks++;
  assert.equal(appState.globalData.review,null);checks++;
  p=api.request('booking/preview/','POST',{slot:1});assert.equal(last.header['X-CSRFToken'],'masked_csrf');assert.equal(last.header.Cookie,'csrftoken=secret');success({proposal_token:'preview'});await p;checks+=2;
  p=api.request('session/');success({csrf_token:'rotated',workspace_token:'signed_workspace',authenticated:true},['sessionid=opaque; HttpOnly']);await p;
  p=api.request('booking/confirm/','POST',{proposal_token:'signed'});assert.equal(last.header['X-ADC-Workspace'],'signed_workspace');assert(last.header.Cookie.includes('sessionid=opaque'));success({id:1});await p;checks+=2;
  p=api.request('visits/');last.success({statusCode:403,data:{ok:false,message:'当前授权失效',request_id:'123'}});await assert.rejects(p,/当前授权失效/);checks++;
  p=api.request('booking/confirm/','POST',{});last.fail({errMsg:'sensitive implementation details'});await assert.rejects(p,/结果尚未确认/);checks++;
  p=api.request('discovery/index/');last.fail({errMsg:'private network detail'});await assert.rejects(p,e=>e.code==='NETWORK_UNAVAILABLE'&&!e.message.includes('结果尚未确认'));checks++;
  appState.globalData.review={private:'old patient preview'};
  p=api.request('visits/');last.success({statusCode:401,data:{ok:false,message:'请先登录'}});await assert.rejects(p,/请先登录/);
  assert.deepEqual(api.sessionInfo(),{});assert.equal(appState.globalData.review,null);checks+=2;
  p=api.signOut();success({csrf_token:'new'},['sessionid=; Max-Age=0']);await p;assert.deepEqual(api.sessionInfo(),{});assert.equal(appState.globalData.review,null);checks+=2;
  p=api.request('session/');success({csrf_token:'c',workspace_token:'w1',workspace_id:'ctx',subject_revision:1,subject_key:'self',authenticated:true});await p;
  const late=api.request('visits/'),oldResponse=last;
  appState.globalData.review={patient:'self'};
  p=api.selectSubject('grant:3');success({csrf_token:'c',workspace_token:'w2',workspace_id:'ctx',subject_revision:2,subject_key:'grant:3',authenticated:true});await p;
  oldResponse.success({statusCode:200,data:{ok:true,data:{patient:'old'}}});
  await assert.rejects(late,e=>e.code==='SUBJECT_CHANGED');assert.equal(appState.globalData.review,null);checks+=2;
  appState.globalData.review={patient:'current'};
  p=api.bootstrap();success({csrf_token:'c',workspace_token:'refreshed_signature',workspace_id:'ctx',subject_revision:2,subject_key:'grant:3',authenticated:true});await p;
  assert.equal(appState.globalData.review.patient,'current');checks++;
  p=api.bootstrap();success({csrf_token:'c',workspace_id:'pending-a',subject_revision:0,account_name:'pending-a',account_authenticated:true,authenticated:false,account_token:'account-a'});await p;
  const oldAccount=api.request('account/'),oldAccountResponse=last;
  p=api.request('account/local-login/','POST',{code:'one-use'});assert.equal(last.header['X-ADC-Account'],'account-a');success({csrf_token:'new-c',workspace_id:'pending-b',subject_revision:0,account_name:'pending-b',account_authenticated:true,authenticated:false,account_token:'account-b'});await p;
  oldAccountResponse.success({statusCode:200,data:{ok:true,data:{phone:'PRIVATE_OLD_ACCOUNT'}}});await assert.rejects(oldAccount,e=>e.code==='SUBJECT_CHANGED');checks+=2;
  let compiler={status:'not_run'};
  if(process.env.ADC_WECHAT_COMPILER_DIR){
    const os=require('node:os'),{spawnSync}=require('node:child_process');
    const output=fs.mkdtempSync(path.join(os.tmpdir(),'adc-wechat-compile-'));
    try{
      for(const [binary,args] of [['wcc',['-o',path.join(output,'wxml.js'),...app.pages.map(p=>p+'.wxml')]],['wcsc',['-lc','-js','-o',path.join(output,'wxss.js'),'app.wxss']]]){
        const result=spawnSync(path.join(process.env.ADC_WECHAT_COMPILER_DIR,binary),args,{cwd:root,encoding:'utf8',timeout:30000});
        assert.equal(result.status,0,binary+': '+result.stderr);
      }
      compiler={status:'passed',wxml_pages:app.pages.length,wxss_files:1,scope:'Official offline syntax only; not an IDE preview or WeChat runtime'};
    }finally{fs.rmSync(output,{recursive:true,force:true});}
  }
  const services=await require('./verify_native_services.cjs').verify();
  const plans=await require('./verify_native_plans.cjs').verify();
  const discovery=await require('./verify_native_discovery.cjs').verify();
  const accounts=await require('./verify_native_accounts.cjs').verify();
  const wechat=await require('./verify_native_wechat.cjs').verify();
  const profiles=await require('./verify_native_profiles.cjs').verify();
  const alignment=await require('./verify_native_alignment.cjs').verify();
  console.log(JSON.stringify({passed:true,checks,services,plans,discovery,accounts,wechat,profiles,alignment,compiler,scope:'native source, handlers, timezone, session/CSRF transport, expiry and uncertain-network response; not a WeChat-runtime execution'}));
})().catch(e=>{console.error(e.message);process.exitCode=1;});
