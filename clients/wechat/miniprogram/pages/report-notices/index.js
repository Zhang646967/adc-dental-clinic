const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {showError}=require('../../utils/format');
const {staleSubject,recoverSubject}=require('../../utils/subject-state');
const {positive}=require('../../utils/booking-intent');
const {buildNoticeList}=require('../../utils/report-notices');

const blankSubject={patientName:'',patientCapacity:'',patientDelegated:false};

Page({
  data:{...blankSubject,rows:[],unreadCount:null,page:1,hasPrevious:false,hasNext:false,
    busy:false,error:'',requestId:'',subjectInvalid:false,environmentLabel:'',readOnly:false},
  onLoad(query){
    const requested=positive(query&&query.page)?Number(query.page):1;
    this.page=requested;
    this.generation=0;
    this.setData({page:requested});
  },
  onShow(){return this.load(this.page||1);},
  onHide(){this.generation++;this.setData({rows:[],unreadCount:null,...blankSubject});},
  onUnload(){this.generation++;},
  async load(page=1){
    const generation=++this.generation;
    this.page=page;
    // Drop the previous patient's notices and unread count before reading; a
    // denied or stale request must never leave another patient's row on screen.
    this.setData({rows:[],unreadCount:null,...blankSubject,error:'',requestId:'',busy:true,subjectInvalid:false});
    try{
      const data=await api.request('report-notices/','GET',{page});
      if(generation!==this.generation)return;
      const list=buildNoticeList(data);
      this.page=list.page;
      api.showSubject(this);
      this.setData({...list,busy:false,readOnly:!!api.sessionInfo().read_only,environmentLabel:api.sessionInfo().environment_label||''});
    }catch(e){
      if(generation!==this.generation)return;
      const state=staleSubject(e,api.sessionInfo(),{uncodedConflictIsStale:false});
      this.setData({subjectInvalid:state.invalid});
      showError(this,e,{separateRequestId:true,stayOnPage:true});
    }
  },
  retry(){return this.load(this.page||1);},
  turn(e){
    if(this.data.busy)return;
    const page=this.data.page+Number(e.currentTarget.dataset.step);
    if(!Number.isSafeInteger(page)||page<1)return;
    if(page>this.data.page&&!this.data.hasNext)return;
    return this.load(page);
  },
  open(e){
    const row=this.data.rows[Number(e.currentTarget.dataset.index)];
    if(!row||!row.canOpen)return;
    navigation.navigateTo({url:row.url});
  },
  contact(e){
    const row=this.data.rows[Number(e.currentTarget.dataset.index)];
    if(!row)return;
    navigation.navigateTo({url:row.contactUrl});
  },
  // Only an explicit tap writes the shared read state. A repeat tap on an
  // already-read row keeps the original read time from the server.
  async markRead(e){
    const index=Number(e.currentTarget.dataset.index);
    const row=this.data.rows[index];
    if(!row||!row.unread||this.data.busy||this.data.readOnly)return;
    const generation=this.generation;
    this.setData({busy:true,error:'',requestId:''});
    try{
      const r=await api.request(`report-notices/${row.id}/read/`,'POST',{});
      if(generation!==this.generation)return;
      const rows=this.data.rows.map((item,i)=>i===index?Object.assign({},item,{
        unread:false,readAt:r.read_at||item.readAt,readLabel:'已读'}):item);
      const unread=Number.isInteger(r.unread_count)?r.unread_count:Math.max(0,(this.data.unreadCount||0)-1);
      this.setData({rows,unreadCount:unread,busy:false});
    }catch(error){
      if(generation!==this.generation)return;
      // A corrected or withdrawn report can retire the old row; re-read the
      // list so the patient sees the current notice instead of a dead entry.
      if(error.status===404||error.status===409)return this.load(this.page||1);
      if(staleSubject(error,api.sessionInfo(),{uncodedConflictIsStale:false}).invalid){
        this.setData({rows:[],unreadCount:null,...blankSubject,subjectInvalid:true});
      }
      showError(this,error,{separateRequestId:true,stayOnPage:true});
    }
  },
  recoverSubject(){return recoverSubject(this,api.bootstrap,navigation.reLaunch);},
  back(){navigation.returnTo('/pages/home/index');}
});
