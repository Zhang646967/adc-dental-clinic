// Documentation-only renderer; requires @viz-js/viz and Playwright with local Chrome.
const fs=require('node:fs'),path=require('node:path');
const {instance}=require('@viz-js/viz'),{chromium}=require('playwright');
(async()=>{
 const folder=path.resolve(__dirname,'../diagrams'),viz=await instance();
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:2400,height:1800},deviceScaleFactor:1});
 for(const name of ['domain_care','domain_appointment','visit_state','improvement_state','domain_reception','domain_resources','reception_state','resource_state']){
  // WASM Graphviz has no CJK font metrics. Reserve measured label widths using
  // monospace proxies, then restore the original text in the resulting SVG.
  const original=fs.readFileSync(path.join(folder,name+'.dot'),'utf8');
  const labels=[];
  const segments=[...original.matchAll(/(?:headlabel|taillabel|label)="((?:\\.|[^"\\])*)"/g)]
    .flatMap(m=>m[1].split(/(\\[lnr]|[{}|])/g)).filter(s=>s&&!/^(\\[lnr]|[{}|])$/.test(s));
  const widths=await page.evaluate(strings=>{
   const c=document.createElement('canvas').getContext('2d');
   c.font='20px "Noto Sans CJK SC", "PingFang SC", sans-serif';
   return strings.map(s=>c.measureText(s).width/20);
  },segments);
  let i=0;
  let measured=original.replace(/((?:headlabel|taillabel|label)=)"((?:\\.|[^"\\])*)"/g,(all,key,label)=>
   key+'"'+label.split(/(\\[lnr]|[{}|])/g).map(s=>{
    if(!s||/^(\\[lnr]|[{}|])$/.test(s))return s;
    const proxy=('p'+String(i).padStart(4,'0')+'_').padEnd(Math.max(6,Math.ceil((widths[i]+.7)/.6)),'x');
    labels.push([proxy,s]);i++;return proxy;
   }).join('')+'"').replaceAll('Noto Sans CJK SC','Courier');
  // HTML compartments support same-rank associations, which Graphviz record
  // shapes can silently omit.
  if(name.startsWith('domain_')){
   measured=measured.replace('shape=record','shape=plain').replace(/label="\{([^"]+)\}"/g,(all,body)=>{
    const cells=body.split('|');
    const line=s=>s.replace(/\\l/g,'<BR ALIGN="LEFT"/>').replace(/\\n/g,'<BR/>');
    return 'label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="9">'+
     cells.map((s,k)=>'<TR><TD '+(k?'ALIGN="LEFT"':'BORDER="1"')+'>'+line(s)+'</TD></TR>').join('')+'</TABLE>>';
   });
  }
  let svg=viz.renderString(measured,{format:'svg',engine:'dot'}).replace(/font-family="Courier[^"]*"/g,'font-family="Noto Sans CJK SC, PingFang SC, sans-serif"');
  for(const [proxy,label] of labels)svg=svg.replace('>'+proxy+'<','>'+label.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')+'<');
  fs.writeFileSync(path.join(folder,name+'.svg'),svg);
  await page.setContent('<style>body{margin:0;background:#fff}svg{width:2200px;height:auto;display:block}</style>'+svg);
  await page.evaluate(()=>document.fonts.ready);
  await page.locator('svg').screenshot({path:path.join(folder,name+'.png')});
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
