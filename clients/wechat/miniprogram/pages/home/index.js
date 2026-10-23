const api = require('../../utils/api');
const {arrangement, showError} = require('../../utils/format');
Page({
  data:{rows:[], queue:'active', page:1, pages:1, busy:false, error:'', patient:'', readOnly:false, overview:null},
  async onShow() {
    try {
      const session = await api.bootstrap();
      if (!session.authenticated) { wx.reLaunch({url:'/pages/login/index'}); return; }
      this.setData({patient:session.patient_name, readOnly:session.read_only,environmentLabel:session.environment_label||''}); await this.load();
    } catch (e) { showError(this, e); }
  },
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
  open(e) { wx.navigateTo({url:`/pages/visit/index?id=${e.currentTarget.dataset.id}`}); },
  book() { wx.navigateTo({url:'/pages/services/index'}); },
  async logout() { try { await api.signOut(); wx.reLaunch({url:'/pages/login/index'}); } catch(e) { showError(this,e); } }
});
