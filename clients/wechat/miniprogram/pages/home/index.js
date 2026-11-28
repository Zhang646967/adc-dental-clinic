const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
const {record} = require('../../utils/visit-record');
const {primaryAction} = require('../../utils/primary-action');
const {staleSubject} = require('../../utils/subject-state');
const {reportEntry}=require('../../utils/report-notices');
const textScale=require('../../utils/text-scale');
const blankList = {rows:[], overview:null, primary:null, reportEntry:null, reportUnread:0};
const blankSubject = {patient:'', patientName:'', patientCapacity:'', patientDelegated:false};
Page({
  loadGeneration:0,
  data:{guest:false,needsSubject:false,needsEnrollment:false,subjectInvalid:false,rows:[], queue:'active', page:1, pages:1, busy:false, error:'', patient:'', readOnly:false, overview:null, primary:null, reportEntry:null, reportUnread:0, textScale:''},
  async onShow() {
    // Read the WeChat font size on every entry, including a return from a
    // detail page, so the list uses the step that is in effect now.
    textScale.apply(this);
    const generation=++this.loadGeneration;
    this.sessionReady=false;
    const pending=navigation.consume('/pages/home/index');
    if(pending&&['active','all','history'].includes(pending.queue))this.setData({queue:pending.queue,page:1});
    this.setData({...blankList,...blankSubject,error:'',requestId:'',subjectInvalid:false,busy:true,guest:false,needsSubject:false,needsEnrollment:false});
    try {
      const session = await api.bootstrap();
      if(generation!==this.loadGeneration)return;
      if(!session.authenticated||session.subject_required){this.setData({guest:!session.account_authenticated,needsSubject:!!session.subject_required,needsEnrollment:session.account_authenticated&&!session.authenticated,busy:false});return;}
      if(session.medical&&!session.can_book){this.setData({busy:false});navigation.redirectTo({url:'/pages/medical-authorizations/index'});return;}
      this.sessionReady=true;
      api.showSubject(this);
      this.setData({guest:false,needsSubject:false,needsEnrollment:false});
      this.setData({patient:session.patient_name, readOnly:session.read_only,environmentLabel:session.environment_label||''}); await this.load();
    } catch (e) {
      if(generation!==this.loadGeneration)return;
      this.clearStaleSubject(e); showError(this,e,{separateRequestId:true});
    }
  },
  onHide(){
    this.loadGeneration++;
    this.sessionReady=false;
    this.setData({...blankList,...blankSubject});
  },
  onUnload(){this.loadGeneration++;},
  login(){navigation.navigateTo({url:'/pages/login/index'});},
  subjects(){navigation.navigateTo({url:'/pages/patients/index'});},
  account(){navigation.navigateTo({url:'/pages/account/index'});},
  // Both entry points (page show and in-page refresh) must drop the cached
  // subject banner when the authority or workspace is no longer valid.
  clearStaleSubject(e){
    const state=staleSubject(e,api.sessionInfo());
    if(state.invalid){
      this.setData({patientName:'',patientCapacity:'',patientDelegated:false,patient:'',
        rows:[],overview:null,primary:null,reportEntry:null,reportUnread:0,subjectInvalid:state.reselect});
    }
    return state;
  },
  async load() {
    // Drop the previous subject's rows, overview and primary action before a
    // refresh. A 403 ACCESS_DENIED or 409 SUBJECT_REQUIRED / SUBJECT_CHANGED
    // means the old data no longer belongs to this session; leaving it on
    // screen would show appointments the patient can no longer access.
    // A queue switch may arrive while the first read is still in flight; the
    // newest read owns the screen so a late response cannot restore the old
    // range or its disclosure state.
    const generation=++this.loadGeneration;
    this.setData({...blankList,error:'',requestId:'',busy:true});
    try {
      const [d,overview] = await Promise.all([api.request('visits/', 'GET', {queue:this.data.queue, page:this.data.page}), api.request('overview/')]);
      if(generation!==this.loadGeneration)return;
      if(overview.next_visit)overview.next_visit=arrangement(overview.next_visit);
      // Older backends omit primary_action; keep the existing entries then.
      const primary=primaryAction(overview,{readOnly:this.data.readOnly});
      // The report entry is a patient capability: a delegate or an overview
      // without report_unread_count must not show it.
      const entry=reportEntry(overview,{delegated:this.data.patientDelegated});
      // Every reload rebuilds the rows, so one record's disclosure can never
      // reappear open on another record or after a subject change.
      const rows=d.rows.map(row=>record(row,{delegated:this.data.patientDelegated,readOnly:this.data.readOnly})).filter(Boolean);
      this.setData({rows, page:d.page, pages:d.pages, overview, primary,
        reportEntry:entry, reportUnread:entry?entry.unread:0, busy:false});
    }
    catch (e) {
      if(generation!==this.loadGeneration)return;
      this.clearStaleSubject(e);
      showError(this,e,{separateRequestId:true});
    }
  },
  primaryTap() {
    const primary=this.data.primary;
    if(!primary||!primary.url)return;
    navigation.navigateTo({url:primary.url});
  },
  changeQueue(e) {
    const queue=e.currentTarget.dataset.queue;
    if(!['active','history','all'].includes(queue)||queue===this.data.queue)return;
    // A tap during the first read still switches; the newest read wins.
    this.setData({queue, page:1});
    if(this.sessionReady)return this.load();
  },
  turn(e) { if (this.data.busy) return; this.setData({page:this.data.page+Number(e.currentTarget.dataset.step)}); this.load(); },
  // The list range travels with the record so the detail's own way back
  // lands on the same queue the patient was reading.
  open(e) {
    const id=Number(e.currentTarget.dataset.id);
    if(!Number.isSafeInteger(id)||id<=0)return;
    navigation.navigateTo({url:`/pages/visit/index?id=${id}&queue=${this.data.queue}`});
  },
  toggleRow(e){
    const id=Number(e.currentTarget.dataset.id);
    if(!Number.isSafeInteger(id)||id<=0)return;
    this.setData({rows:this.data.rows.map(row=>row.id===id?Object.assign({},row,{open:!row.open}):row)});
  },
  book() { navigation.navigateTo({url:'/pages/services/index'}); },
  async logout() { try { await api.signOut(); getApp().globalData.bookingIntent=null;navigation.reLaunch({url:'/pages/discovery/index'}); } catch(e) { showError(this,e,{separateRequestId:true}); } }
});
