const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {showError} = require('../../utils/format');
const intent=require('../../utils/booking-intent');
Page({
  data: {smsMode:true,captchaKey:'',captchaImage:'',passwordMode:false,username: '', password: '', localCode:'',localConfirmed:false,authConfirmed:false,auth:{},phone:'',smsCode:'',smsChallenge:'',smsNotice:'',identityProvider:'disabled',busy: false, error: ''},
  async onLoad() {
    try { const session=await api.bootstrap();this.setData({auth:session.auth_capabilities||{},smsMode:!(session.auth_capabilities||{}).wechat_mini,passwordMode:!((session.auth_capabilities||{}).sms_enabled||(session.auth_capabilities||{}).wechat_mini),environmentLabel:session.environment_label||'',identityProvider:session.identity_provider});if(session.authenticated||session.account_authenticated)navigation.reLaunch({url:intent.destination(getApp(),session)}); }
    catch (e) { showError(this, e); }
  },
  field(e) { this.setData({[e.currentTarget.dataset.field]: e.detail.value}); },
  toggleSms(){this.setData({smsMode:!this.data.smsMode});},
  async captcha(){try{const result=await api.request('auth/sms/captcha/','POST',{});this.setData({captchaImage:result.image,captchaKey:''});}catch(e){showError(this,e);}},
  togglePassword(){this.setData({passwordMode:!this.data.passwordMode,password:'',error:''});},
  consent(e){this.setData({localConfirmed:e.detail.value.includes('agree')});},
  authConsent(e){this.setData({authConfirmed:e.detail.value.includes('agree')});},
  async wechatLogin(){
    if(this.data.busy)return;
    if(!this.data.authConfirmed){this.setData({error:'请先同意使用微信身份登录本人患者账号。'});return;}
    this.setData({busy:true,error:''});
    try{
      const credential=await new Promise((resolve,reject)=>wx.login({success:resolve,fail:()=>reject(new Error('微信登录未完成，请重新点击授权。'))}));
      const session=await api.request('auth/wechat/','POST',{code:credential.code,confirmed:'on',username:this.data.username.trim(),password:this.data.password});
      navigation.reLaunch({url:intent.destination(getApp(),session)});
    }catch(e){showError(this,e);}finally{this.setData({busy:false,password:''});}
  },
  async sendSms(){
    if(this.data.busy)return;
    if(!this.data.authConfirmed){this.setData({error:'请先同意接收验证码并办理本人账号。'});return;}
    this.setData({busy:true,error:''});
    try{
      const sent=await api.request('auth/sms/send/','POST',{phone:this.data.phone,confirmed:'on',captcha_key:this.data.captchaKey});
      this.setData({smsChallenge:sent.challenge,smsCode:'',smsNotice:sent.demo?'测试验证码：'+sent.test_code+'（未发送短信）':'验证码已提交发送，'+Math.ceil((sent.expires_seconds||300)/60)+'分钟内有效；60秒后可重发。'});
    }catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  async smsLogin(){
    if(this.data.busy)return;
    if(!this.data.authConfirmed||!this.data.smsChallenge||!this.data.smsCode){this.setData({error:'请获取并填写验证码，确认同意后继续。'});return;}
    this.setData({busy:true,error:''});
    try{
      const session=await api.request('auth/sms/confirm/','POST',{phone:this.data.phone,challenge:this.data.smsChallenge,code:this.data.smsCode,confirmed:'on'});
      navigation.reLaunch({url:intent.destination(getApp(),session)});
    }catch(e){showError(this,e);}finally{this.setData({busy:false,smsCode:'',smsNotice:''});}
  },
  async localLogin(){
    if(this.data.busy)return;
    if(!this.data.localCode||!this.data.localConfirmed){this.setData({error:'请填写新签发的本地授权码，并明确同意模拟登录。'});return;}
    this.setData({busy:true,error:''});
    try{
      const session=await api.localSignIn(this.data.localCode,this.data.username.trim(),this.data.password,this.data.localConfirmed);
      navigation.reLaunch({url:intent.destination(getApp(),session)});
    }catch(e){showError(this,e);}
    finally{this.setData({localCode:'',password:'',busy:false});}
  },
  async login() {
    if (this.data.busy) return;
    if (!this.data.username.trim() || !this.data.password) { this.setData({error:'请填写原患者账号和密码。'}); return; }
    this.setData({busy:true, error:''});
    try {
      const session=await api.signIn(this.data.username.trim(), this.data.password);
      this.setData({password:''}); navigation.reLaunch({url:intent.destination(getApp(),session)});
    } catch (e) { this.setData({password:''}); showError(this, e); }
  },
  onUnload(){this.setData({password:'',localCode:'',smsCode:'',smsChallenge:'',smsNotice:''});}
});
