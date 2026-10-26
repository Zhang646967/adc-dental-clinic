const api=require('../../utils/api');
const nearby=require('../../utils/nearby');
const {showError}=require('../../utils/format');
Page({
  data:{all:[],rows:[],cities:['全部城市'],cityIndex:0,keyword:'',busy:false,error:'',locating:false,locationNote:'使用当前位置后，由近到远展示门店。也可以手动选择城市。',origin:null},
  async onShow(){await this.load();},
  async load(){
    if(this.data.busy)return;
    const previousCity=this.data.cities[this.data.cityIndex];
    this.setData({busy:true,error:'',rows:[],all:[]});
    try{
      const data=await api.request('discovery/');
      const cities=['全部城市',...new Set(data.clinics.map(r=>r.city))];
      this.setData({all:data.clinics,cities,cityIndex:Math.max(0,cities.indexOf(previousCity)),busy:false,environmentLabel:data.environment_label||''});this.filter();
    }catch(e){showError(this,e);}
  },
  filter(){
    const rows=nearby.select(this.data.all,{city:this.data.cityIndex?this.data.cities[this.data.cityIndex]:'',keyword:this.data.keyword,origin:this.data.origin});
    this.setData({rows:rows.map(r=>({...r,distanceLabel:nearby.distanceLabel(r.distance)}))});
  },
  city(e){this.setData({cityIndex:Number(e.detail.value)});this.filter();},
  keyword(e){this.setData({keyword:e.detail.value});this.filter();},
  locate(){
    if(this.data.locating)return;
    this.setData({locating:true});
    wx.getLocation({type:'wgs84',
      success:p=>{
        if(!nearby.point(p.latitude,p.longitude)){this.setData({locating:false,locationNote:'未取得有效位置，请选择城市。'});return;}
        this.setData({origin:{latitude:p.latitude,longitude:p.longitude},locating:false,locationNote:'按直线距离由近到远排序，实际路程以导航为准。'});this.filter();
      },
      fail:()=>this.setData({locating:false,locationNote:'未取得位置权限或定位暂不可用，仍可手动选择城市和浏览门店。'})
    });
  },
  contact(e){
    const row=this.data.all.find(r=>r.id===Number(e.currentTarget.dataset.id));if(!row)return;
    if(row.synthetic){wx.showModal({title:'合成门店',content:'联系电话和地图位置用于本地试用，不发起真实拨号或导航。',showCancel:false});return;}
    if(e.currentTarget.dataset.action==='call')wx.makePhoneCall({phoneNumber:row.phone});
    else if(row.map_latitude!==null&&row.map_longitude!==null)wx.openLocation({latitude:row.map_latitude,longitude:row.map_longitude,name:row.name,address:row.address+' '+row.entrance});
  },
  clinic(e){wx.navigateTo({url:'/pages/clinic/index?id='+e.currentTarget.dataset.id});},
  doctors(){wx.navigateTo({url:'/pages/dentists/index'});},
  services(){wx.navigateTo({url:'/pages/services/index'});},
  openService(e){wx.navigateTo({url:'/pages/service/index?id='+e.currentTarget.dataset.id});},
  account(){wx.navigateTo({url:'/pages/login/index'});}
});
