function dateTime(value) {
  const d = new Date(new Date(value).getTime() + 8 * 3600000);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
function arrangement(v) { return Object.assign({}, v, {startLabel: dateTime(v.start), endLabel: dateTime(v.end)}); }
function showError(page, error) { page.setData({error: error.message, busy: false}); }
module.exports = {dateTime, arrangement, showError};
