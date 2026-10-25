const api = require('../../utils/api');
const {showError} = require('../../utils/format');
const intent=require('../../utils/booking-intent');
Page({
  data: {username: '', password: '', localCode:'',localConfirmed:false,identityProvider:'disabled',busy: false, error: ''},
  async onLoad() {
    try { const session=await api.bootstrap();this.setData({environmentLabel:session.environment_label||'',identityProvider:session.identity_provider});if(session.authenticated||session.account_authenticated)wx.reLaunch({url:intent.destination(getApp(),session)}); }
    catch (e) { showError(this, e); }
  },
  field(e) { this.setData({[e.currentTarget.dataset.field]: e.detail.value}); },
  consent(e){this.setData({localConfirmed:e.detail.value.includes('agree')});},
  async localLogin(){
    if(this.data.busy)return;
    if(!this.data.localCode||!this.data.localConfirmed){this.setData({error:'请填写新签发的本地授权码，并明确同意模拟登录。'});return;}
    this.setData({busy:true,error:''});
    try{
      const session=await api.localSignIn(this.data.localCode,this.data.username.trim(),this.data.password,this.data.localConfirmed);
      wx.reLaunch({url:intent.destination(getApp(),session)});
    }catch(e){showError(this,e);}
    finally{this.setData({localCode:'',password:'',busy:false});}
  },
  async login() {
    if (this.data.busy) return;
    if (!this.data.username.trim() || !this.data.password) { this.setData({error:'请填写分配的账号和密码。'}); return; }
    this.setData({busy:true, error:''});
    try {
      const session=await api.signIn(this.data.username.trim(), this.data.password);
      this.setData({password:''}); wx.reLaunch({url:intent.destination(getApp(),session)});
    } catch (e) { this.setData({password:''}); showError(this, e); }
  }
});
