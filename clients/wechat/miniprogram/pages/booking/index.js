const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
const intent=require('../../utils/booking-intent');
const {selectedCatalogue}=require('../../utils/service-selection');

function bjDay(iso){
  if(!iso)return '';
  const t=Date.parse(iso);
  return isNaN(t)?'':new Date(t+8*3600000).toISOString().slice(0,10);
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
    day:'', firstDay:'', lastDay:'', rows:[], groups:[], mode:'date', searchFailed:false, emptyReason:'', error:'', busy:false, searched:false, source:null, reason:'',patientRequest:'',selectedService:null},
  onLoad(query) { this.query=query;return this.load(); },
  async load() {
    const query=this.query;
    if(this.data.busy)return;
    this.setData({busy:true,error:'',requestId:'',ready:false});
    api.showSubject(this);
    try {
      const session = await api.bootstrap();api.showSubject(this);
      if (!session.authenticated || session.subject_required) {
        if(!query.visit && intent.positive(query.service) && intent.positive(query.clinic))
          intent.remember(getApp(),query.service,query.clinic,query.dentist,query.day);
        const url=session.subject_required?'/pages/patients/index':session.account_authenticated?'/pages/account/index':'/pages/login/index';
        navigation.reLaunch({url});return;
      }
      if(session.medical&&!session.can_book){navigation.reLaunch({url:'/pages/medical-authorizations/index'});return;}
      if (session.read_only) throw new Error('当前实例仅供查看，暂不办理预约变更。');
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
    } catch(e) { showError(this,e,{separateRequestId:true}); }
    finally { this.setData({busy:false}); }
  },
  subjects(){
    if(this.data.busy)return;
    const service=this.data.selectedService,doctor=this.data.doctors[this.data.doctorIndex];
    if(!this.data.source&&service)intent.remember(getApp(),service.id,service.clinic,doctor.id,this.data.day,service.category);
    navigation.reLaunch({url:'/pages/patients/index'});
  },
  rebuild(selectedId=null) {
    const c=this.data.clinics[this.data.clinicIndex];
    const services=c ? this.data.allServices.filter(s=>s.clinic===c.id && (!this.data.source || s.id===this.data.source.service_id)) : [];
    const serviceIndex=selectedId===null ? 0 : Math.max(0,services.findIndex(s=>s.id===selectedId));
    this.setData({services,serviceIndex,doctorIndex:0,rows:[],searched:false,note:''});this.doctors();
  },
  doctors() {
    const s=this.data.services[this.data.serviceIndex];
    this.setData({selectedService:s||null,doctors:[{id:'',name:'任何可接收的医师'}].concat(s ? s.dentists : []), doctorIndex:0, rows:[], searched:false,note:''});
  },
  async refreshDay(selectedDay=null){
    if(this.data.source)return;
    const service=this.data.services[this.data.serviceIndex],doctor=this.data.doctors[this.data.doctorIndex];
    if(!service)return;
    this.setData({busy:true,error:'',rows:[],searched:false});
    try{
      const info=await api.request(`services/${service.id}/`,'GET',{dentist:doctor.id});
      const day=selectedDay||info.default_day||'';
      if(day&&(day<this.data.firstDay||day>this.data.lastDay))throw Error('所选日期已超出预约范围，请重新选择。');
      this.setData({day,note:info.default_day?'':'近期暂无已发布出诊，可查看其他医师或登记候补。',busy:false});
    }catch(e){this.setData({day:''});showError(this,e,{separateRequestId:true});}
  },
  pickClinic(e) { if(this.data.busy)return;this.setData({clinicIndex:Number(e.detail.value),error:''});this.rebuild();return this.refreshDay(); },
  pickService(e) { if(this.data.busy)return;this.setData({serviceIndex:Number(e.detail.value),error:''});this.doctors();return this.refreshDay(); },
  pickDoctor(e) { if(this.data.busy)return;this.setData({doctorIndex:Number(e.detail.value),rows:[],searched:false,note:''});return this.refreshDay(); },
  pickDay(e) { if(this.data.busy)return;this.setData({day:e.detail.value,rows:[],searched:false,note:''}); },
  reason(e) { this.setData({reason:e.detail.value}); },
  patientRequest(e){this.setData({patientRequest:e.detail.value});},
  waitlist() {
    const c=this.data.clinics[this.data.clinicIndex],s=this.data.services[this.data.serviceIndex];
    if(this.data.source || !c || !s)return;
    const d=this.data.doctors[this.data.doctorIndex];
    navigation.navigateTo({url:`/pages/waitjoin/index?clinic=${c?c.id:''}&service=${s?s.id:''}&day=${this.data.day}&dentist=${d?d.id:''}`});
  },
  setMode(e) {
    if(this.data.busy)return;
    const mode=e.currentTarget.dataset.mode==='dentist'?'dentist':'date';
    if(mode===this.data.mode)return;
    // Keep clinic, service, dentist and date; only the query shape changes.
    this.setData({mode,rows:[],groups:[],searched:false,searchFailed:false,note:'',emptyReason:'',error:''});
    return this.search();
  },
  nextDay() {
    if(this.data.busy)return;
    const first=this.data.firstDay,last=this.data.lastDay;
    const base=this.data.day||first||'2026-01-01';
    let next=new Date(Date.parse(base+'T00:00:00Z')+86400000).toISOString().slice(0,10);
    if(last&&next>last)next=first||next;
    if(first&&next<first)next=first;
    this.setData({mode:'date',day:next});
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
    this.setData({rows:[],groups:[],searched:false,note:'',searchFailed:false,emptyReason:''});
    const c=this.data.clinics[this.data.clinicIndex], s=this.data.services[this.data.serviceIndex], d=this.data.doctors[this.data.doctorIndex];
    if (!c || !s) {this.setData({error:'当前服务尚未配置，请联系前台。'});return;}
    if(mode==='date'&&!this.data.day){this.setData({error:'请先选择有出诊的日期，或登记候补。'});return;}
    this.setData({busy:true,error:'',rows:[],groups:[],searched:false,note:'',searchFailed:false});
    try {
      const path=this.data.source ? `visits/${this.data.source.id}/reschedule/candidates/` : 'candidates/';
      const params={clinic:c.id,service:s.id,dentist:d.id};
      if(mode==='date')params.day=this.data.day;
      const data=await api.request(path,'GET',params);
      const rows=data.rows.map(arrangement);
      const status=data.status||'';
      this.setData({rows,groups:mode==='dentist'?groupByDentist(rows):[],busy:false,searched:true,
        note:data.limited?'本次候选达到查询上限，可缩小日期或联系前台。':data.message||'',
        availabilityTitle:status==='NO_SCHEDULE'?'当天暂无出诊':'当天暂无可用时段',
        emptyReason:rows.length?'':status==='NO_SCHEDULE'?'当天没有已发布出诊，可换日期或换医师。':status==='NO_COMBINATION'?'有出诊但没有符合该服务与医师组合的号源，可换医师或登记候补。':'本次没有可约时段，可换日期、换医师或登记候补。'});
    } catch(e) {
      this.setData({busy:false,searched:false,searchFailed:true,rows:[],groups:[]});
      showError(this,e,{separateRequestId:true});
    }
  },
  async choose(e) {
    if (this.data.busy) return;
    const row=this.data.rows[e.currentTarget.dataset.index], source=this.data.source;
    if(!row)return;
    if (source && !this.data.reason.trim()) {this.setData({error:'请先填写改期原因，无需填写病情或证件资料。'});return;}
    this.setData({busy:true,error:''});
    try {
      const path=source ? `visits/${source.id}/reschedule/preview/` : 'booking/preview/';
      const payload=source ? {action:'preview',slot_id:row.slot,start:row.start,expected_version:source.version,reason:this.data.reason} : {slot:row.slot,start:row.start,service:row.service||'',patient_request:this.data.patientRequest};
      const preview=await api.request(path,'POST',payload);
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,kind:source?'reschedule':'booking',selection:source?null:{service:row.service||this.data.selectedService.id,clinic:this.data.selectedService.clinic,dentist:this.data.doctors[this.data.doctorIndex].id,day:this.data.mode==='dentist'?bjDay(row.start):this.data.day,category:this.data.selectedService.category},preview:arrangement(preview),path:source?`visits/${source.id}/reschedule/confirm/`:'booking/confirm/'};
      navigation.navigateTo({url:'/pages/confirm/index'}); this.setData({busy:false});
    } catch(e) { showError(this,e,{separateRequestId:true}); }
  }
});
