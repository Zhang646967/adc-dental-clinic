const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {positive}=require('../../utils/booking-intent');
const {arrangement,showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const {buildReview}=require('../../utils/visit-review');
const {record}=require('../../utils/visit-record');
const {buildExaminations}=require('../../utils/examinations');
const {buildReturnSources}=require('../../utils/return-sources');
const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};
const blankDraft={reason:'',cancelOpen:false};
Page({
  data:{visit:null,record:null,reviewView:null,examinations:[],returnSources:[],...blankSubject,...blankDraft,busy:false,error:'',requestId:'',readOnly:false,subjectInvalid:false,
    // Detail disclosures start closed; both reset on every read or subject change.
    infoOpen:false,moneyOpen:false,infoLabel:'就诊编号',infoOpenLabel:'展开就诊编号',infoCloseLabel:'收起就诊编号',
    moneyOpenLabel:'展开收款与退款明细',moneyCloseLabel:'收起收款与退款明细'},
  onLoad(q){
    this.id=Number(q.id);
    // Only a numeric instruction id from the current visit response can be
    // located; a missing or stale id never reuses cached instructions.
    this.instructionId=positive(q.instruction)?Number(q.instruction):null;
    // The list range that opened this record; a record opened from another
    // record inherits it so both ways back reach the same queue.
    this.returnQueue=['active','history','all'].includes(q.queue)?q.queue:null;
    this.generation=0;
  },
  onShow(){return this.load();},
  async load(){
    const generation=++this.generation;
    this.setData({visit:null,record:null,reviewView:null,examinations:[],returnSources:[],...blankSubject,error:'',requestId:'',busy:false,subjectInvalid:false,infoOpen:false,moneyOpen:false});
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
      const reviewView=buildReview(visit,{delegated:session.delegated,instruction:this.instructionId});
      const row=record(visit,{delegated:session.delegated});
      const head=reviewView&&reviewView.completedLabel?'就诊编号':'预约编号';
      const label=(row&&row.hasRequest)?head+'与需求':head;
      this.setData({visit,record:row,reviewView,
        infoLabel:label,infoOpenLabel:'展开'+label,infoCloseLabel:'收起'+label,
        examinations:buildExaminations(visit,{delegated:session.delegated}),
        returnSources:buildReturnSources(visit,{delegated:session.delegated}),
        readOnly:session.read_only,environmentLabel:session.environment_label||''},()=>this.focusInstruction());
    }catch(e){
      if(generation!==this.generation)return;
      this.setData(blankDraft);
      this.visitError(e);
    }
  },
  onUnload(){this.generation++;},
  toggleInfo(){this.setData({infoOpen:!this.data.infoOpen});},
  toggleMoney(){this.setData({moneyOpen:!this.data.moneyOpen});},
  focusInstruction(){
    const review=this.data.reviewView;
    if(!review||!this.instructionId)return;
    const row=(review.followups||[]).find(item=>item.selected);
    if(!row)return;
    // Leave a small gap above the located instruction so its own label and
    // service stay visible under the navigation bar.
    const locate=()=>wx.pageScrollTo({selector:`#followup-${row.id}`,offsetTop:-16,duration:250});
    if(typeof wx.nextTick==='function')wx.nextTick(locate);else locate();
  },
  visitError(error){
    if(staleSubject(error,api.sessionInfo(),{uncodedConflictIsStale:false}).invalid){
      getApp().globalData.review=null;
      this.context=null;
      this.setData({visit:null,reviewView:null,examinations:[],returnSources:[],...blankSubject,...blankDraft,subjectInvalid:true});
    }
    showError(this,error,{separateRequestId:true,stayOnPage:true});
  },
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  invoice(){
    const visit=this.data.visit,review=this.data.reviewView;
    const id=(review&&review.settlement&&review.settlement.invoiceId)||(visit&&visit.invoice_id);
    if(!this.data.patientDelegated&&positive(id))navigation.navigateTo({url:`/pages/invoice/index?id=${id}&visit=${this.id}`});
  },
  followupRow(e){
    const key=Number(e.currentTarget.dataset.key);
    const rows=(this.data.reviewView&&this.data.reviewView.followups)||[];
    return rows.find(row=>row.key===key)||null;
  },
  openAppointment(e){
    const row=this.followupRow(e), kind=e.currentTarget.dataset.kind;
    if(!row||this.data.patientDelegated||!['active','historical','linked'].includes(kind))return;
    const appointment=row[kind];
    if(!appointment||(kind==='active'&&!row.showActive))return;
    navigation.navigateTo({url:`/pages/visit/index?id=${appointment.id}${this.returnQueue?'&queue='+this.returnQueue:''}`});
  },
  bookFollowup(e){
    const row=this.followupRow(e);
    if(!row||!row.canBook||this.data.patientDelegated)return;
    navigation.navigateTo({url:row.bookingUrl});
  },
  contactFollowup(e){
    const row=this.followupRow(e);
    if(!row||!row.canContact||this.data.patientDelegated||!positive(this.id))return;
    navigation.navigateTo({url:`/pages/help/index?visit=${this.id}`});
  },
  sourceRow(e){
    const key=e.currentTarget.dataset.key;
    return this.data.returnSources.find(row=>row.key===key)||null;
  },
  openSourceReport(e){
    const row=this.sourceRow(e);
    if(!row||!row.report||this.data.patientDelegated||!this.data.visit||!positive(this.id))return;
    const session=api.sessionInfo();
    // Handoff for the report page. The URL alone can never create 返回这次复诊.
    getApp().globalData.returnSource={visitId:this.id,sourceVisitId:row.sourceVisitId,
      reportId:row.report.id,revision:row.report.revision,
      subjectKey:session.subject_key,workspaceKey:session.workspace_id,
      subjectRevision:session.subject_revision,expires:Date.now()+10*60000};
    navigation.navigateTo({url:`/pages/examination/index?visit=${row.sourceVisitId}&id=${row.report.id}&revision=${row.report.revision}&from=${this.id}`});
  },
  contactSource(e){
    const row=this.sourceRow(e);
    if(!row||!row.canContact||this.data.patientDelegated)return;
    navigation.navigateTo({url:`/pages/help/index?visit=${row.sourceVisitId}`});
  },
  contactClinic(){
    if(!this.data.visit)return;
    navigation.navigateTo({url:`/pages/help/index?visit=${this.id}`});
  },
  openExamination(e){
    const {id,revision}=e.currentTarget.dataset;
    if(!this.data.visit||this.data.patientDelegated||!positive(this.id)||!positive(id)||!positive(revision))return;
    navigation.navigateTo({url:`/pages/examination/index?visit=${this.id}&id=${id}&revision=${revision}`});
  },
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
  related(e){
    const id=Number(e.currentTarget.dataset.id);
    if(!positive(id))return;
    const queue=this.returnQueue?`&queue=${this.returnQueue}`:'';
    navigation.redirectTo({url:`/pages/visit/index?id=${id}${queue}`});
  },
  home(){
    // Prefer the range the list opened with; otherwise derive it from status.
    const queue=this.returnQueue||(this.data.visit&&!['SCHEDULED','CHECKED_IN'].includes(this.data.visit.status)?'history':'active');
    navigation.reLaunch({url:`/pages/home/index?queue=${queue}`});
  }
});
