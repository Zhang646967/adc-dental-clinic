const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
const {selectedCatalogue}=require('../../utils/service-selection');
Page({
  data:{clinics:[], services:[], doctors:[], allServices:[], clinicIndex:0, serviceIndex:0, doctorIndex:0,
    day:'', firstDay:'', lastDay:'', rows:[], error:'', busy:false, searched:false, source:null, reason:'',patientRequest:'',selectedService:null},
  async onLoad(query) { api.showSubject(this);
    try {
      const session = await api.bootstrap();api.showSubject(this);
      if (!session.authenticated) { navigation.reLaunch({url:'/pages/login/index'}); return; }
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
      if(!source)await this.refreshDay(query.day);
    } catch(e) { showError(this,e); }
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
    }catch(e){this.setData({day:''});showError(this,e);}
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
  async search() {
    if (this.data.busy) return;
    this.setData({rows:[],searched:false,note:''});
    const c=this.data.clinics[this.data.clinicIndex], s=this.data.services[this.data.serviceIndex], d=this.data.doctors[this.data.doctorIndex];
    if (!c || !s) {this.setData({error:'当前服务尚未配置，请联系前台。'});return;}
    if(!this.data.day){this.setData({error:'请先选择有出诊的日期，或登记候补。'});return;}
    this.setData({busy:true,error:'',rows:[],searched:false,note:''});
    try {
      const path=this.data.source ? `visits/${this.data.source.id}/reschedule/candidates/` : 'candidates/';
      const data=await api.request(path,'GET',{clinic:c.id,service:s.id,dentist:d.id,day:this.data.day});
      this.setData({rows:data.rows.map(arrangement),busy:false,searched:true,note:data.limited?'本次候选达到查询上限，可缩小日期或联系前台。':data.message||''});
    } catch(e) { showError(this,e); }
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
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,kind:source?'reschedule':'booking',preview:arrangement(preview),path:source?`visits/${source.id}/reschedule/confirm/`:'booking/confirm/'};
      navigation.navigateTo({url:'/pages/confirm/index'}); this.setData({busy:false});
    } catch(e) { showError(this,e); }
  }
});
