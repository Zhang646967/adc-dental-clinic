"""Small, clinic-scoped catalogue forms; confirmation repeats validation."""
from django import forms
from django.db.models import Q
from equipment.models import EquipmentAsset
from registry.models import Dentist
from scheduling.resource_models import (Department, DepartmentHours, TreatmentRoom, BookingService,
    ResourceBinding, ResourceBlock, ServicePresentation, ResourcePolicy)

DATE_TIME = forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type':'datetime-local'})

class DepartmentForm(forms.ModelForm):
    class Meta:
        model=Department;fields=['code','name','is_active'];labels={'code':'科室代码','name':'科室名称','is_active':'可用'}

class HoursForm(forms.ModelForm):
    class Meta:
        model=DepartmentHours;fields=['department','weekday','opens_at','closes_at']
        labels={'department':'科室','weekday':'星期','opens_at':'开放时间','closes_at':'关闭时间'}
        widgets={'opens_at':forms.TimeInput(format='%H:%M',attrs={'type':'time'}),'closes_at':forms.TimeInput(format='%H:%M',attrs={'type':'time'})}
    def clean(self):
        d=super().clean()
        if all(k in d for k in ('department','weekday','opens_at','closes_at')):
            qs=DepartmentHours.objects.filter(department=d['department'],weekday=d['weekday'],opens_at__lt=d['closes_at'],closes_at__gt=d['opens_at'])
            if self.instance.pk:qs=qs.exclude(pk=self.instance.pk)
            if qs.exists():raise forms.ValidationError('该科室开放区间重叠，请修改原区间。')
        return d

class RoomForm(forms.ModelForm):
    class Meta:
        model=TreatmentRoom;fields=['department','code','name','is_active'];labels={'department':'所属科室','code':'诊室代码','name':'诊室名称','is_active':'可用'}

class ServiceForm(forms.ModelForm):
    imaging=forms.IntegerField(label='必要影像设备数量',min_value=0,max_value=8,initial=0)
    sterilizer=forms.IntegerField(label='必要消毒设备数量',min_value=0,max_value=8,initial=0)
    other=forms.IntegerField(label='必要其他设备数量',min_value=0,max_value=8,initial=0)
    class Meta:
        model=BookingService;fields=['department','code','name','duration_minutes','dentists','is_active']
        labels={'department':'服务科室','code':'服务代码','name':'预约服务名称','duration_minutes':'总时长（分钟，含准备及周转）','dentists':'可接收医师','is_active':'可用'}
    def clean_duration_minutes(self):
        v=self.cleaned_data['duration_minutes']
        if v not in range(15,241,15):raise forms.ValidationError('请选择15至240分钟，按15分钟递增。')
        return v
    def clean_dentists(self):
        q=self.cleaned_data['dentists']
        if not q.exists():raise forms.ValidationError('至少配置一名可接收医师。')
        return q

class ServicePresentationForm(forms.ModelForm):
    class Meta:
        model = ServicePresentation
        fields = ['service', 'category', 'title', 'summary', 'suitable_for', 'visit_content',
                  'limitations', 'preparation', 'fee_mode', 'fee_amount', 'fee_note', 'is_published']
        labels = {'service': '对应的预约服务', 'category': '患者服务分类', 'title': '患者看到的名称',
            'summary': '为什么选择这项服务', 'suitable_for': '适合咨询的需求',
            'visit_content': '本次预约具体包含什么', 'limitations': '不包含的内容与服务边界',
            'preparation': '到诊前准备', 'fee_mode': '费用说明方式', 'fee_amount': '人民币金额',
            'fee_note': '费用包含范围与另计项目', 'is_published': '内容及费用已核对，向患者公开展示'}
        help_texts = {'fee_amount': '评估后确认时留空。明确免费才填0；起价需说明费用变动条件。',
            'is_published': '未勾选时保存为草稿；公开后仍按门店、服务、医师启用状态决定是否展示。',
            'visit_content': '写本次预约能提供的服务，不将整套治疗承诺为一次完成。'}
        widgets = {key: forms.Textarea(attrs={'rows': 3}) for key in
            ('suitable_for', 'visit_content', 'limitations', 'preparation', 'fee_note')}

    def clean(self):
        data = super().clean()
        from scheduling.service_content import CONTENT_LIMITS
        for key in CONTENT_LIMITS:
            if isinstance(data.get(key), str):
                data[key] = data[key].strip()
        service = data.get('service')
        if data.get('is_published') and service:
            from scheduling.service_content import operational_blockers
            issues=operational_blockers(service_active=service.is_active,
                department_active=service.department.is_active,clinic_active=service.department.clinic.is_active,
                has_dentists=service.dentists.filter(is_active=True).exists(),
                policy_enabled=ResourcePolicy.objects.filter(clinic_id=service.department.clinic_id,state='ENABLED').exists())
            if issues:self.add_error('is_published','；'.join(issues))
        return data


class BindingForm(forms.ModelForm):
    class Meta:
        model=ResourceBinding;fields=['asset','room','shared','is_active']
        labels={'asset':'现有设备台账','room':'固定所属诊室','shared':'本店共享设备','is_active':'参与排程'}
    def clean(self):
        d=super().clean()
        if d.get('asset') and d['asset'].category=='CHAIR' and (d.get('shared') or not d.get('room')):
            raise forms.ValidationError('牙椅必须固定到一个诊室；同房不同椅位可以并行。')
        return d

class BlockForm(forms.ModelForm):
    class Meta:
        model=ResourceBlock;fields=['department','room','asset','starts_at','ends_at','reason']
        labels={'department':'停用科室（目标三选一）','room':'停用诊室','asset':'停用设备','starts_at':'开始','ends_at':'结束','reason':'停用依据'}
        widgets={'starts_at':DATE_TIME,'ends_at':DATE_TIME}
    def clean(self):
        d=super().clean()
        if sum(bool(d.get(k)) for k in ('department','room','asset'))!=1:raise forms.ValidationError('请选择且仅选择一个停用目标。')
        return d

class ConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='已核对，确认办理')

FORMS={'department':DepartmentForm,'hours':HoursForm,'room':RoomForm,'service':ServiceForm,
       'service_profile':ServicePresentationForm,'binding':BindingForm,'block':BlockForm}
MODELS={k:f._meta.model for k,f in FORMS.items()}

def config_form(clinic,kind,data=None,instance=None):
    form=FORMS[kind](data,instance=instance)
    for name,qs in [('department',Department.objects.filter(clinic_id=clinic)),('room',TreatmentRoom.objects.filter(department__clinic_id=clinic)),
        ('service',BookingService.objects.filter(department__clinic_id=clinic).select_related('department__clinic')),
        ('asset',EquipmentAsset.objects.filter(clinic_id=clinic)),('dentists',Dentist.objects.filter(is_active=True))]:
        if name in form.fields:form.fields[name].queryset=qs
    if instance and kind=='service' and not data:
        values=dict(instance.requirements.values_list('category','quantity'))
        for k,c in [('imaging','IMAGING'),('sterilizer','STERILIZER'),('other','OTHER')]:form.initial[k]=values.get(c,0)
    return form

def scoped_model(clinic,kind):
    qs=MODELS[kind].objects.all()
    lookup={'department':'clinic_id','hours':'department__clinic_id','room':'department__clinic_id','service':'department__clinic_id',
            'service_profile':'service__department__clinic_id','binding':'asset__clinic_id','block':'clinic_id'}[kind]
    return qs.filter(**{lookup:clinic})
