const api=require('../../utils/api');
const {dateTime,showError}=require('../../utils/format');
const states=[{code:'ACCEPTED',label:'认可此步骤'},{code:'DEFERRED',label:'暂缓决定'},{code:'DECLINED',label:'不选择此步骤'}];
const stamp=()=>{const s=api.sessionInfo();return JSON.stringify([s.workspace_id,s.subject_key,s.subject_revision]);};
Page({
 data:{plan:null,states,stateIndex:0,selected:null,note:'',preview:null,checked:false,busy:false,error:'',done:'',uncertain:false,readOnly:false,revision:''},
 onLoad(query){this.planId=Number(query.id);if(!Number.isSafeInteger(this.planId)||this.planId<1)this.planId=null;},
 clear(){this._pending=null;this.setData({plan:null,selected:null,note:'',preview:null,checked:false,uncertain:false,done:''});},
 async onShow(){
  this.setData({busy:true,error:''});
  try{const s=await api.bootstrap();api.showSubject(this);
   if(!s.authenticated){this.clear();this.setData({busy:false});wx.reLaunch({url:'/pages/login/index'});return;}
   if(s.subject_required){this.clear();this.setData({busy:false});wx.reLaunch({url:'/pages/patients/index'});return;}
   if(s.delegated){this.clear();this.setData({busy:false,error:'预约代办不包含临床方案，请切换至本人。'});return;}
   if(!this.planId){this.clear();this.setData({busy:false,error:'方案链接已失效，请从本人计划清单重新打开。'});return;}
   if(this._subject!==stamp())this.clear();this._subject=stamp();this.setData({readOnly:s.read_only});await this.load();
  }catch(e){this.failed(e);}
 },
 async load(){
  this.setData({busy:true,error:''});
  try{const d=await api.request('plans/'+this.planId+'/'+(this.data.revision?'?revision='+this.data.revision:''));
   if(this._subject!==stamp()){this.clear();throw new Error('就诊人已变化，请重新核对本人方案。');}
   const steps=d.steps.map(s=>Object.assign({},s,{actual_history:s.actual_history.map(a=>Object.assign({},a,{timeLabel:dateTime(a.observed_at)}))}));
   this.setData({plan:Object.assign({},d,{steps,timeLabel:dateTime(d.recorded_at)}),busy:false});
  }catch(e){this.failed(e);}
 },
 choose(e){if(this.data.busy||this.data.uncertain||this.data.readOnly||!this.data.plan||!this.data.plan.is_current)return;const selected=this.data.plan.steps.find(s=>s.id===Number(e.currentTarget.dataset.id));if(selected)this.setData({selected,stateIndex:0,note:'',preview:null,checked:false,done:''});},
 pick(e){if(this.data.busy||this.data.uncertain)return;const index=Number(e.detail.value);if(states[index])this.setData({stateIndex:index,preview:null,checked:false});},
 input(e){if(!this.data.busy&&!this.data.uncertain)this.setData({note:e.detail.value,preview:null,checked:false});},
 checked(e){if(!this.data.busy&&!this.data.uncertain)this.setData({checked:e.detail.value.includes('yes')});},
 async preview(){
  if(this.data.busy||this.data.uncertain||this.data.readOnly||!this.data.selected)return;
  if(this._subject!==stamp()||api.sessionInfo().delegated){this.clear();this.setData({error:'就诊人已变化，请重新打开本人方案。'});return;}
  this.setData({busy:true,error:''});
  try{const d=await api.request('plans/'+this.planId+'/steps/'+this.data.selected.id+'/decision/preview/','POST',{decision:states[this.data.stateIndex].code,note:this.data.note});
   if(this._subject!==stamp()){this.clear();throw new Error('本人身份已变化，请重新核对。');}
   this.setData({preview:Object.assign({},d,{decisionLabel:states.find(s=>s.code===d.values.decision).label}),checked:false,busy:false});
  }catch(e){this.failed(e);}
 },
 async confirm(){
  if(this.data.busy||this.data.readOnly||!this.data.preview)return;
  if(this._subject!==stamp()||api.sessionInfo().delegated){this.clear();this.setData({error:'就诊人已变化，原确认不能继续。'});return;}
  if(!this.data.uncertain&&!this.data.checked){this.setData({error:'请先核对并明确确认这个版本步骤的决定。'});return;}
  if(!this._pending)this._pending={step:this.data.preview.step,data:{proposal_token:this.data.preview.proposal_token,confirmed:'on'}};
  this.setData({busy:true,error:''});
  try{await api.request('plans/'+this.planId+'/steps/'+this._pending.step+'/decision/confirm/','POST',this._pending.data);
   if(this._subject!==stamp()){this.clear();throw new Error('本人身份已变化，请重新查看当前决定。');}
   this._pending=null;this.setData({preview:null,selected:null,note:'',checked:false,uncertain:false,busy:false,done:'本人决定已保留，下面显示当前方案状态；未产生治疗或收费。'});await this.load();
  }catch(e){if(e.code==='NETWORK_UNCONFIRMED')this.setData({uncertain:true});else{this._pending=null;this.setData({preview:null,checked:false,uncertain:false});}this.failed(e);}
 },
 version(e){if(this.data.busy||this.data.uncertain)return;this.setData({revision:String(e.currentTarget.dataset.revision||''),selected:null,preview:null,note:'',checked:false,done:''});return this.load();},
 cancel(){if(!this.data.busy&&!this.data.uncertain)this.setData({selected:null,preview:null,note:'',checked:false});},
 failed(e){if(['SUBJECT_CHANGED','SUBJECT_REQUIRED','WORKSPACE_CHANGED','ACCESS_DENIED'].includes(e.code)||e.status===401)this.clear();showError(this,e);},
 onUnload(){this.clear();this._subject=null;}
});
