from django import forms
from decimal import Decimal
from insurance.catalogue_source import SOURCE_KEY
from insurance.models import PolicyCatalogue, PolicyItem, SCHEMES, ELIGIBILITY_STATES
from insurance.services import REGIONS
from registry.models import TreatmentType


class CatalogueImportForm(forms.Form):
    source_key = forms.ChoiceField(label='已核对来源的目录包', choices=[(SOURCE_KEY, '湖南省口腔目录 · 湘医保发〔2026〕12号')])


class CatalogueResubmitForm(forms.Form):
    reason = forms.CharField(label='重新核对的原因及已处理事项', max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
        help_text='沿用同一政策原文，形成关联前次的新审阅记录；不改变原决定，也不直接恢复原安排或映射。')


class DatesForm(forms.Form):
    starts_on = forms.DateField(label='有效起始日期', widget=forms.DateInput(attrs={'type': 'date'}))
    ends_on = forms.DateField(label='有效截止日期', widget=forms.DateInput(attrs={'type': 'date'}))
    reference = forms.CharField(label='合成依据编号', max_length=80, help_text='以 SIM- 开头，例如 SIM-HN-COURSE-01；不填写真实医保、证件或卡号。')


class ArrangementForm(DatesForm):
    catalogue_id = forms.TypedChoiceField(label='独立核对后的目录', coerce=int)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['catalogue_id'].choices = [(r.pk, str(r)) for r in PolicyCatalogue.objects.filter(state='CONFIRMED').order_by('-pk')]


class MappingForm(forms.Form):
    treatment_type_id = forms.TypedChoiceField(label='原收费项目', coerce=int)
    policy_item_id = forms.TypedChoiceField(label='对应目录项目', coerce=int)
    policy_units_per_fee = forms.DecimalField(label='每一原收费单位对应的目录单位数量', max_digits=12, decimal_places=4, min_value=Decimal('0.0001'),
        help_text='明确核对项目含义与单位。例如原收费单位“颗”与目录“每牙”对应一单位时填1。此数值不改变原收费数量或价格。')
    compatibility_basis = forms.CharField(label='项目含义、单位及换算依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['treatment_type_id'].choices = [(r.pk, f'{r.code} · {r.name} · {r.unit_definition}') for r in TreatmentType.objects.filter(is_active=True).order_by('code')]
        self.fields['policy_item_id'].choices = [(r.pk, f'{r.code} · {r.name} · {r.unit or "单位缺失，待核对"}') for r in PolicyItem.objects.filter(catalogue__state='CONFIRMED').order_by('code')]


class EligibilityForm(DatesForm):
    insured_region = forms.ChoiceField(label='患者参保地（独立于定位和就诊城市）', choices=REGIONS)
    scheme = forms.ChoiceField(label='参保类型（课程模拟）', choices=SCHEMES)
    state = forms.ChoiceField(label='本次模拟待遇核对结果', choices=ELIGIBILITY_STATES)
    basis = forms.CharField(label='模拟核对依据及待办说明', max_length=500, widget=forms.Textarea(attrs={'rows': 3}), help_text='只记录合成场景；微信登录、手机号和患者自报均不等同于待遇核验。')


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label='独立复核结果', choices=[('approve', '核对通过并启用'), ('reject', '未通过，保留依据')])
    reason = forms.CharField(label='复核依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class DisableForm(forms.Form):
    reason = forms.CharField(label='停用原因及后续安排', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))
