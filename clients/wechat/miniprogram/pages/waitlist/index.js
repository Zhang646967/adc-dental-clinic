const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {waitEntry,showError}=require('../../utils/format');
Page({
  data:{rows:[],page:1,pages:1,busy:false,error:'',requestId:'',hasOpen:false,readOnly:false},
  async onShow(){ this.setData({rows:[],hasOpen:false,busy:true,error:'',requestId:''});
    try{const s=await api.bootstrap();api.showSubject(this);if(!s.authenticated){navigation.reLaunch({url:'/pages/login/index'});return;}
      if(this.subject!==s.subject_key||this.workspace!==s.workspace_id||this.revision!==s.subject_revision)this.setData({page:1});
      this.subject=s.subject_key;this.workspace=s.workspace_id;this.revision=s.subject_revision;
      this.setData({readOnly:s.read_only});await this.load();
    }catch(e){showError(this,e,{separateRequestId:true});}
  },
  async load(){
    this.setData({busy:true,error:'',requestId:'',rows:[],hasOpen:false});
    try{const d=await api.request('waitlist/','GET',{page:this.data.page});this.setData({rows:d.rows.map(waitEntry),page:d.page,pages:d.pages,hasOpen:d.has_open,busy:false});}
    catch(e){showError(this,e,{separateRequestId:true});}
  },
  turn(e){if(this.data.busy)return;const page=this.data.page+Number(e.currentTarget.dataset.step);if(page<1||page>this.data.pages)return;this.setData({page});return this.load();},
  retry(){return this.onShow();},
  offer(e){navigation.navigateTo({url:`/pages/offer/index?id=${e.currentTarget.dataset.id}`});},
  visit(e){navigation.navigateTo({url:`/pages/visit/index?id=${e.currentTarget.dataset.id}`});},
  async withdraw(e){
    if(this.data.busy)return;this.setData({busy:true,error:'',requestId:''});
    const id=e.currentTarget.dataset.id;
    try{const p=await api.request(`waitlist/${id}/withdraw/preview/`,'POST');
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,kind:'wait_withdraw',preview:p,path:`waitlist/${id}/withdraw/confirm/`};
      this.setData({busy:false});navigation.navigateTo({url:'/pages/confirm/index'});
    }catch(error){showError(this,error,{separateRequestId:true});}
  }
});
