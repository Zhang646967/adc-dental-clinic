const api=require('../../utils/api');
const navigation=require('../../utils/navigation');
const {positive}=require('../../utils/booking-intent');
const {showError,dateTime}=require('../../utils/format');
Page({
  data:{invoice:null,busy:false,error:'',requestId:'',revisionIndex:0,versions:[],fromBilling:false},
  onLoad(query){
    this.id=query.id;this.visitId=positive(query.visit)?Number(query.visit):null;this.revision=positive(query.revision)?Number(query.revision):null;this.cashPage=1;
    this.fromBilling=query.from==='billing';
    this.setData({fromBilling:this.fromBilling});
    const page=Number(query.page);
    this.billingPage=Number.isSafeInteger(page)&&page>0?page:1;
  },
  async onShow(){await this.load();},
  async load(){
    if(this.data.busy)return;
    this.setData({busy:true,error:'',requestId:'',invoice:null,versions:[]});
    try{
      if(!positive(this.id))throw Error('结算单链接无效，请从本人就诊记录进入。');
      const query={cash_page:this.cashPage};if(this.revision)query.revision=this.revision;
      const invoice=await api.request(`invoices/${this.id}/`,'GET',query);
      const versions=invoice.revisions.map(r=>({...r,label:'第'+r.revision_no+'版 · '+dateTime(r.published_at)}));
      invoice.publishedLabel=dateTime(invoice.published_at);
      invoice.treatment_lines=invoice.treatment_lines||invoice.lines;
      invoice.medication_lines=invoice.medication_lines||[];
      if(invoice.cash_activity)invoice.cash_activity.entries=invoice.cash_activity.entries.map(row=>({...row,postedLabel:dateTime(row.posted_at)}));
      this.setData({invoice,versions,revisionIndex:Math.max(0,versions.findIndex(r=>r.revision_no===invoice.revision)),busy:false});
    }catch(e){showError(this,e,{separateRequestId:true});}
  },
  back(){
    if(this.fromBilling){
      const pages=getCurrentPages();
      const previous=pages[pages.length-2];
      return navigation.returnTo(previous&&previous.route==='pages/billing/index'?
        '/pages/billing/index':'/pages/billing/index?page='+this.billingPage);
    }
    const visit=this.data.invoice&&this.visitId;
    navigation.returnTo(visit?'/pages/visit/index?id='+visit:'/pages/home/index?queue=history');
  },
  version(e){if(this.data.busy)return;const selected=this.data.versions[Number(e.detail.value)];if(!selected)return;this.revision=selected.revision_no;this.cashPage=1;return this.load();},
  cashPageChange(e){if(this.data.busy||!this.data.invoice)return;const page=this.data.invoice.cash_activity[e.currentTarget.dataset.direction];if(!positive(page))return;this.cashPage=Number(page);return this.load();}
});
