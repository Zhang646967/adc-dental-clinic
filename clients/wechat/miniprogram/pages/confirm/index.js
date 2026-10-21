const api=require('../../utils/api');
const {arrangement,showError}=require('../../utils/format');
Page({
  data:{review:null,checked:false,busy:false,error:'',done:null},
  onLoad(){
    const review=getApp().globalData.review;
    if(!review){this.setData({error:'核对内容已失效，请返回我的预约重新办理。'});return;}
    const display=Object.assign({},review,{preview:Object.assign({},review.preview)});
    if(display.preview.original)display.preview.original=arrangement(display.preview.original);
    this.setData({review:display});
  },
  checked(e){this.setData({checked:e.detail.value.includes('yes')});},
  async submit(){
    if(this.data.busy||this.data.done||!this.data.checked||!this.data.review)return;
    this.setData({busy:true,error:''});
    try{const r=await api.request(this.data.review.path,'POST',{proposal_token:this.data.review.preview.proposal_token,confirmed:'on'});
      getApp().globalData.review=null;this.setData({done:arrangement(r.visit||r),busy:false});
    }catch(e){showError(this,e);}
  },
  home(){getApp().globalData.review=null;wx.reLaunch({url:'/pages/home/index'});},
  result(){wx.redirectTo({url:`/pages/visit/index?id=${this.data.done.id}`});}
});
