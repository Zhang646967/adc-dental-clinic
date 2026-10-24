const api=require('../../utils/api');
const {dateTime,showError}=require('../../utils/format');
const stamp=()=>{const s=api.sessionInfo();return JSON.stringify([s.workspace_id,s.subject_key,s.subject_revision]);};
Page({
 data:{rows:[],page:1,pages:1,busy:false,error:''},
 clear(){this.setData({rows:[],page:1,pages:1});},
 async onShow(){
  this.setData({busy:true,error:''});
  try{const s=await api.bootstrap();api.showSubject(this);
   if(!s.authenticated){this.clear();this.setData({busy:false});wx.reLaunch({url:'/pages/login/index'});return;}
   if(s.subject_required){this.clear();this.setData({busy:false});wx.reLaunch({url:'/pages/patients/index'});return;}
   if(s.delegated){this.clear();this.setData({busy:false,error:'预约代办不包含临床方案，请切换至本人。'});return;}
   if(this._subject!==stamp())this.clear();this._subject=stamp();await this.load();
  }catch(e){this.failed(e);}
 },
 async load(){
  this.setData({busy:true,error:''});
  try{const d=await api.request('plans/?page='+this.data.page);
   if(this._subject!==stamp()){this.clear();throw new Error('就诊人已变化，请重新核对本人方案。');}
   this.setData({rows:d.rows.map(r=>Object.assign({},r,{timeLabel:dateTime(r.recorded_at)})),page:d.page,pages:d.pages,busy:false});
  }catch(e){this.failed(e);}
 },
 open(e){if(!this.data.busy)wx.navigateTo({url:'/pages/plan/index?id='+Number(e.currentTarget.dataset.id)});},
 turn(e){if(this.data.busy)return;const page=this.data.page+Number(e.currentTarget.dataset.step);if(page<1||page>this.data.pages)return;this.setData({page});return this.load();},
 failed(e){if(['SUBJECT_CHANGED','SUBJECT_REQUIRED','WORKSPACE_CHANGED','ACCESS_DENIED'].includes(e.code)||e.status===401)this.clear();showError(this,e);},
 onUnload(){this.clear();this._subject=null;}
});
