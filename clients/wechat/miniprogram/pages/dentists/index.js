const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const config=require('../../config');
const {positive}=require('../../utils/booking-intent');
const {showError}=require('../../utils/format');
Page({
  data:{rows:[],cities:['全部城市'],cityIndex:0,categories:[{id:'',name:'全部方向'}],categoryIndex:0,keyword:'',scheduled:false,page:1,pages:1,busy:false,error:''},
  onLoad(query){this.clinic=positive(query.clinic)?Number(query.clinic):'';this.initialCity=query.city||'';},
  async onShow(){await this.load(1);},
  async load(page=1){if(this.data.busy)return;this.setData({busy:true,error:'',rows:[]});
    try{const data=await api.request('discovery/dentists/','GET',{clinic:this.clinic,q:this.data.keyword,
      category:this.data.categories[this.data.categoryIndex].id,city:this.initialCity||(this.data.cityIndex?this.data.cities[this.data.cityIndex]:''),scheduled:this.data.scheduled?'1':'',page});
      this.setData({rows:data.rows.map(d=>({...d,portrait:d.images.length?config.apiBase+d.images[0].url:''})),
        cities:['全部城市',...data.cities],cityIndex:this.initialCity?Math.max(0,['全部城市',...data.cities].indexOf(this.initialCity)):this.data.cityIndex,categories:[{id:'',name:'全部方向'},...data.categories],page:data.page,pages:data.pages,busy:false});this.initialCity='';
    }catch(e){showError(this,e);}},
  category(e){if(this.data.busy)return;this.setData({categoryIndex:Number(e.detail.value)});this.load(1);},
  keyword(e){this.setData({keyword:e.detail.value});},
  city(e){if(this.data.busy)return;this.setData({cityIndex:Number(e.detail.value)});this.load(1);},
  scheduled(e){if(this.data.busy)return;this.setData({scheduled:e.detail.value});this.load(1);},
  search(){this.load(1);},
  previous(){if(this.data.page>1)this.load(this.data.page-1);},
  next(){if(this.data.page<this.data.pages)this.load(this.data.page+1);},
  doctor(e){navigation.navigateTo({url:'/pages/dentist/index?id='+e.currentTarget.dataset.id+(this.clinic?'&clinic='+this.clinic:'')});}
});
