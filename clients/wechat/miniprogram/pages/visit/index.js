const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {arrangement,showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};
const blankDraft={reason:'',cancelOpen:false};
Page({
  data:{visit:null,...blankSubject,...blankDraft,busy:false,error:'',requestId:'',readOnly:false,subjectInvalid:false},
  onLoad(q){this.id=Number(q.id);this.generation=0;},
  onShow(){return this.load();},
  async load(){
    const generation=++this.generation;
    this.setData({visit:null,...blankSubject,error:'',requestId:'',busy:false,subjectInvalid:false});
    try{
      const visit=arrangement(await api.request(`visits/${this.id}/`));
      if(generation!==this.generation)return;
      const session=api.sessionInfo();
      const context=[session.workspace_id,session.subject_key,session.subject_revision];
      if(!this.context||context.some((value,index)=>value!==this.context[index])||!visit.can_change||session.read_only){
        this.setData(blankDraft);
      }
      this.context=context;
      api.showSubject(this);
      this.setData({visit,readOnly:session.read_only,environmentLabel:session.environment_label||''});
    }catch(e){
      if(generation!==this.generation)return;
      this.setData(blankDraft);
      this.visitError(e);
    }
  },
  onUnload(){this.generation++;},
  visitError(error){
    if(staleSubject(error,api.sessionInfo(),{uncodedConflictIsStale:false}).invalid){
      getApp().globalData.review=null;
      this.context=null;
      this.setData({visit:null,...blankSubject,...blankDraft,subjectInvalid:true});
    }
    showError(this,error,{separateRequestId:true,stayOnPage:true});
  },
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  invoice(){const id=this.data.visit&&this.data.visit.invoice_id;if(id)navigation.navigateTo({url:`/pages/invoice/index?id=${id}&visit=${this.id}`});},
  canChange(){return !!this.data.visit&&this.data.visit.can_change&&!this.data.readOnly;},
  reschedule(){if(this.canChange())navigation.navigateTo({url:`/pages/booking/index?visit=${this.id}`});},
  cancel(){if(this.canChange())this.setData({cancelOpen:!this.data.cancelOpen,error:'',requestId:''});},
  reason(e){if(this.canChange()&&this.data.cancelOpen)this.setData({reason:e.detail.value});},
  async previewCancel(){
    if(this.data.busy||!this.data.cancelOpen||!this.canChange())return;
    if(!this.data.reason.trim()){this.setData({error:'请填写取消原因。'});return;}
    const generation=this.generation;
    this.setData({busy:true,error:'',requestId:''});
    try{const preview=await api.request(`visits/${this.id}/cancel/preview/`,'POST',{expected_version:this.data.visit.version,reason:this.data.reason});
      if(generation!==this.generation)return;
      const session=api.sessionInfo();
      getApp().globalData.review={subjectKey:session.subject_key,workspaceKey:session.workspace_id,subjectRevision:session.subject_revision,kind:'cancel',preview,path:`visits/${this.id}/cancel/confirm/`};
      this.setData({busy:false});navigation.navigateTo({url:'/pages/confirm/index'});
    }catch(e){if(generation===this.generation)this.visitError(e);}
  },
  related(e){navigation.redirectTo({url:`/pages/visit/index?id=${e.currentTarget.dataset.id}`});},
  home(){navigation.reLaunch({url:'/pages/home/index'});}
});
