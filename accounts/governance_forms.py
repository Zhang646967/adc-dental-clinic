from django import forms
from django.contrib.auth.validators import UnicodeUsernameValidator
from registry.models import Clinic, Dentist
from accounts.models import RoleAssignment
from workspaces.rules import ROLES
from accounts.governance import MANAGED_ROLES

class AuthorityForm(forms.Form):
    reason=forms.CharField(label='操作依据',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':2}),help_text='仅填写业务理由，不填密码、密钥或医疗信息。')
    operator_password=forms.CharField(label='再次输入你自己的技术管理密码',strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}))
    confirmed=forms.BooleanField(label='我已核对目标账号、授权范围和本次变更')

class CreateAccountForm(AuthorityForm):
    username=forms.CharField(label='新用户名',max_length=150,validators=[UnicodeUsernameValidator()])
    dentist=forms.ModelChoiceField(label='关联已有牙医（非牙医账号留空）',queryset=Dentist.objects.none(),required=False)
    password1=forms.CharField(label='为新账号设置密码',strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    password2=forms.CharField(label='再次输入新账号密码',strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    field_order=['username','dentist','password1','password2','reason','operator_password','confirmed']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from accounts.models import UserAccount
        self.fields['dentist'].queryset=Dentist.objects.filter(is_active=True).exclude(pk__in=UserAccount.objects.exclude(dentist_id=None).values('dentist_id'))
    def clean(self):
        data=super().clean()
        if data.get('password1')!=data.get('password2'):self.add_error('password2','两次密码不一致。')
        return data

class AccountActionForm(AuthorityForm):
    target_token=forms.CharField(widget=forms.HiddenInput)
    def __init__(self,*args,action,target,token,**kwargs):
        initial=dict(kwargs.pop('initial',{}));initial['target_token']=token
        super().__init__(*args,initial=initial,**kwargs)
        self.action=action
        if action=='grant':
            self.fields['role']=forms.ChoiceField(label='授予的身份',choices=[(r,ROLES[r][0]) for r in MANAGED_ROLES])
            self.fields['clinic']=forms.ModelChoiceField(label='诊所范围（仅前台／主管需要）',queryset=Clinic.objects.filter(is_active=True),required=False)
        elif action=='revoke':
            self.fields['grant']=forms.ModelChoiceField(label='撤回的授权',queryset=RoleAssignment.objects.filter(user=target,is_active=True).exclude(role='SYSADMIN'))
            self.fields['grant'].label_from_instance=lambda o:f'{ROLES[o.role][0]} · {o.clinic.name if o.clinic_id else o.scope_kind}'
        elif action=='identity_reviewer':
            self.fields['grant']=forms.ModelChoiceField(label='本店前台授权',queryset=RoleAssignment.objects.filter(user=target,role='FRONT_DESK',is_active=True,clinic__is_active=True))
            self.fields['grant'].label_from_instance=lambda o:o.clinic.name+' · 前台'
            self.fields['reviewer_enabled']=forms.BooleanField(label='授予患者关系核验职责（取消勾选则撤回）',required=False)
        elif action=='bind_patient':
            self.fields['patient_no']=forms.CharField(label='已核对的演示患者业务编号',max_length=40,help_text='由获授权技术人员核对后绑定；这不构成真实患者身份认证。')
        elif action=='clinical_reviewer':
            self.fields['clinic']=forms.ModelChoiceField(label='机构委任诊所',queryset=Clinic.objects.filter(is_active=True))
            self.fields['reviewer_enabled']=forms.BooleanField(label='授予专业审核职责（取消勾选则撤回）',required=False)
            self.fields['reviewer_reference']=forms.CharField(label='机构委任依据编号',min_length=4,max_length=160,help_text='仅登记机构已决定的职责，不证明执业资质，不授予病历查阅权限。')
            self.fields['reviewer_from']=forms.DateTimeField(label='职责生效时间（北京时间）',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
            self.fields['reviewer_until']=forms.DateTimeField(label='职责失效时间（北京时间）',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
        elif action=='reset_password':
            for key,label in [('password1','设置新密码'),('password2','再次输入新密码')]:
                self.fields[key]=forms.CharField(label=label,strip=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
        if action=='security_suspend':
            self.fields['security_confirmed']=forms.BooleanField(
                label='确认立即停止此账号访问并使原密码失效；预约和历史保留，恢复须先重置密码再启用')
        self.order_fields(['security_confirmed','target_token','role','clinic','grant','reviewer_enabled','reviewer_reference','reviewer_from','reviewer_until','patient_no','password1','password2','reason','operator_password','confirmed'])
    def clean(self):
        data=super().clean()
        if self.action=='reset_password' and data.get('password1')!=data.get('password2'):self.add_error('password2','两次密码不一致。')
        if self.action=='grant':
            scoped=data.get('role') in ('MANAGER','FRONT_DESK')
            if scoped and not data.get('clinic'):self.add_error('clinic','请明确选择授权诊所。')
            elif not scoped and data.get('clinic'):self.add_error('clinic','该身份不接受诊所范围，请清空。')
        return data
