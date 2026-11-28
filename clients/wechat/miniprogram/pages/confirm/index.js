const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const intent=require('../../utils/booking-intent');
const {arrangement,showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const {comparison}=require('../../utils/reschedule');
const textScale=require('../../utils/text-scale');
const actions={
  booking:['确认就诊安排','我已核对诊所、服务、医师和起止时间，同意提交预约。','确认提交预约','确认成功后产生一次预约，接诊时再确认实际治疗。'],
  reschedule:['确认预约改期','我已核对原、新医师和时间，同意用新安排替代原预约。','确认改期','成功后替换指定原预约，其他候补不会自动退出。'],
  cancel:['确认取消','我确认取消这一次预约，保留历史记录。','确认取消这次预约','取消只影响这一条预约，已保存的历史继续保留。'],
  wait_join:['核对候补偏好','我确认以上可接受范围，理解登记候补尚未形成预约。','确认登记候补','前台核对时段后提供邀约，由你决定是否接受。'],
  wait_withdraw:['确认退出候补','我确认退出这条候补，撤回未确认的邀约，保留已有预约。','确认退出候补','退出不会取消已经存在的正式预约。'],
  offer_accept:['确认新增预约','我同意接受邀约并新增一次就诊，其他已有预约继续保留。','接受并新增预约','本次为新增安排；若需替换原约，请返回明确选择原预约。'],
  offer_decline:['确认拒绝邀约','我确认拒绝这次邀约，候补继续等待安排，已有预约保留。','确认拒绝本次邀约','本次临时保留将释放，前台可继续协调新的安排。']
};
/* Only an appointment or a replacement has a server-side receipt to look up.
   Cancellation, waitlist and offer outcomes are read from their own records. */
const RECEIPT_KINDS={booking:'booking',reschedule:'reschedule'};
Page({
  data:{review:null,checked:false,busy:false,error:'',done:null,subjectInvalid:false,followupVisit:null,followupBlocked:false,
    previewNote:'',backLabel:'返回原页面',uncertain:false,querying:false,queryMessage:'',canQuery:false,
    resultKind:'',resultToken:'',resultSubjectKey:'',resultWorkspaceKey:'',resultSubjectRevision:0,
    conflict:false,conflictMessage:'',conflictTitle:'本次预约未保存',conflictKind:'',conflictOriginal:null,conflictSelection:null,conflictFollowup:null,
    otherUnconfirmed:false,otherFailed:false,recordLabel:'',recordUrl:'',textScale:''},
  onLoad(){ api.showSubject(this); textScale.apply(this);
    const review=getApp().globalData.review;
    const session=api.sessionInfo();
    if(review && (review.subjectKey!==session.subject_key || review.workspaceKey!==session.workspace_id || review.subjectRevision!==session.subject_revision)){
      this.invalidateSubject(new Error('就诊人已变化，请重新核对预约。'));
      return;
    }
    if(!review){this.setData({error:'核对内容已失效，请返回我的预约重新办理。'});return;}
    const display=Object.assign({},review,{preview:Object.assign({},review.preview)});
    if(display.preview.original)display.preview.original=arrangement(display.preview.original);
    // Two groups of facts: what is retained, and what is proposed. Both are
    // projected from the server response; a missing value stays empty.
    const facts=comparison(display.preview);
    this.kind=review.kind;
    this.fromWaitlist=review.fromWaitlist;
    const copy=actions[review.kind];
    // A receipt lookup exists only after an appointment confirmation has been
    // sent without a definite outcome. It is never part of the first preview.
    const previewNote=review.kind==='booking'?'待确认，尚未预约':review.kind==='reschedule'?'待确认，原预约仍保留':'';
    this.setData({review:display,comparison:facts,title:copy[0],consent:copy[1],button:copy[2],note:copy[3],
      followupVisit:review.followupVisit||null,previewNote,
      backLabel:review.kind==='booking'?'返回选时段':'返回原页面'});
  },
  // A return from the system menu re-reads the setting without rebuilding the
  // preview or touching the consent checkbox.
  onShow(){textScale.apply(this);},
  checked(e){if(this.data.review)this.setData({checked:e.detail.value.includes('yes')});},
  async submit(){
    if(this.data.busy||this.data.uncertain||this.data.done||this.data.conflict||this.data.followupBlocked||!this.data.checked||!this.data.review)return;
    const review=this.data.review;
    const token=review.preview.proposal_token;
    const kind=review.kind;
    this.setData({busy:true,error:'',requestId:''});
    try{
      const r=await api.request(review.path,'POST',{proposal_token:token,confirmed:'on'});
      const waitlist=r&&r.kind==='waitlist';
      const receipt=r&&(waitlist?r.wait:r.visit||r);
      if(!receipt||!Number.isSafeInteger(receipt.id)||receipt.id<1){
        throw new Error('没有收到带编号的办理回执。');
      }
      getApp().globalData.review=null;
      this.setData({done:waitlist?receipt:arrangement(receipt),doneType:waitlist?'waitlist':'visit',busy:false,checked:false});
    }catch(e){
      if(staleSubject(e,api.sessionInfo(),{uncodedConflictIsStale:false}).invalid){
        this.invalidateSubject(e);
        return;
      }
      if(e.code==='NETWORK_UNCONFIRMED'||this.ambiguous(e)){
        if(RECEIPT_KINDS[kind])this.enterUncertain(e,review);
        else this.unconfirmedRecord(e,review);
        return;
      }
      // An explicit business rejection (occupied slot, expired confirmation,
      // changed report source) invalidates this proposal. Never resubmit it.
      if(e.status===409&&e.code==='BUSINESS_CONFLICT'){
        if(RECEIPT_KINDS[kind])this.rejected(e,review);
        else this.failedRecord(e,review);
        return;
      }
      // A definite 4xx keeps the proposal usable for one corrected attempt,
      // except when the server says the receipt itself is no longer valid.
      if(e.status===404||e.status===410){
        if(RECEIPT_KINDS[kind])this.rejected(e,review);
        else this.failedRecord(e,review);
        return;
      }
      showError(this,e,{separateRequestId:true});
      this.setData({busy:false});
    }
  },
  /* A 5xx, a timeout or a success body without a receipt means the command may
     have committed. Only the receipt lookup can tell; never resend it. */
  ambiguous(e){
    return !e.status || e.status===408 || e.status>=500;
  },
  enterUncertain(error,review){
    getApp().globalData.review=null;
    const kind=RECEIPT_KINDS[review.kind];
    const token=review.preview.proposal_token;
    this.setData({busy:false,uncertain:true,review:null,checked:false,conflict:false,done:null,otherUnconfirmed:false,otherFailed:false,
      resultKind:kind,resultToken:token||'',
      resultSubjectKey:review.subjectKey||'',resultWorkspaceKey:review.workspaceKey||'',resultSubjectRevision:review.subjectRevision||0,
      canQuery:!!token,queryMessage:'',querying:false,
      error:error.requestId?(error.publicMessage||error.message||''):'',requestId:error.requestId||''});
  },
  /* Cancellation, waitlist and offer outcomes are not receipt lookups. Their
     own records already show whether the command took effect. */
  unconfirmedRecord(error,review){
    this.otherRecord(error,review,false);
  },
  failedRecord(error,review){
    this.otherRecord(error,review,true);
  },
  otherRecord(error,review,failed){
    getApp().globalData.review=null;
    const original=review.preview&&review.preview.original;
    const wait=review.kind==='wait_join'||review.kind==='wait_withdraw'||review.kind==='offer_accept'||review.kind==='offer_decline';
    this.setData({busy:false,otherUnconfirmed:true,otherFailed:!!failed,review:null,checked:false,uncertain:false,conflict:false,done:null,
      recordLabel:wait?'查看候补与邀约记录':'查看原预约核对',
      recordUrl:wait?'/pages/waitlist/index':original&&original.id?`/pages/visit/index?id=${original.id}`:'/pages/home/index?queue=all',
      error:error.publicMessage||error.message||'',requestId:error.requestId||''});
  },
  rejected(error,review){
    getApp().globalData.review=null;
    const reschedule=review.kind==='reschedule';
    const original=reschedule&&review.preview.original?{id:review.preview.original.id,clinic:review.preview.original.clinic,startLabel:review.preview.original.startLabel}:null;
    this.setData({busy:false,checked:false,review:null,conflict:true,conflictKind:review.kind,
      conflictMessage:error.publicMessage||error.message||'本次提交未保存，请重新核对。',
      conflictTitle:reschedule?'本次改期未保存':'本次预约未保存',
      conflictOriginal:original,conflictSelection:review.selection||null,conflictFollowup:review.followupVisit||null,
      followupBlocked:!!review.followupVisit,
      error:'',requestId:error.requestId||''});
  },
  /* Receipt recovery is a read: it must never create a second appointment.
     The proposal belongs to this page, workspace and patient only. */
  async queryResult(){
    if(this.data.querying||!this.data.resultToken||!this.data.canQuery)return;
    const session=api.sessionInfo();
    if((session.subject_key||'')!==this.data.resultSubjectKey||(session.workspace_id||'')!==this.data.resultWorkspaceKey||(session.subject_revision||0)!==this.data.resultSubjectRevision){
      this.invalidateSubject(new Error('就诊人已变化，请在当前患者页面重新核对结果。'));
      return;
    }
    this.setData({querying:true,queryMessage:''});
    try{
      const r=await api.request('booking/result/','POST',{kind:this.data.resultKind,proposal_token:this.data.resultToken});
      if(r&&r.state==='SAVED'&&Number.isSafeInteger(r.visit_id)&&r.visit_id>0){
        getApp().globalData.bookingRefresh=true;
        this.setData({querying:false,canQuery:false,resultToken:''});
        navigation.redirectTo({url:`/pages/visit/index?id=${r.visit_id}`});
        return;
      }
      this.setData({querying:false,queryMessage:'暂未查到本次提交的结果。可以稍后再查，或从原预约、原就诊和预约清单核对。'});
    }catch(e){
      if(staleSubject(e,api.sessionInfo(),{uncodedConflictIsStale:false}).invalid){
        this.invalidateSubject(e);
        return;
      }
      if(e.status===409&&e.code==='BUSINESS_CONFLICT'){
        this.setData({querying:false,canQuery:false,resultToken:'',requestId:e.requestId||'',
          queryMessage:'本次结果查询已失效，请从原预约、原就诊或预约清单核对。'});
        return;
      }
      const message=e.code==='NETWORK_UNCONFIRMED'?'暂时无法连接。':e.publicMessage||e.message||'暂时无法查询。';
      this.setData({querying:false,queryMessage:message+' 可以稍后再查。',requestId:e.requestId||''});
    }
  },
  invalidateSubject(error){
    getApp().globalData.review=null;
    this.setData({
      review:null,checked:false,done:null,subjectInvalid:true,uncertain:false,conflict:false,otherUnconfirmed:false,otherFailed:false,
      canQuery:false,resultToken:'',queryMessage:'',querying:false,
      patientName:'',patientCapacity:'',patientDelegated:false
    });
    showError(this,error,{separateRequestId:true,stayOnPage:true});
  },
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  subjects(){
    if(this.data.busy||this.data.querying||this.data.subjectInvalid)return;
    const selection=this.data.review&&this.data.review.selection;
    if(selection)intent.remember(getApp(),selection.service,selection.clinic,selection.dentist,selection.day,selection.category);
    getApp().globalData.review=null;
    navigation.reLaunch({url:'/pages/patients/index'});
  },
  home(){
    if(this.data.busy||this.data.querying||this.data.subjectInvalid)return;
    getApp().globalData.review=null;
    const waitlist=this.fromWaitlist||this.kind==='offer_accept'||this.kind==='wait_join'||this.kind==='wait_withdraw'||this.kind==='offer_decline';
    const visits=this.data.uncertain||this.data.conflict||this.data.otherUnconfirmed?'/pages/home/index?queue=all':'/pages/home/index';
    navigation.reLaunch({url:waitlist?'/pages/waitlist/index':visits});
  },
  openRecord(){
    if(this.data.busy||this.data.querying)return;
    getApp().globalData.review=null;
    navigation.reLaunch({url:this.data.recordUrl||'/pages/home/index?queue=all'});
  },
  result(){navigation.redirectTo({url:this.data.doneType==='waitlist'?'/pages/waitlist/index':`/pages/visit/index?id=${this.data.done.id}`});},
  visitCheck(){
    if(!this.data.followupVisit)return;
    getApp().globalData.review=null;
    navigation.reLaunch({url:`/pages/visit/index?id=${this.data.followupVisit}`});
  },
  openOriginal(){
    const original=this.data.conflictOriginal;
    if(!original||!original.id)return;
    getApp().globalData.review=null;
    navigation.reLaunch({url:`/pages/visit/index?id=${original.id}`});
  },
  /* Returning keeps the clinic, service, dentist, day and report binding that
     produced this proposal. The booking page refreshes its slot list so a slot
     that just became occupied cannot be selected again. */
  backToSelection(){
    if(this.data.busy||this.data.querying)return;
    const review=this.data.review;
    const selection=review?review.selection:this.data.conflictSelection;
    const followupVisit=review?review.followupVisit:this.data.conflictFollowup;
    getApp().globalData.review=null;
    if(selection)intent.remember(getApp(),selection.service,selection.clinic,selection.dentist,selection.day,selection.category);
    getApp().globalData.bookingRefresh=true;
    const pages=typeof getCurrentPages==='function'?getCurrentPages():[];
    const previous=pages&&pages.length>1?pages[pages.length-2]:null;
    if(previous){navigation.navigateBack({delta:1});return;}
    if(followupVisit){navigation.reLaunch({url:`/pages/visit/index?id=${followupVisit}`});return;}
    if(selection)navigation.reLaunch({url:`/pages/booking/index?clinic=${selection.clinic}&service=${selection.service}${selection.dentist?'&dentist='+selection.dentist:''}${selection.day?'&day='+selection.day:''}`});
    else navigation.reLaunch({url:'/pages/services/index'});
  }
});
