function dateTime(value) {
  if (!value) return '';
  const d = new Date(new Date(value).getTime() + 8 * 3600000);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
function arrangement(v) { return Object.assign({}, v, {startLabel: dateTime(v.start), endLabel: dateTime(v.end)}); }
function waitEntry(v) {
  const offers=v.offers.map(o=>Object.assign(arrangement(o),{expiresLabel:dateTime(o.expires)}));
  // The server may retain a pending offer row until the expiry job runs.
  const expired=v.state==='OFFERED'&&offers.find(o=>o.state==='PENDING'&&o.active===false);
  return Object.assign({},v,{startLabel:dateTime(v.earliest),endLabel:dateTime(v.latest),
    status_label:expired?expired.status_label:v.status_label,offers});
}
function showError(page, error, {stayOnLogin = false, separateRequestId = false} = {}) {
  const display={error:error.message,busy:false};
  if(separateRequestId){display.error=error.publicMessage||error.message;display.requestId=error.requestId||'';}
  page.setData(display);
  if(error.code==='SUBJECT_REQUIRED'){wx.reLaunch({url:'/pages/patients/index'});return;}
  if (error.status === 401 && !stayOnLogin) wx.reLaunch({url:'/pages/login/index'});
}
module.exports = {dateTime, arrangement, waitEntry, showError};
