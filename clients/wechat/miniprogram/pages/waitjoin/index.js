const api=require('../../utils/api');
const {arrangement,showError}=require('../../utils/format');
const {selectedCatalogue}=require('../../utils/service-selection');
Page({
  data:{clinics:[],services:[],allServices:[],doctors:[],clinicIndex:0,serviceIndex:0,doctorIndex:0,firstDay:'',lastDay:'',startDay:'',endDay:'',startTime:'09:00',endTime:'18:00',busy:false,error:''},
  async onLoad(query){ api.showSubject(this);
    try{const session=await api.bootstrap();api.showSubject(this);if(!session.authenticated){wx.reLaunch({url:'/pages/login/index'});return;}
      if(session.read_only)throw new Error('当前实例仅供查看，暂不办理候补。');
      const selection=selectedCatalogue(await api.request('catalogue/'),query);
      const tomorrow=new Date(new Date(session.today+'T00:00:00Z').getTime()+86400000).toISOString().slice(0,10);
      const day=query.day && query.day>session.today && query.day<=session.last_day ? query.day : tomorrow;
      this.setData({...selection,firstDay:session.today,lastDay:session.last_day,startDay:day,endDay:day});
      this.rebuild(selection.selectedId);
      if(query.dentist){const index=this.data.doctors.findIndex(d=>String(d.id)===String(query.dentist));
        if(index<1)throw Error('所选医师已不适配该候补服务，请重新选择。');this.setData({doctorIndex:index});}
    }catch(e){showError(this,e);}
  },
  rebuild(selectedId=null){const c=this.data.clinics[this.data.clinicIndex];const services=c?this.data.allServices.filter(s=>s.clinic===c.id):[];
    this.setData({services,serviceIndex:selectedId===null?0:Math.max(0,services.findIndex(s=>s.id===selectedId))});this.doctors();},
  doctors(){const s=this.data.services[this.data.serviceIndex];this.setData({doctors:[{id:'',name:'不限医师'}].concat(s?s.dentists:[]),doctorIndex:0});},
  pickClinic(e){if(this.data.busy)return;this.setData({clinicIndex:Number(e.detail.value)});this.rebuild();},
  pickService(e){if(this.data.busy)return;this.setData({serviceIndex:Number(e.detail.value)});this.doctors();},
  pickDoctor(e){if(this.data.busy)return;this.setData({doctorIndex:Number(e.detail.value)});},
  field(e){if(this.data.busy)return;this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
  async preview(){
    if(this.data.busy)return;const c=this.data.clinics[this.data.clinicIndex],s=this.data.services[this.data.serviceIndex],d=this.data.doctors[this.data.doctorIndex];
    if(!c||!s){this.setData({error:'请先选择已配置的诊所和服务。'});return;}
    this.setData({busy:true,error:''});
    try{const p=await api.request('waitlist/join/preview/','POST',{clinic:c.id,service:s.id,dentist:d.id,
      earliest:`${this.data.startDay}T${this.data.startTime}:00+08:00`,latest:`${this.data.endDay}T${this.data.endTime}:00+08:00`});
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,kind:'wait_join',preview:arrangement(p),path:'waitlist/join/confirm/'};
      this.setData({busy:false});wx.navigateTo({url:'/pages/confirm/index'});
    }catch(e){showError(this,e);}
  }
});
