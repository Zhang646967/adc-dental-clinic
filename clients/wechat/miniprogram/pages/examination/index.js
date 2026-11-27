const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {positive}=require('../../utils/booking-intent');
const {showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const {buildReport}=require('../../utils/examinations');
const {buildFollowup}=require('../../utils/report-notices');

const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};

Page({
  data:{report:null,followup:null,...blankSubject,busy:false,error:'',requestId:'',subjectInvalid:false,
    returnMedical:false,returnVisit:null,environmentLabel:'',hasVisit:false,
    // The identifiers only open on request; the report body and every follow-up
    // conclusion stay readable without tapping anything.
    infoOpen:false,infoOpenLabel:'查看检查时间与编号',infoCloseLabel:'收起检查时间与编号'},
  onLoad(query){
    this.visitId=positive(query.visit)?Number(query.visit):null;
    this.id=positive(query.id)?Number(query.id):null;
    this.revision=query.revision;
    this.fromVisit=positive(query.from)?Number(query.from):null;
    // Only the visit page can create this handoff; a URL parameter alone never
    // changes where the report returns.
    this.handoff=getApp().globalData.returnSource||null;
    getApp().globalData.returnSource=null;
    this.generation=0;
    this.setData({hasVisit:!!this.visitId});
  },
  onShow(){return this.load();},
  async load(){
    const generation=++this.generation;
    this.setData({report:null,followup:null,...blankSubject,busy:true,error:'',requestId:'',subjectInvalid:false,
      returnMedical:false,returnVisit:null,infoOpen:false});
    try{
      if(!this.visitId||!this.id||(this.revision!==undefined&&!positive(this.revision))){
        throw Error('报告链接无效，请从就诊详情进入。');
      }
      const query=this.revision===undefined?{}:{revision:Number(this.revision)};
      const data=await api.request(`visits/${this.visitId}/examinations/${this.id}/`,'GET',query);
      if(generation!==this.generation)return;
      const report=buildReport(data);
      if(!report)throw Error('报告当前不可查看，请返回就诊核对');
      // The follow-up decision is bound to the version that was actually read,
      // so a booking started from here carries this exact revision.
      const followup=buildFollowup(data.followup,{visitId:this.visitId,examinationId:this.id,revision:report.revision});
      api.showSubject(this);
      this.setData({report,followup,busy:false,environmentLabel:api.sessionInfo().environment_label||''});
      this.bindReturn();
    }catch(e){
      if(generation!==this.generation)return;
      const session=api.sessionInfo();
      if(e.status===403&&e.code==='REPORT_SELF_REQUIRED'){
        this.setData({returnMedical:!!session.medical&&!session.can_book});
        showError(this,e,{separateRequestId:true,stayOnPage:true});
      }else if(e.status===404){
        this.setData({error:'报告当前不可查看，请返回就诊核对',requestId:e.requestId||'',busy:false});
        // The report can be withdrawn after the tap; the arrival context is
        // still the return visit, so its way back stays available.
        this.bindReturn();
      }else if(e.status===403&&e.code==='ACCESS_DENIED'&&session.delegated){
        this.setData({error:'代约仅可查看预约与到诊信息，请由患者本人查看报告。',requestId:e.requestId||'',busy:false});
      }else{
        const state=staleSubject(e,session,{uncodedConflictIsStale:false});
        this.setData({subjectInvalid:state.invalid});
        showError(this,e,{separateRequestId:true,stayOnPage:true});
      }
    }
  },
  onHide(){
    // Leaving the page drops the report, the follow-up block and the expanded
    // identifiers so another report or identity never inherits them.
    this.generation++;
    this.setData({report:null,followup:null,...blankSubject,returnVisit:null,infoOpen:false});
  },
  toggleInfo(){this.setData({infoOpen:!this.data.infoOpen});},
  onUnload(){this.generation++;},
  bindReturn(){
    const none=()=>this.setData({returnVisit:null});
    const handoff=this.handoff;
    if(!this.fromVisit||!handoff||!this.visitId||!this.id||!positive(this.revision))return none();
    if(handoff.visitId!==this.fromVisit||handoff.sourceVisitId!==this.visitId||
      handoff.reportId!==this.id||handoff.revision!==Number(this.revision)||
      !(handoff.expires>Date.now()))return none();
    // The same patient, workspace and subject revision must still be current.
    const session=api.sessionInfo();
    if(!session.authenticated||session.delegated||session.subject_key!==handoff.subjectKey||
      session.workspace_id!==handoff.workspaceKey||session.subject_revision!==handoff.subjectRevision)return none();
    // Arrive through the actual visit page, not a hand-made URL, and require
    // that page's own projected row to name this exact source report version.
    const pages=getCurrentPages();
    const previous=pages[pages.length-2];
    if(!previous||'/'+previous.route!=='/pages/visit/index')return none();
    if(Number(previous.options&&previous.options.id)!==this.fromVisit)return none();
    const rows=(previous.data&&previous.data.returnSources)||[];
    const row=rows.find(item=>item&&item.sourceVisitId===this.visitId&&item.report&&
      item.report.id===this.id&&item.report.revision===Number(this.revision));
    this.setData({returnVisit:row?this.fromVisit:null});
  },
  bookFollowup(){
    const followup=this.data.followup;
    if(!followup||!followup.bookingUrl)return;
    navigation.navigateTo({url:followup.bookingUrl});
  },
  openAppointment(){
    const followup=this.data.followup;
    if(!followup||!followup.appointmentUrl)return;
    navigation.navigateTo({url:followup.appointmentUrl});
  },
  contactClinic(){
    const followup=this.data.followup;
    navigation.navigateTo({url:followup&&followup.contactUrl?followup.contactUrl:`/pages/help/index?visit=${this.visitId}`});
  },
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  back(){
    if(this.data.returnMedical)return navigation.returnTo('/pages/medical-authorizations/index');
    if(this.data.returnVisit)return navigation.returnTo(`/pages/visit/index?id=${this.data.returnVisit}`);
    return navigation.returnTo(this.visitId?`/pages/visit/index?id=${this.visitId}`:'/pages/home/index?queue=history');
  }
});
