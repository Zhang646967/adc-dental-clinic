const navigation=require('../../utils/navigation');
const api=require('../../utils/api');
const {showError}=require('../../utils/format');
Page({
  data:{rows:[],categories:[{id:'',name:'全部服务'}],clinics:[{id:'',name:'全部门店'}],categoryIndex:0,clinicIndex:0,category:'',clinic:'',keyword:'',page:1,pages:1,count:0,busy:false,error:'',alternatives:[],message:''},
  onLoad(query){this.initial=query;},
  async onShow(){api.showSubject(this);const selected=navigation.consume('/pages/services/index')||this.initial||{};this.initial=null;if(selected.category!==undefined)this.setData({category:selected.category});if(selected.clinic!==undefined)this.setData({clinic:selected.clinic});if(selected.city!==undefined)this.setData({city:selected.city,clinic:selected.clinic||'',page:1});await this.load(this.data.page);},
  async load(page=1){
    if(this.data.busy)return;this.setData({busy:true,error:'',rows:[],alternatives:[],message:''});
    try{
      const data=await api.request('discovery/services/','GET',{category:this.data.category,clinic:this.data.clinic,city:this.data.city||'',q:this.data.keyword,page});
      if(!data||!Array.isArray(data.offerings)||!Array.isArray(data.categories)||!Array.isArray(data.clinic_choices))throw Error('服务目录暂不可用，请稍后重试。');
      const categories=[{id:'',name:'全部服务'},...data.categories.map(c=>({...c,name:c.name+' · '+c.count}))];
      const clinics=[{id:'',name:'全部门店'},...data.clinic_choices.map(c=>({...c,name:c.name+(c.count?' · '+c.count+'项':' · 未开放该类服务')}))];
      this.setData({rows:data.offerings,categories,clinics,categoryIndex:Math.max(0,categories.findIndex(c=>c.id===this.data.category)),clinicIndex:Math.max(0,clinics.findIndex(c=>String(c.id)===String(this.data.clinic))),page:data.page,pages:data.pages,count:data.count,alternatives:data.alternatives,message:data.message,busy:false});
    }catch(e){showError(this,e);}
  },
  pickCategory(e){if(this.data.busy)return;const index=Number(e.detail.value);this.setData({category:this.data.categories[index].id,categoryIndex:index});return this.load(1);},
  pickClinic(e){if(this.data.busy)return;const index=Number(e.detail.value);this.setData({clinic:this.data.clinics[index].id,clinicIndex:index});return this.load(1);},
  keyword(e){this.setData({keyword:e.detail.value});},search(){return this.load(1);},
  allCities(){if(this.data.busy)return;this.setData({city:'',clinic:'',keyword:''});return this.load(1);},
  previous(){if(this.data.page>1)this.load(this.data.page-1);},next(){if(this.data.page<this.data.pages)this.load(this.data.page+1);},
  alternative(e){if(this.data.busy)return;this.setData({clinic:e.currentTarget.dataset.id,keyword:''});return this.load(1);},
  open(e){navigation.navigateTo({url:'/pages/service/index?id='+e.currentTarget.dataset.id});}
});
