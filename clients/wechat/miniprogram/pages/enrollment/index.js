const navigation=require('../../utils/navigation');
const api=require('../../utils/api'),{showError}=require('../../utils/format'),intent=require('../../utils/booking-intent');
function emptyForm(){return {name:'',date_of_birth:'',phone:'',billing_address:'',email:'',emergency_name:'',emergency_phone:'',patient_reference:''};}
Page({
  data:{caseId:null,invalidLink:false,clinics:[],clinicIndex:0,kindIndex:0,kinds:['新患者建档','已有档案关联'],form:emptyForm(),preview:null,uncertain:false,restoreOnly:false,readOnly:false,busy:false,error:'',patientMessage:''},
  onLoad(options){if(options.case){if(!intent.positive(options.case)){this.setData({invalidLink:true,error:'申请链接无效。'});return;}this.setData({caseId:Number(options.case)});}},
  async onShow(){
    if(this.data.invalidLink)return;
    this.setData({busy:true,error:''});
    try{
      const session=await api.bootstrap();if(!session.account_authenticated){navigation.reLaunch({url:'/pages/login/index'});return;}
      if(this.ownerContext&&this.ownerContext!==session.workspace_id){this.ownerContext=session.workspace_id;this.setData({form:emptyForm(),caseId:null,preview:null,uncertain:false,clinics:[],patientMessage:'',error:'账号已变化，原申请内容已清除。请从当前账号重新打开办理页。'});return;}
      this.ownerContext=session.workspace_id;this.setData({readOnly:session.read_only,restoreOnly:!!session.self_binding_needs_review});
      const discovery=await api.request('discovery/');const clinics=discovery.clinics.map(c=>({id:c.id,name:c.name}));
      let form=this.data.form,kindIndex=session.self_binding_needs_review?1:this.data.kindIndex,clinicIndex=0,patientMessage='';
      if(this.data.caseId){
        const own=await api.request('account/'),row=own.cases.find(c=>c.id===this.data.caseId);
        if(!row||!row.can_edit)throw Error('申请已变化，请返回账号清单核对当前结果。');
        form=row.details;kindIndex=row.kind==='NEW'?0:1;clinicIndex=clinics.findIndex(c=>c.id===row.clinic);patientMessage=row.patient_message;
      }else{const selected=getApp().globalData.bookingIntent;clinicIndex=selected?clinics.findIndex(c=>c.id===selected.clinic):0;}
      if(!clinics.length||clinicIndex<0)throw Error('原门店当前未开放新申请，请联系该店前台，保留原申请。');
      this.setData({clinics,clinicIndex,form,kindIndex,patientMessage});
    }catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  field(e){if(this.data.busy||this.data.uncertain)return;const form={...this.data.form,[e.currentTarget.dataset.field]:e.detail.value};this.setData({form,preview:null});},
  clinic(e){if(this.data.busy||this.data.uncertain)return;this.setData({clinicIndex:Number(e.detail.value),preview:null});},
  kind(e){if(this.data.busy||this.data.uncertain||this.data.restoreOnly)return;this.setData({kindIndex:Number(e.detail.value),preview:null});},
  date(e){if(this.data.busy||this.data.uncertain)return;this.setData({form:{...this.data.form,date_of_birth:e.detail.value},preview:null});},
  async preview(){
    if(this.data.busy||this.data.readOnly||this.data.uncertain)return;
    const clinic=this.data.clinics[this.data.clinicIndex];if(!clinic){this.setData({error:'请先选择办理门店。'});return;}
    this.setData({busy:true,error:''});
    try{const preview=await api.request('account/enrollment/preview/','POST',{...this.data.form,clinic:clinic.id,kind:this.data.kindIndex===0?'NEW':'EXISTING',case:this.data.caseId||''});this.setData({preview});}
    catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  async confirm(){
    if(this.data.busy||this.data.readOnly||!this.data.preview)return;
    this.setData({busy:true,error:''});
    try{await api.request('account/enrollment/confirm/','POST',{proposal_token:this.data.preview.proposal_token,confirmed:'on'});this.setData({uncertain:false});navigation.redirectTo({url:'/pages/account/index'});}
    catch(e){if(e.code==='NETWORK_UNCONFIRMED')this.setData({uncertain:true});else this.setData({preview:null});showError(this,e);}finally{this.setData({busy:false});}
  },
  revise(){if(!this.data.uncertain)this.setData({preview:null});}
});
