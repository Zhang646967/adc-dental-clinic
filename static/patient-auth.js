/* Website polling observes a ticket; only the explicit POST consumes approval. */
(() => {
  async function json(url, form, data) {
    const response = await fetch(url, {method: data ? 'POST' : 'GET', credentials:'same-origin', cache:'no-store',
      headers: data ? {'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value,'Content-Type':'application/x-www-form-urlencoded'} : {},
      body: data ? new URLSearchParams(data) : undefined});
    const body = await response.json();
    if (!response.ok || !body.ok) throw Error(body.message || '暂时无法办理，请刷新重试。');
    return body.data;
  }
  document.querySelectorAll('#sms-auth-form').forEach(form => {
    const code = form.querySelector('[name=code]'), verify = form.querySelector('[name=action][value=confirm]');
    if (code && verify) code.addEventListener('keydown', e => {if (e.key === 'Enter') {e.preventDefault();form.requestSubmit(verify);}});
    const box = form.querySelector('.sms-captcha');
    if (box) box.querySelector('[data-captcha-refresh]').addEventListener('click', async () => {
      const status=box.querySelector('[data-captcha-status]'), button=box.querySelector('button');button.disabled=true;
      try {const result=await json(box.dataset.url,form,{}),image=box.querySelector('img');image.src=result.image;image.hidden=false;status.textContent='请识别图片，再获取短信验证码。';}
      catch(e){status.textContent=e.message;}finally{button.disabled=false;}
    });
  });
  const root=document.querySelector('#wechat-qr-login');
  if(!root)return;
  const form=root.querySelector('form'),image=root.querySelector('img'),status=root.querySelector('[role=status]'),refresh=root.querySelector('button');
  let ticket='',timer=null,generation=0;
  const labels={PENDING:'请用微信扫描并在手机上确认，登录码三分钟内有效。',REJECTED:'本次登录已拒绝或授权已变化，请刷新重试。',EXPIRED:'登录码已过期，请刷新。',CONSUMED:'登录已办理，请刷新页面查看。'};
  async function poll(current) {
    try {
      const state=await json(root.dataset.status+'?ticket='+encodeURIComponent(ticket),form);
      if(current!==generation)return;
      if(state.state==='APPROVED') {
        status.textContent='手机已确认，正在登录…';
        const target=await json(root.dataset.complete,form,{ticket});
        if(current===generation)window.location.assign(target.redirect);
      } else {status.textContent=labels[state.state]||'请刷新登录码。';if(state.state==='PENDING')timer=setTimeout(()=>poll(current),2000);else image.hidden=true;}
    }catch(e){if(current===generation){status.textContent=e.message;image.hidden=true;}}
  }
  async function start() {
    const current=++generation;clearTimeout(timer);refresh.disabled=true;image.hidden=true;status.textContent='正在准备登录码…';
    try {const data=await json(root.dataset.start,form,{});if(current!==generation)return;ticket=data.ticket;image.src=data.image;image.hidden=false;status.textContent=labels.PENDING;timer=setTimeout(()=>poll(current),2000);}
    catch(e){if(current===generation)status.textContent=e.message;}
    finally{if(current===generation)refresh.disabled=false;}
  }
  refresh.addEventListener('click',start);window.addEventListener('pagehide',()=>{generation++;clearTimeout(timer);});start();
})();
