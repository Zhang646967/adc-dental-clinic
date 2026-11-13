const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
const intent=require('../../utils/booking-intent');
const {selectedCatalogue}=require('../../utils/service-selection');
const {buildFollowup}=require('../../utils/report-notices');
const {staleSubject}=require('../../utils/subject-state');

/* Follow-up booking is bound to the exact report version that produced the
   decision. The three parameters must arrive together; anything else returns
   to the original visit instead of opening an unbound flow. */
function readFollowupQuery(query){
  const keys=['followup_visit','followup_examination','followup_revision'];
  const present=keys.filter(k=>query&&query[k]!==undefined&&query[k]!=='');
  if(!present.length)return null;
  // Keep a usable original visit even when the triple is incomplete, so the
  // fallback can return the patient to the record they came from.
  const visit=intent.positive(query.followup_visit)?Number(query.followup_visit):null;
  if(present.length!==keys.length||!keys.every(k=>intent.positive(query[k])))return {invalid:true,visit};
  return {visit,examination:Number(query.followup_examination),revision:Number(query.followup_revision)};
}

/* By-doctor mode groups the same candidate read on dentist_id and surfaces the
   earliest available slot of this query for each dentist. The flat rows stay
   intact so the existing preview handler can still select any slot by index. */
function groupByDentist(rows){
  const map=new Map();
  rows.forEach((r,index)=>{
    const key=String(r.dentist_id||r.dentist||'');
    if(!map.has(key))map.set(key,{id:key,name:r.dentist||'可接收的医师',earliest:null,rows:[],preview:[],expanded:false,count:0,earliestLabel:''});
    const g=map.get(key);
    g.rows.push(Object.assign({},r,{index}));
    if(!g.earliest||Date.parse(r.start)<Date.parse(g.earliest.start))g.earliest=r;
  });
  const groups=Array.from(map.values()).map(g=>{
    g.count=g.rows.length;
    g.earliestLabel=g.earliest?g.earliest.startLabel:'';
    g.preview=g.rows.slice(0,3);
    return g;
  });
  groups.sort((a,b)=>Date.parse(a.earliest.start)-Date.parse(b.earliest.start));
  return groups;
}
Page({
  data:{clinics:[], services:[], doctors:[], allServices:[], clinicIndex:0, serviceIndex:0, doctorIndex:0,
    day:'', firstDay:'', lastDay:'', rows:[], groups:[], mode:'date', searchFailed:false, emptyReason:'', error:'', busy:false, searched:false, source:null, reason:'',patientRequest:'',selectedService:null,
    followup:false, followupWindow:'', followupService:'', followupBlocked:false, visitId:null},
  onLoad(query) { this.query=query;this.followup=readFollowupQuery(query);this.generation=0;return this.load(); },
  onShow(){
    if(this.followup&&this.wasHidden){this.wasHidden=false;return this.load();}
  },
  onHide(){
    if(!this.followup)return;
    this.wasHidden=true;
    this.generation++;
    this.clearResults({ready:false,busy:false,patientName:'',patientCapacity:'',patientDelegated:false,patientRequest:''});
  },
  onUnload(){this.generation++;},
  async load() {
    const query=this.query;
    if(this.data.busy)return;
    const generation=++this.generation;
    this.setData({busy:true,error:'',requestId:'',ready:false});
    api.showSubject(this);
    try {
      const session = await api.bootstrap();
      if(generation!==this.generation)return;
      api.showSubject(this);
      if (!session.authenticated || session.subject_required) {
        if(!query.visit && intent.positive(query.service) && intent.positive(query.clinic))
          intent.remember(getApp(),query.service,query.clinic,query.dentist,query.day);
        const url=session.subject_required?'/pages/patients/index':session.account_authenticated?'/pages/account/index':'/pages/login/index';
        navigation.reLaunch({url});return;
      }
      if(session.medical&&!session.can_book){navigation.reLaunch({url:'/pages/medical-authorizations/index'});return;}
      if (session.read_only) throw new Error('当前实例仅供查看，暂不办理预约变更。');
      if(this.followup)return await this.loadFollowup(session,generation);
      let source = query.visit ? arrangement(await api.request(`visits/${query.visit}/`)) : null;
      if(source&&!source.reschedule_service)throw Error('本次预约暂不可自助改期，请联系原门店前台。');
      const selection=source ? {clinics:[{id:source.clinic_id,name:source.clinic}],allServices:[source.reschedule_service],clinicIndex:0,selectedId:source.service_id} : selectedCatalogue(await api.request('catalogue/'),query);
      this.setData({...selection,source,day:query.day||(source&&source.start?new Date(Date.parse(source.start)+8*3600000).toISOString().slice(0,10):session.today),firstDay:session.today,lastDay:session.last_day});
      this.rebuild(selection.selectedId);
      if(!source&&query.dentist){
        const index=this.data.doctors.findIndex(d=>String(d.id)===String(query.dentist));
        if(index<1)throw Error('所选医师接诊安排已变化，请重新核对医师。');
        this.setData({doctorIndex:index});
      }
      this.setData({ready:true});
      if(!source)await this.refreshDay(query.day);
    } catch(e) {
      if(generation!==this.generation)return;
      if(this.followup)this.followupError(e);
      else showError(this,e,{separateRequestId:true});
    }
    finally { if(generation===this.generation)this.setData({busy:false}); }
  },
  // A report follow-up fixes the clinic, service and recommended window. The
  // patient only chooses a date, dentist and slot inside that window.
  async loadFollowup(session,generation){
    if(this.followup.invalid){
      this.setData({busy:false,followupBlocked:true,visitId:this.followup.visit||null,error:'复诊链接不完整，请从原报告重新进入。'});
      return;
    }
    const detail=await api.request(`visits/${this.followup.visit}/examinations/${this.followup.examination}/`,'GET',{revision:this.followup.revision});
    if(generation!==this.generation)return;
    const followup=buildFollowup(detail.followup,{visitId:this.followup.visit,examinationId:this.followup.examination,revision:detail.revision});
    if(!followup||!followup.canBook){
      this.setData({busy:false,followupBlocked:true,visitId:this.followup.visit,
        error:(followup&&followup.message)||'当前报告暂不支持自助预约复诊，请联系原门店或返回原就诊核对。'});
      return;
    }
    const catalogue=await api.request('catalogue/');
    if(generation!==this.generation)return;
    const service=(catalogue.services||[]).find(s=>String(s.id)===String(followup.serviceId));
    const clinic=(catalogue.clinics||[]).find(c=>String(c.id)===String(followup.clinicId));
    if(!service||!clinic){
      this.setData({busy:false,followupBlocked:true,visitId:this.followup.visit,
        error:'复诊服务暂不可用，请联系原门店核对。'});
      return;
    }
    // The picker only accepts the recommended window intersected with the
    // current self-service range; the server still decides the real slots.
    const firstDay=followup.firstDay&&followup.firstDay>session.today?followup.firstDay:session.today;
    const lastDay=followup.lastDay&&followup.lastDay<session.last_day?followup.lastDay:session.last_day;
    if(!firstDay||!lastDay||firstDay>lastDay){
      this.setData({busy:false,followupBlocked:true,visitId:this.followup.visit,
        followupWindow:followup.windowLabel,error:'建议复诊日期已超出可预约范围，请联系原门店安排。'});
      return;
    }
    const day=this.data.day>=firstDay&&this.data.day<=lastDay?this.data.day:firstDay;
    const doctor=this.data.doctors[this.data.doctorIndex];
    this.setData({followup:true,followupWindow:followup.windowLabel,followupService:followup.service,visitId:this.followup.visit,
      clinics:[{id:clinic.id,name:clinic.name||followup.clinic}],allServices:[service],clinicIndex:0,
      day,firstDay,lastDay,ready:true,busy:false,followupBlocked:false});
    this.rebuild(service.id);
    if(doctor&&doctor.id){
      const index=this.data.doctors.findIndex(row=>String(row.id)===String(doctor.id));
      if(index>0)this.setData({doctorIndex:index});
    }
    await this.search();
  },
  subjects(){
    if(this.data.busy)return;
    const service=this.data.selectedService,doctor=this.data.doctors[this.data.doctorIndex];
    if(!this.data.source&&!this.data.followup&&service)intent.remember(getApp(),service.id,service.clinic,doctor.id,this.data.day,service.category);
    navigation.reLaunch({url:'/pages/patients/index'});
  },
  rebuild(selectedId=null) {
    const c=this.data.clinics[this.data.clinicIndex];
    const services=c ? this.data.allServices.filter(s=>s.clinic===c.id && (!this.data.source || s.id===this.data.source.service_id)) : [];
    const serviceIndex=selectedId===null ? 0 : Math.max(0,services.findIndex(s=>s.id===selectedId));
    this.setData({services,serviceIndex});this.doctors();
  },
  doctors() {
    const s=this.data.services[this.data.serviceIndex];
    this.clearResults({selectedService:s||null,doctors:[{id:'',name:'任何可接收的医师'}].concat(s ? s.dentists : []),doctorIndex:0});
  },
  clearResults(updates={}) {
    this.setData({rows:[],groups:[],searched:false,searchFailed:false,note:'',emptyReason:'',error:'',requestId:'',...updates});
  },
  async refreshDay(selectedDay=null){
    if(this.data.source)return;
    const service=this.data.services[this.data.serviceIndex],doctor=this.data.doctors[this.data.doctorIndex];
    if(!service)return;
    this.setData({busy:true});
    try{
      const info=await api.request(`services/${service.id}/`,'GET',{dentist:doctor.id});
      const day=selectedDay===null?(info.default_day||''):selectedDay;
      if(day&&(day<this.data.firstDay||day>this.data.lastDay))throw Error('所选日期已超出预约范围，请重新选择。');
      this.setData({day,note:info.default_day?'':'近期暂无已发布出诊，可查看其他医师或登记候补。',busy:false});
    }catch(e){this.setData({day:''});showError(this,e,{separateRequestId:true});}
  },
  pickClinic(e) { if(this.data.busy)return;this.setData({clinicIndex:Number(e.detail.value),error:''});this.rebuild();return this.refreshDay(); },
  pickService(e) { if(this.data.busy)return;this.setData({serviceIndex:Number(e.detail.value),error:''});this.doctors();return this.refreshDay(); },
  pickDoctor(e) { if(this.data.busy)return;this.clearResults({doctorIndex:Number(e.detail.value)});return this.refreshDay(this.data.day); },
  pickDay(e) { if(this.data.busy)return;this.clearResults({day:e.detail.value}); },
  reason(e) { this.setData({reason:e.detail.value}); },
  patientRequest(e){this.setData({patientRequest:e.detail.value});},
  waitlist() {
    const c=this.data.clinics[this.data.clinicIndex],s=this.data.services[this.data.serviceIndex];
    if(this.data.source || this.data.followup || !c || !s)return;
    const d=this.data.doctors[this.data.doctorIndex];
    navigation.navigateTo({url:`/pages/waitjoin/index?clinic=${c?c.id:''}&service=${s?s.id:''}&day=${this.data.day}&dentist=${d?d.id:''}`});
  },
  setMode(e) {
    if(this.data.busy)return;
    const mode=e.currentTarget.dataset.mode==='dentist'?'dentist':'date';
    if(mode===this.data.mode)return;
    this.setData({mode});
    return this.search();
  },
  future() {
    if(this.data.busy||this.data.source)return;
    this.setData({day:''});
    return this.search();
  },
  nextDay() {
    if(this.data.busy)return;
    const first=this.data.firstDay,last=this.data.lastDay;
    const day=this.data.day;
    let next=day?new Date(Date.parse(day+'T00:00:00Z')+86400000).toISOString().slice(0,10):first;
    if(last&&next>last)next=first||next;
    if(first&&next<first)next=first;
    this.setData({day:next});
    return this.search();
  },
  nextDoctor() {
    if(this.data.busy||this.data.doctors.length<2)return;
    this.setData({doctorIndex:(this.data.doctorIndex+1)%this.data.doctors.length});
    return this.search();
  },
  expandGroup(e) {
    const i=Number(e.currentTarget.dataset.index);
    if(isNaN(i))return;
    this.setData({['groups['+i+'].expanded']:true});
  },
  async search() {
    if (this.data.busy) return;
    const mode=this.data.mode||'date';
    this.clearResults();
    const c=this.data.clinics[this.data.clinicIndex], s=this.data.services[this.data.serviceIndex], d=this.data.doctors[this.data.doctorIndex];
    if (!c || !s) {this.setData({error:'当前服务尚未配置，请联系前台。'});return;}
    const day=this.data.day;
    if(this.data.source&&!day){this.setData({error:'请先选择改期日期。'});return;}
    this.setData({busy:true});
    const generation=this.generation;
    try {
      const path=this.data.source ? `visits/${this.data.source.id}/reschedule/candidates/` : 'candidates/';
      const params={clinic:c.id,service:s.id,dentist:d.id};
      if(day)params.day=day;
      // Follow-up reads are checked against the report, decision and window;
      // the three parameters always travel together.
      if(this.followup)Object.assign(params,{followup_visit:this.followup.visit,followup_examination:this.followup.examination,followup_revision:this.followup.revision});
      const data=await api.request(path,'GET',params);
      if(generation!==this.generation)return;
      const rows=data.rows.map(arrangement);
      const status=data.status||'';
      const period=day?'当天':'未来14天';
      this.setData({rows,groups:mode==='dentist'?groupByDentist(rows):[],busy:false,searched:true,
        note:data.limited?data.note||'本次候选达到查询上限，可缩小日期或联系前台。':'',
        availabilityTitle:period+(status==='NO_SCHEDULE'?'暂无出诊':'暂无可用时段'),
        emptyReason:rows.length?'':data.message||(this.data.source?'可选择其他日期，原预约继续保留。':'可换日期、医师或登记候补。')});
    } catch(e) {
      if(generation!==this.generation)return;
      this.setData({busy:false,searched:false,searchFailed:true,rows:[],groups:[]});
      if(this.followup)this.followupError(e);
      else showError(this,e,{separateRequestId:true});
    }
  },
  async choose(e) {
    if (this.data.busy) return;
    const row=this.data.rows[e.currentTarget.dataset.index], source=this.data.source;
    if(!row)return;
    if (source && !this.data.reason.trim()) {this.setData({error:'请先填写改期原因，无需填写病情或证件资料。'});return;}
    this.setData({busy:true,error:''});
    const generation=this.generation;
    try {
      const path=source ? `visits/${source.id}/reschedule/preview/` : 'booking/preview/';
      const payload=source ? {action:'preview',slot_id:row.slot,start:row.start,expected_version:source.version,reason:this.data.reason} : {slot:row.slot,start:row.start,service:row.service||'',patient_request:this.data.patientRequest};
      if(this.followup)Object.assign(payload,{followup_visit:this.followup.visit,followup_examination:this.followup.examination,followup_revision:this.followup.revision});
      const preview=await api.request(path,'POST',payload);
      if(generation!==this.generation)return;
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,kind:source?'reschedule':'booking',selection:source||this.followup?null:{service:row.service||this.data.selectedService.id,clinic:this.data.selectedService.clinic,dentist:this.data.doctors[this.data.doctorIndex].id,day:this.data.day,category:this.data.selectedService.category},preview:arrangement(preview),path:source?`visits/${source.id}/reschedule/confirm/`:'booking/confirm/',followupVisit:this.followup?this.followup.visit:null};
      navigation.navigateTo({url:'/pages/confirm/index'}); this.setData({busy:false});
    } catch(e) {
      if(generation!==this.generation)return;
      if(this.followup)this.followupError(e);
      else showError(this,e,{separateRequestId:true});
    }
  },
  followupError(e){
    const state=staleSubject(e,api.sessionInfo(),{uncodedConflictIsStale:false});
    if(state.invalid){
      getApp().globalData.review=null;
      this.setData({patientName:'',patientCapacity:'',patientDelegated:false,patientRequest:'',ready:false});
    }
    this.setData({visitId:this.followup.visit,followupBlocked:true,rows:[],groups:[]});
    showError(this,e,{separateRequestId:true,stayOnPage:true});
  },
  backToVisit(){
    const id=this.data.visitId||(this.followup&&this.followup.visit)||null;
    navigation.reLaunch({url:id?`/pages/visit/index?id=${id}`:'/pages/home/index'});
  }
});
