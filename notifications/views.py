from django.conf import settings
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from adc_core.rules import RuleError
from notifications.services import list_inbox, mark_read, delivery_status, retry_delivery


def failure(request,text,status=503):
    return render(request,'notifications/recovery.html',{'problem':text},status=status)

@login_required
@never_cache
@require_GET
def inbox(request):
    try: result=list_inbox(actor=request.user,mode=request.GET.get('mode','unread'),page=request.GET.get('page','1'))
    except RuleError as exc: return failure(request,str(exc),400)
    except DatabaseError: return failure(request,'消息暂时无法读取，不代表任务或预约办理失败。请到协调任务列表核对。')
    return render(request,'notifications/inbox.html',{'result':result,'read_only':settings.ADC_READ_ONLY})

@login_required
@never_cache
@require_POST
def acknowledge(request,message_id):
    try: mark_read(actor=request.user,message_id=message_id)
    except (RuleError,ValueError) as exc: return failure(request,str(exc),400)
    except DatabaseError: return failure(request,'已读标记结果暂时不能核对，请刷新消息列表。任务未因此改变。')
    messages.success(request,'已标记为已读；这不表示受理任务或患者已经同意。')
    return redirect('notification_inbox')

@login_required
@never_cache
@require_GET
def status(request):
    try: result=delivery_status(actor=request.user,page=request.GET.get('page','1'))
    except DatabaseError: return failure(request,'本次无法查询通知派发状态，请稍后核对；不自动重发。')
    return render(request,'notifications/status.html',{'result':result,'read_only':settings.ADC_READ_ONLY})

class RetryForm(forms.Form):
    expected_round=forms.IntegerField(min_value=0,max_value=2**31-1)
    confirmed=forms.BooleanField(required=True)

@login_required
@never_cache
@require_POST
def retry(request,event_id):
    form=RetryForm(request.POST)
    if not form.is_valid(): return failure(request,'请重新核对重试轮次并明确确认。',400)
    try: retry_delivery(actor=request.user,event_id=event_id,**form.cleaned_data)
    except (RuleError,ValueError) as exc: return failure(request,str(exc),409)
    except DatabaseError: return failure(request,'本次重试请求结果未知，请先查询派发状态，不重复办理原任务。')
    messages.success(request,'仅通知已重新排队；未重新执行任务或任何预约操作。')
    return redirect('notification_status')
