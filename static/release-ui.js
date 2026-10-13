(function () {
  "use strict";
  document.querySelectorAll("form").forEach(function (form) {
    var fields=[];
    form.querySelectorAll("input:not([type=hidden]),select,textarea").forEach(function (control) {
      var parent=control.closest(".field") || control.parentElement;
      var errors=control.getAttribute("aria-invalid")==="true";
      var list=parent && parent.querySelector(".errorlist");
      if (list) {
        errors=true; control.setAttribute("aria-invalid","true");
        if (!list.id) list.id=(control.id || "field")+"_rc_errors";
        var desc=(control.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
        if (desc.indexOf(list.id)<0) desc.push(list.id);
        control.setAttribute("aria-describedby",desc.join(" "));
      }
      if (errors && control.id && fields.indexOf(control)<0) fields.push(control);
    });
    if (!fields.length) return;
    var box=document.createElement("section");box.className="rc-error-summary";
    box.setAttribute("role","alert");box.setAttribute("tabindex","-1");
    var heading=document.createElement("h2");heading.textContent="请检查以下输入，本次尚未保存";box.appendChild(heading);
    var ul=document.createElement("ul");
    fields.forEach(function(control){
      var li=document.createElement("li"),a=document.createElement("a");
      a.href="#"+control.id;
      a.textContent=(control.labels && control.labels[0] ? control.labels[0].textContent : "检查输入").trim();
      a.addEventListener("click",function(e){e.preventDefault();control.focus();control.scrollIntoView({block:"center"});});
      li.appendChild(a);ul.appendChild(li);
    });
    box.appendChild(ul);form.insertBefore(box,form.firstChild);
  });
})();
