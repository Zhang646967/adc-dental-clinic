const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {positive}=require('../../utils/booking-intent');
const {showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const {buildReport}=require('../../utils/examinations');
const {buildFollowup}=require('../../utils/report-notices');

const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};

Page({
  data:{report:null,followup:null,...blankSubject,busy:false,error:'',requestId:'',subjectInvalid:false,environmentLabel:'',hasVisit:false},
  onLoad(query){
    this.visitId=positive(query.visit)?Number(query.visit):null;
    this.id=positive(query.id)?Number(query.id):null;
    this.revision=query.revision;
    this.generation=0;
    this.setData({hasVisit:!!this.visitId});
  },
  onShow(){return this.load();},
  async load(){
    const generation=++this.generation;
    this.setData({report:null,followup:null,...blankSubject,busy:true,error:'',requestId:'',subjectInvalid:false});
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
    }catch(e){
      if(generation!==this.generation)return;
      const session=api.sessionInfo();
      if(e.status===404){
        this.setData({error:'报告当前不可查看，请返回就诊核对',requestId:e.requestId||'',busy:false});
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
    this.generation++;
    this.setData({report:null,followup:null,...blankSubject});
  },
  onUnload(){this.generation++;},
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
  back(){navigation.returnTo(this.visitId?`/pages/visit/index?id=${this.visitId}`:'/pages/home/index?queue=history');}
});
