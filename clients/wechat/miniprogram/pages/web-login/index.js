const api=require('../../utils/api'),{showError,dateTime}=require('../../utils/format');
Page({
  data:{ticket:null,expiresLabel:'',busy:false,error:'',notice:''},
  async onLoad(options){
    const value=options.scene?decodeURIComponent(options.scene):options.ticket;
    if(!/^[a-f0-9]{32}$/.test(value||'')){this.setData({error:'登录码无效，请在电脑网站重新生成。'});return;}
    this.value=value;getApp().globalData.webLoginTicket=value;
    this.setData({busy:true});
    try{
      const session=await api.bootstrap();
      if(!session.account_authenticated){wx.reLaunch({url:'/pages/login/index'});return;}
      const ticket=await api.request('account/web-login/','GET',{ticket:value});
      this.setData({ticket,expiresLabel:dateTime(ticket.expires_at),notice:ticket.state!=='PENDING'?'登录码已办理或过期，请在电脑核对。':''});
    }catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  async decide(decision){
    if(this.data.busy||!this.value)return;this.setData({busy:true,error:''});
    try{
      let code='';
      if(decision==='approve'){
        const proof=await new Promise((resolve,reject)=>wx.login({success:resolve,fail:()=>reject(Error('微信确认未完成，请重试。'))}));code=proof.code;
      }
      const ticket=await api.request('account/web-login/','POST',{ticket:this.value,decision,code,confirmed:decision==='approve'?'on':''});
      getApp().globalData.webLoginTicket=null;
      this.setData({ticket,notice:decision==='approve'?'已确认，请回到电脑网站查看登录结果。':'已拒绝，电脑不会登录。'});
    }catch(e){showError(this,e);}finally{this.setData({busy:false});}
  },
  approve(){return this.decide('approve');},reject(){return this.decide('reject');},
  async switchAccount(){try{await api.signOut();getApp().globalData.webLoginTicket=this.value;wx.reLaunch({url:'/pages/login/index'});}catch(e){showError(this,e);}}
});
