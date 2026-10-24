from django import forms
from django.db.models import Q
from django.utils import timezone
from accounts.models import UserAccount
from clinical.models import ProfessionalAuthorization, ClinicalReferral, ClinicalReviewerAppointment,ClinicalRecordVersion
from scheduling.models import Visit
from scheduling.resource_models import BookingService
from care.models import VisitRecordVersion


def moment(label):
    return forms.DateTimeField(label=label+'（北京时间）', widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))


class ProfessionalCaseForm(forms.Form):
    user=forms.ModelChoiceField(label='申请操作范围的医师账号',queryset=UserAccount.objects.none())
    service=forms.ModelChoiceField(label='本店预约服务（无服务的旧记录单独选“不适用”）',queryset=BookingService.objects.none(),required=False,empty_label='不适用：仅无服务的旧就诊')
    source_kind=forms.ChoiceField(label='资质核验来源',choices=ProfessionalAuthorization.SOURCES)
    source_reference=forms.CharField(label='内部资质核验依据编号',min_length=4,max_length=160,help_text='引用机构保管的原始依据，不录入证件全文。')
    issuer=forms.CharField(label='资质来源机构',min_length=4,max_length=160)
    credential_from=moment('资质生效')
    credential_until=moment('资质失效')
    valid_from=moment('操作范围生效')
    valid_until=moment('操作范围失效')
    can_read=forms.BooleanField(label='临床查阅',initial=True)
    can_record=forms.BooleanField(label='记录与确认本次诊疗',required=False)
    can_refer=forms.BooleanField(label='发起受控跨店转诊',required=False)
    def __init__(self,*args,clinic_id,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['user'].queryset=UserAccount.objects.filter(is_active=True,dentist__is_active=True,
            role_assignments__role='DENTIST',role_assignments__is_active=True).distinct().order_by('username')
        self.fields['user'].label_from_instance=lambda u:f'{u.dentist.name} · {u.username}'
        self.fields['service'].queryset=BookingService.objects.filter(department__clinic_id=clinic_id,is_active=True).select_related('department').order_by('pk')
    def fields_data(self):
        d=dict(self.cleaned_data)
        d['user_id']=d.pop('user').pk; service=d.pop('service'); d['service_id']=service.pk if service else None
        return d


class DecisionForm(forms.Form):
    note=forms.CharField(label='办理依据与结果说明',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))


class ActivationForm(DecisionForm):
    clinic=forms.ModelChoiceField(label='启用专业操作范围控制的诊所',queryset=ClinicalReviewerAppointment.objects.none())
    checked=forms.BooleanField(label='已核对本店医师、服务与未来／在诊预约的授权；后续到期或撤回仍须显式协调')
    def __init__(self,*args,actor,**kwargs):
        super().__init__(*args,**kwargs)
        from registry.models import Clinic
        now=timezone.now()
        self.fields['clinic'].queryset=Clinic.objects.filter(is_active=True,pk__in=ClinicalReviewerAppointment.objects.filter(
            user=actor,is_active=True,valid_from__lte=now,valid_until__gt=now).values('clinic_id'))


class ConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput,max_length=16384)
    confirmed=forms.BooleanField(label='我已核对对象、范围、期限和依据，确认保存本次办理结果')


class ReferralForm(forms.Form):
    source_clinical_record=forms.ModelChoiceField(label='披露的结构化检查版本（与既有版本只选一种）',queryset=ClinicalRecordVersion.objects.none(),required=False)
    source_record=forms.ModelChoiceField(label='明确披露的已发布记录版本（可不披露历史记录）',queryset=VisitRecordVersion.objects.none(),required=False)
    destination_service=forms.ModelChoiceField(label='接收店服务范围（无服务旧模式可不选）',queryset=BookingService.objects.none(),required=False)
    destination_clinic=forms.ModelChoiceField(label='接收诊所',queryset=Visit.objects.none())
    receiver=forms.ModelChoiceField(label='接收医师账号',queryset=UserAccount.objects.none())
    consent_basis=forms.ChoiceField(label='独立的临床披露同意',choices=ClinicalReferral._meta.get_field('consent_basis').choices)
    consent_reference=forms.CharField(label='披露同意依据编号',min_length=4,max_length=160,help_text='法定代理须另行核验临床同意权限；代约关系不等于临床披露同意。')
    purpose=forms.CharField(label='转诊目的',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    valid_until=moment('限定查阅截止')
    def __init__(self,*args,visit,**kwargs):
        super().__init__(*args,**kwargs)
        from registry.models import Clinic
        self.visit=visit
        self.fields['source_clinical_record'].queryset=ClinicalRecordVersion.objects.filter(encounter__visit=visit).order_by('-revision')
        self.fields['source_clinical_record'].label_from_instance=lambda r:f'检查第 {r.revision} 版 · {timezone.localtime(r.recorded_at):%Y-%m-%d %H:%M}'
        self.fields['source_record'].queryset=VisitRecordVersion.objects.filter(visit=visit,state='PUBLISHED').order_by('-revision_no')
        self.fields['source_record'].label_from_instance=lambda r:f'版本 {r.revision_no} · {timezone.localtime(r.published_at):%Y-%m-%d %H:%M}'
        self.fields['destination_clinic'].queryset=Clinic.objects.filter(is_active=True).exclude(pk=visit.clinic_id)
        self.fields['destination_service'].queryset=BookingService.objects.filter(department__clinic__is_active=True,is_active=True).exclude(department__clinic_id=visit.clinic_id).select_related('department__clinic')
        self.fields['destination_service'].label_from_instance=lambda s:f'{s.department.clinic.name} · {s.name}'
        self.fields['receiver'].queryset=UserAccount.objects.filter(is_active=True,dentist__is_active=True,role_assignments__role='DENTIST',role_assignments__is_active=True).distinct().order_by('username')
        self.fields['receiver'].label_from_instance=lambda u:f'{u.dentist.name} · {u.username}'
    def fields_data(self):
        d=dict(self.cleaned_data)
        for key in ('source_record','source_clinical_record','destination_clinic','destination_service','receiver'):
            value=d.pop(key); d[key+'_id']=value.pk if value else None
        d['source_visit_id']=self.visit.pk
        return d


class IdentityForm(DecisionForm):
    patient_no=forms.CharField(label='核对后的现有患者完整编号',max_length=40,help_text='同名、电话相同不自动合并；编号不同请先登记“身份待澄清”。')
