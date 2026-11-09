/* Invoice Page handlers only; official tool and physical device remain separate. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const file=path.resolve(__dirname,'../clients/wechat/miniprogram/pages/invoice/index.js');
const fundsFile=path.resolve(__dirname,'../clients/wechat/miniprogram/pages/funds/index.js');
function fixture(options={}){
 let definition;const calls=[];
 const api={request:async(route,method,data)=>{
  calls.push({route,method,data:{...data}});if(options.fail)throw Error('当前就诊人权限已失效');
  const page=data.cash_page||1;
  return {revision:data.revision||2,revisions:[{revision_no:2,published_at:'2026-11-02T00:00:00Z'},{revision_no:1,published_at:'2026-11-01T00:00:00Z'}],published_at:'2026-11-02T00:00:00Z',cash_activity:{receipts:'200.00',refunds:'40.00',entries:[{id:page,posted_at:'2026-11-02T00:00:00Z'}],page,previous:page===2?1:null,next:page===1?2:null}};
 }};
 vm.runInNewContext(fs.readFileSync(file,'utf8'),{Page:p=>definition=p,require:n=>n.endsWith('/api')?api:n.endsWith('/booking-intent')?{positive:v=>Number.isSafeInteger(Number(v))&&Number(v)>0}:{showError:(p,e)=>p.setData({invoice:null,error:e.message,busy:false}),dateTime:x=>'BJ '+x}});
 const p={...definition,data:JSON.parse(JSON.stringify(definition.data)),setData:v=>Object.assign(p.data,v)};
 p.onLoad({id:'1'});return {p,calls,options};
}
async function verify(){
 const details=[];const test=async(name,fn)=>{await fn();details.push(name);};
 await test('initial read requests first cash page and displays posted date',async()=>{const d=fixture();await d.p.onShow();assert.equal(d.calls[0].data.cash_page,1);assert.equal(d.p.data.invoice.cash_activity.entries[0].postedLabel,'BJ 2026-11-02T00:00:00Z');});
 await test('cash pagination preserves selected invoice revision',async()=>{const d=fixture();d.p.revision=1;await d.p.onShow();await d.p.cashPageChange({currentTarget:{dataset:{direction:'next'}}});assert.deepEqual(d.calls[1].data,{cash_page:2,revision:1});assert.equal(d.p.data.invoice.cash_activity.receipts,'200.00');});
 await test('changing invoice version returns cash list to first page',async()=>{const d=fixture();await d.p.onShow();await d.p.cashPageChange({currentTarget:{dataset:{direction:'next'}}});await d.p.version({detail:{value:1}});assert.deepEqual(d.calls[2].data,{cash_page:1,revision:1});});
 await test('missing next page makes no additional request',async()=>{const d=fixture();await d.p.onShow();await d.p.cashPageChange({currentTarget:{dataset:{direction:'previous'}}});assert.equal(d.calls.length,1);});
 await test('revoked read clears displayed invoice and supports a fresh retry',async()=>{const d=fixture();await d.p.onShow();d.options.fail=true;await d.p.load();assert.equal(d.p.data.invoice,null);assert(d.p.data.error);assert.equal(d.p.data.busy,false);d.options.fail=false;await d.p.load();assert(d.p.data.invoice);assert.equal(d.p.data.error,'');});
 await test('busy state prevents duplicate pagination reads',async()=>{const d=fixture();await d.p.onShow();d.p.data.busy=true;await d.p.cashPageChange({currentTarget:{dataset:{direction:'next'}}});assert.equal(d.calls.length,1);});
 return {passed:true,cases:details.length,details,scope:'Native invoice Page handlers with controlled transport; not official-tool or phone acceptance'};
}

async function verifyFunds(){
 let definition;
 const requests=[];
 const api={request(route,method,query){return new Promise((resolve,reject)=>requests.push({route,method,query:{...query},resolve,reject}));}};
 const format={dateTime:x=>'BJ '+x,showError:(p,e)=>p.setData({error:e.message,busy:false})};
 vm.runInNewContext(fs.readFileSync(fundsFile,'utf8'),{Page:p=>definition=p,require:n=>n.endsWith('/api')?api:format});
 const p={...definition,data:{...definition.data},setData:v=>Object.assign(p.data,v)};
 const data=(id,page)=>({selected:{id,available:'130.00'},entries:[{posted_at:'2026-11-08T10:00:00Z'}],page,next:page===1?2:null});

 let pending=p.onShow();
 assert.deepEqual([requests[0].route,requests[0].method,requests[0].query],['funds/','GET',{clinic:'',page:1}]);
 requests[0].resolve(data(1,1));await pending;
 assert.equal(p.data.statement.entries[0].postedLabel,'BJ 2026-11-08T10:00:00Z');
 pending=p.turn({currentTarget:{dataset:{direction:'next'}}});
 assert.deepEqual(requests[1].query,{clinic:1,page:2});
 requests[1].resolve(data(1,2));await pending;
 pending=p.selectClinic({currentTarget:{dataset:{clinic:2}}});
 assert.deepEqual(requests[2].query,{clinic:2,page:1});
 assert.equal(p.data.statement,null);
 requests[2].resolve(data(2,1));await pending;
 pending=p.onShow();p.onHide();
 requests[3].resolve(data(2,1));await pending;
 assert.equal(p.data.statement,null);
 pending=p.onShow();requests[4].reject(Error('当前账号授权已失效'));await pending;
 assert.equal(p.data.statement,null);assert(p.data.error);
 pending=p.retry();assert.deepEqual(requests[5].query,{clinic:'',page:1});
 requests[5].resolve(data(1,1));await pending;
 assert.equal(p.data.error,'');assert.equal(p.data.statement.selected.available,'130.00');
 return {passed:true,cases:6,scope:'read, date, pagination, clinic change, late response, and revoked retry with controlled transport'};
}

module.exports={verify,verifyFunds};
