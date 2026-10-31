const api=require('../../utils/api');
const navigation=require('../../utils/navigation');
const {dateTime,showError}=require('../../utils/format');
const actions=[{code:'QUESTION',label:'我有问题需要医师答复'},{code:'AGREED',label:'我同意本版本具体医疗行为'},{code:'DECLINED',label:'我拒绝本版本医疗行为'},{code:'DEFERRED',label:'我暂缓决定'},{code:'WITHDRAWN',label:'撤回本版本同意'}];
const stamp=()=>{const s=api.sessionInfo();return JSON.stringify([s.workspace_id,s.subject_key,s.subject_revision]);};
Page({
 data:{medical:null,actions,actionIndex:0,text:'',preview:null,checked:false,busy:false,error:'',done:'',uncertain:false,readOnly:false,revision:''},
 onLoad(q){this.stepId=Number(q.step);if(!Number.isSafeInteger(this.stepId)||this.stepId<1)this.stepId=null;},
 clear(){this._pending=null;this.setData({medical:null,text:'',preview:null,checked:false,uncertain:false,done:''});},
 async onShow(){
  this.setData({busy:true,error:''});
  try{const s=await api.bootstrap();api.showSubject(this);
   if(!s.authenticated){this.clear();this.setData({busy:false});navigation.reLaunch({url:'/pages/login/index'});return;}
   if(s.subject_required){this.clear();this.setData({busy:false});navigation.reLaunch({url:'/pages/patients/index'});return;}
   if(s.delegated){this.clear();this.setData({busy:false,error:'预约代办不包含医疗告知查阅或代签，请切换至本人。'});return;}
   if(this._subject!==stamp())this.clear();this._subject=stamp();this.setData({readOnly:s.read_only});await this.load();
  }catch(e){this.failed(e);}
 },
 async load(){
  if(!this.stepId){this.clear();this.setData({error:'请从本人治疗方案的具体步骤进入医疗告知。',busy:false});return;}
  this.setData({busy:true,error:''});
  try{const d=await api.request('steps/'+this.stepId+'/consent/'+(this.data.revision?'?revision='+this.data.revision:''));
   if(this._subject!==stamp()){this.clear();throw new Error('就诊人已变化，请重新核对。');}
   this.stepId=d.step;d.timeLabel=dateTime(d.recorded_at);d.events=d.events.map(e=>Object.assign({},e,{timeLabel:dateTime(e.occurred_at),recordedLabel:dateTime(e.recorded_at)}));
   this.setData({medical:d,busy:false});
  }catch(e){this.failed(e);}
 },
 change(e){if(this.data.busy||this.data.uncertain)return;const i=Number(e.detail.value);if(actions[i])this.setData({actionIndex:i,preview:null,checked:false,done:''});},
 input(e){if(!this.data.busy&&!this.data.uncertain)this.setData({text:e.detail.value,preview:null,checked:false});},
 checked(e){if(!this.data.busy&&!this.data.uncertain)this.setData({checked:e.detail.value.includes('yes')});},
 async preview(){
  if(this.data.busy||this.data.uncertain||this.data.readOnly||!this.data.medical)return;
  if(this._subject!==stamp()||api.sessionInfo().delegated){this.clear();this.setData({error:'本人身份已变化，请重新打开。'});return;}
  this.setData({busy:true,error:''});
  try{const action=actions[this.data.actionIndex];const d=await api.request('steps/'+this.stepId+'/consent/preview/','POST',{action:action.code,text:this.data.text,version:this.data.medical.version});
   if(this._subject!==stamp()){this.clear();throw new Error('就诊人已变化，请重新核对。');}
   this.setData({preview:Object.assign({},d,{label:action.label}),checked:false,busy:false});
  }catch(e){this.failed(e);}
 },
 async confirm(){
  if(this.data.busy||this.data.readOnly||!this.data.preview)return;
  if(this._subject!==stamp()||api.sessionInfo().delegated){this.clear();this.setData({error:'本人身份已变化，原确认不能继续。'});return;}
  if(!this.data.uncertain&&!this.data.checked){this.setData({error:'请先核对具体内容、版本及本人表达。'});return;}
  if(!this._pending)this._pending={step:this.stepId,data:{proposal_token:this.data.preview.proposal_token,confirmed:'on'}};
  this.setData({busy:true,error:''});
  try{await api.request('steps/'+this._pending.step+'/consent/confirm/','POST',this._pending.data);
   if(this._subject!==stamp()){this.clear();throw new Error('就诊人已变化，请重新查看当前记录。');}
   this._pending=null;this.setData({preview:null,checked:false,text:'',uncertain:false,busy:false,done:'本次医疗沟通／决定已保留，可在历史中核对。'});await this.load();
  }catch(e){if(e.code==='NETWORK_UNCONFIRMED')this.setData({uncertain:true});else{this._pending=null;this.setData({preview:null,checked:false,uncertain:false});}this.failed(e);}
 },
 version(e){if(this.data.busy||this.data.uncertain)return;this.stepId=Number(e.currentTarget.dataset.step);this.setData({revision:String(e.currentTarget.dataset.revision||''),text:'',preview:null,checked:false,done:''});return this.load();},
 cancel(){if(!this.data.busy&&!this.data.uncertain)this.setData({preview:null,checked:false});},
 failed(e){if(['SUBJECT_CHANGED','SUBJECT_REQUIRED','WORKSPACE_CHANGED','ACCESS_DENIED'].includes(e.code)||e.status===401||e.status===403)this.clear();showError(this,e);},
 onUnload(){this.clear();this._subject=null;}
});
