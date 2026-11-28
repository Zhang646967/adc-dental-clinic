const navigation=require('../../utils/navigation');
const api = require('../../utils/api');
const {showError: presentError} = require('../../utils/format');
const intent=require('../../utils/booking-intent');
const config=require('../../config');
function showError(page,error){presentError(page,error,{stayOnLogin:true});}
const courseInvitePattern = /^[A-Za-z0-9_-]{43}$/;
Page({
  data: {smsMode:false,realSmsAvailable:false,captchaKey:'',captchaImage:'',passwordMode:false,username: '', password: '', localCode:'',localConfirmed:false,authConfirmed:false,auth:{},phone:'',smsCode:'',smsChallenge:'',smsNotice:'',identityProvider:'disabled',busy: false, error: '',
    courseRoles: [], selectedCourseRole: '', courseBusy: false, courseMessage: ''},
  async onLoad(options = {}) {
    const app = getApp();
    const supplied = Object.prototype.hasOwnProperty.call(options, 'course');
    if (supplied) {
      app.globalData.courseInvite = typeof options.course === 'string' && courseInvitePattern.test(options.course)
        ? options.course : '';
    }
    this.courseInvite = app.globalData.courseInvite || '';
    this.publicTrial = !supplied && !this.courseInvite && config && config.mode === 'experience' && config.publicTrialRoles === true;
    try {
      const session = await api.bootstrap();
      const auth = session.auth_capabilities || {};
      const realSmsAvailable = !!(auth.sms_enabled && !auth.sms_demo);
      this.setData({auth, realSmsAvailable, smsMode: !auth.wechat_mini && realSmsAvailable,
        passwordMode: !(realSmsAvailable || auth.wechat_mini),
        environmentLabel: session.environment_label || '', identityProvider: session.identity_provider});
      if (session.authenticated || session.account_authenticated) {
        navigation.reLaunch({url:intent.destination(app,session)});
        return;
      }
      if (this.courseInvite || this.publicTrial) await this.loadCourseRoles();
      else if (supplied) this.setData({courseMessage:'体验入口无效。你可以手动登录。'});
    }
    catch (e) { showError(this, e); }
  },
  async loadCourseRoles() {
    const invite = this.courseInvite;
    try {
      const response = await api.request('auth/course-role/', 'POST', this.publicTrial ? {trial:'public'} : {invite});
      if (this.courseInvite === invite) this.setData({courseRoles: response.roles});
    } catch (error) {
      if (this.courseInvite !== invite) return;
      if (error.status === 404) {
        this.courseInvite = '';
        getApp().globalData.courseInvite = '';
      }
      this.setData({courseMessage: error.status === 404
        ? '体验入口无效或已过期。你可以手动登录。'
        : '暂时无法读取体验角色。你可以使用原账号登录。'});
    }
  },
  async fillCourseRole(event) {
    const role = event.currentTarget.dataset.role;
    const invite = this.courseInvite;
    if (this.data.busy || this.data.courseBusy || (!invite && !this.publicTrial) || !this.data.courseRoles.some(item => item.id === role)) return;
    this.setData({courseBusy: true, courseMessage: '', selectedCourseRole: '', username: '', password: '', error: ''});
    try {
      const fields = await api.request('auth/course-role/', 'POST', this.publicTrial ? {trial:'public',role} : {invite,role});
      if (this.courseInvite !== invite) return;
      this.setData({selectedCourseRole: role, passwordMode: true, username: fields.username,
        password: fields.password, courseMessage: '已填好账号和密码。请点「登录原账号」。'});
    } catch (error) {
      if (this.courseInvite === invite) this.setData({courseMessage: error.status === 404
        ? '这个体验账号暂不可用。你可以选择其他角色或手动登录。'
        : '暂时无法填入账号。请重试或手动登录。'});
    } finally {
      if (this.courseInvite === invite) this.setData({courseBusy: false});
    }
  },
  field(e) { this.setData({[e.currentTarget.dataset.field]: e.detail.value}); },
  toggleSms(){this.setData({smsMode:!this.data.smsMode});},
  async captcha(){try{await api.bootstrap();const result=await api.request('auth/sms/captcha/','POST',{});this.setData({captchaImage:result.image,captchaKey:''});}catch(e){showError(this,e);}},
  togglePassword(){this.setData({passwordMode:!this.data.passwordMode,password:'',error:''});},
  consent(e){this.setData({localConfirmed:e.detail.value.includes('agree')});},
  authConsent(e){this.setData({authConfirmed:e.detail.value.includes('agree')});},
  wechatLogin(){return this.submitWechat({});},
  associateWechat(){
    if(this.data.busy)return;
    const username=this.data.username.trim(),password=this.data.password;
    if(!username||!password){this.setData({error:'请填写原患者账号和密码。'});return;}
    return this.submitWechat({username,password});
  },
  async submitWechat(association){
    if(this.data.busy)return;
    if(!this.data.authConfirmed){this.setData({error:'请先同意使用微信身份登录本人患者账号。'});return;}
    this.setData({busy:true,error:''});
    try{
      await api.bootstrap();
      const credential=await new Promise((resolve,reject)=>wx.login({success:resolve,fail:()=>reject(new Error('微信登录未完成，请重新点击授权。'))}));
      const session=await api.request('auth/wechat/','POST',{code:credential.code,confirmed:'on',...association});
      navigation.reLaunch({url:intent.destination(getApp(),session)});
    }catch(e){showError(this,e);}finally{this.setData({busy:false,password:''});}
  },
  async sendSms(){
    if(this.data.busy)return;
    if(!this.data.realSmsAvailable){this.setData({error:'短信登录暂未开通，请使用微信或原账号登录。'});return;}
    if(!this.data.authConfirmed){this.setData({error:'请先同意接收验证码并办理本人账号。'});return;}
    this.setData({busy:true,error:''});
    try{
      await api.bootstrap();
      const sent=await api.request('auth/sms/send/','POST',{phone:this.data.phone,confirmed:'on',captcha_key:this.data.captchaKey});
      if(sent.demo)throw new Error('短信服务配置已变化，请重新进入登录页。');
      this.setData({smsChallenge:sent.challenge,smsCode:'',smsNotice:'验证码已提交发送，'+Math.ceil((sent.expires_seconds||300)/60)+'分钟内有效；60秒后可重发。'});
    }catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  async smsLogin(){
    if(this.data.busy)return;
    if(!this.data.realSmsAvailable){this.setData({error:'短信登录暂未开通，请使用微信或原账号登录。'});return;}
    if(!this.data.authConfirmed||!this.data.smsChallenge||!this.data.smsCode){this.setData({error:'请获取并填写验证码，确认同意后继续。'});return;}
    this.setData({busy:true,error:''});
    try{
      await api.bootstrap();
      const session=await api.request('auth/sms/confirm/','POST',{phone:this.data.phone,challenge:this.data.smsChallenge,code:this.data.smsCode,confirmed:'on'});
      navigation.reLaunch({url:intent.destination(getApp(),session)});
    }catch(e){showError(this,e);}finally{this.setData({busy:false,smsCode:'',smsNotice:''});}
  },
  async localLogin(){
    if(this.data.busy)return;
    if(!this.data.localCode||!this.data.localConfirmed){this.setData({error:'请输入新签发的验收专用授权码，并勾选同意登录。此方式未向微信或短信服务发起认证。'});return;}
    this.setData({busy:true,error:''});
    try{
      const session=await api.localSignIn(this.data.localCode,this.data.username.trim(),this.data.password,this.data.localConfirmed);
      navigation.reLaunch({url:intent.destination(getApp(),session)});
    }catch(e){showError(this,e);}
    finally{this.setData({localCode:'',password:'',busy:false});}
  },
  async login() {
    if (this.data.busy || this.data.courseBusy) return;
    if (!this.data.username.trim() || !this.data.password) { this.setData({error:'请填写原患者账号和密码。'}); return; }
    this.setData({busy:true, error:''});
    try {
      const session=await api.signIn(this.data.username.trim(), this.data.password);
      this.setData({password:''}); navigation.reLaunch({url:intent.destination(getApp(),session)});
    } catch (e) { this.setData({password:''}); showError(this, e); }
  },
  onUnload(){this.courseInvite=null;this.publicTrial=false;this.setData({password:'',localCode:'',smsCode:'',smsChallenge:'',smsNotice:''});}
});
