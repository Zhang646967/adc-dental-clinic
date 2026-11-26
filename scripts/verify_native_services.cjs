/* Real Page handlers with a mocked API boundary; not WeChat/HTTP/PG execution. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
const {selectedCatalogue}=require(path.join(root,'utils/service-selection'));
const patientAction=require(path.join(root,'utils/primary-action'));
const subjectState=require(path.join(root,'utils/subject-state'));
const visitReview=require(path.join(root,'utils/visit-review'));
const examinations=require(path.join(root,'utils/examinations'));
const reportNotices=require(path.join(root,'utils/report-notices'));
const returnSources=require(path.join(root,'utils/return-sources'));
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
  const api={selectSubject:async key=>{calls.push({route:'patients/select/',method:'POST',data:{subject:key}});state.globalData.review=null;},showSubject:p=>p.setData({patientName:currentSession.patient_name||'',patientCapacity:currentSession.acting_capacity||'',patientDelegated:!!currentSession.delegated}),bootstrap:async()=>currentSession,sessionInfo:()=>currentSession,request:async(route,method='GET',data)=>{
    calls.push({route,method,data});
    if(options.request)return options.request(route,method,data);
    if(route==='discovery/services/'){
      const source=options.catalogue||catalogue;if(!Array.isArray(source.offerings))return source;
      const rows=source.offerings.filter(s=>(!data.category||s.category===data.category)&&(!data.clinic||String(s.clinic)===String(data.clinic))&&(!data.q||[s.name,s.summary,s.suitable_for].join(' ').includes(data.q)));
      return {offerings:rows,categories:[...new Map(source.offerings.map(s=>[s.category,{id:s.category,name:s.category_label,count:source.offerings.filter(x=>x.category===s.category).length}])).values()],clinic_choices:source.clinics.map(c=>({...c,count:source.offerings.filter(s=>s.clinic===c.id).length})),alternatives:[],message:rows.length?'':'没有匹配服务',page:1,pages:1,count:rows.length};
    }
    if(route==='catalogue/'||route==='discovery/')return options.catalogue||catalogue;
    if(route.startsWith('services/'))return {...offerings.find(s=>String(s.id)===route.split('/')[1]),default_day:'2026-10-23'};
    if(route.startsWith('discovery/services/'))return {...offerings.find(s=>String(s.id)===route.split('/')[2]),default_day:'2026-10-23'};
    throw Error('Unexpected request '+route);
  }};
  const format={exports:{}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'utils/format.js'),'utf8'),{module:format,wx});
  vm.runInNewContext(fs.readFileSync(path.join(root,'pages',name,'index.js'),'utf8'),{
    Page:value=>{definition=value;},wx,getApp:()=>state,
    require:module=>module.endsWith('/return-sources')?returnSources:module.endsWith('/report-notices')?reportNotices:module.endsWith('/subject-state')?subjectState:module.endsWith('/visit-review')?visitReview:module.endsWith('/examinations')?examinations:
      module.endsWith('/navigation')?{navigateTo:wx.navigateTo,reLaunch:wx.reLaunch,redirectTo:wx.redirectTo,returnTo:url=>navigation.push({method:'returnTo',url}),consume:()=>options.tabSelection||null}:module.endsWith('/api')?api:module.endsWith('/format')?format.exports:module.endsWith('/primary-action')?patientAction:module.endsWith('/booking-intent')?require(path.join(root,'utils/booking-intent')):module.endsWith('/nearby')?require(path.join(root,'utils/nearby')):module.endsWith('/visit-record')?require(path.join(root,'utils/visit-record')):{selectedCatalogue}
  });
  const instance={...definition,data:plain(definition.data),setData(values){Object.assign(this.data,values);}};
  return {p:instance,calls,navigation,state,session:currentSession};
}

async function verify(){
  const cases=[];
  async function test(name,run){await run();cases.push(name);}
  await test('booking keeps only public choices when switching patients',async()=>{
    const {p,state,navigation}=page('booking');
    await p.onLoad({clinic:'2',service:'22',dentist:'5',day:'2026-10-24'});
    p.setData({patientRequest:'Private note'});
    p.subjects();
    const saved=state.globalData.bookingIntent;
    assert.deepEqual([saved.clinic,saved.service,saved.dentist,saved.day],[2,22,5,'2026-10-24']);
    assert(!JSON.stringify(saved).includes('Private note'));
    assert.equal(navigation.at(-1).url,'/pages/patients/index');
  });
  await test('booking distinguishes unpublished shifts from occupied resources',async()=>{
    for(const [status,title] of [['NO_SCHEDULE','当天暂无出诊'],['NO_COMBINATION','当天暂无可用时段']]){
      const {p}=page('booking',{request:async route=>route==='catalogue/'?catalogue:route==='candidates/'?{status,rows:[],message:'请选择其他日期'}:{default_day:'2026-10-23'}});
      await p.onLoad({clinic:'2',service:'22'});
      await p.search();
      assert.equal(p.data.availabilityTitle,title);
      assert.equal(p.data.emptyReason,'请选择其他日期');
    }
  });
  await test('date and dentist views share filters and explicitly widen to the next fourteen days',async()=>{
    const {p,calls}=page('booking',{request:async route=>{
      if(route==='catalogue/')return catalogue;
      if(route.startsWith('services/'))return {default_day:'2026-10-23'};
      assert.equal(route,'candidates/');
      return {rows:[{...slot,dentist_id:5,dentist:'合成医师'}]};
    }});
    await p.onLoad({service:'22',day:'2026-10-24'});
    await p.search();
    const selected=plain(calls.at(-1).data);
    await p.setMode({currentTarget:{dataset:{mode:'dentist'}}});
    assert.deepEqual(plain(calls.at(-1).data),selected);
    assert.equal(p.data.groups[0].count,1);
    p.pickDay({detail:{value:'2026-10-25'}});
    assert.equal(p.data.groups.length,0);
    await p.future();
    assert.equal(calls.at(-1).route,'candidates/');
    assert(!Object.hasOwn(calls.at(-1).data,'day'));
  });
  await test('interrupted booking confirmation opens the results list without resubmitting',async()=>{
    const error=Object.assign(Error('连接中断，结果尚未确认。'),{code:'NETWORK_UNCONFIRMED'});
    const {p,state,calls,navigation}=page('confirm',{request:async()=>{throw error;}});
    state.globalData.review={kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed'}};
    p.onLoad();
    p.checked({detail:{value:['yes']}});
    await p.submit();
    await p.submit();
    assert.equal(calls.length,1);
    assert.equal(p.data.uncertain,true);
    assert.equal(p.data.review,null);
    p.home();
    assert.equal(navigation.at(-1).url,'/pages/home/index?queue=all');
  });
  await test('checking an uncertain result includes cancelled and replaced visits',async()=>{
    const {p,calls}=page('home',{tabSelection:{queue:'all'},request:async route=>route==='visits/'?{rows:[],page:1,pages:1}:{}});
    p.setData({queue:'active',page:3});
    await p.onShow();
    assert.deepEqual(plain(calls[0].data),{queue:'all',page:1});
  });
  await test('offer refresh removes revoked details and choices',async()=>{
    let allowed=true;
    const d=page('offer',{request:async()=>{
      if(!allowed)throw Object.assign(Error('不可读取邀约'),{status:403});
      return {offer:{...slot,id:5,expires:slot.end,active:true},sources:[]};
    }});
    d.p.onLoad({id:'5'});
    await d.p.onShow();
    assert.equal(d.p.data.offer.id,5);
    allowed=false;
    await d.p.load();
    assert.equal(d.p.data.offer,null);
    assert.equal(d.p.data.choices.length,0);
    await d.p.decline();
    assert(d.calls.every(c=>c.method==='GET'));
  });
  await test('candidate outcome after an offer-based change returns to the waitlist',()=>{
    const d=page('confirm');
    d.state.globalData.review={kind:'reschedule',fromWaitlist:true,preview:{}};
    d.p.onLoad();d.p.home();
    assert.equal(d.navigation.at(-1).url,'/pages/waitlist/index');
  });
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
    p.keyword({detail:{value:'孩子'}});await p.search();assert.equal(p.data.rows[0].id,33);
    p.keyword({detail:{value:''}});await p.pickCategory({detail:{value:'1'}});assert.equal(p.data.rows.length,1);
    await p.pickClinic({detail:{value:'2'}});assert.equal(p.data.rows.length,0);
  });
  await test('guest discovery reads only public catalogue without forcing login',async()=>{
    const {p,calls,navigation}=page('services',{session:{authenticated:false}});await p.onShow();assert.equal(calls.length,1);assert.equal(calls[0].route,'discovery/services/');assert.equal(p.data.rows.length,3);assert.equal(navigation.length,0);
  });
  await test('guest service choice survives typed login navigation',async()=>{
    const {p,calls,navigation,state}=page('service',{session:{authenticated:false}});p.onLoad({id:'22'});await p.onShow();p.book();assert.equal(calls[0].route,'discovery/services/22/');assert.equal(navigation[0].url,'/pages/login/index');assert.equal(state.globalData.bookingIntent.service,22);assert.equal(state.globalData.bookingIntent.clinic,2);
  });
  await test('service detail hands off the exact service and clinic',async()=>{
    const {p,navigation}=page('service');p.onLoad({id:'22'});await p.onShow();p.book();assert.equal(navigation[0].url,'/pages/booking/index?clinic=2&service=22&day=2026-10-23');
  });
  await test('child detail leads to verification and read-only cannot book',async()=>{
    for(const options of [{id:'33'},{id:'22',session:{read_only:true}}]){
      const {p,navigation}=page('service',options);p.onLoad({id:options.id});await p.onShow();p.book();if(options.id==='33')assert(!navigation.some(n=>n.url.startsWith('/pages/booking/')));else assert.equal(navigation.length,0);
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
    const {p}=page('booking');await p.onLoad({service:'22'});assert.equal(p.data.clinics[p.data.clinicIndex].id,2);assert.equal(p.data.selectedService.id,22);assert.equal(p.data.selectedService.duration,45);assert.equal(p.data.day,'2026-10-23');
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
    const {p,calls}=page('booking',{request:async(route,method,data)=>{
      if(route==='visits/41/')return source;
      assert.equal(route,'visits/41/reschedule/candidates/');
      assert.equal(data.day,'2026-10-23');
      return {rows:[{...slot,dentist_id:5,dentist:'合成医师'}]};
    }});
    await p.onLoad({visit:'41'});assert.equal(calls.length,1);assert.equal(p.data.selectedService.id,44);assert.equal(p.data.clinics[0].id,3);
    await p.setMode({currentTarget:{dataset:{mode:'dentist'}}});
    assert.equal(p.data.groups.length,1);
    await p.future();
    assert.equal(calls.length,2);
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
      if(route==='services/22/')return {...offerings[1],default_day:'2026-10-23'};
      assert.equal(route,'booking/preview/');assert.equal(method,'POST');assert.equal(data.patient_request,'希望检查一下');
      return {...slot,service:'复查',patient_request:'服务器确认的需求',proposal_token:'signed',fee_label:'¥0.00 / 本次服务'};
    }});
    await p.onLoad({service:'22'});p.patientRequest({detail:{value:'希望检查一下'}});p.setData({rows:[slot]});await p.choose({currentTarget:{dataset:{index:0}}});
    assert.equal(calls.length,3);assert.equal(state.globalData.review.preview.patient_request,'服务器确认的需求');assert.equal(state.globalData.review.preview.fee_label,'¥0.00 / 本次服务');assert.equal(navigation[0].url,'/pages/confirm/index');
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
  await test('appointment delegate cannot load clinical referral controls',async()=>{
    const {p,calls}=page('referrals',{session:{delegated:true}});await p.onShow();
    assert.equal(calls.length,0);assert.match(p.data.error,/代约范围不包含/);
  });
  await test('referral termination previews before sending only its signed decision',async()=>{
    let stopped=false;const row={id:8,source:'甲',destination:'乙',valid_until:'2026-11-01T01:00:00Z',status_label:'已接收'};
    const {p,calls}=page('referrals',{session:{subject_key:'self',subject_revision:3},request:async route=>{
      if(route==='referrals/')return {rows:[{...row,status_label:stopped?'已撤销':'已接收'}],page:1,pages:1};
      if(route.endsWith('/preview/'))return {referral:row,proposal_token:'signed-referral'};
      stopped=true;return {referral:{...row,status_label:'已撤销'}};
    }});
    await p.onShow();await p.stop({currentTarget:{dataset:{id:8}}});assert.equal(stopped,false);
    p.checked({detail:{value:['yes']}});await p.confirm();
    const submission=calls.find(c=>c.route.endsWith('/confirm/'));
    assert.deepEqual(plain(submission.data),{proposal_token:'signed-referral',confirmed:'on'});
    assert.equal(p.data.preview,null);assert.equal(p.data.done,'已撤销');
  });
  await test('referral preview cannot cross patient subject revision',async()=>{
    const {p,calls}=page('referrals',{session:{subject_key:'self',subject_revision:4}});
    p.setData({preview:{referral:{id:8},proposal_token:'old'},checked:true,subject:'self',revision:3});
    await p.confirm();assert.equal(calls.length,0);assert.equal(p.data.preview,null);assert.match(p.data.error,/就诊人已变化/);
  });
  const historyRow={id:4,revision:1,recorded_at:'2026-10-24T01:00:00Z',medical_status:'UNKNOWN',medical_history:'',medication_status:'UNKNOWN',medications:'',allergy_status:'UNKNOWN',reported_allergies:''};
  const historySession={subject_key:'self',workspace_id:'ctx',subject_revision:1,delegated:false};
  const historyList={rows:[historyRow],latest:historyRow,current_revision:1,operation_id:'history-operation',page:1,pages:1};
  await test('appointment delegate cannot load or submit patient clinical history',async()=>{
    const {p,calls}=page('history',{session:{...historySession,delegated:true}});await p.onShow();assert.equal(calls.length,0);assert(p.data.error);assert.equal(p.data.rows.length,0);
    await p.submit();assert.equal(calls.length,0);
  });
  await test('patient history preserves unknown and requires explicit confirmation',async()=>{
    const {p,calls}=page('history',{session:historySession,request:async()=>historyList});await p.onShow();
    assert.equal(p.data.fields.allergy_status,'UNKNOWN');assert.equal(p.data.expected,1);
    await p.submit();assert.equal(calls.filter(c=>c.method==='POST').length,0);assert(p.data.error);
  });
  await test('patient history submits the displayed source revision and no other patient identifier',async()=>{
    let saved=false;const {p,calls}=page('history',{session:historySession,request:async(route,method,data)=>{
      if(method==='POST'){saved=true;return {row:{...historyRow,id:5,revision:2,medical_status:data.medical_status,medical_history:data.medical_history},current_revision:2,operation_id:'next-operation'};}
      return saved?{...historyList,current_revision:2,latest:{...historyRow,revision:2,medical_status:'REPORTED',medical_history:'PRIVATE_SELF'},operation_id:'next-operation'}:historyList;
    }});await p.onShow();p.pick({currentTarget:{dataset:{field:'medical_status'}},detail:{value:'1'}});p.field({currentTarget:{dataset:{field:'medical_history'}},detail:{value:'PRIVATE_SELF'}});p.checked({detail:{value:['yes']}});await p.submit();
    const request=calls.find(c=>c.method==='POST');assert.equal(request.data.expected_revision,1);assert.equal(request.data.operation_id,'history-operation');assert.equal(request.data.medical_history,'PRIVATE_SELF');assert(!('patient' in request.data));assert.match(p.data.done,/第 2 版/);
  });
  await test('uncertain history save freezes edits and retries the same intent',async()=>{
    let attempts=0;const {p,calls}=page('history',{session:historySession,request:async(route,method,data)=>{
      if(method==='POST'){attempts++;if(attempts===1){const e=Error('结果尚未确认');e.code='NETWORK_UNCONFIRMED';throw e;}return {row:historyRow,current_revision:1,operation_id:'next'};}
      return historyList;
    }});await p.onShow();p.checked({detail:{value:['yes']}});await p.submit();assert(p.data.uncertain);
    p.field({currentTarget:{dataset:{field:'medical_history'}},detail:{value:'must not change pending intent'}});assert.equal(p.data.fields.medical_history,'');
    await p.submit();const writes=calls.filter(c=>c.method==='POST');assert.equal(writes.length,2);assert.deepEqual(plain(writes[0].data),plain(writes[1].data));assert.equal(p.data.uncertain,false);
  });
  await test('history subject switch clears private draft before any write',async()=>{
    const {p,calls,session:s}=page('history',{session:historySession,request:async()=>historyList});await p.onShow();p.field({currentTarget:{dataset:{field:'medical_history'}},detail:{value:'PRIVATE_OLD_PATIENT'}});p.checked({detail:{value:['yes']}});
    s.subject_key='grant:9';s.subject_revision=2;s.delegated=true;await p.submit();assert.equal(calls.filter(c=>c.method==='POST').length,0);assert.equal(p.data.fields.medical_history,'');assert.equal(p.data.rows.length,0);
  });
  await test('foreground refresh keeps acknowledged unsaved history work',async()=>{
    const {p}=page('history',{session:historySession,request:async()=>historyList});await p.onShow();p.field({currentTarget:{dataset:{field:'medical_history'}},detail:{value:'PRIVATE_UNSAVED'}});await p.onShow();assert.equal(p.data.fields.medical_history,'PRIVATE_UNSAVED');assert.equal(p.data.dirty,true);
  });
  await test('read-only history client cannot issue a reporting write',async()=>{
    const {p,calls}=page('history',{session:{...historySession,read_only:true},request:async()=>historyList});await p.onShow();p.checked({detail:{value:['yes']}});await p.submit();assert.equal(calls.filter(c=>c.method==='POST').length,0);
  });

  /* WB-PB03: confirmation transport states. The receipt lookup is a read of
     the exact attempt; it never resends the confirmation. */
  await test('confirmation preview states the business fact and offers no receipt lookup',()=>{
    for(const [kind,note,back] of [['booking','待确认，尚未预约','返回选时段'],['reschedule','待确认，原预约仍保留','返回原页面']]){
      const {p,state,calls}=page('confirm');
      state.globalData.review={kind,path:kind==='booking'?'booking/confirm/':'visits/9/reschedule/confirm/',
        preview:{proposal_token:'signed',clinic:'门店',dentist:'医师',start:slot.start,end:slot.end,service:'初诊',original:{id:9,clinic:'门店',startLabel:'2026-10-23 09:00'}}};
      p.onLoad();
      assert.equal(p.data.previewNote,note);assert.equal(p.data.backLabel,back);
      assert.equal(p.data.uncertain,false);assert.equal(p.data.canQuery,false);assert.equal(p.data.review.preview.proposal_token,'signed');
      assert.equal(calls.length,0);
    }
  });
  await test('in-flight confirmation shows one submitting state and ignores duplicate taps',async()=>{
    let release;const pending=new Promise(resolve=>{release=resolve;});
    const {p,state,calls,navigation}=page('confirm',{request:async()=>pending});
    state.globalData.review={kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed'}};
    p.onLoad();p.checked({detail:{value:['yes']}});
    const first=p.submit();
    assert.equal(p.data.busy,true);assert.equal(p.data.uncertain,false);
    await p.submit();await p.submit();
    assert.equal(calls.length,1);
    release({...slot,id:77,status_label:'已预约'});await first;
    assert.equal(p.data.done.id,77);assert.equal(p.data.busy,false);
    await p.submit();assert.equal(calls.length,1);
    p.result();assert.equal(navigation.at(-1).url,'/pages/visit/index?id=77');
  });
  await test('a saved confirmation opens the exact receipt and never queries again',async()=>{
    const {p,state,calls}=page('confirm',{request:async route=>{
      assert.equal(route,'booking/confirm/');
      return {...slot,id:88,status_label:'已预约'};
    }});
    state.globalData.review={kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed'}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();
    assert.equal(p.data.done.id,88);assert.equal(p.data.uncertain,false);assert.equal(p.data.canQuery,false);
    assert.equal(calls.length,1);assert(calls.every(c=>c.route!=='booking/result/'));
  });
  await test('a successful response without a receipt number keeps the appointment unconfirmed',async()=>{
    const {p,state,calls,navigation}=page('confirm',{request:async route=>{
      if(route==='booking/confirm/')return {status_label:'已预约'};
      assert.equal(route,'booking/result/');
      return {state:'SAVED',visit_id:103};
    }});
    state.globalData.review={kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed'}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();
    assert.equal(p.data.done,null);assert.equal(p.data.canQuery,true);
    await p.submit();await p.queryResult();
    assert.deepEqual(calls.map(call=>call.route),['booking/confirm/','booking/result/']);
    assert.equal(navigation.at(-1).url,'/pages/visit/index?id=103');
  });
  await test('an explicit occupied slot clears the proposal and keeps the original appointment readable',async()=>{
    const error=Object.assign(Error('所选时段已占用，请重新选择。'),{status:409,code:'BUSINESS_CONFLICT',requestId:'REJECT-1'});
    const {p,state,calls,navigation}=page('confirm',{request:async()=>{throw error;}});
    state.globalData.review={kind:'reschedule',path:'visits/9/reschedule/confirm/',selection:{service:2,clinic:1,dentist:1,day:'2026-11-23'},
      preview:{proposal_token:'signed',clinic:'门店',dentist:'医师',start:slot.start,end:slot.end,original:{id:9,clinic:'原门店',startLabel:'2026-10-23 09:00'}}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();
    assert.equal(p.data.review,null);assert.equal(p.data.checked,false);assert.equal(p.data.conflict,true);
    assert.equal(p.data.conflictOriginal.id,9);assert.match(p.data.conflictMessage,/占用/);
    await p.submit();assert.equal(calls.length,1);
    p.openOriginal();assert.equal(navigation.at(-1).url,'/pages/visit/index?id=9');
    p.backToSelection();assert.equal(navigation.at(-1).url,'/pages/booking/index?clinic=1&service=2&dentist=1&day=2026-11-23');
  });
  await test('a request that never reaches the server recovers through a read-only lookup',async()=>{
    let confirms=0;const reads=[];
    const {p,state}=page('confirm',{request:async(route,method,data)=>{
      if(route==='booking/confirm/'){confirms++;throw Object.assign(Error('连接中断，结果尚未确认。'),{code:'NETWORK_UNCONFIRMED'});}
      assert.equal(route,'booking/result/');reads.push(plain(data));return {state:'UNCONFIRMED'};
    }});
    state.globalData.review={kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed-attempt'}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();
    assert.equal(p.data.uncertain,true);assert.equal(p.data.canQuery,true);assert.equal(p.data.resultToken,'signed-attempt');
    await p.queryResult();
    assert.deepEqual(reads,[{kind:'booking',proposal_token:'signed-attempt'}]);
    assert.match(p.data.queryMessage,/暂未查到/);assert.equal(confirms,1);
  });
  await test('a committed confirmation whose response was lost returns its exact visit',async()=>{
    let confirms=0;
    const {p,state,navigation}=page('confirm',{request:async(route,method,data)=>{
      if(route==='visits/9/reschedule/confirm/'){confirms++;throw Object.assign(Error('连接中断，结果尚未确认。'),{code:'NETWORK_UNCONFIRMED'});}
      assert.equal(route,'booking/result/');assert.deepEqual(plain(data),{kind:'reschedule',proposal_token:'signed-reschedule'});
      return {state:'SAVED',visit_id:91};
    }});
    state.globalData.review={kind:'reschedule',path:'visits/9/reschedule/confirm/',preview:{proposal_token:'signed-reschedule'}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();await p.queryResult();
    assert.equal(confirms,1);assert.equal(navigation.at(-1).method,'redirectTo');
    assert.equal(navigation.at(-1).url,'/pages/visit/index?id=91');assert.equal(p.data.canQuery,false);
  });
  await test('a changed patient or workspace cannot query another attempt',async()=>{
    let reads=0;
    const {p,state,session}=page('confirm',{session:{subject_key:'self',workspace_id:'ctx',subject_revision:2},request:async(route)=>{
      if(route==='booking/confirm/')throw Object.assign(Error('连接中断，结果尚未确认。'),{code:'NETWORK_UNCONFIRMED'});
      reads++;return {state:'SAVED',visit_id:5};
    }});
    state.globalData.review={subjectKey:'self',workspaceKey:'ctx',subjectRevision:2,kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed'}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();
    session.subject_key='grant:2';session.subject_revision=3;
    await p.queryResult();
    assert.equal(reads,0);assert.equal(p.data.subjectInvalid,true);assert.equal(p.data.canQuery,false);
  });
  await test('a connection failure after a patient switch keeps the original scope',async()=>{
    let rejectConfirmation;
    const response=new Promise((_resolve,reject)=>{rejectConfirmation=reject;});
    const {p,state,calls,session}=page('confirm',{
      session:{subject_key:'self',workspace_id:'ctx',subject_revision:2},request:()=>response
    });
    state.globalData.review={subjectKey:'self',workspaceKey:'ctx',subjectRevision:2,kind:'booking',
      path:'booking/confirm/',preview:{proposal_token:'signed'}};
    p.onLoad();p.checked({detail:{value:['yes']}});
    const submit=p.submit();
    session.subject_key='grant:2';session.subject_revision=3;
    rejectConfirmation(Object.assign(Error('连接中断'),{code:'NETWORK_UNCONFIRMED'}));
    await submit;await p.queryResult();
    assert.deepEqual(calls.map(call=>call.route),['booking/confirm/']);
    assert.equal(p.data.subjectInvalid,true);assert.equal(p.data.resultToken,'');
  });
  await test('an expired receipt stops further lookups instead of resubmitting',async()=>{
    let reads=0;
    const {p,state}=page('confirm',{request:async(route)=>{
      if(route==='booking/confirm/')throw Object.assign(Error('连接中断，结果尚未确认。'),{code:'NETWORK_UNCONFIRMED'});
      reads++;throw Object.assign(Error('确认内容无效或已过期，请重新预览。'),{status:409,code:'BUSINESS_CONFLICT'});
    }});
    state.globalData.review={kind:'booking',path:'booking/confirm/',preview:{proposal_token:'signed'}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();await p.queryResult();
    assert.equal(reads,1);assert.equal(p.data.canQuery,false);assert.equal(p.data.resultToken,'');
    assert.match(p.data.queryMessage,/已失效/);
  });
  await test('cancellation and waitlist outcomes go to their own record, not the booking lookup',async()=>{
    const {p,state,navigation}=page('confirm',{request:async()=>{throw Object.assign(Error('连接中断，结果尚未确认。'),{code:'NETWORK_UNCONFIRMED'});}});
    state.globalData.review={kind:'cancel',path:'visits/9/cancel/confirm/',preview:{proposal_token:'cancel-token',original:{id:9,clinic:'门店'}}};
    p.onLoad();p.checked({detail:{value:['yes']}});await p.submit();
    assert.equal(p.data.otherUnconfirmed,true);assert.equal(p.data.uncertain,false);assert.equal(p.data.canQuery,false);
    assert.equal(p.data.recordUrl,'/pages/visit/index?id=9');
    p.openRecord();assert.equal(navigation.at(-1).url,'/pages/visit/index?id=9');
  });
  return {passed:true,cases:cases.length,case_names:cases,scope:'actual Page handlers with mocked API; not Django/PostgreSQL, official compilation or WeChat runtime'};
}
module.exports={verify,page};
if(require.main===module)verify().then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error.stack);process.exitCode=1;});
