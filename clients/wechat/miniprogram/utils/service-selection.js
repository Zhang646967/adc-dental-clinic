/* A typed service hint may select that service only; never silently substitute. */
function selectedCatalogue(catalogue, query={}) {
  if(!catalogue || !Array.isArray(catalogue.services) || !Array.isArray(catalogue.clinics) || !Array.isArray(catalogue.offerings))throw Error('服务目录暂不可用，请稍后重试或联系前台。');
  const services=catalogue.services.filter(s=>s.self_booking);
  const clinics=catalogue.clinics.filter(c=>services.some(s=>s.clinic===c.id));
  let chosen=null;
  if(query.service!==undefined && query.service!=='') {
    const value=String(query.service);
    if(!/^[1-9][0-9]{0,17}$/.test(value) || !Number.isSafeInteger(Number(value))) throw Error('服务链接无效，请返回服务目录重新选择。');
    chosen=services.find(s=>String(s.id)===value);
    if(!chosen || (query.clinic && String(chosen.clinic)!==String(query.clinic))) throw Error('所选服务已变化，请返回服务目录重新查看。');
  }
  const clinic=chosen ? chosen.clinic : query.clinic;
  const clinicIndex=clinic ? clinics.findIndex(c=>String(c.id)===String(clinic)) : 0;
  if(clinic && clinicIndex<0) throw Error('本店暂未开放在线服务，请查看其他门店或联系前台。');
  return {clinics,allServices:services,clinicIndex:Math.max(0,clinicIndex),selectedId:chosen ? chosen.id : null};
}
module.exports={selectedCatalogue};
