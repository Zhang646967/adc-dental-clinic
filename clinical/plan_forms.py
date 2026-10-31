from copy import deepcopy
from decimal import Decimal
from django import forms
from django.utils import timezone
from clinical.encounter_forms import RevisionForm
from clinical.plan_models import PlanStepVersion
from clinical.tooth_rules import PERMANENT,PRIMARY,SURFACES
from clinical.models import ProfessionalAuthorization
from registry.models import TreatmentType
from scheduling.models import BookingService,Visit


def services_for(actor,visit):
    now=timezone.now()
    scopes=ProfessionalAuthorization.objects.filter(user=actor,clinic_id=visit.clinic_id,state='APPROVED',can_record=True,valid_from__lte=now,valid_until__gt=now)
    from django.conf import settings
    if not settings.ADC_CLINICAL_SYNTHETIC:scopes=scopes.exclude(source_kind='SYNTHETIC')
    return BookingService.objects.filter(department__clinic_id=visit.clinic_id,department__is_active=True,is_active=True,pk__in=scopes.values('service_id')).select_related('department')


def current_steps(visit,actor):
    from clinical.plan_locks import readable_services
    return PlanStepVersion.objects.filter(version__plan__origin_encounter__visit__patient_id=visit.patient_id,
        version__plan__origin_encounter__visit__clinic_id=visit.clinic_id,version__next_version__isnull=True,service_id__in=readable_services(actor,visit.clinic_id)).select_related('treatment_type','version__plan','service','step')


class PlanStartForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    operation_id=forms.UUIDField(widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='已核对就诊人及检查依据，建立本次治疗计划草稿')


class PlanNotesForm(RevisionForm):
    summary=forms.CharField(label='治疗计划摘要',max_length=3000,widget=forms.Textarea(attrs={'rows':4}))
    discussion_note=forms.CharField(label='与患者讨论的说明',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    amendment_reason=forms.CharField(label='新版本依据',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))


class DisclosureForm(RevisionForm):
    sequence=forms.IntegerField(min_value=1,max_value=30,widget=forms.HiddenInput)
    step_key=forms.UUIDField(widget=forms.HiddenInput)
    prepared=forms.BooleanField(required=False,label='本步骤说明已准备，随确认方案提供给患者核对')
    def __init__(self,*args,**kwargs):
        from clinical.disclosures import FIELDS
        super().__init__(*args,**kwargs)
        # Keep the action checkbox after its actual clinical content.
        prepared=self.fields.pop('prepared')
        for key,label,limit in FIELDS:
            self.fields[key]=forms.CharField(label=label,max_length=limit,required=False,
                widget=forms.Textarea(attrs={'rows':3 if key in ('risks','alternatives','aftercare') else 2}))
        self.fields['prepared']=prepared
    def clean(self):
        values=super().clean()
        if not self.errors:
            from clinical.disclosures import content
            from adc_core.rules import RuleError
            try:content(values)
            except RuleError as exc:raise forms.ValidationError(str(exc)) from exc
        return values
    def fields_data(self):
        data=dict(self.cleaned_data);data['step_key']=str(data['step_key']);return data


