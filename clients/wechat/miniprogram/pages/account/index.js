const api=require('../../utils/api'),{showError,dateTime}=require('../../utils/format'),intent=require('../../utils/booking-intent');
function consent(content){return new Promise(resolve=>wx.showModal({title:'核对本人账号',content,success:r=>resolve(!!r.confirm),fail:()=>resolve(false)}));}
Page({
  data:{profile:null,phoneCode:'',loginCode:'',newPassword:'',repeatPassword:'',unlinkPassword:'',auth:{},smsPhone:'',smsCode:'',smsChallenge:'',smsNotice:'',readOnly:false,busy:false,error:''},
  async onShow(){await this.load();},
  async load(){
    this.setData({busy:true,error:'',profile:null});
    try{
      const session=await api.bootstrap();
      if(!session.account_authenticated){wx.reLaunch({url:'/pages/login/index'});return;}
      if(this.ownerContext&&this.ownerContext!==session.workspace_id)this.setData({phoneCode:'',loginCode:'',newPassword:'',repeatPassword:'',unlinkPassword:'',smsPhone:'',smsCode:'',smsChallenge:'',smsNotice:''});
      this.ownerContext=session.workspace_id;
      const profile=await api.request('account/');profile.cases=profile.cases.map(c=>({...c,createdLabel:dateTime(c.created_at)}));
      this.setData({profile,auth:session.auth_capabilities||{},readOnly:session.read_only});
    }catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  field(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
  async bindWechat(){
    if(this.data.busy||this.data.readOnly||!await consent('同意将当前微信身份绑定到这个ADC账号，用于后续快捷登录？'))return;
    this.setData({busy:true,error:''});
    try{const credential=await new Promise((resolve,reject)=>wx.login({success:resolve,fail:()=>reject(new Error('微信授权未完成，请重试。'))}));await api.request('account/wechat/bind/','POST',{code:credential.code,confirmed:'on'});await this.load();}
    catch(error){showError(this,error);}finally{this.setData({busy:false});}
  },
  async wechatPhone(e){
    if(this.data.busy||this.data.readOnly)return;
    if(!e.detail.code){this.setData({error:'未取得手机号授权，可重新授权或改用短信验证。'});return;}
    this.setData({busy:true,error:''});
    try{await api.request('account/phone/wechat/','POST',{code:e.detail.code,confirmed:'on'});await this.load();}
    catch(error){showError(this,error);}finally{this.setData({busy:false});}
  },
  async sendPhoneSms(){
    if(this.data.busy||this.data.readOnly||!await consent('同意向填写的号码发送验证码，核验后用于本人账号联络和登录？'))return;
    this.setData({busy:true,error:''});
    try{const sent=await api.request('account/phone/sms/send/','POST',{phone:this.data.smsPhone,confirmed:'on'});this.setData({smsChallenge:sent.challenge,smsCode:'',smsNotice:sent.demo?'测试验证码：'+sent.test_code+'（未发送短信）':'验证码已提交发送，五分钟内有效。'});}
    catch(error){showError(this,error);}finally{this.setData({busy:false});}
  },
  async bindPhoneSms(){
    if(this.data.busy||this.data.readOnly||!await consent('核验并将此号码绑定到本人登录账号？不会合并患者档案。'))return;
    this.setData({busy:true,error:''});
    try{await api.request('account/phone/sms/confirm/','POST',{phone:this.data.smsPhone,code:this.data.smsCode,challenge:this.data.smsChallenge,confirmed:'on'});await this.load();}
    catch(error){showError(this,error);}finally{this.setData({smsCode:'',smsNotice:'',busy:false});}
  },
  async phone(){
    if(this.data.busy||this.data.readOnly||!this.data.phoneCode)return;
    if(!await consent('确认绑定此授权码对应的合成号码？这是本地模拟，不会改变患者档案或合并家人。'))return;
    this.setData({busy:true,error:''});
    try{await api.request('account/phone/','POST',{code:this.data.phoneCode,confirmed:'on'});await this.load();}
    catch(e){showError(this,e);}finally{this.setData({phoneCode:'',busy:false});}
  },
  async password(){
    if(this.data.busy||this.data.readOnly)return;
    if(!this.data.loginCode||!this.data.newPassword||this.data.newPassword!==this.data.repeatPassword){this.setData({error:'请填写当前身份的新授权码及一致的两次密码。'});return;}
    if(!await consent('用当前绑定身份核验后设置本人账号密码，以便网站登录及恢复？'))return;
    this.setData({busy:true,error:''});
    try{await api.request('account/password/','POST',{code:this.data.loginCode,new_password:this.data.newPassword,repeat_password:this.data.repeatPassword,confirmed:'on'});await this.load();}
    catch(e){showError(this,e);}finally{this.setData({loginCode:'',newPassword:'',repeatPassword:'',busy:false});}
  },
  async unlink(e){
    if(this.data.busy||this.data.readOnly)return;
    if(!this.data.unlinkPassword){this.setData({error:'请先设置可用密码，再填写密码核对解绑。'});return;}
    if(!await consent('确认解除此快捷登录绑定？ADC账号、本人档案及预约保留，可用原账号密码登录。'))return;
    this.setData({busy:true,error:''});
    try{await api.request('account/unlink/','POST',{identity:e.currentTarget.dataset.id,revision:e.currentTarget.dataset.revision,password:this.data.unlinkPassword,confirmed:'on'});await this.load();}
    catch(error){showError(this,error);}finally{this.setData({unlinkPassword:'',busy:false});}
  },
  async activate(){
    if(this.data.busy)return;
    this.setData({busy:true,error:''});
    try{const session=await api.request('account/activate/','POST',{confirmed:'on'});wx.reLaunch({url:intent.destination(getApp(),session)});}
    catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  edit(e){wx.navigateTo({url:'/pages/enrollment/index?case='+e.currentTarget.dataset.id});},
  async withdraw(e){
    if(this.data.busy||this.data.readOnly||!await consent('确认撤回本次档案申请？原业务及其他记录保留。'))return;
    this.setData({busy:true,error:''});
    try{await api.request('account/enrollment/'+e.currentTarget.dataset.id+'/withdraw/','POST',{revision:e.currentTarget.dataset.revision,confirmed:'on'});await this.load();}
    catch(error){showError(this,error);}finally{this.setData({busy:false});}
  },
  async logout(){try{await api.signOut();wx.reLaunch({url:'/pages/discovery/index'});}catch(e){showError(this,e);}},
  onUnload(){this.setData({phoneCode:'',loginCode:'',newPassword:'',repeatPassword:'',unlinkPassword:'',smsCode:'',smsChallenge:'',smsNotice:''});}
});
