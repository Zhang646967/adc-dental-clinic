/* The WeChat client reports the user's choice in `fontSizeSetting` (16 at the
   standard step). WXSS sizes are rpx, which follow the screen width instead,
   so every patient appointment screen maps that value onto one of the existing
   typography tiers. A missing, non-numeric or out-of-range value keeps the
   default tier, which is the layout the app already had. */

const BASE = 16;
const MIN = 12;
const MAX = 40;

/* The client offers 15/16/17/19/23/26. The two larger steps are what the
   patient notices; anything between them follows the nearest tier. */
const TIERS = [
  {name: 'compact', from: MIN, to: 15.4},
  {name: '', from: 15.5, to: 17.5},
  {name: 'large', from: 17.6, to: 21.5},
  {name: 'xlarge', from: 21.6, to: MAX}
];

function normalize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return BASE;
  const rounded = Math.round(size * 10) / 10;
  if (rounded < MIN || rounded > MAX) return BASE;
  return rounded;
}

/* Read once per page show: the patient may change the setting in WeChat and
   come back to a page that is already in the stack. */
function read() {
  try {
    const info = wx.getSystemInfoSync();
    return normalize(info && info.fontSizeSetting);
  } catch (e) {
    return BASE;
  }
}

function tier(value) {
  const size = normalize(value);
  const match = TIERS.find(item => size >= item.from && size <= item.to);
  return match ? match.name : '';
}

function className(value) {
  const name = tier(value);
  return name ? 'text-scale-' + name : '';
}

/* Pages call this from onShow so the first open and every return use the
   value that is in effect now, not the one captured at launch. */
function apply(page) {
  const size = read();
  const name = className(size);
  if (page && typeof page.setData === 'function') page.setData({textScale: name, textScaleSize: size});
  return name;
}

module.exports = {BASE, MIN, MAX, normalize, read, tier, className, apply};
