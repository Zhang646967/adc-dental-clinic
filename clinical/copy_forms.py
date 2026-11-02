from datetime import timedelta
from django import forms
from django.utils import timezone
from clinical.copy_models import RecordCopyRequest
from clinical.archive_models import ArchivePackage
from clinical.models import ClinicalReviewerAppointment
from clinical import record_copies as cmd
from portal.policies import patient_access
from registry.models import Clinic
from scheduling.models import Visit


class CopyApplyForm(forms.Form):
    clinic=forms.ModelChoiceField(label='办理门店',queryset=Clinic.objects.none())
    visits=forms.MultipleChoiceField(label='需要复制的已结束接诊',choices=[],widget=forms.CheckboxSelectMultiple)
    package=forms.ChoiceField(label='固定版本',choices=[],required=False,help_text='默认各次接诊最近固定版本；选择历史版本时单独申请该次接诊。')
    sections=forms.MultipleChoiceField(label='资料类别',choices=list(cmd.SECTIONS.items()),widget=forms.CheckboxSelectMultiple,initial=list(cmd.SECTIONS))
    purpose=forms.CharField(label='复制用途',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,actor,clinic_id=None,staff=False,patient_no='',**kw):
        super().__init__(*args,**kw)
        if clinic_id and (not str(clinic_id).isdecimal() or int(clinic_id)<=0):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('门店链接无效，请从本人申请清单重新选择。')
        visits=Visit.objects.filter(status__in=['COMPLETED','CLOSED_NO_TREATMENT'])
        if staff:
            duty=cmd.front(actor);self.fields['clinic'].queryset=Clinic.objects.filter(pk=duty.clinic_id);clinic_id=duty.clinic_id
            visits=visits.filter(clinic_id=clinic_id,patient__patient_no=patient_no)
            self.fields['patient_no']=forms.CharField(label='已核对患者业务编号',max_length=40,initial=patient_no)
            self.fields['recipient_account']=forms.CharField(label='已注册领取账号',max_length=150)
            self.fields['recipient_name']=forms.CharField(label='原件核对的实际领取人',max_length=80)
            self.fields['kind']=forms.ChoiceField(label='本用途代理依据',choices=RecordCopyRequest.KINDS[1:])
        else:
            access=patient_access(actor,self_only=True)
            visits=visits.filter(patient_id=access.patient_id)
            self.fields['clinic'].queryset=Clinic.objects.filter(pk__in=visits.values('clinic_id'),is_active=True)
            clinic_id=clinic_id or self.fields['clinic'].queryset.values_list('pk',flat=True).first()
            visits=visits.filter(clinic_id=clinic_id)
        self.fields['clinic'].initial=clinic_id
        self.fields['visits'].choices=[(str(v.pk),v.visit_no+' · '+timezone.localtime(v.scheduled_start).strftime('%Y-%m-%d')+' · '+v.get_status_display()) for v in visits.order_by('-scheduled_start')]
        self.fields['package'].choices=[('','最近固定版本；尚无固定材料时保留申请，转负责医师处理')]+[(str(p.pk),p.archive.encounter.visit.visit_no+' · 第'+str(p.number)+'包 · '+p.submission.get_kind_display()) for p in ArchivePackage.objects.filter(archive__encounter__visit_id__in=visits.values('pk')).select_related('archive__encounter__visit','submission').order_by('-pk')]
        self.order_fields(['patient_no','recipient_account','recipient_name','kind','clinic','visits','package','sections','purpose'])
    def values(self):
        d=dict(self.cleaned_data);d['clinic']=d['clinic'].pk;d['package']=d['package'] or None;return d


class CopyVerifyForm(forms.Form):
    decision=forms.ChoiceField(label='材料核对结果',choices=[('VERIFY','身份、用途与范围核验通过'),('RETURN','退回补充资料'),('REJECT','不通过')])
    basis=forms.ChoiceField(label='实际核对方式',choices=[('IN_PERSON','现场核对患者／领取人及账号'),('ORIGINAL_CONTACT','通过原档案联络与原始材料核对')],required=False)
    identity_reference=forms.CharField(label='身份材料内部编号',max_length=160,required=False,help_text='记录原件保管编号，不填写完整证件号码。')
    authority_reference=forms.CharField(label='本用途代理原件编号',max_length=160,required=False,help_text='仅代理复制需要；预约、医疗决定授权不能替代。')
    purpose_checked=forms.BooleanField(label='已核对本用途、范围、原件、领取人及指定账号',required=False)
    pickup_until=forms.DateTimeField(label='领取有效期限（北京时间）',required=False,widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    reviewer=forms.ModelChoiceField(label='独立医务审核人',queryset=ClinicalReviewerAppointment.objects.none(),required=False)
    message=forms.CharField(label='退回或不通过时给申请人的说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,row,**kw):
        super().__init__(*args,**kw);self.fields['pickup_until'].initial=timezone.localtime(timezone.now()+timedelta(days=7)).strftime('%Y-%m-%dT%H:%M')
        self.fields['reviewer'].queryset=ClinicalReviewerAppointment.objects.filter(clinic=row.clinic,is_active=True,can_review_copies=True).select_related('user__dentist')
        self.fields['reviewer'].label_from_instance=lambda r:r.user.dentist.name+' · '+r.user.username
    def values(self):
        d=dict(self.cleaned_data);d['reviewer']=d['reviewer'].pk if d['reviewer'] else None;return d


class CopyReviewForm(forms.Form):
    decision=forms.ChoiceField(label='独立医务结论',choices=[('APPROVE','批准所列准确范围'),('RETURN','退回材料重新核验'),('REJECT','不通过')])
    message=forms.CharField(label='申请人可见的办理说明',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))


class CopyMessageForm(forms.Form):
    message=forms.CharField(label='补充说明或办理原因',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))


class CopyConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='已核对就诊人、用途、准确范围及实际领取账号，明确确认')
