const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {arrangement,dateTime,showError}=require('../../utils/format');
Page({
  data:{offer:null,choices:[],choice:0,reason:'',busy:false,error:'',readOnly:false},
  onLoad(q){ api.showSubject(this);this.id=Number(q.id);},
  async onShow(){ api.showSubject(this);
    try{const d=await api.request(`offers/${this.id}/`);const choices=[{name:'请明确选择此次用途',source:null},{name:'新增一次预约（保留其他预约）',source:null}].concat(d.sources.map(v=>({name:`替换原预约 #${v.id} · ${dateTime(v.start)}`,source:v})));
      this.setData({offer:Object.assign(arrangement(d.offer),{expiresLabel:dateTime(d.offer.expires)}),choices,choice:0,readOnly:api.sessionInfo().read_only});
    }catch(e){showError(this,e);}
  },
  pick(e){this.setData({choice:Number(e.detail.value)});},
  reason(e){this.setData({reason:e.detail.value});},
  async accept(){
    if(!this.data.choice){this.setData({error:'请先选择新增预约，或明确指定要替换的原预约。'});return;}
    const source=this.data.choices[this.data.choice].source;
    if(source&&!this.data.reason.trim()){this.setData({error:'请填写改期原因，再核对原、新安排。'});return;}
    await this.preview('accept',source);
  },
  async decline(){await this.preview('decline',null);},
  async preview(action,source){
    if(this.data.busy)return;this.setData({busy:true,error:''});
    try{const p=source ? await api.request(`visits/${source.id}/reschedule/preview/`,'POST',{action:'preview',offer_id:this.id,slot_id:this.data.offer.slot,start:this.data.offer.start,expected_version:source.version,reason:this.data.reason}) : await api.request(`offers/${this.id}/preview/`,'POST',{action});
      getApp().globalData.review={subjectKey:api.sessionInfo().subject_key,workspaceKey:api.sessionInfo().workspace_id,subjectRevision:api.sessionInfo().subject_revision,kind:source?'reschedule':action==='accept'?'offer_accept':'offer_decline',preview:arrangement(p),path:source?`visits/${source.id}/reschedule/confirm/`:`offers/${this.id}/confirm/`};
      this.setData({busy:false});navigation.navigateTo({url:'/pages/confirm/index'});
    }catch(e){showError(this,e);}
  },
  visit(){navigation.redirectTo({url:`/pages/visit/index?id=${this.data.offer.visit.id}`});}
});
