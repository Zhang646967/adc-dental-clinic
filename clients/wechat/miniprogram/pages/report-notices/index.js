const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {showError,dateTime}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const {positive}=require('../../utils/booking-intent');
const {buildNoticeList}=require('../../utils/report-notices');

const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};
const blankNotices={rows:[],unreadCount:null,hasPrevious:false,hasNext:false,focusId:null,...blankSubject};
// A row opened from this list stays the return anchor for one back gesture.
// The window is short on purpose: a stale anchor must never move a later visit.
const RETURN_TTL=10*60*1000;
// Bounded lookup when sorting or pagination moved the row to another page.
const LOOKUP_PAGES=4;

function actionUrl(row,action){
  if(action==='open')return row.url;
  if(action==='visit')return row.visitUrl;
  return row.canOpen?'':row.contactUrl;
}

Page({
  data:{...blankNotices,page:1,busy:false,error:'',requestId:'',subjectInvalid:false,
    selfOnly:false,returnMedical:false,environmentLabel:'',readOnly:false,focusId:null},
  onLoad(query){
    const requested=positive(query&&query.page)?Number(query.page):1;
    this.page=requested;
    this.entryPage=requested;
    this.generation=0;
    this.returnTarget=null;
    this.setData({page:requested});
  },
  onShow(){
    // A back gesture returns here with the anchor set by the row action. It is
    // consumed once and only for the same patient and workspace that opened it.
    const target=this.consumeTarget();
    const page=target?target.page:(this.entryPage||1);
    this.entryPage=null;
    return this.load(page,target);
  },
  onHide(){this.generation++;this.setData(blankNotices);},
  onUnload(){this.generation++;this.returnTarget=null;},
  context(){
    const session=api.sessionInfo()||{};
    return {subjectKey:session.subject_key||'',workspaceId:session.workspace_id||'',
      revision:session.subject_revision};
  },
  sameContext(stored){
    if(!stored)return false;
    const current=this.context();
    return stored.subjectKey===current.subjectKey && stored.workspaceId===current.workspaceId &&
      stored.revision===current.revision;
  },
  remember(row,action){
    const anchor=row&&positive(row.id)?{id:row.id,action,url:actionUrl(row,action),page:this.data.page||1,
      context:this.context(),expires:Date.now()+RETURN_TTL}:null;
    this.returnTarget=anchor&&api.sessionInfo().authenticated?anchor:null;
  },
  consumeTarget(){
    const target=this.returnTarget;
    this.returnTarget=null;
    if(!target)return null;
    if(!(target.expires>Date.now()))return null;
    if(!api.sessionInfo().authenticated)return null;
    // The patient, delegate scope or workspace may have changed while the
    // detail page was open; the old anchor belongs to that identity only.
    return this.sameContext(target.context)?target:null;
  },
  async load(page=1,target=null){
    const generation=++this.generation;
    this.page=page;
    // Drop the previous patient's notices and unread count before reading; a
    // denied or stale request must never leave another patient's row on screen.
    this.setData({...blankNotices,error:'',requestId:'',busy:true,subjectInvalid:false,selfOnly:false,
      returnMedical:false,focusId:null});
    try{
      const data=await api.request('report-notices/','GET',{page});
      if(generation!==this.generation)return;
      const located=target?await this.locate(target,data,generation):{list:buildNoticeList(data),found:null};
      if(generation!==this.generation)return;
      if(!located)return this.load(1);
      const list=located.list;
      this.page=list.page;
      api.showSubject(this);
      this.setData({...list,busy:false,readOnly:!!api.sessionInfo().read_only,
        environmentLabel:api.sessionInfo().environment_label||'',
        focusId:located.found?target.id:null});
      if(located.found)this.scrollToNotice(target,generation);
    }catch(e){
      if(generation!==this.generation)return;
      this.showNoticeError(e);
    }
  },
  // The anchor is matched by notice id, never by row position. If sorting or a
  // correction moved it to another page, the current authorized list is walked
  // a bounded number of pages; a missing row falls back to the first page.
  async locate(target,first,generation){
    const original=buildNoticeList(first);
    let list=original;
    let nextPage=1;
    const visited=new Set();
    while(!visited.has(list.page)&&visited.size<LOOKUP_PAGES){
      if(!api.sessionInfo().authenticated||!this.sameContext(target.context))return null;
      if(target.expires<=Date.now())break;
      visited.add(list.page);
      const row=list.rows.find(item=>item.id===target.id);
      if(row)return {list,found:!!target.url&&actionUrl(row,target.action)===target.url};
      while(visited.has(nextPage))nextPage++;
      if(visited.size===LOOKUP_PAGES||(nextPage>list.page&&!list.hasNext))break;
      const data=await api.request('report-notices/','GET',{page:nextPage++});
      if(generation!==this.generation)return null;
      list=buildNoticeList(data);
    }
    return {list:original,found:false};
  },
  scrollToNotice(target,generation){
    // Restore the reading position on the row itself, not on an index: the
    // list may have been re-read and re-sorted while the report was open.
    const id=target.id;
    const current=()=>this.generation===generation&&this.data.focusId===id&&
      this.sameContext(target.context)&&!!api.sessionInfo().authenticated&&target.expires>Date.now();
    const run=()=>{
      if(!current()||typeof wx==='undefined'||!wx.createSelectorQuery)return;
      const query=wx.createSelectorQuery();
      query.selectViewport().scrollOffset();
      query.select('#notice-'+id).boundingClientRect();
      query.exec(result=>{
        const viewport=result&&result[0], box=result&&result[1];
        if(!box||!current())return;
        const top=Math.max(0,(viewport?viewport.scrollTop:0)+box.top-16);
        if(wx.pageScrollTo)wx.pageScrollTo({scrollTop:top,duration:0});
      });
    };
    if(typeof wx!=='undefined'&&wx.nextTick)wx.nextTick(run); else run();
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
    this.remember(row,'open');
    navigation.navigateTo({url:row.url});
  },
  contact(e){
    const row=this.data.rows[Number(e.currentTarget.dataset.index)];
    if(!row)return;
    this.remember(row,'contact');
    navigation.navigateTo({url:row.contactUrl});
  },
  rememberVisit(e){
    const row=this.data.rows[Number(e.currentTarget.dataset.index)];
    if(!row)return;
    this.remember(row,'visit');
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
          item.occurredLabel&&item.occurredLabel+'（北京时间）'].filter(Boolean).join('，')}):item);
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
