// Documentation-only exports. Use the bundled Node runtime, @viz-js/viz and Chrome.
const fs=require('node:fs'),path=require('node:path');
const {instance}=require('@viz-js/viz'),{chromium}=require('playwright');
(async()=>{
 const folder=__dirname,manifest=JSON.parse(fs.readFileSync(path.join(folder,'view_manifest.json')));
 const viz=await instance(),browser=await chromium.launch({channel:'chrome',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:2400,height:2400},deviceScaleFactor:1});
  const validation={};
  for(const [name,view] of Object.entries(manifest)){
   if(name==='validation')continue;
   const result=viz.render(fs.readFileSync(path.join(folder,name+'.dot'),'utf8'),{format:'svg',engine:'dot'});
   if(result.status!=='success')throw new Error(JSON.stringify(result.errors));
   let svg=result.output.replace('<svg ','<svg role="img" aria-labelledby="'+name+'-title '+name+'-desc" ')
     .replace(/(<svg[^>]*>)/,'$1<title id="'+name+'-title">'+view.title+'</title><desc id="'+name+'-desc">'+view.note+'</desc>');
   fs.writeFileSync(path.join(folder,name+'.svg'),svg);
   await page.setContent('<style>body{margin:0;background:white}svg{display:block;width:2200px;height:auto}</style>'+svg);
   await page.evaluate(()=>document.fonts.ready);
   const facts=await page.locator('svg').evaluate(el=>{
    const vb=el.viewBox.baseVal;
    const text=[...el.querySelectorAll('text')];
    return {nodes:el.querySelectorAll('g.node').length,edges:el.querySelectorAll('g.edge').length,
     width:vb.width,height:vb.height,minPrintedFontPt:Math.min(...text.filter(t=>!['1','0..1','0..*'].includes(t.textContent)).map(t=>Number(t.getAttribute('font-size'))))*453.54/vb.width,
     diagramText:text.map(t=>t.textContent).join('\n')};
   });
   if(facts.nodes!==view.tables||facts.edges!==view.relationships)throw new Error(name+': missing nodes/edges');
   for(const [table,cols] of Object.entries(view.columns)){
    if(!facts.diagramText.includes(table)||cols.some(c=>!facts.diagramText.includes(c)))throw new Error(name+': missing labels');
   }
   await page.locator('svg').screenshot({path:path.join(folder,name+'.png')});
   delete facts.diagramText;validation[name]=facts;
  }
  fs.writeFileSync(path.join(folder,'render_validation.json'),JSON.stringify(validation,null,2)+'\n');
  console.log(JSON.stringify(validation));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
