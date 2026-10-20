from datetime import date
from urllib.parse import urlencode
from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from scheduling.availability_services import require_availability_actor
from scheduling.resource_models import BookingService
from scheduling.calendar import calendar_context,doctor_choices

class CalendarForm(forms.Form):
    day=forms.DateField(label='日期',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    mode=forms.ChoiceField(label='查看方式',choices=[('day','日排班'),('week','周排班')])
    dentist=forms.ModelChoiceField(label='医师',queryset=None,required=False,empty_label='本店全部医师')
    service=forms.ModelChoiceField(label='核对预约服务（可选）',queryset=None,required=False,empty_label='先查看全部出诊')
    def __init__(self,*args,clinic,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['dentist'].queryset=doctor_choices(clinic)
        self.fields['service'].queryset=BookingService.objects.filter(department__clinic_id=clinic,is_active=True,department__is_active=True).select_related('department').order_by('name','pk')
    def clean_day(self):
        value=self.cleaned_data['day']
        if not date(2000,1,8)<=value<=date(2100,12,20):raise forms.ValidationError('请选择2000至2100年内日期。')
        return value

@login_required
@never_cache
@require_GET
def calendar(request):
    ctx=require_availability_actor(request.user)
    data={'day':timezone.localdate().isoformat(),'mode':'week'}|request.GET.dict()
    form=CalendarForm(data,clinic=ctx.clinic_id);context={'form':form,'days':[]}
    if form.is_valid():
        d=form.cleaned_data
        context.update(calendar_context(actor=request.user,day=d['day'],mode=d['mode'],dentist_id=d['dentist'].pk if d['dentist'] else None,
            service=d['service'],page=request.GET.get('page',1)))
        query=dict(day=d['day'].isoformat(),mode=d['mode'],dentist=d['dentist'].pk if d['dentist'] else '',service=d['service'].pk if d['service'] else '')
        link=lambda extra:reverse('schedule_calendar')+'?'+urlencode(query|extra)
        context.update(previous_url=link({'day':context['previous_day'].isoformat()}),next_url=link({'day':context['next_day'].isoformat()}),
            day_url=link({'mode':'day'}),week_url=link({'mode':'week'}),today_url=link({'day':timezone.localdate().isoformat()}))
        page=context['page']
        context['previous_page']=link({'page':page.previous_page_number()}) if page.has_previous() else ''
        context['next_page']=link({'page':page.next_page_number()}) if page.has_next() else ''
        for group in context['days']:
            for row in group['rows']:
                row['candidates_url']=reverse('resource_candidates')+'?'+urlencode({'day':group['day'].isoformat(),
                    'service':d['service'].pk if d['service'] else '', 'dentist':row['slot'].dentist_id})
    return render(request,'scheduling/calendar.html',context,status=200 if form.is_valid() else 400)
