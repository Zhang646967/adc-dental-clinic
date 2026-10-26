/* Actual P1 Page handlers with controlled transport, not WeChat device proof. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
async function verify(){
  let count=0;
  const intent=require(path.join(root,'utils/booking-intent'));
  function page(name,{responses=[],session={authenticated:false}}={}){
    const calls=[],navigations=[],app={globalData:{}};let definition;
    const api={async request(...args){calls.push(args);const next=responses.shift();if(next instanceof Error)throw next;return next;},
      async bootstrap(){calls.push(['bootstrap']);return session;}};
    const wx={navigateTo:r=>navigations.push(r.url),makePhoneCall:()=>{throw Error('Synthetic clinic must not call');}};
    vm.runInNewContext(fs.readFileSync(path.join(root,`pages/${name}/index.js`),'utf8'),{
      Page:d=>{definition=d;},getApp:()=>app,wx,require:key=>key.endsWith('/api')?api:key.endsWith('/config')?{apiBase:'https://fixture.invalid'}:
        key.endsWith('/booking-intent')?intent:key.endsWith('/format')?{showError:(p,e)=>p.setData({busy:false,error:e.message})}:null});
    const p={...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(d){Object.assign(this.data,d);}};
    return {p,calls,navigations,app};
  }
  const doctor=()=>({id:7,name:'课程医师',images:[],clinics:[{id:3,name:'课程门店',services:[{id:11}],shifts:[]}]});
  let h=page('dentist');h.p.onLoad({id:'../account'});await h.p.load();assert.equal(h.calls.length,0);assert(h.p.data.error);count++;
  h=page('dentist',{responses:[doctor()]});h.p.onLoad({id:'7',clinic:'3'});await h.p.load();assert.equal(h.p.data.doctor.id,7);assert.equal(h.calls[0][0],'discovery/dentists/7/');count++;
  await h.p.book({currentTarget:{dataset:{clinic:3,service:11}}});assert.equal(h.navigations[0],'/pages/login/index');assert.equal(h.app.globalData.bookingIntent.dentist,7);count++;
  h=page('dentist',{responses:[doctor()],session:{authenticated:true,account_authenticated:true,subject_required:true}});h.p.onLoad({id:7});await h.p.load();await h.p.book({currentTarget:{dataset:{clinic:3,service:11}}});assert.equal(h.navigations[0],'/pages/patients/index');count++;
  h=page('dentist',{responses:[doctor()],session:{authenticated:true}});h.p.onLoad({id:7});await h.p.load();await h.p.book({currentTarget:{dataset:{clinic:3,service:11}}});assert.equal(h.navigations[0],'/pages/booking/index?clinic=3&service=11&dentist=7');count++;
  h=page('dentist',{responses:[doctor()],session:{authenticated:true}});h.p.onLoad({id:7});await h.p.load();await h.p.book({currentTarget:{dataset:{clinic:999,service:11}}});assert.equal(h.navigations.length,0);assert.equal(h.calls.length,1);count++;
  h=page('dentist',{responses:[doctor()],session:{authenticated:true,read_only:true}});h.p.onLoad({id:7});await h.p.load();await h.p.book({currentTarget:{dataset:{clinic:3,service:11}}});assert.equal(h.navigations.length,0);assert(h.p.data.error);count++;
  h=page('dentist',{responses:[Error('资料已撤回')]});h.p.onLoad({id:7});h.p.data.doctor=doctor();await h.p.load();assert.equal(h.p.data.doctor,null);count++;
  h=page('clinic',{responses:[{id:3,images:[{url:'/profiles/media/1/'}],team:[],synthetic:true}]});h.p.onLoad({id:3});await h.p.load();assert.equal(h.p.data.clinic.images[0].url,'https://fixture.invalid/profiles/media/1/');h.p.call();count++;
  h=page('clinic',{responses:[Error('门店已撤回')]});h.p.onLoad({id:3});h.p.data.clinic={id:3};await h.p.load();assert.equal(h.p.data.clinic,null);count++;
  const app={globalData:{}};intent.remember(app,11,3,7);assert.equal(intent.destination(app,{authenticated:true}),'/pages/booking/index?service=11&clinic=3&dentist=7');assert.equal(app.globalData.bookingIntent,null);count++;
  app.globalData.bookingIntent={service:11,clinic:3,dentist:7,expires:Date.now()-1};assert.equal(intent.destination(app,{authenticated:true}),'/pages/home/index');count++;
  return {passed:true,cases:count,scope:'Profile Page handlers and typed doctor continuation; provider/device validation remains separate'};
}
module.exports={verify};
if(require.main===module)verify().then(result=>console.log(JSON.stringify(result))).catch(e=>{console.error(e);process.exitCode=1;});
