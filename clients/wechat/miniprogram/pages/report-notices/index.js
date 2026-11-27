const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {showError,dateTime}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const {positive}=require('../../utils/booking-intent');
const {buildNoticeList}=require('../../utils/report-notices');

const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};
const blankNotices={rows:[],unreadCount:null,hasPrevious:false,hasNext:false,...blankSubject};

Page({
  data:{...blankNotices,page:1,busy:false,error:'',requestId:'',subjectInvalid:false,
    selfOnly:false,returnMedical:false,environmentLabel:'',readOnly:false},
  onLoad(query){
    const requested=positive(query&&query.page)?Number(query.page):1;
    this.page=requested;
    this.generation=0;
    this.setData({page:requested});
  },
  onShow(){return this.load(this.page||1);},
  onHide(){this.generation++;this.setData(blankNotices);},
  onUnload(){this.generation++;},
  async load(page=1){
    const generation=++this.generation;
    this.page=page;
    // Drop the previous patient's notices and unread count before reading; a
    // denied or stale request must never leave another patient's row on screen.
    this.setData({...blankNotices,error:'',requestId:'',busy:true,subjectInvalid:false,selfOnly:false,returnMedical:false});
    try{
      const data=await api.request('report-notices/','GET',{page});
      if(generation!==this.generation)return;
      const list=buildNoticeList(data);
      this.page=list.page;
      api.showSubject(this);
      this.setData({...list,busy:false,readOnly:!!api.sessionInfo().read_only,environmentLabel:api.sessionInfo().environment_label||''});
    }catch(e){
      if(generation!==this.generation)return;
      this.showNoticeError(e);
    }
  },
  showNoticeError(error){
    const session=api.sessionInfo();
    const selfOnly=error.status===403&&error.code==='REPORT_SELF_REQUIRED';
    const subjectInvalid=!selfOnly&&staleSubject(error,session,{uncodedConflictIsStale:false}).invalid;
    if(selfOnly||subjectInvalid)this.setData(blankNotices);
    this.setData({selfOnly,subjectInvalid,returnMedical:selfOnly&&!!session.medical&&!session.can_book});
    showError(this,error,{separateRequestId:true,stayOnPage:true});
  },
  retry(){return this.load(this.page||1);},
  turn(e){
    if(this.data.busy)return;
    const page=this.data.page+Number(e.currentTarget.dataset.step);
    if(!Number.isSafeInteger(page)||page<1)return;
    if(page>this.data.page&&!this.data.hasNext)return;
    return this.load(page);
  },
  open(e){
    const row=this.data.rows[Number(e.currentTarget.dataset.index)];
    if(!row||!row.canOpen)return;
    navigation.navigateTo({url:row.url});
  },
  contact(e){
    const row=this.data.rows[Number(e.currentTarget.dataset.index)];
    if(!row)return;
    navigation.navigateTo({url:row.contactUrl});
  },
  // Only an explicit tap writes the shared read state. A repeat tap on an
  // already-read row keeps the original read time from the server.
  async markRead(e){
    const index=Number(e.currentTarget.dataset.index);
    const row=this.data.rows[index];
    if(!row||!row.unread||this.data.busy||this.data.readOnly)return;
    const generation=this.generation;
    this.setData({busy:true,error:'',requestId:''});
    try{
      const r=await api.request(`report-notices/${row.id}/read/`,'POST',{});
      if(generation!==this.generation)return;
      const rows=this.data.rows.map((item,i)=>i===index?Object.assign({},item,{
        unread:false,readAt:r.read_at||item.readAt,readLabel:'已读',
        readLabelFull:'已读'+(r.read_at||item.readAt?' '+dateTime(r.read_at||item.readAt):''),
        ariaLabel:[item.heading,item.showStatus?item.statusLabel:'','已读',item.clinic,
          item.occurredLabel&&item.occurredLabel+'（北京时间）']
          .filter(Boolean).join('，')}):item);
      let unread=this.data.unreadCount;
      if(Number.isInteger(r.unread_count)&&r.unread_count>=0)unread=r.unread_count;
      else if(Number.isInteger(unread))unread=Math.max(0,unread-1);
      this.setData({rows,unreadCount:unread,busy:false});
    }catch(error){
      if(generation!==this.generation)return;
      // A corrected or withdrawn report can retire the old row; re-read the
      // list so the patient sees the current notice instead of a dead entry.
      if(error.status===404||error.status===409)return this.load(this.page||1);
      this.showNoticeError(error);
    }
  },
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  back(){navigation.returnTo(this.data.returnMedical?'/pages/medical-authorizations/index':'/pages/home/index');}
});
