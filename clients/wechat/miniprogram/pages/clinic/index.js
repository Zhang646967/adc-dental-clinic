const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const config=require('../../config');
const {positive}=require('../../utils/booking-intent');
const {showError}=require('../../utils/format');
Page({
  data:{clinic:null,busy:false,error:''},
  onLoad(query){this.id=query.id;},
  async onShow(){await this.load();},
  async load(){if(this.data.busy)return;this.setData({busy:true,error:'',clinic:null});
    try{if(!positive(this.id))throw Error('门店链接无效，请返回门店列表。');
      const clinic=await api.request(`discovery/clinics/${this.id}/`);
      clinic.images=clinic.images.map(i=>({...i,url:config.apiBase+i.url}));
      clinic.team=clinic.team.map(d=>({...d,portrait:d.images.length?config.apiBase+d.images[0].url:''}));
      this.setData({clinic,busy:false});
    }catch(e){showError(this,e);}},
  photos(){if(this.data.clinic)wx.previewImage({urls:this.data.clinic.images.map(i=>i.url)});},
  doctor(e){navigation.navigateTo({url:`/pages/dentist/index?id=${e.currentTarget.dataset.id}&clinic=${this.id}`});},
  service(e){navigation.navigateTo({url:'/pages/service/index?id='+e.currentTarget.dataset.id});},
  call(){const c=this.data.clinic;if(!c||c.synthetic)return;wx.makePhoneCall({phoneNumber:c.phone});},
  doctors(){navigation.navigateTo({url:'/pages/dentists/index?clinic='+this.id});}
});
