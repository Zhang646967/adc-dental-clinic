from django import forms
from portal.enrollment_models import PatientEnrollment
from portal.enrollment import BASES
from registry.models import Clinic


class LocalLoginForm(forms.Form):
    code=forms.CharField(label='本地授权码',max_length=160,widget=forms.PasswordInput(render_value=False),help_text='仅用于本地替身验证，由私有维护命令签发；不是微信验证码。')
    username=forms.CharField(label='已有患者账号（首次使用可留空）',required=False,max_length=150)
    password=forms.CharField(label='原账号密码（绑定已有账号时填写）',required=False,strip=False,widget=forms.PasswordInput)
    booking_service=forms.IntegerField(required=False,min_value=1,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='我同意使用本地模拟身份继续患者服务。')


class PhoneCodeForm(forms.Form):
    code=forms.CharField(label='本地手机授权码',max_length=160,widget=forms.PasswordInput)
    confirmed=forms.BooleanField(label='我同意绑定此合成联络号码（仅本地模拟）。')


class SmsAuthForm(forms.Form):
    phone=forms.CharField(label='手机号码',max_length=16,widget=forms.TextInput(attrs={'inputmode':'tel','autocomplete':'tel','placeholder':'请输入手机号'}))
    code=forms.CharField(label='短信验证码',required=False,min_length=6,max_length=6,widget=forms.TextInput(attrs={'inputmode':'numeric','autocomplete':'one-time-code'}))
    challenge=forms.UUIDField(required=False,widget=forms.HiddenInput)
    captcha_key=forms.CharField(label='图片验证码（平台要求时填写）',required=False,max_length=6)
    confirmed=forms.BooleanField(label='我同意接收验证码，并使用此号码办理本人登录账号。')


class WechatCodeForm(forms.Form):
    code=forms.CharField(max_length=512)
    confirmed=forms.BooleanField()
    username=forms.CharField(required=False,max_length=150)
    password=forms.CharField(required=False,strip=False,widget=forms.PasswordInput)


class UnlinkForm(forms.Form):
    identity=forms.IntegerField(min_value=1,widget=forms.HiddenInput)
    revision=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    password=forms.CharField(label='核对我的账号密码',strip=False,widget=forms.PasswordInput)
    confirmed=forms.BooleanField(label='我确认解绑；原患者档案、预约和历史保留。')


class PasswordSetupForm(forms.Form):
    code=forms.CharField(label='当前绑定身份的新本地授权码',max_length=160,widget=forms.PasswordInput)
    new_password=forms.CharField(label='设置登录密码',strip=False,widget=forms.PasswordInput)
    repeat_password=forms.CharField(label='再次输入密码',strip=False,widget=forms.PasswordInput)
    confirmed=forms.BooleanField(label='我确认设置本人账号密码，便于网站登录及恢复。')
    def clean(self):
        data=super().clean()
        if data.get('new_password')!=data.get('repeat_password'):self.add_error('repeat_password','两次密码不一致。')
        return data


class EnrollmentForm(forms.Form):
    clinic=forms.ModelChoiceField(label='办理门店',queryset=Clinic.objects.none())
    kind=forms.ChoiceField(label='办理事项',choices=PatientEnrollment.KINDS)
    name=forms.CharField(label='患者姓名',max_length=80)
    date_of_birth=forms.DateField(label='出生日期',widget=forms.DateInput(attrs={'type':'date'}))
    phone=forms.CharField(label='联络号码',max_length=32,help_text='可以与家人共用；不会按此号码合并档案。')
    billing_address=forms.CharField(label='账单／联系地址（新建档必填）',max_length=255,required=False)
    email=forms.EmailField(label='电子邮箱（选填）',required=False)
    emergency_name=forms.CharField(label='紧急联系人（新建档必填）',max_length=80,required=False)
    emergency_phone=forms.CharField(label='紧急联系电话（新建档必填）',max_length=32,required=False)
    patient_reference=forms.CharField(label='原患者编号（记得时填写）',max_length=40,required=False)
    def __init__(self,*args,**kwargs):
        restore_only=kwargs.pop('restore_only',False)
        super().__init__(*args,**kwargs)
        if restore_only:self.fields['kind'].choices=[('EXISTING','复核原本人关联')]
        self.fields['clinic'].queryset=Clinic.objects.filter(is_active=True,public_directory__is_published=True).order_by('public_directory__city','pk')
        self.fields['clinic'].label_from_instance=lambda c:c.public_contact['name']
    def clean(self):
        d=super().clean()
        if d.get('kind')=='NEW':
            for field in ('billing_address','emergency_name','emergency_phone'):
                if not d.get(field):self.add_error(field,'新建完整档案需要此资料。')
        return d


class EnrollmentReviewForm(forms.Form):
    action=forms.ChoiceField(label='办理结果',choices=[('APPROVE','核验通过并关联本人'),('NEED_INFO','退回补充资料'),('REJECT','未通过')])
    basis=forms.ChoiceField(label='本人及账号核验方式',choices=BASES)
    reference=forms.CharField(label='内部依据编号',max_length=160,help_text='只填内部引用编号，不填完整证件号。')
    patient_no=forms.CharField(label='明确选择的原患者编号（旧档关联必填）',max_length=40,required=False)
    patient_message=forms.CharField(label='给患者的补充要求／办理说明',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))


class ConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput,max_length=16384)
    confirmed=forms.BooleanField(label='我已核对上述资料及办理结果，确认提交。')
