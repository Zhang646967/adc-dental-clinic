const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const nearby=require('../../utils/nearby');
const {showError, dateTime}=require('../../utils/format');
const actionModule=require('../../utils/primary-action');
const {reportEntry}=require('../../utils/report-notices');
const locationPrompt='使用当前位置，可按直线距离查看门店。';
const mapPrimary=actionModule&&typeof actionModule.primaryAction==='function'?actionModule.primaryAction:()=>null;

/* Both entry points use the same primary action. Older backends return only
   an offer count or the next visit. */
function composePrimary(overview,readOnly){
  const mapped=mapPrimary(overview,{readOnly});
  if(!mapped){
    if(overview&&overview.offer_count)return {label:'待确认邀约',actionLabel:'查看邀约',hint:'时段为限时保留，请先查看截止时间。',url:'/pages/waitlist/index',timeLabel:'',detail:'',serviceLine:'',deadline:'',review:false,arrived:false,contact:false};
    const v=overview&&overview.next_visit;
    if(v&&v.id)return {label:'下一次就诊',actionLabel:'查看安排与到诊提示',hint:'核对时间和门店，按预约安排到诊。',url:'/pages/visit/index?id='+v.id,timeLabel:dateTime(v.start),detail:(v.clinic||'')+' · '+(v.dentist||''),serviceLine:(v.service||'')+' · '+(v.status_label||''),deadline:'',review:false,arrived:v.status==='CHECKED_IN',contact:false};
    return null;
  }
  return Object.assign({},mapped,{
    arrived:mapped.kind==='CHECKED_IN',
    contact:mapped.kind==='CONTACT_CLINIC'
  });
}

