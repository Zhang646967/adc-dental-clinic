const api=require('../../utils/api');
const navigation=require('../../utils/navigation');
const {dateTime, showError}=require('../../utils/format');

Page({
  data:{rows:[],page:1,pages:1,count:0,previous:null,next:null,busy:false,error:'',requestId:''},
  onLoad(query){
    const requested=Number(query&&query.page);
    this.page=Number.isSafeInteger(requested)&&requested>0?requested:1;
  },
  onShow(){return this.load(this.page||1);},
  onHide(){this.sequence=(this.sequence||0)+1;this.setData({rows:[],count:0});},
  async load(page=1){
    const sequence=(this.sequence||0)+1;this.sequence=sequence;
    this.page=page;
    // Drop the previous patient's rows before reading; a denied or stale
    // request must never leave an old invoice on screen.
    this.setData({busy:true,error:'',requestId:'',rows:[],count:0});
    try{
      const d=await api.request('billing/','GET',{page});
      if(sequence!==this.sequence)return;
      const rows=(d.rows||[]).map(r=>Object.assign({},r,{scheduledLabel:dateTime(r.scheduled_start),publishedLabel:dateTime(r.published_at)}));
      this.page=d.page||page;
      this.setData({rows,page:this.page,pages:d.pages||1,count:d.count||0,previous:d.previous,next:d.next,busy:false});
    }catch(e){
      if(sequence===this.sequence)showError(this,e,{separateRequestId:true});
    }
  },
  retry(){return this.load(this.page||1);},
  turn(e){
    if(this.data.busy)return;
    const page=this.data.page+Number(e.currentTarget.dataset.step);
    if(!Number.isSafeInteger(page)||page<1||page>this.data.pages)return;
    return this.load(page);
  },
  open(e){
    const r=this.data.rows[Number(e.currentTarget.dataset.index)];
    if(!r)return;
    const visit=r.visit_id?'&visit='+r.visit_id:'';
    navigation.navigateTo({url:`/pages/invoice/index?id=${r.id}${visit}&from=billing&page=${this.data.page}`});
  },
  back(){navigation.returnTo('/pages/discovery/index');}
});
