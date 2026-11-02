const api=require('../../utils/api');
const {dateTime,showError}=require('../../utils/format');
const {positive}=require('../../utils/booking-intent');
Page({
 data:{busy:false,error:'',rows:[],detail:null,options:null,preview:null,confirmed:false,purpose:'',message:'',visitIds:[],sectionIds:[],clinicIndex:0,packageIndex:0,readOnly:false},
 onLoad(q){this.id=positive(q.id)?Number(q.id):null;this.newApplication=q.new==='1';this.page=1;},
 async onShow(){await this.load();},
 async load(){
  if(this.data.busy)return;
  this.setData({busy:true,error:'',rows:[],detail:null,options:null,preview:null,confirmed:false});
  try{
   const session=await api.bootstrap();if(!session.account_authenticated){wx.navigateTo({url:'/pages/login/index'});this.setData({busy:false});return;}
   const contextKey=[session.account_name,session.workspace_id,session.subject_revision].join('|');
   if(this.contextKey!==contextKey)this.setData({purpose:'',message:'',visitIds:[],sectionIds:[],preview:null,confirmed:false});
   this.contextKey=contextKey;this.setData({readOnly:!!session.read_only});
   if(this.newApplication){await this.options();}
   else if(this.id){const d=await api.request(`record-copies/${this.id}/`);d.pickupLabel=d.pickup_until?dateTime(d.pickup_until):'';d.history=d.history.map(e=>({...e,atLabel:dateTime(e.at)}));this.setData({detail:d});}
   else{const list=await api.request('record-copies/','GET',{page:this.page});this.setData({rows:list.rows,pagination:list});}
   this.setData({busy:false});
  }catch(e){showError(this,e);}
 },
 async options(clinic){const o=await api.request('record-copies/options/','GET',clinic?{clinic}:{});o.sections=o.sections.map(s=>({...s,checked:true}));this.setData({options:o,clinicIndex:Math.max(0,o.clinics.findIndex(c=>String(c.id)===String(o.clinic))),packageIndex:0,visitIds:[],sectionIds:o.sections.map(s=>s.id)});},
 async clinic(e){if(this.data.busy)return;this.setData({busy:true,error:''});try{await this.options(this.data.options.clinics[Number(e.detail.value)].id);this.setData({busy:false});}catch(e){showError(this,e);}},
 package(e){this.setData({packageIndex:Number(e.detail.value)});},
 visits(e){const ids=e.detail.value;this.setData({visitIds:ids,'options.visits':this.data.options.visits.map(v=>({...v,checked:ids.includes(v.id)}))});},
 sections(e){const ids=e.detail.value;this.setData({sectionIds:ids,'options.sections':this.data.options.sections.map(v=>({...v,checked:ids.includes(v.id)}))});},
 input(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
 consent(e){this.setData({confirmed:e.detail.value.includes('yes')});},
 async prepare(e){
  if(this.data.busy||this.data.readOnly)return;this.setData({busy:true,error:'',preview:null,confirmed:false});
  try{
   let p;const action=e.currentTarget.dataset.action;
   if(action==='SUBMIT'){const o=this.data.options;if(!o||!o.clinics.length)throw Error('请先由门店核对本人档案与已结束的就诊。');p=await api.request('record-copies/preview/','POST',{clinic:o.clinics[this.data.clinicIndex].id,visits:this.data.visitIds.join(','),sections:this.data.sectionIds.join(','),package:o.packages[this.data.packageIndex].id,purpose:this.data.purpose});}
   else p=await api.request(`record-copies/${this.id}/preview/`,'POST',{action,message:this.data.message});
   this.setData({preview:p,busy:false});
  }catch(e){showError(this,e);}
 },
 async confirm(){
  if(this.data.busy||this.data.readOnly||!this.data.preview||!this.data.confirmed)return;this.setData({busy:true,error:''});
  try{
   const result=await api.request('record-copies/confirm/','POST',{proposal_token:this.data.preview.proposal_token,confirmed:'on'});
   this.id=result.id;this.newApplication=false;this.setData({preview:null,confirmed:false});
   if(result.ticket){const filePath=await api.downloadRecordCopy(result.ticket);await new Promise((resolve,reject)=>wx.openDocument({filePath,fileType:'pdf',showMenu:true,success:resolve,fail(){reject(Error('文件已传输，暂时无法打开。请返回本申请重新领取或使用网站。'));}}));}
   this.setData({busy:false});await this.load();
  }catch(e){showError(this,e);}
 },
 cancelPreview(){this.setData({preview:null,confirmed:false});},
 async pageChange(e){const page=this.data.pagination[e.currentTarget.dataset.direction];if(!page||this.data.busy)return;this.page=page;await this.load();}
});
