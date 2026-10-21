const api=require('../../utils/api');
const {waitEntry,showError}=require('../../utils/format');
Page({
  data:{rows:[],page:1,pages:1,busy:false,error:'',hasOpen:false,readOnly:false},
  async onShow(){
    try{const s=await api.bootstrap();if(!s.authenticated){wx.reLaunch({url:'/pages/login/index'});return;}
      this.setData({readOnly:s.read_only});await this.load();
    }catch(e){showError(this,e);}
  },
  async load(){
    this.setData({busy:true,error:''});
    try{const d=await api.request('waitlist/','GET',{page:this.data.page});this.setData({rows:d.rows.map(waitEntry),page:d.page,pages:d.pages,hasOpen:d.has_open,busy:false});}
    catch(e){showError(this,e);}
  },
  turn(e){if(this.data.busy)return;this.setData({page:this.data.page+Number(e.currentTarget.dataset.step)});this.load();},
  offer(e){wx.navigateTo({url:`/pages/offer/index?id=${e.currentTarget.dataset.id}`});},
  visit(e){wx.navigateTo({url:`/pages/visit/index?id=${e.currentTarget.dataset.id}`});},
  async withdraw(e){
    if(this.data.busy)return;this.setData({busy:true,error:''});
    const id=e.currentTarget.dataset.id;
    try{const p=await api.request(`waitlist/${id}/withdraw/preview/`,'POST');
      getApp().globalData.review={kind:'wait_withdraw',preview:p,path:`waitlist/${id}/withdraw/confirm/`};
      this.setData({busy:false});wx.navigateTo({url:'/pages/confirm/index'});
    }catch(error){showError(this,error);}
  }
});
