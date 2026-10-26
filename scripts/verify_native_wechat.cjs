/* Actual QR Page handlers with mocked transport. Real device acceptance is separate. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../clients/wechat/miniprogram'),intent=require(path.join(root,'utils/booking-intent'));
function page(options={}){
 let definition,proof=0;const calls=[],navigation=[],state={globalData:{}};
 const wx={reLaunch:v=>navigation.push(v.url),login:v=>{proof++;options.refuse?v.fail():v.success({code:'fresh-platform-code'});}};
 const api={bootstrap:async()=>({account_authenticated:options.logged!==false}),signOut:async()=>{},request:async(route,method,data)=>{
  calls.push({route,method,data});if(options.fail)throw Error('授权已变化');return {state:method==='POST'?(data.decision==='approve'?'APPROVED':'REJECTED'):'PENDING',origin:'https://adc.example.test',expires_at:'2026-10-25T12:03:00+08:00'};
 }};
 vm.runInNewContext(fs.readFileSync(path.join(root,'pages/web-login/index.js'),'utf8'),{Page:p=>definition=p,wx,getApp:()=>state,decodeURIComponent,require:n=>n.endsWith('/api')?api:{showError:(p,e)=>p.setData({error:e.message}),dateTime:x=>x}});
 const p={...definition,data:JSON.parse(JSON.stringify(definition.data)),setData:v=>Object.assign(p.data,v)};return {p,calls,navigation,state,proof:()=>proof};
}
async function verify(){
 const details=[],ticket='0123456789abcdef0123456789abcdef',test=async(name,fn)=>{await fn();details.push(name);};
 await test('scanned scene contains only one typed public ticket',async()=>{const d=page();await d.p.onLoad({scene:ticket});assert.equal(d.calls[0].data.ticket,ticket);assert.equal(d.p.data.ticket.origin,'https://adc.example.test');assert.equal(d.proof(),0);});
 await test('scan from guest resumes QR confirmation before patient enrollment',async()=>{const d=page({logged:false});await d.p.onLoad({scene:ticket});assert.equal(d.navigation[0],'/pages/login/index');assert.equal(intent.destination(d.state,{account_authenticated:true,authenticated:false}),'/pages/web-login/index?ticket='+ticket);assert.equal(d.calls.length,0);});
 await test('invalid scene never becomes an API request',async()=>{const d=page();await d.p.onLoad({scene:'arbitrary/path'});assert.equal(d.calls.length,0);assert(d.p.data.error);});
 await test('approval obtains fresh wx.login proof and sends explicit consent',async()=>{const d=page();await d.p.onLoad({ticket});await d.p.approve();assert.equal(d.proof(),1);const call=d.calls[1];assert.equal(call.method,'POST');assert.equal(call.data.code,'fresh-platform-code');assert.equal(call.data.confirmed,'on');assert.equal(call.data.decision,'approve');assert.equal(d.state.globalData.webLoginTicket,null);});
 await test('rejection does not acquire or send a WeChat login code',async()=>{const d=page();await d.p.onLoad({ticket});await d.p.reject();assert.equal(d.proof(),0);assert.equal(d.calls[1].data.decision,'reject');assert.equal(d.calls[1].data.code,'');});
 await test('platform refusal leaves browser approval unsubmitted',async()=>{const d=page({refuse:true});await d.p.onLoad({ticket});await d.p.approve();assert.equal(d.calls.length,1);assert(d.p.data.error);});
 await test('uncertain or revoked approval retains the public continuation',async()=>{const d=page({fail:true});await d.p.onLoad({ticket});await d.p.approve();assert.equal(d.state.globalData.webLoginTicket,ticket);assert(d.p.data.error);});
 await test('changing accounts preserves only the public ticket',async()=>{const d=page();await d.p.onLoad({ticket});await d.p.switchAccount();assert.equal(d.state.globalData.webLoginTicket,ticket);assert.equal(d.navigation[0],'/pages/login/index');});
 return {passed:true,cases:details.length,details,scope:'Mock transport and native Page handlers; not WeChat platform acceptance'};
}
module.exports={verify};
