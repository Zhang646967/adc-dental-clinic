document.querySelectorAll('form[data-clinical-finding]').forEach(form=>{
  const select=form.querySelector('select[name=tooth]'),output=form.querySelector('[data-selected-tooth]');
  if(!select)return;
  const buttons=[...form.querySelectorAll('[data-clinical-tooth]')];
  const mark=()=>{
    buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.clinicalTooth===select.value)));
    if(output)output.textContent=select.value?'已选择牙位 '+select.value:'未选择牙位';
  };
  buttons.forEach(button=>button.addEventListener('click',()=>{
    select.value=button.dataset.clinicalTooth;select.dispatchEvent(new Event('change',{bubbles:true}));select.focus();
  }));
  select.addEventListener('change',mark);mark();
});
