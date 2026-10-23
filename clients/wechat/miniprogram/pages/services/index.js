const api=require('../../utils/api');
const {showError}=require('../../utils/format');
Page({
  data:{all:[],rows:[],categories:[{id:'',name:'全部服务'}],clinics:[{id:'',name:'全部门店'}],categoryIndex:0,clinicIndex:0,keyword:'',busy:false,error:'',environmentLabel:''},
  async onShow(){await this.load();},
  async load(){
    if(this.data.busy)return;
    this.setData({busy:true,error:'',rows:[],all:[]});
    try{
      const session=await api.bootstrap();
      if(!session.authenticated){this.setData({busy:false});wx.reLaunch({url:'/pages/login/index'});return;}
      const cat=await api.request('catalogue/');
      if(!Array.isArray(cat.offerings)||!Array.isArray(cat.clinics))throw Error('服务目录暂不可用，请稍后重试或联系前台。');
      const categories=[{id:'',name:'全部服务'}];
      for(const row of cat.offerings)if(!categories.some(c=>c.id===row.category))categories.push({id:row.category,name:row.category_label});
      this.setData({all:cat.offerings,categories,clinics:[{id:'',name:'全部门店'}].concat(cat.clinics.filter(c=>cat.offerings.some(s=>s.clinic===c.id))),categoryIndex:0,clinicIndex:0,busy:false,environmentLabel:session.environment_label||''});
      this.filter();
    }catch(e){showError(this,e);}
  },
  filter(){
    const category=this.data.categories[this.data.categoryIndex].id,clinic=this.data.clinics[this.data.clinicIndex].id,term=this.data.keyword.trim().toLowerCase();
    this.setData({rows:this.data.all.filter(s=>(!category||s.category===category)&&(!clinic||s.clinic===clinic)&&(!term||[s.name,s.summary,s.suitable_for].join(' ').toLowerCase().includes(term)))});
  },
  pickCategory(e){this.setData({categoryIndex:Number(e.detail.value)});this.filter();},
  pickClinic(e){this.setData({clinicIndex:Number(e.detail.value)});this.filter();},
  keyword(e){this.setData({keyword:e.detail.value});this.filter();},
  open(e){wx.navigateTo({url:`/pages/service/index?id=${e.currentTarget.dataset.id}`});}
});