Page({
  data:{all:[],rows:[],cities:['全部城市'],cityIndex:0,categories:[{id:'',name:'全部服务'}],categoryIndex:0,keyword:'',onlineOnly:false,busy:false,error:'',locating:false,nearbyActive:false,locationDenied:false,filtersOpen:false,limit:10,count:0,hasMore:false,locationNote:locationPrompt,
    serviceState:'loading',patientName:'',patientCapacity:'',patientDelegated:false,readOnly:false,primary:null,overview:null,canViewFunds:false,reportEntry:null,reportUnread:0,moreOpen:false,environmentLabel:'',serviceError:'',serviceRequestId:''},
  async onShow(){
    if(this.locationOrigin && typeof wx.getSetting==='function'){
      const request=this.locationRequest;
      wx.getSetting({success:settings=>{
        if(request===this.locationRequest && (!settings.authSetting || settings.authSetting['scope.userLocation']!==true))this.resetLocation();
      },fail:()=>{if(request===this.locationRequest)this.resetLocation();}});
    }
    await this.load();
  },
  onHide(){
    this.clearPrivate({keepReview:true});
    if(!this.openingClinic || this.data.locating)this.resetLocation();
    this.openingClinic=false;
  },
  onUnload(){this.locationRequest=(this.locationRequest||0)+1;this.locationOrigin=null;},
  resetLocation(){
    this.locationRequest=(this.locationRequest||0)+1;
    this.locationOrigin=null;
    this.setData({locating:false,nearbyActive:false,locationDenied:false,locationNote:locationPrompt});
    this.filter();
  },
  async load(){
    this.clearPrivate({keepReview:true});
    const sequence=this.serviceSequence;
    this.setData({serviceState:'loading',serviceError:'',serviceRequestId:''});
    this.setData({busy:true,error:'',rows:[],all:[]});
    try{
      const data=await api.request('discovery/index/');
      if(!Array.isArray(data.clinics)||!Array.isArray(data.categories))throw Error('门店目录暂不可用，请稍后重试。');
      if(sequence!==this.serviceSequence)return;
      const previousCity=this.data.cities[this.data.cityIndex];
      const previousCategory=this.data.categories[this.data.categoryIndex];
      const cities=['全部城市',...new Set(data.clinics.map(r=>r.city).filter(Boolean))];
      const categories=[{id:'',name:'全部服务'},...data.categories];
      this.setData({all:data.clinics,cities,categories,cityIndex:Math.max(0,cities.indexOf(previousCity)),
        categoryIndex:Math.max(0,categories.findIndex(c=>previousCategory && c.id===previousCategory.id)),
        busy:false,environmentLabel:data.environment_label||''});this.filter();
    }catch(e){
      if(sequence!==this.serviceSequence)return;
      showError(this,e,{stayOnPage:true});
    }
    await this.loadService();
  },
  /* The private section is a separate branch: a failed or unavailable
     authentication read must never hide the public clinic/doctor catalogue. */
  async loadService(){
    if(typeof api.bootstrap!=='function'){this.setData({serviceState:'guest'});return;}
    const sequence=(this.serviceSequence||0)+1;this.serviceSequence=sequence;
    this.setData({serviceState:'loading',serviceError:'',serviceRequestId:''});
    let session;
    try{session=await api.bootstrap();}
    catch(e){
      if(sequence!==this.serviceSequence)return;
      this.clearPrivate();
      this.setData({serviceState:'guest',serviceError:e.publicMessage||e.message||'暂时无法核对就诊人。',serviceRequestId:e.requestId||''});
      return;
    }
    if(sequence!==this.serviceSequence)return;
    if(!session.authenticated){
      this.clearPrivate();
      this.setData({serviceState:session.subject_required?'subject':session.account_authenticated?'enrollment':'guest'});
      return;
    }
    if(session.subject_required){this.clearPrivate();this.setData({serviceState:'subject'});return;}
    if(session.medical&&!session.can_book){this.clearPrivate();this.setData({serviceState:'medical'});return;}
    let overview;
    try{overview=await api.request('overview/');}
    catch(e){
      if(sequence!==this.serviceSequence)return;
      this.clearPrivate();
      this.setData({serviceState:'error',serviceError:e.publicMessage||e.message||'暂时无法读取主行动。',serviceRequestId:e.requestId||''});
      return;
    }
    if(sequence!==this.serviceSequence)return;
    const canViewFunds=!!overview.can_view_funds&&!session.delegated;
    // The report shortcut exists only for the patient themself and only when
    // the overview carries the capability; the money entries follow funds.
    const entry=reportEntry(overview,{delegated:!!session.delegated});
    this.setData({serviceState:'ready',patientName:session.patient_name||'',patientCapacity:session.acting_capacity||'',patientDelegated:!!session.delegated,
      overview,primary:composePrimary(overview,session.read_only),readOnly:!!session.read_only,canViewFunds,reportEntry:entry,reportUnread:entry?entry.unread:0});
  },
  /* Switching subject, signing out or losing authority invalidates in-flight
     reads. Bumping the sequence makes a late response unable to refill the
     page with the previous patient's private data. */
  clearPrivate({keepReview=false}={}){
    this.serviceSequence=(this.serviceSequence||0)+1;
    this.setData({patientName:'',patientCapacity:'',patientDelegated:false,readOnly:false,primary:null,overview:null,canViewFunds:false,
      reportEntry:null,reportUnread:0,moreOpen:false});
    if(!keepReview&&typeof getApp==='function')getApp().globalData.review=null;
  },
  filter(){
    const category=this.data.categories[this.data.categoryIndex].id;
    const rows=nearby.select(this.data.all,{city:this.data.cityIndex?this.data.cities[this.data.cityIndex]:'',keyword:this.data.keyword,origin:this.locationOrigin}).filter(c=>(!category||c.service_categories.includes(category))&&(!this.data.onlineOnly||c.online_booking));
    this.setData({rows:rows.slice(0,this.data.limit).map(r=>({...r,distanceLabel:this.data.nearbyActive && r.distance===null?'距离未知':nearby.distanceLabel(r.distance)})),count:rows.length,hasMore:rows.length>this.data.limit});
  },
  toggleFilters(){this.setData({filtersOpen:!this.data.filtersOpen});},
  city(e){this.resetLocation();this.setData({cityIndex:Number(e.detail.value),limit:10});this.filter();},
  category(e){this.setData({categoryIndex:Number(e.detail.value),limit:10});this.filter();},
  keyword(e){this.setData({keyword:e.detail.value,limit:10});this.filter();},
  online(e){this.setData({onlineOnly:e.detail.value,limit:10});this.filter();},
  more(){this.setData({limit:this.data.limit+10});this.filter();},
  locate({allStores=false}={}){
    if(this.data.locating)return;
    this.resetLocation();
    const request=this.locationRequest;
    this.setData({locating:true,locationNote:'正在获取当前位置…'});
    const failed=(error={})=>{
      if(request!==this.locationRequest)return;
      const denied=/auth(?:orize)?[^:]{0,20}den(?:y|ied)|permission denied/i.test(error.errMsg||'');
      this.setData({locating:false,locationDenied:denied,filtersOpen:true,
        locationNote:denied?'未授权定位，可手动选择城市。':'暂时无法定位，可手动选择城市或重新定位。'});
    };
    if(typeof wx.getLocation!=='function'){failed();return;}
    wx.getLocation({type:'wgs84',success:position=>{
      if(request!==this.locationRequest)return;
      if(!position || !nearby.point(position.latitude,position.longitude)){failed();return;}
      this.locationOrigin={latitude:position.latitude,longitude:position.longitude};
      const filters=allStores?{cityIndex:0,categoryIndex:0,keyword:'',onlineOnly:false}:{};
      this.setData({...filters,locating:false,nearbyActive:true,limit:10,locationNote:'按直线距离，从近到远排列。'});
      this.filter();
    },fail:failed});
  },
  locationSettings(e){
    if(e.detail && e.detail.authSetting && e.detail.authSetting['scope.userLocation']===true)this.locate();
  },
  stores(){
    wx.pageScrollTo({selector:'#store-search'});
    this.locate({allStores:true});
  },
  clinic(e){
    this.openingClinic=true;
    navigation.navigateTo({url:'/pages/clinic/index?id='+e.currentTarget.dataset.id,fail:()=>{this.openingClinic=false;}});
  },
  doctors(){const city=this.data.cityIndex?this.data.cities[this.data.cityIndex]:'';navigation.navigateTo({url:'/pages/dentists/index?city='+encodeURIComponent(city)});},
  services(){const city=this.data.cityIndex?this.data.cities[this.data.cityIndex]:'';navigation.navigateTo({url:'/pages/services/index?category='+this.data.categories[this.data.categoryIndex].id+'&city='+encodeURIComponent(city)});},
  account(){this.clearPrivate();navigation.navigateTo({url:'/pages/account/index'});},
  login(){this.clearPrivate();navigation.navigateTo({url:'/pages/login/index'});},
  subjects(){this.clearPrivate();navigation.navigateTo({url:'/pages/patients/index'});},
  medical(){navigation.navigateTo({url:'/pages/medical-authorizations/index'});},
  async logout(){
    this.clearPrivate();
    this.setData({serviceState:'loading',serviceError:'',serviceRequestId:''});
    try{await api.signOut();}
    catch(e){
      this.setData({serviceState:'error',serviceError:'暂时无法确认退出，请重试。',serviceRequestId:e.requestId||''});
      return;
    }
    this.setData({serviceState:'guest'});
    navigation.reLaunch({url:'/pages/discovery/index'});
  },
  retryService(){this.clearPrivate();return this.loadService();},
  primaryTap(){const p=this.data.primary;if(p&&p.url)navigation.navigateTo({url:p.url});},
  book(){navigation.navigateTo({url:'/pages/services/index'});},
  arrangements(){navigation.navigateTo({url:'/pages/home/index?queue=active'});},
  records(){navigation.navigateTo({url:'/pages/home/index?queue=history'});},
  reports(){navigation.navigateTo({url:'/pages/report-notices/index'});},
  fees(){navigation.navigateTo({url:'/pages/billing/index'});},
  // Secondary tools live behind one named disclosure; it only renders for a
  // signed-in subject and its entries still follow the capability flags.
  toggleMore(){this.setData({moreOpen:!this.data.moreOpen});}
});
