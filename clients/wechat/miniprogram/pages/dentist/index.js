const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const config=require('../../config');
const intent=require('../../utils/booking-intent');
const {showError}=require('../../utils/format');
Page({
  data:{doctor:null,busy:false,error:''},
  onLoad(query){this.id=query.id;this.clinic=intent.positive(query.clinic)?Number(query.clinic):'';},
  async onShow(){await this.load();},
  async load(){if(this.data.busy)return;this.setData({busy:true,error:'',doctor:null});
    try{if(!intent.positive(this.id))throw Error('医师链接无效。');
      const doctor=await api.request(`discovery/dentists/${this.id}/`,'GET',{clinic:this.clinic});
      doctor.portrait=doctor.images.length?config.apiBase+doctor.images[0].url:'';
      this.setData({doctor,busy:false});
    }catch(e){showError(this,e);}},
  clinic(e){navigation.navigateTo({url:'/pages/clinic/index?id='+e.currentTarget.dataset.id});},
  async book(e){if(this.data.busy||!this.data.doctor)return;
    const branch=this.data.doctor.clinics.find(c=>c.id===Number(e.currentTarget.dataset.clinic));
    const service=branch&&branch.services.find(s=>s.id===Number(e.currentTarget.dataset.service));if(!service)return;
    this.setData({busy:true,error:''});
    try{const session=await api.bootstrap();
      if(session.read_only)throw Error('当前实例仅供查看。');
      const day=branch.shifts.length?branch.shifts[0].day:null;
      intent.remember(getApp(),service.id,branch.id,this.data.doctor.id,day,service.category);
      const route=(service.category==='CHILDREN'&&!session.guardian&&session.account_authenticated)?'/pages/patients/index':(!session.authenticated||session.subject_required)?(!session.account_authenticated?'/pages/login/index':session.subject_required?'/pages/patients/index':'/pages/account/index'):
        `/pages/booking/index?clinic=${branch.id}&service=${service.id}&dentist=${this.data.doctor.id}${day?'&day='+day:''}`;
      this.setData({busy:false});navigation.navigateTo({url:route});
    }catch(e){showError(this,e);}}
});
