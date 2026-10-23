const api=require('../../utils/api');
const {showError}=require('../../utils/format');
Page({
  data:{service:null,busy:false,error:'',readOnly:false,environmentLabel:''},
  onLoad(query){ api.showSubject(this);this.id=query.id;},
  async onShow(){ api.showSubject(this);await this.load();},
  async load(){
    if(this.data.busy)return;
    this.setData({busy:true,error:'',service:null});
    try{
      const session=await api.bootstrap();api.showSubject(this);
      if(!session.authenticated){this.setData({busy:false});wx.reLaunch({url:'/pages/login/index'});return;}
      if(!/^[1-9][0-9]{0,17}$/.test(String(this.id)) || !Number.isSafeInteger(Number(this.id)))throw Error('服务链接无效，请返回服务目录。');
      const service=await api.request(`services/${this.id}/`);
      this.setData({service,busy:false,readOnly:session.read_only,environmentLabel:session.environment_label||''});
    }catch(e){showError(this,e);}
  },
  book(){
    const s=this.data.service;
    if(!s||!s.self_booking||this.data.readOnly||this.data.busy)return;
    wx.navigateTo({url:`/pages/booking/index?clinic=${s.clinic}&service=${s.id}`});
  }
});
