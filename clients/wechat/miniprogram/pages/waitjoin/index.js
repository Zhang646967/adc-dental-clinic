const api=require('../../utils/api');
const {arrangement,showError}=require('../../utils/format');
Page({
  data:{clinics:[],services:[],allServices:[],doctors:[],clinicIndex:0,serviceIndex:0,doctorIndex:0,firstDay:'',lastDay:'',startDay:'',endDay:'',startTime:'09:00',endTime:'18:00',busy:false,error:''},
  async onLoad(query){
    try{const session=await api.bootstrap();if(!session.authenticated){wx.reLaunch({url:'/pages/login/index'});return;}
      if(session.read_only)throw new Error('当前实例仅供查看，暂不办理候补。');
      const cat=await api.request('catalogue/');
      const tomorrow=new Date(new Date(session.today+'T00:00:00Z').getTime()+86400000).toISOString().slice(0,10);
      const day=query.day && query.day>session.today && query.day<=session.last_day ? query.day : tomorrow;
      this.setData({clinics:cat.clinics,allServices:cat.services,resourceClinics:cat.resource_clinics,firstDay:session.today,lastDay:session.last_day,startDay:day,endDay:day,
        clinicIndex:Math.max(0,cat.clinics.findIndex(c=>String(c.id)===query.clinic))});
      this.rebuild();const si=this.data.services.findIndex(s=>String(s.id)===query.service);if(si>=0){this.setData({serviceIndex:si});this.doctors();}
    }catch(e){showError(this,e);}
  },
  rebuild(){const c=this.data.clinics[this.data.clinicIndex];const services=c?this.data.allServices.filter(s=>s.clinic===c.id):[];
    if(c&&!this.data.resourceClinics.includes(c.id))services.push({id:'',name:'常规预约',duration:30,dentists:[]});
    this.setData({services,serviceIndex:0});this.doctors();},
  doctors(){const s=this.data.services[this.data.serviceIndex];this.setData({doctors:[{id:'',name:'不限医师'}].concat(s?s.dentists:[]),doctorIndex:0});},
  pickClinic(e){this.setData({clinicIndex:Number(e.detail.value)});this.rebuild();},
  pickService(e){this.setData({serviceIndex:Number(e.detail.value)});this.doctors();},
  pickDoctor(e){this.setData({doctorIndex:Number(e.detail.value)});},
  field(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
  async preview(){
    if(this.data.busy)return;const c=this.data.clinics[this.data.clinicIndex],s=this.data.services[this.data.serviceIndex],d=this.data.doctors[this.data.doctorIndex];
    if(!c||!s){this.setData({error:'请先选择已配置的诊所和服务。'});return;}
    this.setData({busy:true,error:''});
    try{const p=await api.request('waitlist/join/preview/','POST',{clinic:c.id,service:s.id,dentist:d.id,
      earliest:`${this.data.startDay}T${this.data.startTime}:00+08:00`,latest:`${this.data.endDay}T${this.data.endTime}:00+08:00`});
      getApp().globalData.review={kind:'wait_join',preview:arrangement(p),path:'waitlist/join/confirm/'};
      this.setData({busy:false});wx.navigateTo({url:'/pages/confirm/index'});
    }catch(e){showError(this,e);}
  }
});
