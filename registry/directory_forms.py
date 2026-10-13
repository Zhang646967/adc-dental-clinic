from decimal import Decimal
from django import forms
from registry.models import Qualification
from registry.directory_rules import FIELDS, REASONS, DirectoryInputError, normalize_registration
from django.utils import timezone

class RegistrationForm(forms.Form):
    """Only bounded model facts. Authorization and field checks repeat in services."""
    reason_code = forms.ChoiceField(label='登记依据', choices=[('SOURCE_RECORD', REASONS['SOURCE_RECORD'])])

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        definitions = {
            'clinic_code': forms.CharField(label='诊所编码', max_length=24, help_text='大写字母、数字、短横线或下划线；登记后本入口不改编码。'),
            'employee_no': forms.CharField(label='牙医员工编号', max_length=24, help_text='业务编号，不是登录账号或执业许可编号。'),
            'code': forms.CharField(label='资格类别编码', max_length=24),
            'name': forms.CharField(label={'clinic':'诊所名称','dentist':'牙医姓名','qualification':'资格类别名称'}[kind], max_length=80 if kind == 'dentist' else 120),
            'postal_address': forms.CharField(label='诊所地址', max_length=255),
            'supervisor_name': forms.CharField(label='主管联络姓名', max_length=80, help_text='仅登记联系人；填写姓名不会授予任何账号主管身份。'),
            'phone': forms.CharField(label='联系电话', max_length=32, widget=forms.TextInput(attrs={'inputmode':'tel'})),
            'email': forms.EmailField(label='邮箱', max_length=254, help_text='本课程仅使用 example.invalid 合成地址，不发送邮件。'),
            'area_sqm': forms.DecimalField(label='面积（平方米）', max_digits=10, decimal_places=2, min_value=Decimal('0.01')),
            'date_of_birth': forms.DateField(label='出生日期', widget=forms.DateInput(attrs={'type':'date','max':timezone.localdate().isoformat()},format='%Y-%m-%d')),
            'home_address': forms.CharField(label='联系地址', max_length=255, help_text='只填写虚构演示资料，不录入真实个人信息。'),
        }
        for key in FIELDS[kind]:
            self.fields[key] = definitions[key]
        self.order_fields([*FIELDS[kind], 'reason_code'])

    def clean(self):
        data = super().clean()
        if all(key in data for key in FIELDS[self.kind]):
            try:
                data.update(normalize_registration(self.kind, {k:data[k] for k in FIELDS[self.kind]}, today=timezone.localdate()))
            except DirectoryInputError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return data

class AssociationForm(forms.Form):
    qualification = forms.ModelChoiceField(label='资格类别', queryset=Qualification.objects.none(), empty_label='请选择已登记的资格类别')
    reason_code = forms.ChoiceField(label='登记依据', choices=[('SOURCE_RECORD',REASONS['SOURCE_RECORD']),('RESTORE_LINK',REASONS['RESTORE_LINK'])])

    def __init__(self,*args, dentist, **kwargs):
        super().__init__(*args,**kwargs)
        self.fields['qualification'].queryset = Qualification.objects.filter(is_active=True).exclude(
            pk__in=dentist.qualifications.filter(is_active=True).values('qualification_id')).order_by('code')
        self.fields['qualification'].label_from_instance = lambda o: f'{o.code} · {o.name}'
        self.fields['qualification'].help_text = '未在列表中找到时，先登记资格类别；已有有效关联不重复列出。'

class DirectoryConfirmForm(forms.Form):
    proposal_token = forms.CharField(max_length=16000, widget=forms.HiddenInput)
    operator_password = forms.CharField(label='再次输入你自己的技术管理密码', strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}))
    confirmed = forms.BooleanField(label='我已核对目标、资料和影响；此操作不会自动授予账号权限、安排出诊或认证执业资格')
