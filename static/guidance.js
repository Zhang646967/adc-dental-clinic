(function () {
  'use strict';
  var panel=document.querySelector('[data-guide-selector]');
  if(panel && panel.dataset.guideSelector){
    try{var target=document.querySelector(panel.dataset.guideSelector);if(target)target.classList.add('guide-highlight');}catch(_){/* Missing targets never trigger a guessed action. */}
  }
  var dirty=false;
  document.querySelectorAll('form[method=post]').forEach(function(form){
    form.addEventListener('input',function(){dirty=true;});
    form.addEventListener('submit',function(){dirty=false;});
  });
  document.querySelectorAll('[data-switch]').forEach(function(link){link.addEventListener('click',function(event){
    if(dirty && !window.confirm('当前页面有未提交内容。切换不会保存这些内容，是否继续？'))event.preventDefault();
  });});
  // Preserve guide id + step across same-origin manual navigation. No patient or message storage.
  if(panel){
    var key=panel.dataset.guideKey, step=panel.dataset.guideStep;
    if(!key)return;
    document.querySelectorAll('main a[href]').forEach(function(link){
      if(link.closest('.guide-panel')||link.hasAttribute('data-switch'))return;
      try{var u=new URL(link.href,window.location.href);if(u.origin===window.location.origin && !u.pathname.startsWith('/workspace/')&&!u.pathname.startsWith('/guide/')){
        u.searchParams.set('guide',key);u.searchParams.set('step',step||'1');link.href=u.pathname+u.search+u.hash;
      }}catch(_){}
    });
  }
})();
