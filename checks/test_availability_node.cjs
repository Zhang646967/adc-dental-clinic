'use strict';
const assert = require('node:assert/strict');
const {nextMinute} = require('../static/availability.js');
const cases = [
 ['2026-10-08T09:00','2026-10-08T09:01'],
 ['2026-10-08T09:59','2026-10-08T10:00'],
 ['2026-10-08T23:59','2026-10-09T00:00'],
 ['2026-10-31T23:59','2026-11-01T00:00'],
 ['2026-12-31T23:59','2027-01-01T00:00'],
 ['2028-02-28T23:59','2028-02-29T00:00'],
 ['2026-02-28T23:59','2026-03-01T00:00'],
 ['2026-02-29T09:00',''],['2026-10-08T25:00',''],['2026-10-08T09:61',''],
 ['2026-10-08',''],['2026-10-08T09:00:00',''],['bad',''],['',''],['9999-12-31T23:59',''],['0000-01-01T00:00',''],
];
for (const [input, expected] of cases) assert.equal(nextMinute(input),expected);
console.log(JSON.stringify({scope:'Pure wall-time arithmetic; not real form POST',assertions:cases.length,passed:cases.length}));
