const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
Page({
  data:{clinics:[], services:[], doctors:[], allServices:[], clinicIndex:0, serviceIndex:0, doctorIndex:0,
    day:'', firstDay:'', lastDay:'', rows:[], error:'', busy:false, searched:false, source:null, reason:''},
  async onLoad(query) {
    try {
      const session = await api.bootstrap();
      if (!session.authenticated) { wx.reLaunch({url:'/pages/login/index'}); return; }
      if (session.read_only) throw new Error('当前实例仅供查看，暂不办理预约变更。');
      const cat = await api.request('catalogue/');
      let source = query.visit ? arrangement(await api.request(`visits/${query.visit}/`)) : null;
      const clinics = source ? cat.clinics.filter(c=>c.id===source.clinic_id) : cat.clinics;
      this.setData({clinics, allServices:cat.services, resourceClinics:cat.resource_clinics, source, day:session.today, firstDay:session.today, lastDay:session.last_day});
      this.rebuild();
    } catch(e) { showError(this,e); }
  },
  rebuild() {
    const c=this.data.clinics[this.data.clinicIndex];
    const services=c ? this.data.allServices.filter(s=>s.clinic===c.id && (!this.data.source || s.id===this.data.source.service_id)) : [];
    if (c && !this.data.resourceClinics.includes(c.id)) services.push({id:'',name:'常规预约',duration:30,dentists:[]});
    this.setData({services, serviceIndex:0, doctorIndex:0, rows:[], searched:false}); this.doctors();
  },
  doctors() {
    const s=this.data.services[this.data.serviceIndex];
    this.setData({doctors:[{id:'',name:'任何可接收的医师'}].concat(s ? s.dentists : []), doctorIndex:0, rows:[], searched:false});
  },
  pickClinic(e) { this.setData({clinicIndex:Number(e.detail.value)}); this.rebuild(); },
  pickService(e) { this.setData({serviceIndex:Number(e.detail.value)}); this.doctors(); },
  pickDoctor(e) { this.setData({doctorIndex:Number(e.detail.value),rows:[],searched:false}); },
  pickDay(e) { this.setData({day:e.detail.value,rows:[],searched:false}); },
  reason(e) { this.setData({reason:e.detail.value}); },
  async search() {
    if (this.data.busy) return;
    const c=this.data.clinics[this.data.clinicIndex], s=this.data.services[this.data.serviceIndex], d=this.data.doctors[this.data.doctorIndex];
    if (!c || !s) {this.setData({error:'当前服务尚未配置，请联系前台。'});return;}
    this.setData({busy:true,error:'',rows:[]});
    try {
      const path=this.data.source ? `visits/${this.data.source.id}/reschedule/candidates/` : 'candidates/';
      const data=await api.request(path,'GET',{clinic:c.id,service:s.id,dentist:d.id,day:this.data.day});
      this.setData({rows:data.rows.map(arrangement),busy:false,searched:true,note:data.limited?'本次候选达到查询上限，可缩小日期或联系前台。':''});
    } catch(e) { showError(this,e); }
  },
  async choose(e) {
    if (this.data.busy) return;
    const row=this.data.rows[e.currentTarget.dataset.index], source=this.data.source;
    if (source && !this.data.reason.trim()) {this.setData({error:'请先填写改期原因，无需填写病情或证件资料。'});return;}
    this.setData({busy:true,error:''});
    try {
      const path=source ? `visits/${source.id}/reschedule/preview/` : 'booking/preview/';
      const payload=source ? {action:'preview',slot_id:row.slot,start:row.start,expected_version:source.version,reason:this.data.reason} : {slot:row.slot,start:row.start,service:row.service||''};
      const preview=await api.request(path,'POST',payload);
      getApp().globalData.review={kind:source?'reschedule':'booking',preview:arrangement(preview),path:source?`visits/${source.id}/reschedule/confirm/`:'booking/confirm/'};
      wx.navigateTo({url:'/pages/confirm/index'}); this.setData({busy:false});
    } catch(e) { showError(this,e); }
  }
});
