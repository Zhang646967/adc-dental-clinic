const api=require('../../utils/api');
const {dateTime,showError}=require('../../utils/format');
const states=[{code:'UNKNOWN',label:'尚未明确'},{code:'REPORTED',label:'自述有相关情况'},{code:'NO_KNOWN',label:'自述目前无已知情况'}];
const blank=()=>({medical_status:'UNKNOWN',medical_history:'',medication_status:'UNKNOWN',medications:'',allergy_status:'UNKNOWN',reported_allergies:''});
const stamp=()=>{const s=api.sessionInfo();return JSON.stringify([s.workspace_id,s.subject_key,s.subject_revision]);};
const fieldsOf=row=>Object.assign(blank(),...Object.keys(blank()).map(key=>({[key]:row?row[key]:blank()[key]})));
const labels=row=>Object.assign({},row,{timeLabel:dateTime(row.recorded_at),medicalLabel:states.find(s=>s.code===row.medical_status).label,medicationLabel:states.find(s=>s.code===row.medication_status).label,allergyLabel:states.find(s=>s.code===row.allergy_status).label});
Page({
 data:{states,fields:blank(),medicalIndex:0,medicationIndex:0,allergyIndex:0,rows:[],page:1,pages:1,expected:0,operationId:'',busy:false,error:'',done:'',checked:false,dirty:false,uncertain:false,readOnly:false,expanded:null},
 clear(){this._ready=false;this._pending=null;this.setData({fields:blank(),rows:[],medicalIndex:0,medicationIndex:0,allergyIndex:0,checked:false,dirty:false,uncertain:false,expected:0,operationId:'',done:''});},
 fill(row){const fields=fieldsOf(row);this.setData({fields,medicalIndex:states.findIndex(s=>s.code===fields.medical_status),medicationIndex:states.findIndex(s=>s.code===fields.medication_status),allergyIndex:states.findIndex(s=>s.code===fields.allergy_status)});},
 async onShow(){
  this.setData({busy:true,error:''});
  try{const s=await api.bootstrap();api.showSubject(this);
   if(!s.authenticated){this.clear();this.setData({busy:false});wx.reLaunch({url:'/pages/login/index'});return;}
   if(s.subject_required){this.clear();this.setData({busy:false});wx.reLaunch({url:'/pages/patients/index'});return;}
   if(s.delegated){this.clear();this.setData({busy:false,error:'预约代办不包含临床自述，请切换到本人。'});return;}
   if(this._subject!==stamp())this.clear();this._subject=stamp();this.setData({readOnly:s.read_only});await this.load();
  }catch(e){this.failed(e);}
 },
 async load(rebase=false){
  this.setData({busy:true,error:''});
  try{const d=await api.request('history/','GET',{page:this.data.page});
   if(this._subject!==stamp()){this.clear();throw new Error('就诊人已经变化，请返回本人页面重新核对。');}
   if(!Array.isArray(d.rows)||!Number.isInteger(d.current_revision)||!d.operation_id)throw new Error('自述清单暂时无法核对，请重新打开。');
   this.setData({rows:d.rows.map(labels),page:d.page,pages:d.pages,serverRevision:d.current_revision,busy:false});
   if(!this._ready||(!this.data.dirty&&!this.data.uncertain))this.fill(d.latest);
   if(!this._ready||(!this.data.dirty&&!this.data.uncertain)||rebase){
    if(!this.data.uncertain){this.setData({expected:d.current_revision,operationId:d.operation_id,checked:false});this._ready=true;}
   }
  }catch(e){this.failed(e);}
 },
 field(e){if(this.data.busy||this.data.uncertain)return;const key=e.currentTarget.dataset.field;
  if(!['medical_history','medications','reported_allergies'].includes(key))return;
  this.setData({fields:Object.assign({},this.data.fields,{[key]:e.detail.value}),dirty:true,checked:false,done:''});
 },
 pick(e){if(this.data.busy||this.data.uncertain)return;const key=e.currentTarget.dataset.field,index=Number(e.detail.value);
  const names={medical_status:'medicalIndex',medication_status:'medicationIndex',allergy_status:'allergyIndex'};
  if(!names[key]||!states[index])return;
  this.setData({fields:Object.assign({},this.data.fields,{[key]:states[index].code}),[names[key]]:index,dirty:true,checked:false,done:''});
 },
 checked(e){if(!this.data.busy&&!this.data.uncertain)this.setData({checked:e.detail.value.includes('yes')});},
 async submit(){
  if(this.data.busy||this.data.readOnly)return;
  if(this._subject!==stamp()||api.sessionInfo().delegated){this.clear();this.setData({error:'就诊人已变化，请重新打开本人自述页面。'});return;}
  if(!this.data.uncertain&&!this.data.checked){this.setData({error:'请先核对并确认本次患者自述。'});return;}
  if(!this._pending)this._pending=Object.assign({},this.data.fields,{expected_revision:this.data.expected,operation_id:this.data.operationId,confirmed:'on'});
  this.setData({busy:true,error:'',done:''});
  try{const d=await api.request('history/submit/','POST',this._pending);
   if(this._subject!==stamp()){this.clear();throw new Error('就诊人已经变化，请重新核对已保存的本人记录。');}
   this._pending=null;this.fill(d.row);this.setData({expected:d.current_revision,operationId:d.operation_id,dirty:false,uncertain:false,checked:false,busy:false,done:'已保留第 '+d.row.revision+' 版患者自述，接诊时仍由医师核对。'});await this.load();
  }catch(e){if(e.code==='NETWORK_UNCONFIRMED')this.setData({uncertain:true});else this._pending=null;this.failed(e);}
 },
 failed(e){if(['SUBJECT_CHANGED','SUBJECT_REQUIRED','WORKSPACE_CHANGED','ACCESS_DENIED'].includes(e.code)||e.status===401)this.clear();showError(this,e);},
 refresh(){if(!this.data.busy)return this.load(true);},
 expand(e){const id=Number(e.currentTarget.dataset.id);this.setData({expanded:this.data.expanded===id?null:id});},
 turn(e){if(this.data.busy)return;const page=this.data.page+Number(e.currentTarget.dataset.step);if(page<1||page>this.data.pages)return;this.setData({page});return this.load();},
 onUnload(){this.clear();this._subject=null;}
});
