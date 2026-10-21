function dateTime(value) {
  const d = new Date(new Date(value).getTime() + 8 * 3600000);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
function arrangement(v) { return Object.assign({}, v, {startLabel: dateTime(v.start), endLabel: dateTime(v.end)}); }
function waitEntry(v) {
  return Object.assign({}, v, {startLabel:dateTime(v.earliest), endLabel:dateTime(v.latest),
    offers:v.offers.map(o=>Object.assign(arrangement(o), {expiresLabel:dateTime(o.expires)}))});
}
function showError(page, error) {
  page.setData({error: error.message, busy: false});
  if (error.status === 401) wx.reLaunch({url:'/pages/login/index'});
}
module.exports = {dateTime, arrangement, waitEntry, showError};
