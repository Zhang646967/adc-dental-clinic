const api=require('../../utils/api');
const navigation=require('../../utils/navigation');
const {dateTime,showError}=require('../../utils/format');
const stamp=()=>{const s=api.sessionInfo();return JSON.stringify([s.workspace_id,s.subject_key,s.subject_revision]);};
Page({
 data:{rows:[],medical:null,busy:false,error:'',requestId:'',preview:null,checked:false,note:'',uncertain:false,readOnly:false,done:''},
 onLoad(q){this.caseId=q.id?Number(q.id):null;this.setData({isDetail:!!q.id});if(!Number.isSafeInteger(this.caseId)||this.caseId<1)this.caseId=null;},
 clear(){this._pending=null;this.setData({rows:[],medical:null,preview:null,note:'',checked:false,uncertain:false,done:''});},
 async onShow(){this.setData({busy:true,error:'',requestId:''});try{const s=await api.bootstrap();api.showSubject(this);if(!s.authenticated&&!s.account_authenticated){this.clear();navigation.reLaunch({url:'/pages/login/index'});this.setData({busy:false});return;}if(this._subject!==stamp())this.clear();this._subject=stamp();this.setData({readOnly:s.read_only});await this.load();}catch(e){this.failed(e);}},
 async load(){this.setData({busy:true,error:'',requestId:'',rows:[],medical:null});try{if(this.data.isDetail&&!this.caseId)throw Error('授权链接无效，请从办理记录重新打开。');const d=await api.request('medical-authorizations/'+(this.caseId?this.caseId+'/':''));if(this._subject!==stamp()){this.clear();throw new Error('就诊人已变化，请重新打开医疗授权。');}if(this.caseId){d.fromLabel=d.valid_from?dateTime(d.valid_from):'';d.untilLabel=d.valid_until?dateTime(d.valid_until):'';d.history=d.history.map(e=>({...e,timeLabel:dateTime(e.recorded_at)}));this.setData({medical:d,busy:false});}else this.setData({rows:d.rows,busy:false});}catch(e){this.failed(e);}},
 open(e){navigation.navigateTo({url:'/pages/medical-authorizations/index?id='+Number(e.currentTarget.dataset.id)});},
 async plan(){if(this.data.busy||!this.data.medical||!this.data.medical.clinical_available)return;this.setData({busy:true,error:'',requestId:''});try{const plan=this.data.medical.plan;await api.selectSubject('medical:'+this.data.medical.id);this.clear();navigation.navigateTo({url:'/pages/plan/index?id='+plan});}catch(e){this.failed(e);}},
 input(e){if(!this.data.busy&&!this.data.uncertain)this.setData({note:e.detail.value,preview:null,checked:false});},
 checked(e){if(!this.data.busy&&!this.data.uncertain)this.setData({checked:e.detail.value.includes('yes')});},
 async preview(){if(this.data.busy||this.data.uncertain||this.data.readOnly||!this.data.medical)return;this.setData({busy:true,error:'',requestId:''});try{if(this.data.isDetail&&!this.caseId)throw Error('授权链接无效，请从办理记录重新打开。');const d=await api.request('medical-authorizations/'+this.caseId+'/preview/','POST',{action:'REVOKE',note:this.data.note});this.setData({preview:d,busy:false,checked:false});}catch(e){this.failed(e);}},
 async confirm(){if(this.data.busy||!this.data.preview||this.data.readOnly)return;if(this._subject!==stamp()){this.clear();this.setData({error:'患者或授权已变化，请重新打开。'});return;}if(!this.data.checked&&!this.data.uncertain){this.setData({error:'请明确核对要撤销的患者与本项授权。'});return;}if(!this._pending)this._pending={proposal_token:this.data.preview.proposal_token,confirmed:'on'};this.setData({busy:true,error:'',requestId:''});try{await api.request('medical-authorizations/'+this.caseId+'/confirm/','POST',this._pending);this.clear();this.setData({busy:false});
   await this.onShow();
   if(this.data.medical)this.setData({done:'本项授权已撤销。可在办理状态中核对结果。'});}catch(e){if(e.code==='NETWORK_UNCONFIRMED')this.setData({uncertain:true});else{this._pending=null;this.setData({preview:null,uncertain:false});}this.failed(e);}},
 back(){navigation.returnTo(this.data.isDetail?'/pages/medical-authorizations/index':'/pages/account/index');},
 cancel(){if(!this.data.busy&&!this.data.uncertain)this.setData({preview:null,checked:false});},
 subjects(){navigation.reLaunch({url:'/pages/patients/index'});},
 failed(e){if(e.status===401||e.status===403||['SUBJECT_CHANGED','SUBJECT_REQUIRED','WORKSPACE_CHANGED','ACCESS_DENIED'].includes(e.code))this.clear();showError(this,e,{separateRequestId:true});},
 onUnload(){this.clear();this._subject=null;}
});
