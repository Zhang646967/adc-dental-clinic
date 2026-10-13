"""GET-only coordination views. All writes stay at their original command boundary."""
from urllib.parse import urlencode
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from scheduling.availability_rules import AvailabilityError
from scheduling.front_coordination_selectors import (require_front_coordination,
    list_coordination_slots, read_coordination_slot)


class CoordinationQueryForm(forms.Form):
    mode = forms.ChoiceField(label='查询范围', choices=[('upcoming','未来及进行中的出诊'),('all','全部（含历史）')], required=False)
    slot_id = forms.IntegerField(label='出诊编号（可选，精确查找）', min_value=1, max_value=2**63-1, required=False)


def link(name, pk, origin):
    return reverse(name, args=[pk]) + '?' + urlencode({'coord_slot': origin})


@login_required
@never_cache
@require_GET
def listing(request):
    require_front_coordination(request.user)
    form = CoordinationQueryForm(request.GET if request.GET else {'mode':'upcoming'})
    context = {'form': form, 'rows': [], 'total': 0, 'read_only': settings.ADC_READ_ONLY}
    if form.is_valid():
        mode = form.cleaned_data['mode'] or 'upcoming'; sid = form.cleaned_data['slot_id']
        try:
            context.update(list_coordination_slots(actor=request.user, mode=mode, slot_id=sid, page=request.GET.get('page')))
        except DatabaseError:
            return render(request,'scheduling/front_coordination_error.html',status=503)
        query = {'mode': mode}
        if sid is not None: query['slot_id'] = sid
        base = reverse('front_coordination_list')
        n, pages = context['number'], context['pages']
        context['previous_url'] = base + '?' + urlencode(query | {'page': n-1}) if n>1 else ''
        context['next_url'] = base + '?' + urlencode(query | {'page': n+1}) if n<pages else ''
    return render(request,'scheduling/front_coordination_list.html',context)


@login_required
@never_cache
@require_GET
def detail(request, pk):
    require_front_coordination(request.user)
    try:
        context = read_coordination_slot(actor=request.user, slot_id=pk,
            visit_page=request.GET.get('visit_page'), offer_page=request.GET.get('offer_page'))
    except (DatabaseError, AvailabilityError):
        return render(request,'scheduling/front_coordination_error.html',{'slot_id':pk},status=503)
    context['read_only'] = settings.ADC_READ_ONLY
    if not context['unsafe']:
        for row in context['visits']:
            row['detail_url'] = link('visit_detail', row['id'], pk)
            row['reschedule_url'] = link('visit_reschedule', row['id'], pk) if row['reschedule'] and not settings.ADC_READ_ONLY else ''
        for row in context['offers']:
            row['detail_url'] = link('wait_offer', row['id'], pk) if row['offer'] else ''
            row['appointment_url'] = link('visit_detail', row['visit_id'], pk) if row['appointment'] else ''
        base = reverse('front_coordination_detail', args=[pk])
        vn, vp = context['visit_number'], context['visit_pages']
        on, op = context['offer_number'], context['offer_pages']
        for key, value in (('visit_previous',vn-1 if vn>1 else None),('visit_next',vn+1 if vn<vp else None)):
            context[key] = base+'?'+urlencode({'visit_page':value,'offer_page':on})+'#coord-visits' if value else ''
        for key, value in (('offer_previous',on-1 if on>1 else None),('offer_next',on+1 if on<op else None)):
            context[key] = base+'?'+urlencode({'visit_page':vn,'offer_page':value})+'#coord-offers' if value else ''
    return render(request,'scheduling/front_coordination_detail.html',context)
