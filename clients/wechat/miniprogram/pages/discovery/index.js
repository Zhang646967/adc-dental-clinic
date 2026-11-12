const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const nearby=require('../../utils/nearby');
const config=require('../../config');
const {showError, dateTime}=require('../../utils/format');
const actionModule=require('../../utils/primary-action');
const mapPrimary=actionModule&&typeof actionModule.primaryAction==='function'?actionModule.primaryAction:()=>null;

/* Prefer the server's label/button/hint. Older backends omit them, in which
   case the mapped action and the original offer/next-visit entries still work. */
function composePrimary(overview){
  const mapped=mapPrimary(overview);
  const raw=overview&&overview.primary_action;
  if(!mapped){
    if(overview&&overview.offer_count)return {label:'待确认邀约',actionLabel:'查看邀约',hint:'时段为限时保留，请先查看截止时间。',url:'/pages/waitlist/index',timeLabel:'',detail:'',serviceLine:'',deadline:'',review:false,arrived:false,contact:false};
    const v=overview&&overview.next_visit;
    if(v&&v.id)return {label:'下一次就诊',actionLabel:'查看安排与到诊提示',hint:'核对时间和门店，按预约安排到诊。',url:'/pages/visit/index?id='+v.id,timeLabel:dateTime(v.start),detail:(v.clinic||'')+' · '+(v.dentist||''),serviceLine:(v.service||'')+' · '+(v.status_label||''),deadline:'',review:false,arrived:v.status==='CHECKED_IN',contact:false};
    return null;
  }
  return Object.assign({},mapped,{
    label:(raw&&raw.label)||mapped.label,
    actionLabel:(raw&&raw.button)||mapped.actionLabel,
    hint:(raw&&raw.hint)||mapped.hint,
    arrived:mapped.kind==='CHECKED_IN',
    contact:mapped.kind==='CONTACT_CLINIC'
  });
}

Page({
  data:{all:[],rows:[],cities:['全部城市'],cityIndex:0,categories:[{id:'',name:'全部服务'}],categoryIndex:0,keyword:'',onlineOnly:false,busy:false,error:'',locating:false,origin:null,limit:10,count:0,hasMore:false,locationNote:'可直接浏览；主动使用定位后，按直线距离由近到远排序。',
    serviceState:'loading',patientName:'',patientCapacity:'',patientDelegated:false,primary:null,overview:null,canViewFunds:false,environmentLabel:'',serviceError:'',serviceRequestId:''},
  async onShow(){await this.load();},
  async load(){
    if(this.data.busy)return;
    const previousCity=this.data.cities[this.data.cityIndex];this.setData({busy:true,error:'',rows:[],all:[]});
    try{
      const data=await api.request('discovery/index/');
      if(!Array.isArray(data.clinics)||!Array.isArray(data.categories))throw Error('门店目录暂不可用，请稍后重试。');
      const cities=['全部城市',...new Set(data.clinics.map(r=>r.city))];
      this.setData({all:data.clinics.map(c=>({...c,cover:c.images.length?config.apiBase+c.images[0].url:''})),cities,categories:[{id:'',name:'全部服务'},...data.categories],cityIndex:Math.max(0,cities.indexOf(previousCity)),busy:false,environmentLabel:data.environment_label||''});this.filter();
    }catch(e){showError(this,e);}
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
    this.setData({serviceState:'ready',patientName:session.patient_name||'',patientCapacity:session.acting_capacity||'',patientDelegated:!!session.delegated,
      overview,primary:composePrimary(overview),canViewFunds});
  },
  /* Switching subject, signing out or losing authority invalidates in-flight
     reads. Bumping the sequence makes a late response unable to refill the
     page with the previous patient's private data. */
  clearPrivate(){
    this.serviceSequence=(this.serviceSequence||0)+1;
    this.setData({patientName:'',patientCapacity:'',patientDelegated:false,primary:null,overview:null,canViewFunds:false});
    if(typeof getApp==='function'){const app=getApp();if(app&&app.globalData)app.globalData.review=null;}
  },
  filter(){
    const category=this.data.categories[this.data.categoryIndex].id;
    const rows=nearby.select(this.data.all,{city:this.data.cityIndex?this.data.cities[this.data.cityIndex]:'',keyword:this.data.keyword,origin:this.data.origin}).filter(c=>(!category||c.service_categories.includes(category))&&(!this.data.onlineOnly||c.online_booking));
    this.setData({rows:rows.slice(0,this.data.limit).map(r=>({...r,distanceLabel:nearby.distanceLabel(r.distance)})),count:rows.length,hasMore:rows.length>this.data.limit});
  },
  city(e){this.setData({cityIndex:Number(e.detail.value),limit:10});this.filter();},
  category(e){this.setData({categoryIndex:Number(e.detail.value),limit:10});this.filter();},
  keyword(e){this.setData({keyword:e.detail.value,limit:10});this.filter();},
  online(e){this.setData({onlineOnly:e.detail.value,limit:10});this.filter();},
  more(){this.setData({limit:this.data.limit+10});this.filter();},
  locate(){
    if(this.data.locating)return;this.setData({locating:true});
    wx.getLocation({type:'wgs84',success:p=>{
      if(!nearby.point(p.latitude,p.longitude)){this.setData({locating:false,locationNote:'未取得有效位置，仍可手动选城市。'});return;}
      this.setData({origin:{latitude:p.latitude,longitude:p.longitude},locating:false,locationNote:'已按全部匹配门店的直线距离排序，实际路程以导航为准。'});this.filter();
    },fail:()=>this.setData({locating:false,locationNote:'定位未开启，仍可手动选择城市和区域。'})});
  },
  stores(){wx.pageScrollTo({selector:'#store-search'});},
  clinic(e){navigation.navigateTo({url:'/pages/clinic/index?id='+e.currentTarget.dataset.id});},
  doctors(){const city=this.data.cityIndex?this.data.cities[this.data.cityIndex]:'';navigation.navigateTo({url:'/pages/dentists/index?city='+encodeURIComponent(city)});},
  services(){const city=this.data.cityIndex?this.data.cities[this.data.cityIndex]:'';navigation.navigateTo({url:'/pages/services/index?category='+this.data.categories[this.data.categoryIndex].id+'&city='+encodeURIComponent(city)});},
  account(){this.clearPrivate();navigation.navigateTo({url:'/pages/account/index'});},
  login(){this.clearPrivate();navigation.navigateTo({url:'/pages/login/index'});},
  subjects(){this.clearPrivate();navigation.navigateTo({url:'/pages/patients/index'});},
  medical(){navigation.navigateTo({url:'/pages/medical-authorizations/index'});},
  async logout(){
    try{await api.signOut();}catch(e){}
    this.clearPrivate();this.setData({serviceState:'guest',serviceError:'',serviceRequestId:''});
    navigation.reLaunch({url:'/pages/discovery/index'});
  },
  retryService(){this.clearPrivate();return this.loadService();},
  primaryTap(){const p=this.data.primary;if(p&&p.url)navigation.navigateTo({url:p.url});},
  book(){navigation.navigateTo({url:'/pages/services/index'});},
  arrangements(){navigation.navigateTo({url:'/pages/home/index'});},
  records(){navigation.navigateTo({url:'/pages/home/index?queue=history'});},
  fees(){navigation.navigateTo({url:'/pages/billing/index'});}
});
