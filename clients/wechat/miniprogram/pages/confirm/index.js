const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const intent=require('../../utils/booking-intent');
const {arrangement,showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const actions={
  booking:['确认就诊安排','我已核对诊所、服务、医师和起止时间，同意提交预约。','确认提交预约','确认成功后产生一次预约，接诊时再确认实际治疗。'],
  reschedule:['确认预约改期','我已核对原、新医师和时间，同意用新安排替代原预约。','确认改期','成功后替换指定原预约，其他候补不会自动退出。'],
  cancel:['确认取消','我确认取消这一次预约，保留历史记录。','确认取消这次预约','取消只影响这一条预约，已保存的历史继续保留。'],
  wait_join:['核对候补偏好','我确认以上可接受范围，理解登记候补尚未形成预约。','确认登记候补','前台核对时段后提供邀约，由你决定是否接受。'],
  wait_withdraw:['确认退出候补','我确认退出这条候补，撤回未确认的邀约，保留已有预约。','确认退出候补','退出不会取消已经存在的正式预约。'],
  offer_accept:['确认新增预约','我同意接受邀约并新增一次就诊，其他已有预约继续保留。','接受并新增预约','本次为新增安排；若需替换原约，请返回明确选择原预约。'],
  offer_decline:['确认拒绝邀约','我确认拒绝这次邀约，候补继续等待安排，已有预约保留。','确认拒绝本次邀约','本次临时保留将释放，前台可继续协调新的安排。']
};
Page({
  data:{review:null,checked:false,busy:false,error:'',done:null,subjectInvalid:false,followupVisit:null,followupBlocked:false},
  onLoad(){ api.showSubject(this);
    const review=getApp().globalData.review;
    const session=api.sessionInfo();
    if(review && (review.subjectKey!==session.subject_key || review.workspaceKey!==session.workspace_id || review.subjectRevision!==session.subject_revision)){
      this.invalidateSubject(new Error('就诊人已变化，请重新核对预约。'));
      return;
    }
    if(!review){this.setData({error:'核对内容已失效，请返回我的预约重新办理。'});return;}
    const display=Object.assign({},review,{preview:Object.assign({},review.preview)});
    if(display.preview.original)display.preview.original=arrangement(display.preview.original);
    this.kind=review.kind;
    this.fromWaitlist=review.fromWaitlist;
    const copy=actions[review.kind];
    this.setData({review:display,title:copy[0],consent:copy[1],button:copy[2],note:copy[3],followupVisit:review.followupVisit||null});
  },
  checked(e){if(this.data.review)this.setData({checked:e.detail.value.includes('yes')});},
  async submit(){
    if(this.data.busy||this.data.uncertain||this.data.done||!this.data.checked||!this.data.review)return;
    this.setData({busy:true,error:'',requestId:''});
    try{const r=await api.request(this.data.review.path,'POST',{proposal_token:this.data.review.preview.proposal_token,confirmed:'on'});
      getApp().globalData.review=null;
      this.setData({done:r.kind==='waitlist'?r.wait:arrangement(r.visit||r),doneType:r.kind==='waitlist'?'waitlist':'visit',busy:false});
    }catch(e){
      if(staleSubject(e,api.sessionInfo(),{uncodedConflictIsStale:false}).invalid){
        this.invalidateSubject(e);
        return;
      }
      if(e.code==='NETWORK_UNCONFIRMED'){
        getApp().globalData.review=null;
        this.setData({uncertain:true,review:null,checked:false});
      }
      // A follow-up booking that hits a conflict or an unconfirmed result can
      // always go back to the original visit to read the real state.
      if(this.data.followupVisit&&(e.status===409||e.code==='NETWORK_UNCONFIRMED'||e.code==='BUSINESS_CONFLICT'))this.setData({followupBlocked:true});
      showError(this,e,{separateRequestId:true});
    }
  },
  invalidateSubject(error){
    getApp().globalData.review=null;
    this.setData({
      review:null,checked:false,done:null,subjectInvalid:true,uncertain:error.code==='SUBJECT_CHANGED',
      patientName:'',patientCapacity:'',patientDelegated:false
    });
    showError(this,error,{separateRequestId:true,stayOnPage:true});
  },
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  subjects(){
    if(this.data.busy||this.data.subjectInvalid)return;
    const selection=this.data.review&&this.data.review.selection;
    if(selection)intent.remember(getApp(),selection.service,selection.clinic,selection.dentist,selection.day,selection.category);
    getApp().globalData.review=null;
    navigation.reLaunch({url:'/pages/patients/index'});
  },
  home(){
    if(this.data.subjectInvalid)return;
    getApp().globalData.review=null;
    const waitlist=this.fromWaitlist||this.kind==='offer_accept'||this.kind==='wait_join'||this.kind==='wait_withdraw'||this.kind==='offer_decline';
    const visits=this.data.uncertain?'/pages/home/index?queue=all':'/pages/home/index';
    navigation.reLaunch({url:waitlist?'/pages/waitlist/index':visits});
  },
  result(){navigation.redirectTo({url:this.data.doneType==='waitlist'?'/pages/waitlist/index':`/pages/visit/index?id=${this.data.done.id}`});},
  visitCheck(){
    if(!this.data.followupVisit)return;
    getApp().globalData.review=null;
    navigation.reLaunch({url:`/pages/visit/index?id=${this.data.followupVisit}`});
  }
});
