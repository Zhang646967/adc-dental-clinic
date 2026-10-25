/* Typed navigation only. The backend still rechecks service, patient and resources. */
function positive(value){return /^[1-9][0-9]{0,17}$/.test(String(value))&&Number.isSafeInteger(Number(value));}
function remember(app,service,clinic){
  if(!positive(service)||!positive(clinic))throw Error('服务或门店链接无效，请重新选择。');
  app.globalData.bookingIntent={service:Number(service),clinic:Number(clinic),expires:Date.now()+10*60000};
}
function destination(app,session){
  if(session.subject_required)return '/pages/patients/index';
  const intent=app.globalData.bookingIntent;app.globalData.bookingIntent=null;
  if(intent&&intent.expires>Date.now()&&positive(intent.service)&&positive(intent.clinic))
    return '/pages/booking/index?service='+intent.service+'&clinic='+intent.clinic;
  return '/pages/home/index';
}
module.exports={remember,destination,positive};
