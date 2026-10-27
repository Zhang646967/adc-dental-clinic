const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {dateTime,showError}=require('../../utils/format');
Page({
 data:{rows:[],page:1,pages:1,busy:false,error:'',preview:null,checked:false,done:'',readOnly:false},
 async onShow(){
  this.setData({rows:[],preview:null,checked:false,done:'',error:'',busy:true});api.showSubject(this);
  try{
   const s=await api.bootstrap();api.showSubject(this);
   if(!s.authenticated){navigation.reLaunch({url:'/pages/login/index'});return;}
   if(s.subject_required){navigation.reLaunch({url:'/pages/patients/index'});return;}
   if(s.delegated){this.setData({busy:false,error:'代约范围不包含临床转诊披露，请切换到本人。'});return;}
   this.setData({readOnly:s.read_only});await this.load();
  }catch(e){showError(this,e);}
 },
 async load(){
  this.setData({busy:true,error:''});
  try{const d=await api.request('referrals/','GET',{page:this.data.page});
   this.setData({rows:d.rows.map(r=>Object.assign({},r,{untilLabel:dateTime(r.valid_until)})),page:d.page,pages:d.pages,busy:false});
  }catch(e){this.setData({rows:[]});showError(this,e);}
 },
 async stop(e){
  if(this.data.busy||this.data.readOnly)return;this.setData({busy:true,error:'',done:'',preview:null,checked:false});
  try{const p=await api.request(`referrals/${e.currentTarget.dataset.id}/stop/preview/`,'POST');
   const s=api.sessionInfo();this.setData({preview:p,subject:s.subject_key,revision:s.subject_revision,busy:false});
  }catch(e){showError(this,e);}
 },
 checked(e){this.setData({checked:e.detail.value.includes('yes')});},
 async confirm(){
  if(this.data.busy||!this.data.preview||!this.data.checked||this.data.readOnly)return;
  const s=api.sessionInfo();
  if(s.subject_key!==this.data.subject||s.subject_revision!==this.data.revision){this.setData({preview:null,checked:false,error:'就诊人已变化，请重新核对。'});return;}
  this.setData({busy:true,error:''});
  try{const p=this.data.preview;const r=await api.request(`referrals/${p.referral.id}/stop/confirm/`,'POST',{proposal_token:p.proposal_token,confirmed:'on'});
   this.setData({preview:null,checked:false,done:r.referral.status_label,busy:false});await this.load();
  }catch(e){showError(this,e);}
 },
 cancel(){if(!this.data.busy)this.setData({preview:null,checked:false});},
 turn(e){if(this.data.busy)return;this.setData({page:this.data.page+Number(e.currentTarget.dataset.step),preview:null,checked:false});this.load();}
});
