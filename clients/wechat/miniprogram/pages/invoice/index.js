const api=require('../../utils/api');
const {positive}=require('../../utils/booking-intent');
const {showError,dateTime}=require('../../utils/format');
Page({
  data:{invoice:null,busy:false,error:'',revisionIndex:0,versions:[]},
  onLoad(query){this.id=query.id;this.revision=positive(query.revision)?Number(query.revision):null;},
  async onShow(){await this.load();},
  async load(){
    if(this.data.busy)return;
    this.setData({busy:true,error:'',invoice:null,versions:[]});
    try{
      if(!positive(this.id))throw Error('结算单链接无效，请从本人就诊记录进入。');
      const invoice=await api.request(`invoices/${this.id}/`,'GET',this.revision?{revision:this.revision}:{});
      const versions=invoice.revisions.map(r=>({...r,label:'第'+r.revision_no+'版 · '+dateTime(r.published_at)}));
      invoice.publishedLabel=dateTime(invoice.published_at);
      this.setData({invoice,versions,revisionIndex:Math.max(0,versions.findIndex(r=>r.revision_no===invoice.revision)),busy:false});
    }catch(e){showError(this,e);}
  },
  version(e){if(this.data.busy)return;this.revision=this.data.versions[Number(e.detail.value)].revision_no;this.load();}
});
