const api = require('../../utils/api');
const {showError} = require('../../utils/format');
Page({
  data: {username: '', password: '', busy: false, error: ''},
  async onLoad() {
    try { const session=await api.bootstrap();this.setData({environmentLabel:session.environment_label||''});if(session.authenticated)wx.reLaunch({url:'/pages/home/index'}); }
    catch (e) { showError(this, e); }
  },
  field(e) { this.setData({[e.currentTarget.dataset.field]: e.detail.value}); },
  async login() {
    if (this.data.busy) return;
    if (!this.data.username.trim() || !this.data.password) { this.setData({error:'请填写分配的账号和密码。'}); return; }
    this.setData({busy:true, error:''});
    try {
      await api.signIn(this.data.username.trim(), this.data.password);
      this.setData({password:''}); wx.reLaunch({url:'/pages/home/index'});
    } catch (e) { this.setData({password:''}); showError(this, e); }
  }
});
