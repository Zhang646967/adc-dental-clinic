/* Beijing wall-clock choices. No browser timezone inference, no automatic submit. */
(function (root) {
  'use strict';
  const MINUTE = 60000, DAY = 86400000;
  function parseWall(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value || '');
    if (!m) return NaN;
    const parts = m.slice(1).map(Number);
    const n = Date.UTC(parts[0], parts[1]-1, parts[2], parts[3], parts[4]);
    const d = new Date(n);
    return d.getUTCFullYear() === parts[0] && d.getUTCMonth()+1 === parts[1] &&
      d.getUTCDate() === parts[2] && d.getUTCHours() === parts[3] && d.getUTCMinutes() === parts[4] ? n : NaN;
  }
  function wall(n) { return new Date(n).toISOString().slice(0,16); }
  function dayStart(n) { return Math.floor(n / DAY) * DAY; }
  function dates(low, high) {
    if (!Number.isFinite(low) || !Number.isFinite(high) || low > high) return [];
    const result=[];
    for (let n=dayStart(low); n<=dayStart(high); n+=DAY) result.push(wall(n).slice(0,10));
    return result;
  }
  function times(date, low, high, step, exact) {
    const base=parseWall(date+'T00:00');
    if (!Number.isFinite(base) || !Number.isFinite(low) || !Number.isFinite(high) || low>high) return [];
    const floor=Math.max(base, low), ceiling=Math.min(base+DAY-MINUTE, high);
    const values=[];
    for (let n=Math.ceil(floor/(step*MINUTE))*(step*MINUTE); n<=ceiling; n+=step*MINUTE) values.push(n);
    // Re-rendered valid minute precision is preserved, never rounded into another preference.
    const old=parseWall(exact);
    if (Number.isFinite(old) && old>=floor && old<=ceiling && !values.includes(old)) values.push(old);
    return values.sort((a,b)=>a-b).map(n=>wall(n).slice(11));
  }
  function allowed(start, end, low, high, duration) {
    return Number.isFinite(start) && Number.isFinite(end) && start>=low && end<=high && end-start>=duration*MINUTE;
  }
  const api = {parseWall, wall, dates, times, allowed};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  root.ADCWaitWindow=api;
  if (typeof document === 'undefined') return;
  function init() {
    const form=document.querySelector('form[data-wait-window]');
    const meta=document.getElementById('wait-window-limits');
    if (!form || !meta) return;
    let limits;
    try {limits=JSON.parse(meta.textContent);} catch (_) {return;}
    const rawStart=form.querySelector('[name="earliest"]'), rawEnd=form.querySelector('[name="latest"]');
    const feedback=form.querySelector('[data-window-feedback]'), submit=form.querySelector('button[type="submit"]');
    const high=parseWall(limits.max_end), low0=parseWall(limits.min_start);
    const epoch=Date.parse(limits.server_now), loaded=performance.now();
    if (!rawStart || !rawEnd || !feedback || !submit || !Number.isFinite(high) || !Number.isFinite(low0) || !Number.isFinite(epoch)) return;
    const duration=limits.duration_minutes || 30, step=limits.choice_step_minutes || 15;
    const originals=[rawStart.value,rawEnd.value];
    function controls(raw, description) {
      const oldId=raw.id;
      const wrap=document.createElement('div');wrap.className='wait-controls';
      const date=document.createElement('select');date.id=oldId;date.required=true;
      const time=document.createElement('select');time.id=oldId+'_time';time.required=true;
      date.setAttribute('aria-label',description+'日期（北京时间）');
      time.setAttribute('aria-label',description+'时刻（北京时间）');
      for (const el of [date,time]) {el.setAttribute('aria-describedby','window-explanation');}
      raw.id=oldId+'_value';raw.type='hidden';raw.required=false;
      wrap.append(date,time);raw.after(wrap);
      return {raw,date,time};
    }
    const a=controls(rawStart,'最早可开始'), b=controls(rawEnd,'最晚必须结束');
    function options(el, values, label, current) {
      const selected=current === undefined ? el.value : current;
      el.replaceChildren();
      const p=document.createElement('option');p.value='';p.textContent=label;el.append(p);
      values.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.append(o);});
      el.value=values.includes(selected)?selected:'';
      el.disabled=values.length === 0;
    }
    function lowNow() {
      // UTC epoch +08:00 is used only as a wall-clock coordinate; no local timezone conversion.
      const epochNow=epoch+Math.max(0,performance.now()-loaded);
      return Math.max(low0,(Math.floor((epochNow+8*3600000)/MINUTE)+1)*MINUTE);
    }
    function value(c) {return c.date.value && c.time.value ? c.date.value+'T'+c.time.value : '';}
    function sync() {
      const oldEnd=rawEnd.value, oldStart=rawStart.value;
      const low=lowNow();
      options(a.date, dates(low,high-duration*MINUTE),'选择最早日期');
      options(a.time,times(a.date.value,low,high-duration*MINUTE,step,originals[0]),'选择开始时刻');
      rawStart.value=value(a);
      const start=parseWall(rawStart.value);
      options(b.date,Number.isFinite(start)?dates(start+duration*MINUTE,high):[],'先选择最早时间，再选结束日期');
      options(b.time,Number.isFinite(start)?times(b.date.value,start+duration*MINUTE,high,step,originals[1]):[],'选择结束时刻');
      rawEnd.value=value(b);
      const okay=allowed(start,parseWall(rawEnd.value),low,high,duration);
      submit.disabled=!okay;
      if ((oldEnd && !rawEnd.value) || (oldStart && !rawStart.value)) {
        feedback.textContent='原时间已经不符合当前范围，已清空失效选项。请重新选择；未替你自动修改时间。';
      } else if (!Number.isFinite(start)) {
        feedback.textContent='请先选择最早日期和时刻。所有选择均按北京时间；过去时间不会列出。';
      } else if (!okay) {
        feedback.textContent='最晚结束必须在 '+wall(start+duration*MINUTE).replace('T',' ')+' 至 '+limits.max_end.replace('T',' ')+' 之间（北京时间）。';
      } else {
        feedback.textContent='你可以接受 '+rawStart.value.replace('T',' ')+' 至 '+rawEnd.value.replace('T',' ')+' 范围内的预约。请核对后提交，登记不等于已预约。';
      }
      return okay;
    }
    options(a.date,dates(lowNow(),high-duration*MINUTE),'选择最早日期',originals[0].slice(0,10));
    options(a.time,times(a.date.value,lowNow(),high-duration*MINUTE,step,originals[0]),'选择开始时刻',originals[0].slice(11));
    const initialStart=parseWall(value(a));
    options(b.date,Number.isFinite(initialStart)?dates(initialStart+duration*MINUTE,high):[],'先选择最早时间，再选结束日期',originals[1].slice(0,10));
    options(b.time,Number.isFinite(initialStart)?times(b.date.value,initialStart+duration*MINUTE,high,step,originals[1]):[],'选择结束时刻',originals[1].slice(11));
    for (const c of [a,b]) {c.date.addEventListener('change',sync);c.time.addEventListener('change',sync);}
    form.addEventListener('submit',e=>{if (!sync()) {e.preventDefault();feedback.focus();}});
    feedback.tabIndex=-1;
    window.setInterval(()=>{if (!document.hidden) sync();},30000);
    window.addEventListener('pageshow',sync);
    sync();form.dataset.windowEnhanced='true';
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',init); else init();
})(typeof globalThis !== 'undefined' ? globalThis : this);
