from django.contrib.auth.decorators import login_required
from django.shortcuts import render,get_object_or_404
from django.http import Http404
from django.urls import reverse
from django.views.decorators.http import require_GET
from guidance.catalog import GUIDES,VERSION

def data_for(g):
    return {'key':g.key,'title':g.title,'goal':g.goal,'version':VERSION,'steps':[
        {'title':s.title,'instruction':s.instruction,'url':reverse(s.route)+'?guide='+g.key+'&step='+str(i+1)} for i,s in enumerate(g.steps)]}

@login_required
@require_GET
def index(request):
    role=request.workspace.role
    return render(request,'guidance/index.html',{'guides':[data_for(g) for g in GUIDES.values() if role in g.roles], 'base_template':'portal/base.html' if role=='PATIENT' else 'base.html'})

@login_required
@require_GET
def task(request,key):
    g=GUIDES.get(key)
    if not g or request.workspace.role not in g.roles:raise Http404('当前身份没有这份任务指南。')
    return render(request,'guidance/task.html',{'task':data_for(g),'base_template':'portal/base.html' if request.workspace.role=='PATIENT' else 'base.html'})
