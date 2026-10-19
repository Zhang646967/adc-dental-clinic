from django import forms
from registry.models import Dentist
from scheduling.resource_models import BookingService
from reception.models import REASONS
from reception.services import contact_owners

DT=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'})

class CaseForm(forms.Form):
    caller_name=forms.CharField(label='来电者姓名',max_length=80)
    relationship=forms.CharField(label='与患者关系',max_length=80,help_text='例如本人、父母、子女；不授予病历访问权限。')
    contact=forms.CharField(label='待核实联络方式',max_length=120)
    patient_hint=forms.CharField(label='待核实患者称呼',max_length=80,required=False)
    patient_no=forms.CharField(label='已建档患者业务编号',max_length=40,required=False,help_text='咨询可留空；正式预约前须完成建档。不能按电话自动合并。')
    service_id=forms.ModelChoiceField(label='预约服务',queryset=BookingService.objects.none(),required=False)
    dentist_id=forms.ModelChoiceField(label='医师偏好',queryset=Dentist.objects.none(),required=False)
    preferred_day=forms.DateField(label='日期偏好',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    owner=forms.ModelChoiceField(label='联系负责人',queryset=contact_owners(-1))
    due_at=forms.DateTimeField(label='下次联系期限',required=False,widget=DT)
    state=forms.ChoiceField(label='办理状态',choices=[('VERIFY','待核对'),('CONTACT','待联系'),('CONFIRM','待患者确认')])
    note=forms.CharField(label='本次沟通与核实结果',max_length=2000,widget=forms.Textarea(attrs={'rows':4}))
    def __init__(self,*args,clinic,existing=False,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['service_id'].queryset=BookingService.objects.filter(department__clinic_id=clinic,is_active=True).select_related('department')
        self.fields['dentist_id'].queryset=Dentist.objects.filter(is_active=True)
        self.fields['owner'].queryset=contact_owners(clinic)
        # Consultation contact corrections are versioned in communication history;
        # they never update the separate patient contact record.
    def business_fields(self):
        d=dict(self.cleaned_data)
        for k in ('service_id','dentist_id','owner'):
            if k in d:d[k]=d[k].pk if d[k] else None
        if d.get('preferred_day'):d['preferred_day']=d['preferred_day'].isoformat()
        return d

class NoteForm(forms.Form):
    note=forms.CharField(label='沟通或交接说明',max_length=2000,widget=forms.Textarea(attrs={'rows':3}))

class AssignForm(NoteForm):
    owner=forms.ModelChoiceField(label='重新分配负责人',queryset=contact_owners(-1))
    due_at=forms.DateTimeField(label='下次联系期限',widget=DT)
    def __init__(self,*args,clinic,**kwargs):
        super().__init__(*args,**kwargs);self.fields['owner'].queryset=contact_owners(clinic)

class CloseForm(NoteForm):
    reason_code=forms.ChoiceField(label='未成约原因',choices=REASONS)

class WaitForm(NoteForm):
    earliest=forms.DateTimeField(label='最早可开始',widget=DT)
    latest=forms.DateTimeField(label='最晚必须结束',widget=DT)
    due_at=forms.DateTimeField(label='候补联系期限',widget=DT)

class BookingForm(NoteForm):
    slot_id=forms.IntegerField(label='已选择出诊编号',min_value=1)
    start=forms.DateTimeField(label='预约开始',widget=DT)
    end=forms.DateTimeField(label='预约结束',widget=DT)
    consent=forms.BooleanField(label='已复述诊所、服务、医师和起止时间，患者明确同意')
