const api=require('../../utils/api');
const {showError}=require('../../utils/format');
Page({data:{clinics:[],error:'',environmentLabel:''},async onLoad(){ api.showSubject(this);try{const session=await api.bootstrap();api.showSubject(this);this.setData({environmentLabel:session.environment_label||''});if(session.authenticated)this.setData({clinics:(await api.request('catalogue/')).clinics});}catch(e){showError(this,e);}}});
