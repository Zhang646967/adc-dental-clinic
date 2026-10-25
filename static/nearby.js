/* All distance inputs are WGS-84. No coordinates are persisted or transmitted. */
(function(root){
  function point(lat,lon){return typeof lat==='number'&&typeof lon==='number'&&Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180;}
  function distance(a,b){
    if(!point(a.latitude,a.longitude)||!point(b.latitude,b.longitude))return null;
    const rad=x=>x*Math.PI/180,dx=rad(b.latitude-a.latitude),dy=rad(b.longitude-a.longitude);
    const h=Math.sin(dx/2)**2+Math.cos(rad(a.latitude))*Math.cos(rad(b.latitude))*Math.sin(dy/2)**2;
    return 6371*2*Math.atan2(Math.sqrt(Math.min(1,h)),Math.sqrt(Math.max(0,1-h)));
  }
  function select(rows,{city='',keyword='',origin=null}={}){
    const term=keyword.trim().toLowerCase();
    return rows.filter(r=>(!city||r.city===city)&&(!term||[r.name,r.city,r.district,r.address].join(' ').toLowerCase().includes(term)))
      .map(r=>({...r,distance:origin?distance(origin,r):null})).sort((a,b)=>{
        if(a.distance!==null||b.distance!==null){const d=(a.distance===null?Infinity:a.distance)-(b.distance===null?Infinity:b.distance);if(d)return d;}
        return a.id-b.id;
      });
  }
  function distanceLabel(value){return value===null?'':value<1?'约'+Math.round(value*1000)+'米':'约'+value.toFixed(1)+'公里';}
  const api={point,distance,select,distanceLabel};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ADCNearby=api;
})(typeof window!=='undefined'?window:this);
