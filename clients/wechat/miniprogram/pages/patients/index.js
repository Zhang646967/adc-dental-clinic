const api=require('../../utils/api');
const {dateTime,showError}=require('../../utils/format');
const intent=require('../../utils/booking-intent');
Page({
 data:{rows:[],busy:false,error:''},
 async onShow(){
  this.setData({busy:true,error:'',rows:[]});
  try{
   const session=await api.bootstrap();
   if(!session.authenticated){wx.reLaunch({url:'/pages/login/index'});return;}
   const d=await api.request('patients/');
   this.setData({rows:d.rows.map(r=>Object.assign({},r,{expiresLabel:r.expires?dateTime(r.expires):''})),busy:false});
  }catch(e){showError(this,e);}
 },
 async choose(e){
  if(this.data.busy)return;
  this.setData({busy:true,error:''});
  try{await api.selectSubject(e.currentTarget.dataset.key);wx.reLaunch({url:intent.destination(getApp(),api.sessionInfo())});}
  catch(e){showError(this,e);}
 }
});
