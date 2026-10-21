const api=require('../../utils/api');
const {showError}=require('../../utils/format');
Page({data:{clinics:[],error:''},async onLoad(){try{if((await api.bootstrap()).authenticated)this.setData({clinics:(await api.request('catalogue/')).clinics});}catch(e){showError(this,e);}}});
