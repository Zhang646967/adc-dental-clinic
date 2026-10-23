/* Real Page handlers with a mocked API boundary; not WeChat/HTTP/PG execution. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
const {selectedCatalogue}=require(path.join(root,'utils/service-selection'));
const session={authenticated:true,today:'2026-10-22',last_day:'2026-11-05',read_only:false,environment_label:'测试环境'};
const dentists=[{id:5,name:'接诊医师'}];
const offerings=[
  {id:11,clinic:1,name:'初诊评估',category:'CHECKUP',category_label:'初诊',summary:'了解口腔状况',suitable_for:'想做检查',self_booking:true,duration:30,dentists,fee_label:'评估后确认费用'},
  {id:22,clinic:2,name:'复查',category:'FOLLOWUP',category_label:'复查',summary:'继续已有安排',suitable_for:'已有就诊计划',self_booking:true,duration:45,dentists,fee_label:'¥0.00 / 本次服务'},
  {id:33,clinic:2,name:'儿童检查',category:'CHILDREN',category_label:'儿童',summary:'了解儿童就诊安排',suitable_for:'带孩子检查',self_booking:false,duration:30,dentists,fee_label:'评估后确认费用'}
];
const catalogue={clinics:[{id:1,name:'门店一'},{id:2,name:'门店二'},{id:3,name:'待发布门店'}],offerings,services:offerings.filter(s=>s.self_booking),resource_clinics:[1,2]};
const slot={id:'8:time',slot:8,service:22,start:'2026-10-23T09:00:00+08:00',end:'2026-10-23T09:45:00+08:00'};
const plain=x=>JSON.parse(JSON.stringify(x));
function page(name,options={}){
  let definition;
  const calls=[],navigation=[],state={globalData:{review:null}};
  const wx=Object.fromEntries(['navigateTo','reLaunch','redirectTo'].map(method=>[method,data=>navigation.push({method,...data})]));
  const currentSession={...session,...options.session};
  const api={selectSubject:async key=>{calls.push({route:'patients/select/',method:'POST',data:{subject:key}});state.globalData.review=null;},showSubject:p=>p.setData({patientName:currentSession.patient_name||'',patientCapacity:currentSession.acting_capacity||''}),bootstrap:async()=>currentSession,sessionInfo:()=>currentSession,request:async(route,method='GET',data)=>{
    calls.push({route,method,data});
    if(options.request)return options.request(route,method,data);
    if(route==='catalogue/')return options.catalogue||catalogue;
    if(route.startsWith('services/'))return offerings.find(s=>String(s.id)===route.split('/')[1]);
    throw Error('Unexpected request '+route);
  }};
  const format={exports:{}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'utils/format.js'),'utf8'),{module:format,wx});
  vm.runInNewContext(fs.readFileSync(path.join(root,'pages',name,'index.js'),'utf8'),{
    Page:value=>{definition=value;},wx,getApp:()=>state,
    require:module=>module.endsWith('/api')?api:module.endsWith('/format')?format.exports:{selectedCatalogue}
  });
  const instance={...definition,data:plain(definition.data),setData(values){Object.assign(this.data,values);}};
  return {p:instance,calls,navigation,state};
}

async function verify(){
  const cases=[];
  async function test(name,run){await run();cases.push(name);}
  await test('typed service hint selects its clinic and exact service',()=>{
    const d=selectedCatalogue(catalogue,{service:'22'});
    assert.equal(d.clinics[d.clinicIndex].id,2);assert.equal(d.selectedId,22);
  });
  await test('invalid, withdrawn, child and cross-clinic hints never substitute',()=>{
    for(const query of [{service:'-1'},{service:'//example.invalid'},{service:'999'},{service:'33'},{service:'22',clinic:'1'},{service:'9007199254740993'}])assert.throws(()=>selectedCatalogue(catalogue,query));
  });
  await test('empty catalogue cannot invent a legacy service',()=>{
    const d=selectedCatalogue({...catalogue,services:[]});assert.equal(d.clinics.length,0);assert.equal(d.allServices.length,0);
  });
  await test('older catalogue responses fail with a patient-facing error',async()=>{
    const old={clinics:catalogue.clinics,services:catalogue.services};
    assert.throws(()=>selectedCatalogue(old),/服务目录暂不可用/);
    const {p}=page('services',{catalogue:old});await p.onShow();assert.equal(p.data.rows.length,0);assert.match(p.data.error,/服务目录暂不可用/);
  });
  await test('home starts with service discovery',()=>{
    const {p,navigation}=page('home');p.book();assert.equal(navigation[0].url,'/pages/services/index');
  });
  await test('discovery filters published offerings by need, category and clinic',async()=>{
    const {p}=page('services');await p.onShow();assert.equal(p.data.rows.length,3);
    p.keyword({detail:{value:'孩子'}});assert.equal(p.data.rows[0].id,33);
    p.keyword({detail:{value:''}});p.pickCategory({detail:{value:'1'}});assert.equal(p.data.rows.length,1);
    p.pickClinic({detail:{value:'2'}});assert.equal(p.data.rows.length,0);
  });
  await test('unauthenticated discovery returns to login before catalogue access',async()=>{
    const {p,calls,navigation}=page('services',{session:{authenticated:false}});await p.onShow();assert.equal(calls.length,0);assert.equal(navigation[0].url,'/pages/login/index');
  });
  await test('service detail hands off the exact service and clinic',async()=>{
    const {p,navigation}=page('service');p.onLoad({id:'22'});await p.onShow();p.book();assert.equal(navigation[0].url,'/pages/booking/index?clinic=2&service=22');
  });
  await test('child and read-only detail cannot navigate into self booking',async()=>{
    for(const options of [{id:'33'},{id:'22',session:{read_only:true}}]){
      const {p,navigation}=page('service',options);p.onLoad({id:options.id});await p.onShow();p.book();assert.equal(navigation.length,0);
    }
  });
  await test('detail refresh clears withdrawn content before displaying an error',async()=>{
    let gone=false;const {p,navigation}=page('service',{request:async()=>{if(gone)throw Error('服务暂不可用');return offerings[1];}});
    p.onLoad({id:'22'});await p.onShow();gone=true;await p.onShow();p.book();assert.equal(p.data.service,null);assert(p.data.error);assert.equal(navigation.length,0);
  });
  await test('invalid detail link does not issue a path request',async()=>{
    const {p,calls}=page('service');p.onLoad({id:'../visits'});await p.onShow();assert.equal(calls.length,0);assert(p.data.error);
  });
  await test('booking preserves the non-first service, clinic and duration',async()=>{
    const {p}=page('booking');await p.onLoad({service:'22'});assert.equal(p.data.clinics[p.data.clinicIndex].id,2);assert.equal(p.data.selectedService.id,22);assert.equal(p.data.selectedService.duration,45);
  });
  await test('removed service hint blocks booking instead of choosing a replacement',async()=>{
    const {p,calls}=page('booking');await p.onLoad({service:'999'});assert(p.data.error);assert.equal(p.data.services.length,0);assert.equal(calls.length,1);
  });
  await test('empty booking catalogue stays empty without a fake default',async()=>{
    const {p}=page('booking',{catalogue:{...catalogue,services:[]}});await p.onLoad({});await p.search();assert.equal(p.data.services.length,0);assert(p.data.error);
  });
  await test('own historical reschedule works without a public catalogue',async()=>{
    const source={id:41,clinic_id:3,clinic:'原门店',service_id:44,service:'保留的服务',start:slot.start,end:slot.end,version:0,
      reschedule_service:{id:44,clinic:3,name:'保留的服务',duration:45,dentists}};
    const {p,calls}=page('booking',{request:async(route)=>{assert.equal(route,'visits/41/');return source;}});
    await p.onLoad({visit:'41'});assert.equal(calls.length,1);assert.equal(p.data.selectedService.id,44);assert.equal(p.data.clinics[0].id,3);
  });
  await test('legacy own visit retains a source-only rescheduling option',async()=>{
    const {p}=page('booking',{request:async()=>({id:41,clinic_id:3,clinic:'原门店',service_id:null,start:slot.start,end:slot.end,
      reschedule_service:{id:null,clinic:3,name:'原预约',duration:30,dentists}})});
    await p.onLoad({visit:'41'});assert.equal(p.data.services.length,1);assert.equal(p.data.selectedService.id,null);
  });
  await test('older visit responses fail before constructing a rescheduling choice',async()=>{
    const {p}=page('booking',{request:async()=>({id:41,clinic_id:3,clinic:'原门店'})});await p.onLoad({visit:'41'});
    assert.equal(p.data.services.length,0);assert.match(p.data.error,/暂不可自助改期/);
  });
  await test('busy search ignores selection changes and failed search clears old results',async()=>{
    const {p}=page('booking',{request:async(route)=>{if(route==='catalogue/')return catalogue;throw Error('接诊配置变化');}});
    await p.onLoad({service:'22'});p.setData({busy:true});p.pickClinic({detail:{value:'0'}});assert.equal(p.data.clinics[p.data.clinicIndex].id,2);
    p.setData({busy:false,rows:[slot],searched:true,note:'旧提示'});await p.search();assert.equal(p.data.rows.length,0);assert.equal(p.data.searched,false);assert.equal(p.data.note,'');assert.equal(p.data.busy,false);
  });
  await test('patient request is sent once to preview and server text is reviewed',async()=>{
    const {p,calls,state,navigation}=page('booking',{request:async(route,method,data)=>{
      if(route==='catalogue/')return catalogue;
      assert.equal(route,'booking/preview/');assert.equal(method,'POST');assert.equal(data.patient_request,'希望检查一下');
      return {...slot,service:'复查',patient_request:'服务器确认的需求',proposal_token:'signed',fee_label:'¥0.00 / 本次服务'};
    }});
    await p.onLoad({service:'22'});p.patientRequest({detail:{value:'希望检查一下'}});p.setData({rows:[slot]});await p.choose({currentTarget:{dataset:{index:0}}});
    assert.equal(calls.length,2);assert.equal(state.globalData.review.preview.patient_request,'服务器确认的需求');assert.equal(state.globalData.review.preview.fee_label,'¥0.00 / 本次服务');assert.equal(navigation[0].url,'/pages/confirm/index');
  });
  await test('confirmation submits signed token only, not editable reason or fee fields',async()=>{
    const {p,calls,state}=page('confirm',{request:async()=>({...slot,id:42,status_label:'已预约'})});
    state.globalData.review={kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed',patient_request:'需求',fee_amount:'0'}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();await p.submit();
    assert.equal(calls.length,1);assert.deepEqual(plain(calls[0].data),{proposal_token:'signed',confirmed:'on'});assert.equal(state.globalData.review,null);assert.equal(p.data.done.id,42);
  });
  await test('waitlist preserves selected service and never invents a generic fallback',async()=>{
    const {p}=page('waitjoin');await p.onLoad({service:'22',clinic:'2',day:'2026-10-25'});assert.equal(p.data.services[p.data.serviceIndex].id,22);assert.equal(p.data.startDay,'2026-10-25');
    const empty=page('waitjoin',{catalogue:{...catalogue,services:[]}});await empty.p.onLoad({});await empty.p.preview();assert.equal(empty.p.data.services.length,0);assert(empty.p.data.error);
  });
  await test('historical reschedule cannot redirect to new public waitlist registration',async()=>{
    const {p,navigation}=page('booking');p.setData({source:{id:41}});p.waitlist();assert.equal(navigation.length,0);
  });
  await test('visit refresh removes private cached text if authorization fails',async()=>{
    const {p}=page('visit',{request:async()=>{throw Error('授权已失效');}});p.onLoad({id:'41'});p.setData({visit:{patient_request:'此前的患者需求'}});
    await p.onShow();assert.equal(p.data.visit,null);assert(p.data.error);
  });
  await test('subject selector submits exact server choice and clears prior review',async()=>{
    const {p,calls,navigation,state}=page('patients',{request:async()=>({rows:[{key:'grant:7',name:'患者乙',capacity:'父母',clinic:'门店一',expires:'2026-11-01T01:00:00Z'}]})});
    await p.onShow();assert.equal(p.data.rows[0].expiresLabel,'2026-11-01 09:00');
    state.globalData.review={patient:'old'};await p.choose({currentTarget:{dataset:{key:'grant:7'}}});
    assert.equal(calls.at(-1).data.subject,'grant:7');assert.equal(state.globalData.review,null);assert.equal(navigation.at(-1).url,'/pages/home/index');
  });
  await test('stale subject review cannot reach confirmation transport',async()=>{
    const {p,state,calls}=page('confirm',{session:{subject_key:'grant:2',workspace_token:'new'}});
    state.globalData.review={subjectKey:'self',workspaceToken:'old',kind:'booking',preview:{}};p.onLoad();
    p.checked({detail:{value:['yes']}});await p.submit();assert.equal(calls.length,0);assert(p.data.error);
  });
  await test('same subject and context permit a refreshed transport signature',async()=>{
    const {p,state}=page('confirm',{session:{subject_key:'grant:2',workspace_id:'ctx',subject_revision:3,workspace_token:'refreshed'}});
    state.globalData.review={subjectKey:'grant:2',workspaceKey:'ctx',subjectRevision:3,workspaceToken:'prior',kind:'booking',preview:{}};p.onLoad();assert(p.data.review);assert.equal(p.data.error,'');
  });
  return {passed:true,cases:cases.length,case_names:cases,scope:'actual Page handlers with mocked API; not Django/PostgreSQL, official compilation or WeChat runtime'};
}
module.exports={verify};
if(require.main===module)verify().then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error.stack);process.exitCode=1;});
