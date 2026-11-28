const api=require('../../utils/api');
const navigation=require('../../utils/navigation');
const {positive}=require('../../utils/booking-intent');
const {showError,dateTime}=require('../../utils/format');
const {invoiceView,versionOptions}=require('../../utils/billing');

Page({
  data:{invoice:null,view:null,busy:false,error:'',requestId:'',revisionIndex:0,versions:[],
    fromBilling:false,cashOpen:false,cashOpenLabel:'查看已记账收退款与分担明细',cashCloseLabel:'收起收款与退款明细'},
  onLoad(query){
    this.id=query.id;this.visitId=positive(query.visit)?Number(query.visit):null;this.revision=positive(query.revision)?Number(query.revision):null;this.cashPage=1;
    this.fromBilling=query.from==='billing';
    this.setData({fromBilling:this.fromBilling});
    const page=Number(query.page);
    this.billingPage=Number.isSafeInteger(page)&&page>0?page:1;
    this.sequence=0;
  },
  async onShow(){await this.load();},
  async load(){
    const sequence=(this.sequence||0)+1;this.sequence=sequence;
    // Every read starts from an empty card: a version switch, a patient change
    // or a rejected read must never leave the previous amount on screen.
    this.setData({busy:true,error:'',requestId:'',invoice:null,view:null,versions:[]});
    try{
      if(!positive(this.id))throw Error('结算单链接无效，请从本人就诊记录进入。');
      const query={cash_page:this.cashPage};if(this.revision)query.revision=this.revision;
      const invoice=await api.request(`invoices/${this.id}/`,'GET',query);
      if(sequence!==this.sequence)return;
      const versions=versionOptions(invoice);
      invoice.publishedLabel=dateTime(invoice.published_at);
      invoice.treatment_lines=invoice.treatment_lines||invoice.lines;
      invoice.medication_lines=invoice.medication_lines||[];
      if(invoice.cash_activity)invoice.cash_activity.entries=(invoice.cash_activity.entries||[]).map(row=>({...row,postedLabel:dateTime(row.posted_at)}));
      const found=versions.findIndex(r=>r.revision===invoice.revision);
      this.setData({invoice,view:invoiceView(invoice),versions,revisionIndex:found>=0?found:0,busy:false});
    }catch(e){
      if(sequence!==this.sequence)return;
      this.setData({invoice:null,view:null,versions:[],busy:false});
      showError(this,e,{separateRequestId:true});
    }
  },
  // Leaving the page drops the bill, its version list and any expanded cash
  // detail, so re-entering never shows another bill's hidden content.
  onHide(){this.sequence=(this.sequence||0)+1;this.setData({invoice:null,view:null,versions:[],cashOpen:false,busy:false});},
  onUnload(){this.sequence=(this.sequence||0)+1;},
  toggleCash(){
    if(!this.data.invoice)return;
    this.setData({cashOpen:!this.data.cashOpen});
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
  version(e){
    const selected=this.data.versions[Number(e.detail.value)];
    if(!selected)return;
    this.revision=selected.revision;
    this.cashPage=1;
    this.setData({cashOpen:false});
    return this.load();
  },
  cashPageChange(e){
    if(this.data.busy||!this.data.invoice)return;
    const page=this.data.invoice.cash_activity[e.currentTarget.dataset.direction];
    if(!positive(page))return;
    this.cashPage=Number(page);
    return this.load();
  }
});
