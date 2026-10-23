const api=require('../../utils/api');
const {arrangement,showError}=require('../../utils/format');
Page({
  data:{visit:null,reason:'',cancelOpen:false,busy:false,error:'',readOnly:false},
  onLoad(q){ api.showSubject(this);this.id=Number(q.id);},
  async onShow(){ api.showSubject(this);this.setData({visit:null,error:''});try{this.setData({visit:arrangement(await api.request(`visits/${this.id}/`)),readOnly:api.sessionInfo().read_only,environmentLabel:api.sessionInfo().environment_label||''});}catch(e){showError(this,e);}},
  reschedule(){wx.navigateTo({url:`/pages/booking/index?visit=${this.id}`});},
  cancel(){this.setData({cancelOpen:!this.data.cancelOpen,error:''});},
  reason(e){this.setData({reason:e.detail.value});},
  async previewCancel(){
    if(this.data.busy)return;
    if(!this.data.reason.trim()){this.setData({error:'请填写取消原因。'});return;}
    this.setData({busy:true,error:''});
    try{const preview=await api.request(`visits/${this.id}/cancel/preview/`,'POST',{expected_version:this.data.visit.version,reason:this.data.reason});
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,kind:'cancel',preview,path:`visits/${this.id}/cancel/confirm/`};
      this.setData({busy:false});wx.navigateTo({url:'/pages/confirm/index'});
    }catch(e){showError(this,e);}
  },
  related(e){wx.redirectTo({url:`/pages/visit/index?id=${e.currentTarget.dataset.id}`});},
  home(){wx.reLaunch({url:'/pages/home/index'});}
});
