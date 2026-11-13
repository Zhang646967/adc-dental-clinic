const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
const {primaryAction} = require('../../utils/primary-action');
const {staleSubject} = require('../../utils/subject-state');
// The projection is optional at load time so a harness that stubs modules
// cannot break the page; the real build always ships it.
const {reportEntry}=require('../../utils/report-notices');
Page({
  data:{guest:false,needsSubject:false,needsEnrollment:false,subjectInvalid:false,rows:[], queue:'active', page:1, pages:1, busy:false, error:'', patient:'', readOnly:false, overview:null, primary:null, reportEntry:null, reportUnread:0},
  async onShow() {
    const pending=navigation.consume('/pages/home/index');
    if(pending&&['all','history'].includes(pending.queue))this.setData({queue:pending.queue,page:1});
    this.setData({rows:[],overview:null,primary:null,reportEntry:null,reportUnread:0,patient:'',error:'',requestId:'',subjectInvalid:false,busy:true,guest:false,needsSubject:false,needsEnrollment:false});
    api.showSubject(this);
    try {
      const session = await api.bootstrap();api.showSubject(this);
      if(!session.authenticated||session.subject_required){this.setData({guest:!session.account_authenticated,needsSubject:!!session.subject_required,needsEnrollment:session.account_authenticated&&!session.authenticated,busy:false});return;}
      if(session.medical&&!session.can_book){this.setData({busy:false});navigation.redirectTo({url:'/pages/medical-authorizations/index'});return;}
      this.setData({guest:false,needsSubject:false,needsEnrollment:false});
      this.setData({patient:session.patient_name, readOnly:session.read_only,environmentLabel:session.environment_label||''}); await this.load();
    } catch (e) { this.clearStaleSubject(e); showError(this,e,{separateRequestId:true}); }
  },
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
    this.setData({rows:[],overview:null,primary:null,reportEntry:null,reportUnread:0,error:'',requestId:'',busy:true});
    try {
      const [d,overview] = await Promise.all([api.request('visits/', 'GET', {queue:this.data.queue, page:this.data.page}), api.request('overview/')]);
      if(overview.next_visit)overview.next_visit=arrangement(overview.next_visit);
      // Older backends omit primary_action; keep the existing entries then.
      const primary=primaryAction(overview);
      // The report entry is a patient capability: a delegate or an overview
      // without report_unread_count must not show it.
      const entry=reportEntry(overview,{delegated:this.data.patientDelegated});
      this.setData({rows:d.rows.map(arrangement), page:d.page, pages:d.pages, overview, primary,
        reportEntry:entry, reportUnread:entry?entry.unread:0, busy:false});
    }
    catch (e) {
      this.clearStaleSubject(e);
      showError(this,e,{separateRequestId:true});
    }
  },
  primaryTap() {
    const primary=this.data.primary;
    if(!primary||!primary.url)return;
    navigation.navigateTo({url:primary.url});
  },
  changeQueue(e) { if (this.data.busy) return; this.setData({queue:e.currentTarget.dataset.queue, page:1}); this.load(); },
  turn(e) { if (this.data.busy) return; this.setData({page:this.data.page+Number(e.currentTarget.dataset.step)}); this.load(); },
  open(e) { navigation.navigateTo({url:`/pages/visit/index?id=${e.currentTarget.dataset.id}`}); },
  book() { navigation.navigateTo({url:'/pages/services/index'}); },
  async logout() { try { await api.signOut(); getApp().globalData.bookingIntent=null;navigation.reLaunch({url:'/pages/discovery/index'}); } catch(e) { showError(this,e,{separateRequestId:true}); } }
});
