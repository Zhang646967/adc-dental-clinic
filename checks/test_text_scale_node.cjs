/* The WeChat font size is a runtime value, so the mapping is tested as a pure
   function and the rendered tiers are read back from the committed WXSS. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../clients/wechat/miniprogram');
const scale = require(path.join(root, 'utils/text-scale'));

let checks = 0;
const ok = (value, message) => { assert.ok(value, message); checks++; };
const eq = (actual, expected, message) => { assert.equal(actual, expected, message); checks++; };

// --- the three steps the client offers ------------------------------------
eq(scale.normalize(16), 16, 'the standard step is 16');
eq(scale.className(16), '', 'the standard step keeps the default tier');
eq(scale.className(19), 'text-scale-large', '19 uses the large tier');
eq(scale.className(26), 'text-scale-xlarge', '26 uses the extra-large tier');
eq(scale.className(15), 'text-scale-compact', '15 uses the compact tier');
eq(scale.className(17), '', '17 still reads as the standard tier');
eq(scale.className(23), 'text-scale-xlarge', '23 already needs the largest tier');

// --- a missing or unusable value never breaks the page --------------------
for (const value of [undefined, null, '', 0, -1, NaN, Infinity, 'large', 999, 4]) {
  eq(scale.normalize(value), 16, 'invalid font size falls back to 16: ' + String(value));
  eq(scale.className(value), '', 'invalid font size keeps the default tier: ' + String(value));
}
eq(scale.normalize(19.4), 19.4, 'a fractional setting is kept');
eq(scale.normalize(26.04), 26, 'a fractional setting is rounded to one decimal');

// --- read() uses the value the client reports, and survives an old client --
global.wx = {getSystemInfoSync: () => ({fontSizeSetting: 26})};
eq(scale.read(), 26, 'read follows the reported setting');
global.wx = {getSystemInfoSync: () => ({fontSizeSetting: 19})};
eq(scale.read(), 19, 'read follows a second setting');
global.wx = {getSystemInfoSync: () => ({})};
eq(scale.read(), 16, 'an old client without the field stays standard');
global.wx = {getSystemInfoSync: () => { throw new Error('unsupported'); }};
eq(scale.read(), 16, 'a failing system call stays standard');

// --- apply() sets the class on the page that asks for it ------------------
let received = null;
global.wx = {getSystemInfoSync: () => ({fontSizeSetting: 26})};
const page = {setData: data => { received = data; }};
eq(scale.apply(page), 'text-scale-xlarge', 'apply returns the tier');
eq(received.textScale, 'text-scale-xlarge', 'the page receives the class');
eq(received.textScaleSize, 26, 'the page receives the value for support reports');
eq(scale.apply(null), 'text-scale-xlarge', 'a missing page is tolerated');

// --- every appointment screen reads the setting on entry ------------------
const pages = {
  'pages/home/index': '就诊入口',
  'pages/visit/index': '预约详情',
  'pages/booking/index': '选新时段',
  'pages/confirm/index': '确认改期'
};
for (const [file, label] of Object.entries(pages)) {
  const js = fs.readFileSync(path.join(root, file + '.js'), 'utf8');
  const wxml = fs.readFileSync(path.join(root, file + '.wxml'), 'utf8');
  ok(/require\('\.\.\/\.\.\/utils\/text-scale'\)/.test(js), label + ' loads the font scale');
  ok(/textScale\.apply\(this\)/.test(js), label + ' reads the size when it is shown');
  ok(/<view class="page patient-flow \{\{textScale\}\}">/.test(wxml), label + ' binds the tier on the page root');
}

// --- the committed tiers really grow, and keep the default hierarchy ------
const css = fs.readFileSync(path.join(root, 'app.wxss'), 'utf8');
function tierSizes(tier) {
  const sizes = {};
  const prefix = '.patient-flow.' + tier;
  const pattern = new RegExp('\\.patient-flow\\.' + tier + '([^{}]*)\\{([^}]*)\\}', 'g');
  let match;
  while ((match = pattern.exec(css))) {
    const font = /font-size:(\d+)rpx/.exec(match[2]);
    if (!font) continue;
    const rest = match[1].split(prefix).join('');
    for (const selector of rest.split(',')) sizes[selector.trim()] = Number(font[1]);
  }
  return sizes;
}
const base = {body: 31, title: 47, section: 35, helper: 27, time: 37, button: 31, check: 31, id: 28};
const largeMap = tierSizes('text-scale-large');
const xlargeMap = tierSizes('text-scale-xlarge');
const keys = {body: '', title: '.title', section: '.section-title', helper: '.muted',
  time: '.time', button: 'button', check: '.check', id: '.checkout-id'};
for (const key of Object.keys(base)) {
  const large = largeMap[keys[key]];
  const xlarge = xlargeMap[keys[key]];
  ok(large > base[key], 'the large tier raises ' + key + ': ' + large);
  ok(xlarge > large, 'the extra-large tier raises ' + key + ' again: ' + xlarge);
}
ok(xlargeMap['.title'] > xlargeMap['.section-title']
  && xlargeMap['.section-title'] > xlargeMap['']
  && xlargeMap[''] > xlargeMap['.muted'],
  'the title / section / body / helper hierarchy survives the largest tier');
ok(xlargeMap['.title'] === 76 && xlargeMap['.time'] === 60
  && xlargeMap['button'] === 50 && xlargeMap['.check'] === 50,
  'the largest tier uses the sizes that were measured in the tool');

// The scale block must not introduce clipping or a fixed height for text.
const block = css.slice(css.indexOf('18555: the appointment screens'));
ok(!/-webkit-line-clamp|text-overflow:ellipsis|overflow:hidden/.test(block),
  'the scale block adds no clipping');

// Long text is allowed to wrap instead of widening the page.
ok(/\.page\{[^}]*overflow-wrap:anywhere/.test(css), 'the page keeps its character-level wrapping');
ok(/\.patient-flow \.visit-source,\.patient-flow \.checkout-id\{[^}]*word-break:break-all/.test(css),
  'long appointment numbers still break instead of overflowing');
ok(/button\{[^}]*white-space:normal/.test(css), 'button labels wrap at large sizes');

module.exports = {passed: checks, total: checks, layer: 'Node JS font tier mapping and committed WXSS'};
if (require.main === module) console.log(JSON.stringify(module.exports));
