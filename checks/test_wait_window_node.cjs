/* Node contract assertions for the JS used by the real preference picker. */
const assert=require('node:assert/strict');
const w=require('../static/wait-window.js');
const t=s=>w.parseWall(s), low=t('2026-09-27T15:21'), high=t('2026-10-11T15:20');
let count=0;
function check(fn){fn();count++;}
check(()=>assert(Number.isNaN(t('not-a-date'))));
check(()=>assert(Number.isNaN(t('2026-02-30T10:00'))));
check(()=>assert(Number.isNaN(t('2026-09-27T24:00'))));
check(()=>assert.equal(w.wall(t('2026-09-27T15:21')),'2026-09-27T15:21'));
check(()=>assert.equal(w.dates(low,high).length,15));
check(()=>assert.deepEqual(w.dates(high,low),[]));
check(()=>assert.deepEqual(w.times('2026-09-26',low,high,15),[]));
check(()=>assert.equal(w.times('2026-09-27',low,high,15)[0],'15:30'));
check(()=>assert.equal(w.times('2026-10-11',low,high,15).at(-1),'15:15'));
check(()=>assert.deepEqual(w.times('',low,high,15),[]));
check(()=>assert(w.times('2026-09-28',low,high,15,'2026-09-28T02:13').includes('02:13')));
check(()=>assert(!w.times('2026-09-28',t('2026-09-28T15:00'),high,15,'2026-09-28T02:13').includes('02:13')));
check(()=>assert(w.allowed(t('2026-09-28T14:00'),t('2026-09-28T14:30'),low,high,30)));
check(()=>assert(!w.allowed(t('2026-09-28T14:00'),t('2026-09-28T14:29'),low,high,30)));
check(()=>assert(!w.allowed(t('2026-09-28T14:00'),t('2026-09-28T13:00'),low,high,30)));
check(()=>assert(!w.allowed(t('2026-09-26T14:00'),t('2026-09-28T14:00'),low,high,30)));
check(()=>assert(!w.allowed(t('2026-09-28T14:00'),t('2026-10-12T14:00'),low,high,30)));
check(()=>assert.deepEqual(w.times('2026-09-28',t('2026-09-28T00:15'),t('2026-09-28T00:30'),15),['00:15','00:30']));
console.log(JSON.stringify({layer:'Node JS contract assertions (no Django/DB)',passed:count,total:count}));
