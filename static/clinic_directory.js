(function(){
  const node=document.getElementById('clinic-discovery-data');if(!node)return;
  const data=JSON.parse(node.textContent),rows=data.clinics,nearby=window.ADCNearby;
  const city=document.getElementById('clinic-city'),area=document.getElementById('clinic-area'),list=document.getElementById('clinic-results');
  const status=document.getElementById('clinic-location-status'),button=document.getElementById('clinic-locate');
  const limit=Number(document.querySelector('.clinic-discovery').dataset.limit)||0;
  const cards=new Map([...list.querySelectorAll('[data-clinic]')].map(c=>[Number(c.dataset.clinic),c]));
  let origin=null;
  for(const name of [...new Set(rows.map(r=>r.city))].sort()){const o=document.createElement('option');o.value=name;o.textContent=name;city.append(o);}
  function render(){
    for(const c of cards.values())c.hidden=true;
    const selected=nearby.select(rows,{city:city.value,keyword:area.value,origin});
    for(const row of (limit?selected.slice(0,limit):selected)){const c=cards.get(row.id);if(!c)continue;c.hidden=false;c.querySelector('.clinic-distance').textContent=nearby.distanceLabel(row.distance);list.append(c);}
    document.getElementById('clinic-empty').hidden=selected.length!==0;
  }
  city.addEventListener('change',render);area.addEventListener('input',render);
  button.addEventListener('click',()=>{
    if(!navigator.geolocation){status.textContent='当前浏览器无法定位，请手动选择城市或区域。';return;}
    button.disabled=true;status.textContent='正在请求当前位置，仅用于本次找店排序…';
    navigator.geolocation.getCurrentPosition(p=>{
      button.disabled=false;
      if(!nearby.point(p.coords.latitude,p.coords.longitude)){status.textContent='暂未取得有效位置，请手动选择城市。';return;}
      origin={latitude:p.coords.latitude,longitude:p.coords.longitude};
      status.textContent='已按直线距离由近到远排序；实际路程请以导航为准，可继续筛选城市。';render();
    },()=>{button.disabled=false;status.textContent='未取得位置权限或定位暂不可用，仍可手动选择城市和浏览门店。';},{enableHighAccuracy:false,timeout:10000,maximumAge:60000});
  });
  render();
})();