class StepForm(RevisionForm):
    sequence=forms.IntegerField(required=False,min_value=1,max_value=30,widget=forms.HiddenInput)
    treatment_type=forms.ModelChoiceField(label='拟实施治疗目录',queryset=TreatmentType.objects.none())
    service=forms.ModelChoiceField(label='后续预约服务',queryset=BookingService.objects.none())
    description=forms.CharField(label='步骤说明',max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    goal=forms.CharField(label='本步骤目标',max_length=1000,widget=forms.Textarea(attrs={'rows':2}))
    tooth=forms.TypedChoiceField(label='牙位（全口／非特定牙位可不选）',coerce=int,empty_value=None,required=False,
        choices=[('','不指定牙位')]+[(n,str(n)) for n in PERMANENT+PRIMARY])
    surfaces=forms.MultipleChoiceField(label='牙面（整牙可不选）',choices=list(SURFACES.items()),required=False,widget=forms.CheckboxSelectMultiple)
    estimated_quantity=forms.DecimalField(label='预计数量',max_digits=12,decimal_places=3,min_value=Decimal('0.001'))
    estimated_unit_price=forms.DecimalField(label='预计单价（元，未确定请留空）',max_digits=12,decimal_places=2,min_value=Decimal('0'),required=False)
    estimate_note=forms.CharField(label='费用估算说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))
    alternative_group=forms.CharField(label='互斥选项组（无则留空）',max_length=32,required=False,help_text='同一组中的步骤代表可替代方案，不会相加为承诺总价。')
    charge_basis=forms.ChoiceField(label='实际计费时点',choices=[('PER_EXECUTION','按每次实际已提供项目计费'),('ON_COMPLETION','本步骤分次完成时计费')])
    requires_lab=forms.ChoiceField(label='本步骤的加工件依赖',choices=[('NO','已明确本步骤无需加工件'),('YES','需要加工件并由医师验收'),('UNKNOWN','尚待明确，暂不执行本步骤')],initial='NO')
    def __init__(self,*args,actor,visit,**kwargs):
        super().__init__(*args,**kwargs);self.fields['treatment_type'].queryset=TreatmentType.objects.filter(is_active=True)
        self.fields['service'].queryset=services_for(actor,visit)
    def fields_data(self):
        data=dict(self.cleaned_data);data['treatment_type']=data['treatment_type'].pk;data['service']=data['service'].pk
        data['surface']=''.join(data.pop('surfaces'))
        for k in ('estimated_quantity','estimated_unit_price'):data[k]=str(data[k]) if data[k] is not None else None
        data['requires_lab']={'NO':False,'YES':True,'UNKNOWN':None}[data['requires_lab']]
        return data


class PlanReasonForm(RevisionForm):
    reason=forms.CharField(label='办理依据',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='已核对本次就诊人与当前方案，确认办理')


class StepRemoveForm(RevisionForm):
    sequence=forms.IntegerField(min_value=1,max_value=30,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='确认仅从当前草稿移除此步骤，保留已经发布的历史')


class PlanRefreshForm(RevisionForm):
    confirmed=forms.BooleanField(label='已核对本次最新确认检查，将其作为当前计划草稿的依据')


class DecisionForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096,required=False)
    decision=forms.ChoiceField(label='本人对这个版本步骤的决定',choices=[('ACCEPTED','认可此步骤'),('DEFERRED','暂缓决定'),('DECLINED','不选择此步骤')])
    reference=forms.CharField(label='患者本人表态的依据／沟通记录编号',max_length=500,required=False)
    note=forms.CharField(label='决定说明或后续安排',max_length=1000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,manual=False,**kwargs):
        super().__init__(*args,**kwargs)
        if manual:self.fields['reference'].required=True;self.fields['patient_binding'].required=True
        else:self.fields.pop('reference');self.fields.pop('patient_binding')


class ExecutionForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    step_version=forms.ModelChoiceField(label='关联已讨论方案步骤（计划外可不选）',queryset=PlanStepVersion.objects.none(),required=False)
    treatment_type=forms.ModelChoiceField(label='实际已提供的项目',queryset=TreatmentType.objects.none())
    quantity=forms.DecimalField(label='实际数量',max_digits=12,decimal_places=3,min_value=Decimal('0.001'))
    tooth=deepcopy(StepForm.base_fields['tooth'])
    surfaces=deepcopy(StepForm.base_fields['surfaces'])
    progress=forms.ChoiceField(label='本步骤本次进展',choices=[('COMPLETE','本步骤实际完成'),('PARTIAL','仅完成当前阶段，仍待继续')])
    charge_mode=forms.ChoiceField(label='本次计费',choices=[('CHARGE','按目录及实际数量开单'),('NO_CHARGE','约定完成时计费，本次阶段不另计费')])
    observed_at=forms.DateTimeField(label='实际执行时间（北京时间，留空按当前时间）',required=False,
        widget=forms.DateTimeInput(attrs={'type':'datetime-local','step':'1'},format='%Y-%m-%dT%H:%M:%S'))
    reason=forms.CharField(label='计划外、阶段不计费或估算差异的依据',max_length=1000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,visit,actor,**kwargs):
        super().__init__(*args,**kwargs);self.fields['step_version'].queryset=current_steps(visit,actor)
        self.fields['step_version'].label_from_instance=lambda s:f'计划{s.version.plan_id} · V{s.version.revision} 第{s.sequence}步 · {s.treatment_type.name}'
        self.fields['treatment_type'].queryset=TreatmentType.objects.filter(is_active=True)
    def fields_data(self):
        data=dict(self.cleaned_data);data.pop('patient_binding')
        for key in ('step_version','treatment_type'):data[key]=data[key].pk if data[key] else None
        data['quantity']=str(data['quantity']);data['surface']=''.join(data.pop('surfaces'))
        if data['observed_at']:data['observed_at']=data['observed_at'].isoformat()
        return data


class InstructionForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    step_version=forms.ModelChoiceField(label='关联方案步骤（一般复诊可不选）',queryset=PlanStepVersion.objects.none(),required=False)
    service=forms.ModelChoiceField(label='后续预约服务',queryset=BookingService.objects.none())
    earliest_on=forms.DateField(label='建议最早日期',widget=forms.DateInput(attrs={'type':'date'}))
    latest_on=forms.DateField(label='建议最晚日期',widget=forms.DateInput(attrs={'type':'date'}))
    clinical_purpose=forms.CharField(label='临床后续目标',max_length=1000,widget=forms.Textarea(attrs={'rows':3}),help_text='仅进入医师和患者本人范围，不提供给前台。')
    booking_note=forms.CharField(label='前台安排说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}),help_text='只填写前台安排需要的内容；临床细节请写在上方。')
    completion_rule=forms.ChoiceField(label='此后续目标何时算实际完成',choices=[('EXAM_CONFIRMED','后续实际接诊已关闭，并有确认检查记录'),('STEP_COMPLETED','指定这个版本步骤实际完成，并关闭接诊')])
    def __init__(self,*args,actor,visit,**kwargs):
        super().__init__(*args,**kwargs);self.fields['step_version'].queryset=current_steps(visit,actor)
        self.fields['service'].queryset=services_for(actor,visit)
        self.fields['step_version'].label_from_instance=lambda s:f'计划{s.version.plan_id} · V{s.version.revision} 第{s.sequence}步'
    def fields_data(self):
        data=dict(self.cleaned_data);data.pop('patient_binding')
        for key in ('step_version','service'):data[key]=data[key].pk if data[key] else None
        for key in ('earliest_on','latest_on'):data[key]=data[key].isoformat()
        return data


class ConfirmPlanActionForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput,max_length=16384)
    confirmed=forms.BooleanField(label='已核对就诊人、具体版本与本次办理内容，确认提交')


class PlainReasonForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    reason=forms.CharField(label='明确办理依据',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':3}))


class LinkAppointmentForm(forms.Form):
    visit=forms.ModelChoiceField(label='已与患者确认的同服务预约',queryset=Visit.objects.none())
    def __init__(self,*args,instruction,**kwargs):
        super().__init__(*args,**kwargs);source=instruction.source_record.encounter.visit
        self.fields['visit'].queryset=Visit.objects.filter(patient_id=source.patient_id,clinic_id=source.clinic_id,status='SCHEDULED',scheduled_start__gt=timezone.now(),
            resource_plans__is_current=True,resource_plans__service_id=instruction.service_id).order_by('scheduled_start')
        self.fields['visit'].label_from_instance=lambda v:f'{v.visit_no} · {timezone.localtime(v.scheduled_start):%Y-%m-%d %H:%M} · {v.get_status_display()}'
