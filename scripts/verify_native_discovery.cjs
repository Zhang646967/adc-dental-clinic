/* C0.4 actual Page handlers and analytic distance checks; no WeChat runtime claim. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram');
const nearby=require(path.join(root,'utils/nearby')),intent=require(path.join(root,'utils/booking-intent'));
const clinics=[
 {id:1,name:'长沙中心门店',city:'长沙',district:'芙蓉区',address:'合成地址',latitude:28.2,longitude:113.0,synthetic:true},
 {id:2,name:'长沙梅溪湖门店',city:'长沙',district:'岳麓区',address:'合成地址',latitude:28.18,longitude:112.9,synthetic:true},
 {id:3,name:'武汉光谷门店',city:'武汉',district:'洪山区',address:'合成地址',latitude:30.5,longitude:114.4,synthetic:true},
 {id:4,name:'尚未核对坐标',city:'长沙',district:'长沙县',address:'合成地址',latitude:null,longitude:null,synthetic:true}
].map(c=>({...c,images:[],services:[],service_categories:[],team_count:0,online_booking:false}));
function page(options={}){
 let definition,geo,requests=[],navigation=[],dialogs=[],phone=0,map=0;
 const wx={getLocation(o){geo=o;},showModal(o){dialogs.push(o);},makePhoneCall(){phone++;},openLocation(){map++;},
   navigateTo(o){navigation.push(o);},reLaunch(o){navigation.push(o);}};
 const api={request:async route=>{requests.push(route);if(options.fail)throw Error('暂时无法更新');return {clinics,categories:[],environment_label:'测试环境'};}};
 const module={exports:{}};
 vm.runInNewContext(fs.readFileSync(path.join(root,'utils/format.js'),'utf8'),{module,wx});
 vm.runInNewContext(fs.readFileSync(path.join(root,'pages/discovery/index.js'),'utf8'),{
   Page:d=>definition=d,wx,require:name=>name.endsWith('/navigation')?{navigateTo:wx.navigateTo,reLaunch:wx.reLaunch,consume:()=>null}:name.endsWith('/config')?{apiBase:'https://fixture.invalid'}:name.endsWith('/api')?api:name.endsWith('/nearby')?nearby:module.exports
 });
 const p={...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(v){Object.assign(this.data,v);}};
 return {p,requests,navigation,dialogs,geo:()=>geo,external:()=>({phone,map})};
}
async function verify(){
 const cases=[];async function test(name,run){await run();cases.push(name);}
 await test('browser and native distance source bytes match',()=>assert.deepEqual(fs.readFileSync(path.join(root,'utils/nearby.js')),fs.readFileSync(path.resolve(__dirname,'../static/nearby.js'))));
 await test('analytic zero and quarter-equator distance',()=>{
   assert.equal(nearby.distance({latitude:0,longitude:0},{latitude:0,longitude:0}),0);
   assert(Math.abs(nearby.distance({latitude:0,longitude:0},{latitude:0,longitude:90})-10007.54)<.02);
 });
 await test('unknown coordinates remain unknown and sort after measured points',()=>{
   const rows=nearby.select(clinics,{origin:{latitude:28.18,longitude:112.9}});
   assert.equal(rows[0].id,2);assert.equal(rows.at(-1).id,4);assert.equal(rows.at(-1).distance,null);
 });
 await test('manual city and district filtering works without GPS',()=>{
   assert.deepEqual(nearby.select(clinics,{city:'长沙',keyword:'梅溪湖'}).map(r=>r.id),[2]);
   assert.equal(nearby.select(clinics,{city:'不存在的城市'}).length,0);
 });
 await test('guest startup requests only public discovery without login or automatic location',async()=>{
   const d=page();await d.p.onShow();assert.deepEqual(d.requests,['discovery/index/']);assert.equal(d.navigation.length,0);assert.equal(d.geo(),undefined);assert.equal(d.p.data.rows.length,4);
 });
 await test('permission denial preserves manual browsing',async()=>{
   const d=page();await d.p.onShow();d.p.locate();assert.equal(d.geo().type,'wgs84');d.geo().fail();
   assert.equal(d.p.data.locating,false);assert.equal(d.p.data.rows.length,4);assert.match(d.p.data.locationNote,/手动/);
 });
 await test('location success changes order without sending coordinates to the API',async()=>{
   const d=page();await d.p.onShow();d.p.locate();d.geo().success({latitude:28.18,longitude:112.9});
   assert.equal(d.p.data.rows[0].id,2);assert.equal(d.p.data.rows[0].distanceLabel,'约0米');assert.deepEqual(d.requests,['discovery/index/']);
 });
 await test('all synthetic contact actions stop before external calls',async()=>{
   const d=page();await d.p.onShow();
   d.p.clinic({currentTarget:{dataset:{id:1}}});
   assert.deepEqual(d.external(),{phone:0,map:0});assert.equal(d.navigation[0].url,'/pages/clinic/index?id=1');
 });
 await test('failed refresh clears previously published cards',async()=>{
   const d=page({fail:true});d.p.setData({all:clinics,rows:clinics});await d.p.load();
   assert.equal(d.p.data.rows.length,0);assert.equal(d.p.data.all.length,0);assert(d.p.data.error);
 });
 await test('return to discovery retains manual city choice',async()=>{
   const d=page();await d.p.onShow();const i=d.p.data.cities.indexOf('武汉');d.p.city({detail:{value:i}});await d.p.onShow();assert.equal(d.p.data.rows[0].city,'武汉');
 });
 await test('typed intent survives patient selection and is consumed only at continuation',()=>{
   const app={globalData:{}};intent.remember(app,17,3);
   assert.equal(intent.destination(app,{subject_required:true}),'/pages/patients/index');assert.equal(app.globalData.bookingIntent.service,17);
   assert.equal(intent.destination(app,{subject_required:false}),'/pages/booking/index?service=17&clinic=3');assert.equal(app.globalData.bookingIntent,null);
 });
 await test('invalid and expired intent cannot become arbitrary navigation',()=>{
   const app={globalData:{}};assert.throws(()=>intent.remember(app,'//example.invalid',3));
   app.globalData.bookingIntent={service:17,clinic:3,expires:Date.now()-1};
   assert.equal(intent.destination(app,{subject_required:false}),'/pages/home/index');
 });
 return {passed:true,cases:cases.length,details:cases,scope:'actual discovery Page handlers with mocked transport; analytic distance and typed continuation; not WeChat runtime'};
}
module.exports={verify};
if(require.main===module)verify().then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e.stack);process.exitCode=1;});
