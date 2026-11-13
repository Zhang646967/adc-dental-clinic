const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {positive}=require('../../utils/booking-intent');
const {showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const examModule=require('../../utils/examinations');
const buildReport=examModule&&typeof examModule.buildReport==='function'?examModule.buildReport:data=>data;

const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};

Page({
  data:{report:null,...blankSubject,busy:false,error:'',requestId:'',subjectInvalid:false,environmentLabel:''},
  onLoad(query){
    this.visitId=positive(query.visit)?Number(query.visit):null;
    this.id=positive(query.id)?Number(query.id):null;
    this.revision=positive(query.revision)?Number(query.revision):null;
    this.generation=0;
  },
  onShow(){return this.load();},
  async load(){
    const generation=++this.generation;
    // Clear the previous body, identifiers and subject before every read so a
    // failed or late response can never leave an older report on screen.
    this.setData({report:null,...blankSubject,busy:true,error:'',requestId:'',subjectInvalid:false});
    try{
      if(!positive(this.visitId)||!positive(this.id))throw Error('报告链接无效，请从就诊详情进入。');
      const query=this.revision?{revision:this.revision}:{};
      const data=await api.request(`visits/${this.visitId}/examinations/${this.id}/`,'GET',query);
      if(generation!==this.generation)return;
      api.showSubject(this);
      this.setData({report:buildReport(data),busy:false,environmentLabel:api.sessionInfo().environment_label||''});
    }catch(e){
      if(generation!==this.generation)return;
      const state=staleSubject(e,api.sessionInfo(),{uncodedConflictIsStale:false});
      // A delegate's 403 is a scope decision, not a lost subject; keep the
      // denial and the return path instead of prompting a subject switch.
      if(state.invalid&&e.status!==403)this.setData({report:null,...blankSubject,subjectInvalid:true});
      showError(this,e,{separateRequestId:true,stayOnPage:true});
      if(e.status===404)this.setData({error:'报告当前不可查看，请返回就诊核对',requestId:e.requestId||'',busy:false});
    }
  },
  onUnload(){this.generation++;},
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  back(){navigation.returnTo(`/pages/visit/index?id=${this.visitId}`);}
});
