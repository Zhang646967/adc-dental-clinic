const api=require('../../utils/api');
const navigation=require('../../utils/navigation');
const {dateTime,showError}=require('../../utils/format');
const {positive}=require('../../utils/booking-intent');
const contextKey=s=>JSON.stringify([s.account_name,s.workspace_id,s.subject_revision]);
Page({
 data:{busy:false,error:'',requestId:'',rows:[],detail:null,options:null,preview:null,confirmed:false,purpose:'',message:'',visitIds:[],sectionIds:[],clinicIndex:0,packageIndex:0,readOnly:false,uncertain:false,done:'',fileError:'',isDetail:false},
 onLoad(q){this.id=positive(q.id)?Number(q.id):null;this.newApplication=q.new==='1';this.page=1;this.setData({isDetail:!!q.id||this.newApplication});},
 async onShow(){
  if(!this.data.uncertain)return this.load();
  if(this.data.busy)return;
  this.setData({busy:true});
  try{
   const session=await api.bootstrap();
   if(!session.account_authenticated||this.contextKey!==contextKey(session)){
    this.setData({uncertain:false,preview:null,confirmed:false,busy:false});
    return this.load();
   }
   this.setData({busy:false,readOnly:!!session.read_only});
  }catch(e){showError(this,e,{separateRequestId:true});}
 },
 async load(){
  if(this.data.busy||this.data.uncertain)return;
  this.setData({busy:true,error:'',requestId:'',rows:[],detail:null,options:null,preview:null,confirmed:false});
  try{
   const session=await api.bootstrap();if(!session.account_authenticated){this.contextKey=null;this.setData({purpose:'',message:'',done:'',fileError:''});wx.navigateTo({url:'/pages/login/index'});this.setData({busy:false});return;}
   const key=contextKey(session);
   if(this.contextKey!==key)this.setData({purpose:'',message:'',visitIds:[],sectionIds:[],preview:null,confirmed:false,done:'',fileError:'',pagination:null});
   this.contextKey=key;this.setData({readOnly:!!session.read_only});
   if(this.data.isDetail&&!this.id&&!this.newApplication)throw Error('副本申请链接无效，请从申请清单重新打开。');
   if(this.newApplication){await this.loadOptions();}
   else if(this.id){const d=await api.request(`record-copies/${this.id}/`);d.pickupLabel=d.pickup_until?dateTime(d.pickup_until):'';d.history=d.history.map(e=>({...e,atLabel:dateTime(e.at)}));this.setData({detail:d});}
   else{const list=await api.request('record-copies/','GET',{page:this.page});this.setData({rows:list.rows,pagination:list});}
   this.setData({busy:false});
  }catch(e){showError(this,e,{separateRequestId:true});}
 },
 async loadOptions(clinic){const o=await api.request('record-copies/options/','GET',clinic?{clinic}:{});o.sections=o.sections.map(s=>({...s,checked:true}));this.setData({options:o,clinicIndex:Math.max(0,o.clinics.findIndex(c=>String(c.id)===String(o.clinic))),packageIndex:0,visitIds:[],sectionIds:o.sections.map(s=>s.id)});},
 async clinic(e){if(this.data.busy)return;this.setData({busy:true,error:'',requestId:''});try{await this.loadOptions(this.data.options.clinics[Number(e.detail.value)].id);this.setData({busy:false});}catch(e){showError(this,e,{separateRequestId:true});}},
 package(e){this.setData({packageIndex:Number(e.detail.value)});},
 visits(e){const ids=e.detail.value;this.setData({visitIds:ids,'options.visits':this.data.options.visits.map(v=>({...v,checked:ids.includes(v.id)}))});},
 sections(e){const ids=e.detail.value;this.setData({sectionIds:ids,'options.sections':this.data.options.sections.map(v=>({...v,checked:ids.includes(v.id)}))});},
 input(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
 consent(e){if(this.data.busy||this.data.uncertain)return;this.setData({confirmed:e.detail.value.includes('yes')});},
 async prepare(e){
  if(this.data.busy||this.data.readOnly||this.data.uncertain)return;this.setData({busy:true,error:'',requestId:'',preview:null,confirmed:false,done:'',fileError:''});
  try{
   let p;const action=e.currentTarget.dataset.action;
   if(action==='SUBMIT'){const o=this.data.options;if(!o||!o.clinics.length)throw Error('请先由门店核对本人档案与已结束的就诊。');p=await api.request('record-copies/preview/','POST',{clinic:o.clinics[this.data.clinicIndex].id,visits:this.data.visitIds.join(','),sections:this.data.sectionIds.join(','),package:o.packages[this.data.packageIndex].id,purpose:this.data.purpose});}
   else p=await api.request(`record-copies/${this.id}/preview/`,'POST',{action,message:this.data.message});
   this.setData({preview:p,busy:false});
  }catch(e){showError(this,e,{separateRequestId:true});}
 },
 async confirm(){
  if(this.data.busy||this.data.readOnly||!this.data.preview||!this.data.confirmed)return;this.setData({busy:true,error:'',requestId:''});
  try{
   const result=await api.request('record-copies/confirm/','POST',{proposal_token:this.data.preview.proposal_token,confirmed:'on'});
   this.id=result.id;
   this.newApplication=false;
   this.setData({preview:null,confirmed:false,uncertain:false,done:result.ticket?'领取已确认。':'办理已提交，可查看当前进度。',purpose:'',message:''});
   if(result.ticket){
    try{
     const filePath=await api.downloadRecordCopy(result.ticket);
     await new Promise((resolve,reject)=>wx.openDocument({filePath,fileType:'pdf',showMenu:true,success:resolve,fail:reject}));
    }catch(e){this.setData({fileError:'暂时无法打开副本。请在本申请核对领取状态，再按可用入口重试。'});}
   }
   this.setData({busy:false});await this.load();
  }catch(e){
   if(e.code==='NETWORK_UNCONFIRMED')this.setData({uncertain:true});
   else if(e.status===401||e.status===403||['SUBJECT_CHANGED','SUBJECT_REQUIRED','WORKSPACE_CHANGED','ACCESS_DENIED'].includes(e.code))
    this.setData({preview:null,confirmed:false,uncertain:false,detail:null,options:null,purpose:'',message:''});
   else this.setData({preview:null,confirmed:false,uncertain:false});
   showError(this,e,{separateRequestId:true});
  }
 },
 back(){navigation.returnTo(this.data.isDetail?'/pages/record-copies/index':'/pages/account/index');},
 cancelPreview(){if(!this.data.busy&&!this.data.uncertain)this.setData({preview:null,confirmed:false});},
 async pageChange(e){const page=this.data.pagination[e.currentTarget.dataset.direction];if(!page||this.data.busy)return;this.page=page;await this.load();}
});
