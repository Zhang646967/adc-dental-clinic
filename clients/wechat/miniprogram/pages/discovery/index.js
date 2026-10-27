const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const nearby=require('../../utils/nearby');
const config=require('../../config');
const {showError}=require('../../utils/format');
Page({
  data:{all:[],rows:[],cities:['全部城市'],cityIndex:0,categories:[{id:'',name:'全部服务'}],categoryIndex:0,keyword:'',onlineOnly:false,busy:false,error:'',locating:false,origin:null,limit:10,count:0,hasMore:false,locationNote:'可直接浏览；主动使用定位后，按直线距离由近到远排序。'},
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
  clinic(e){navigation.navigateTo({url:'/pages/clinic/index?id='+e.currentTarget.dataset.id});},
  doctors(){const city=this.data.cityIndex?this.data.cities[this.data.cityIndex]:'';navigation.navigateTo({url:'/pages/dentists/index?city='+encodeURIComponent(city)});},
  services(){const city=this.data.cityIndex?this.data.cities[this.data.cityIndex]:'';navigation.navigateTo({url:'/pages/services/index?category='+this.data.categories[this.data.categoryIndex].id+'&city='+encodeURIComponent(city)});},
  account(){navigation.navigateTo({url:'/pages/account/index'});}
});
