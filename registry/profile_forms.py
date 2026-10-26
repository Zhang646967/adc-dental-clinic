from django import forms
from scheduling.service_content import CATEGORY_CHOICES


class DentistProfileForm(forms.Form):
    title = forms.ChoiceField(label='申报职称', choices=[('医师','医师'),('主治医师','主治医师'),
        ('副主任医师','副主任医师'),('主任医师','主任医师')])
    specialties = forms.MultipleChoiceField(label='专业方向', choices=CATEGORY_CHOICES)
    summary = forms.CharField(label='一句话介绍', max_length=160)
    biography = forms.CharField(label='医师介绍', max_length=1800, widget=forms.Textarea(attrs={'rows':5}))
    practicing_since = forms.DateField(label='从业起始日期', required=False, widget=forms.DateInput(attrs={'type':'date'}))
    languages = forms.CharField(label='沟通语言', max_length=120, initial='普通话')
    education = forms.CharField(label='学习与进修经历', max_length=600, required=False, widget=forms.Textarea(attrs={'rows':3}))
    credential_reference = forms.CharField(label='职称与经历来源（仅内部）', max_length=300)
    media_ids = forms.CharField(label='头像图片编号', required=False, widget=forms.HiddenInput)


class ClinicProfileForm(forms.Form):
    summary = forms.CharField(label='门店特色', max_length=160)
    biography = forms.CharField(label='门店介绍', max_length=1800, widget=forms.Textarea(attrs={'rows':5}))
    transport = forms.CharField(label='公共交通与入口指引', max_length=500, widget=forms.Textarea(attrs={'rows':3}))
    parking = forms.CharField(label='停车说明', max_length=300, required=False)
    accessibility = forms.ChoiceField(label='无障碍条件', choices=[('UNKNOWN','待核对'),('YES','具备'),('NO','暂不具备')])
    accessibility_note = forms.CharField(label='无障碍说明', max_length=300, required=False)
    fee_note = forms.CharField(label='费用说明', max_length=500)
    media_ids = forms.CharField(label='门店图片编号', required=False, widget=forms.HiddenInput)


class AffiliationForm(forms.Form):
    dentist_id = forms.IntegerField(label='医师编号', min_value=1)
    kind = forms.ChoiceField(label='接诊安排', choices=[('RESIDENT','常驻'),('VISITING','轮诊')])
    starts_on = forms.DateField(label='开始日期', widget=forms.DateInput(attrs={'type':'date'}))
    ends_on = forms.DateField(label='结束日期', required=False, widget=forms.DateInput(attrs={'type':'date'}))


class ProfileConfirmForm(forms.Form):
    proposal_token = forms.CharField(widget=forms.HiddenInput)
    confirmed = forms.BooleanField(label='我已核对并确认办理')


class MediaForm(forms.Form):
    image = forms.FileField(label='头像／门店图片（JPEG、PNG、WebP，最多5MiB）')
    alt_text = forms.CharField(label='图片说明', max_length=160)
