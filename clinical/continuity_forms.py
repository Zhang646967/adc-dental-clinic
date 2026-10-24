from django import forms
from clinical.plan_forms import current_steps
from clinical.continuity_models import LabCase


def due_field():return forms.DateTimeField(label='下次内部跟进期限（北京时间）',widget=forms.DateTimeInput(attrs={'type':'datetime-local','step':'1'},format='%Y-%m-%dT%H:%M:%S'))


class RecallOpenForm(forms.Form):
    followup_due_at=due_field()
    note=forms.CharField(label='责任接续说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))
    def fields_data(self):
        d=dict(self.cleaned_data);d['followup_due_at']=d['followup_due_at'].isoformat();return d


class RecallContactForm(RecallOpenForm):
    outcome=forms.ChoiceField(label='实际联系结果',choices=[('REACHED','已联系，仍需继续安排'),('NO_ANSWER','未接通／未取得回复'),('DECLINED','本人暂不继续，转医师核对'),('COORDINATION','内部协调进展')])
    note=forms.CharField(label='联系或内部协调记录',max_length=500,widget=forms.Textarea(attrs={'rows':3}),help_text='只记录安排需要的情况。本人暂不继续时，不自动再次联系或取消原预约。')


class RecallResponsibilityForm(RecallOpenForm):
    note=forms.CharField(label='接续／恢复协调依据',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))


class RecallCompletionForm(forms.Form):
    evidence=forms.ChoiceField(label='已实际完成并关闭的复诊依据',choices=[])
    note=forms.CharField(label='核对说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))
    def __init__(self,*args,candidates,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['evidence'].choices=[(r['kind']+':'+str(r['id']),r['visit_no']+' · '+('确认检查' if r['kind']=='RECORD' else '指定步骤完成')+(' · 晚于原窗口'+str(r['late_days'])+'天' if r['late_days'] else '')) for r in candidates]
    def fields_data(self):
        d=dict(self.cleaned_data);kind,pk=d.pop('evidence').split(':');d.update(evidence_kind=kind,evidence_id=int(pk));return d


class RecallWithdrawalForm(forms.Form):
    note=forms.CharField(label='核对医师撤回及原预约后记录办理说明',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def fields_data(self):return dict(self.cleaned_data)


class LabRequestForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    step_version=forms.ModelChoiceField(label='本版本已明确需要加工件的步骤',queryset=None)
    work_kind=forms.ChoiceField(label='加工类别',choices=LabCase._meta.get_field('work_kind').choices)
    vendor_name=forms.CharField(label='手工登记的加工方',max_length=120)
    specification=forms.CharField(label='医师加工要求',max_length=3000,widget=forms.Textarea(attrs={'rows':5}),help_text='临床要求只在医师范围查阅；本系统不向外部供应方自动发送资料。')
    logistics_note=forms.CharField(label='前台送返说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))
    needed_on=forms.DateField(label='原计划需要日期',widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,visit,actor,**kwargs):
        super().__init__(*args,**kwargs);self.fields['step_version'].queryset=current_steps(visit,actor).filter(requires_lab=True)
        self.fields['step_version'].label_from_instance=lambda s:f'计划{s.version.plan_id} V{s.version.revision} · 第{s.sequence}步 · {s.treatment_type.name}'
    def fields_data(self):
        d=dict(self.cleaned_data);d.pop('patient_binding');d['step_version']=d['step_version'].pk;d['needed_on']=d['needed_on'].isoformat();return d


class LabLogisticsForm(forms.Form):
    note=forms.CharField(label='本次手工办理记录',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    followup_due_at=due_field()
    reference=forms.CharField(label='手工送返凭据／交接编号',max_length=500,required=False)
    occurred_at=forms.DateTimeField(label='实际送返时间（北京时间，留空按当前时间）',required=False,
        widget=forms.DateTimeInput(attrs={'type':'datetime-local','step':'1'},format='%Y-%m-%dT%H:%M:%S'))
    expected_on=forms.DateField(label='本次获悉的预计返回日期（未知留空）',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,action,**kwargs):
        super().__init__(*args,**kwargs)
        if action in ('DISPATCH','RECEIVE'):self.fields['reference'].required=True
        else:self.fields.pop('reference');self.fields.pop('occurred_at')
        if action!='DELAY':self.fields.pop('expected_on')
    def fields_data(self):
        d=dict(self.cleaned_data)
        for k in ('followup_due_at','occurred_at','expected_on'):
            if k in d:d[k]=d[k].isoformat() if d[k] else None
        return d


class LabReviewForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    target_step_version=forms.ModelChoiceField(label='本次明确核对适配的当前方案步骤',queryset=None)
    decision=forms.ChoiceField(label='本周期临床验收结果',choices=[('ACCEPTED','已核对该版本步骤，验收通过'),('REWORK','未通过，明确返工')])
    findings=forms.CharField(label='医师验收与适配结论',max_length=3000,widget=forms.Textarea(attrs={'rows':5}))
    coordination_note=forms.CharField(label='前台返工／安排说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}),help_text='返工时必须明确前台需要协调的事项，临床细节写在医师结论中。')
    assessed_at=forms.DateTimeField(label='实际验收时间（北京时间，留空按当前时间）',required=False,
        widget=forms.DateTimeInput(attrs={'type':'datetime-local','step':'1'},format='%Y-%m-%dT%H:%M:%S'))
    def __init__(self,*args,visit,case,actor,**kwargs):
        super().__init__(*args,**kwargs);old=case.step_version
        self.fields['target_step_version'].queryset=current_steps(visit,actor).filter(step_id=old.step_id,treatment_type_id=old.treatment_type_id,
            service_id=old.service_id,tooth=old.tooth,surface=old.surface,requires_lab=True)
        self.fields['target_step_version'].label_from_instance=lambda s:f'计划{s.version.plan_id} V{s.version.revision} · 第{s.sequence}步 · {s.description}'
    def fields_data(self):
        d=dict(self.cleaned_data);d.pop('patient_binding');d['target_step_version']=d['target_step_version'].pk
        d['assessed_at']=d['assessed_at'].isoformat() if d['assessed_at'] else None;return d


class LabWithdrawalForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    note=forms.CharField(label='撤回加工请求的明确依据',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def fields_data(self):return dict(note=self.cleaned_data['note'])
