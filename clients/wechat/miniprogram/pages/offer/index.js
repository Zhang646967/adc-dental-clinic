const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {positive}=require('../../utils/booking-intent');
const {arrangement,dateTime,showError}=require('../../utils/format');
Page({
  data:{offer:null,choices:[],choice:0,reason:'',busy:false,error:'',requestId:'',readOnly:false},
  onLoad(q){this.id=positive(q.id)?Number(q.id):null;},
  onShow(){return this.load();},
  async load(){
    if(this.data.busy)return;
    this.setData({busy:true,error:'',requestId:'',offer:null,choices:[],choice:0,reason:''});
    api.showSubject(this);
    try{if(!this.id)throw Error('邀约链接无效，请从候补记录重新打开。');
      const d=await api.request(`offers/${this.id}/`);const choices=[{name:'请明确选择此次用途',source:null},{name:'新增一次预约（保留其他预约）',source:null}].concat(d.sources.map(v=>({name:`替换原预约 #${v.id} · ${dateTime(v.start)}`,source:v})));
      this.setData({offer:Object.assign(arrangement(d.offer),{expiresLabel:dateTime(d.offer.expires)}),choices,choice:0,busy:false,readOnly:api.sessionInfo().read_only});
    }catch(e){showError(this,e,{separateRequestId:true});}
  },
  pick(e){this.setData({choice:Number(e.detail.value)});},
  reason(e){this.setData({reason:e.detail.value});},
  async accept(){
    if(this.data.busy||this.data.readOnly||!this.data.offer||!this.data.offer.active)return;
    if(!this.data.choice){this.setData({requestId:'',error:'请先选择新增预约，或明确指定要替换的原预约。'});return;}
    const source=this.data.choices[this.data.choice].source;
    if(source&&!this.data.reason.trim()){this.setData({requestId:'',error:'请填写改期原因，再核对原、新安排。'});return;}
    await this.preview('accept',source);
  },
  async decline(){await this.preview('decline',null);},
  async preview(action,source){
    if(this.data.busy||this.data.readOnly||!this.data.offer||!this.data.offer.active)return;this.setData({busy:true,error:'',requestId:''});
    try{const p=source ? await api.request(`visits/${source.id}/reschedule/preview/`,'POST',{action:'preview',offer_id:this.id,slot_id:this.data.offer.slot,start:this.data.offer.start,expected_version:source.version,reason:this.data.reason}) : await api.request(`offers/${this.id}/preview/`,'POST',{action});
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,fromWaitlist:true,kind:source?'reschedule':action==='accept'?'offer_accept':'offer_decline',preview:arrangement(p),path:source?`visits/${source.id}/reschedule/confirm/`:`offers/${this.id}/confirm/`};
      this.setData({busy:false});navigation.navigateTo({url:'/pages/confirm/index'});
    }catch(e){showError(this,e,{separateRequestId:true});}
  },
  back(){navigation.returnTo('/pages/waitlist/index');},
  visit(){navigation.navigateTo({url:`/pages/visit/index?id=${this.data.offer.visit.id}`});}
});
