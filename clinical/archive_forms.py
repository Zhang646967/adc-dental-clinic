from django import forms


class ArchiveRequestForm(forms.Form):
    kind=forms.ChoiceField(label='办理类型',choices=[('ARCHIVE','完整病历归档'),('MATERIALS','仅保全缺项资料，不标为完整归档')])
    fee_version=forms.ChoiceField(label='同时保留的已发布收费版本',required=False)
    reviewer=forms.ChoiceField(label='独立医务审核人')
    reason=forms.CharField(label='办理依据及本次补充说明',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,details,**kw):
        super().__init__(*args,**kw)
        from care.models import VisitRecordVersion
        self.fields['fee_version'].choices=[('','按当前已发布版本；尚未发布时明确保留无已发布费用单')]+[(str(v.pk),'第'+str(v.revision_no)+'版 · ¥'+str(v.total_amount)) for v in VisitRecordVersion.objects.filter(visit=details['visit'],state='PUBLISHED').order_by('-revision_no')]
        self.fields['reviewer'].choices=[(str(r.pk),r.user.dentist.name+' · '+r.user.username) for r in details['reviewer_options']]


class AmendmentRequestForm(forms.Form):
    target=forms.ChoiceField(label='已准备准确更正草稿的对象',choices=[('DOCUMENT','完整病历文书'),('RECORD','检查及牙位记录')])
    reviewer=forms.ChoiceField(label='独立医务审核人')
    reason=forms.CharField(label='补正原因、具体差异与来源',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':4}))
    def __init__(self,*args,details,**kw):
        super().__init__(*args,**kw)
        self.fields['reviewer'].choices=[(str(r.pk),r.user.dentist.name+' · '+r.user.username) for r in details['reviewer_options']]


class ArchiveReviewForm(forms.Form):
    decision=forms.ChoiceField(label='独立医务结论',choices=[('APPROVE','通过准确内容'),('RETURN','退回完善'),('REJECT','不通过')])
    note=forms.CharField(label='审核意见及依据',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':4}))


class ArchiveActionForm(forms.Form):
    action=forms.ChoiceField(label='办理动作',choices=[('WITHDRAW','撤回未完成的申请'),('RETRY','明确重试原生成失败')])
    reason=forms.CharField(label='办理依据',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':3}))


class ArchiveConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='已核对就诊人、准确内容、来源、岗位责任及本次操作后果，明确确认')
