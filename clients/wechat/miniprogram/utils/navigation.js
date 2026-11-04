/* Native tab routing; keep only public navigation choices between pages. */
const tabs=new Set(['/pages/discovery/index','/pages/services/index','/pages/home/index','/pages/account/index']);
const allowed=new Set(['clinic','category','city','district','q','page','queue']);
function navigate(options,method){
  const [path,query='']=options.url.split('?');
  if(!tabs.has(path))return wx[method](options);
  const values={};
  for(const pair of query.split('&')){
    const [key,value='']=pair.split('=');
    if(allowed.has(key))values[key]=decodeURIComponent(value).slice(0,80);
  }
  if(query)getApp().globalData.tabNavigation={path,values,expires:Date.now()+600000};
  return wx.switchTab({...options,url:path});
}
function consume(path){
  const pending=getApp().globalData.tabNavigation;
  if(!pending||pending.path!==path)return null;
  getApp().globalData.tabNavigation=null;
  return pending.expires>Date.now()?pending.values:null;
}
// Prefer the existing list or detail so its pagination and filter stay intact.
function returnTo(url){
  const [path,query='']=url.split('?');
  if(tabs.has(path))return navigate({url},'reLaunch');
  const pages=getCurrentPages();
  const previous=pages[pages.length-2];
  if(previous&&'/'+previous.route===path){
    const values=previous.options||{};
    const same=query?query.split('&').every(pair=>{
      const [key,value]=pair.split('=');
      return String(values[key])===value;
    }):!values.id&&!values.new&&!values.step;
    if(same)return wx.navigateBack({delta:1});
  }
  return wx.redirectTo({url});
}
module.exports={consume,returnTo,navigateTo:options=>navigate(options,'navigateTo'),
  redirectTo:options=>navigate(options,'redirectTo'),reLaunch:options=>navigate(options,'reLaunch')};
