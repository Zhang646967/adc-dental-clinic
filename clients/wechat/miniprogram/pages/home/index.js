const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
Page({
  data:{guest:false,needsSubject:false,needsEnrollment:false,rows:[], queue:'active', page:1, pages:1, busy:false, error:'', patient:'', readOnly:false, overview:null},
  async onShow() { this.setData({rows:[],overview:null,patient:'',error:''});api.showSubject(this);
    try {
      const session = await api.bootstrap();api.showSubject(this);
      if(!session.authenticated||session.subject_required){this.setData({guest:!session.account_authenticated,needsSubject:!!session.subject_required,needsEnrollment:session.account_authenticated&&!session.authenticated,busy:false});return;}
      this.setData({guest:false,needsSubject:false,needsEnrollment:false});
      this.setData({patient:session.patient_name, readOnly:session.read_only,environmentLabel:session.environment_label||''}); await this.load();
    } catch (e) { showError(this, e); }
  },
  login(){navigation.navigateTo({url:'/pages/login/index'});},
  subjects(){navigation.navigateTo({url:'/pages/patients/index'});},
  account(){navigation.navigateTo({url:'/pages/account/index'});},
  async load() {
    this.setData({busy:true, error:''});
    try {
      const [d,overview] = await Promise.all([api.request('visits/', 'GET', {queue:this.data.queue, page:this.data.page}), api.request('overview/')]);
      if(overview.next_visit)overview.next_visit=arrangement(overview.next_visit);
      this.setData({rows:d.rows.map(arrangement), page:d.page, pages:d.pages, overview, busy:false});
    }
    catch (e) { showError(this,e); }
  },
  changeQueue(e) { if (this.data.busy) return; this.setData({queue:e.currentTarget.dataset.queue, page:1}); this.load(); },
  turn(e) { if (this.data.busy) return; this.setData({page:this.data.page+Number(e.currentTarget.dataset.step)}); this.load(); },
  open(e) { navigation.navigateTo({url:`/pages/visit/index?id=${e.currentTarget.dataset.id}`}); },
  book() { navigation.navigateTo({url:'/pages/services/index'}); },
  async logout() { try { await api.signOut(); getApp().globalData.bookingIntent=null;navigation.reLaunch({url:'/pages/discovery/index'}); } catch(e) { showError(this,e); } }
});
