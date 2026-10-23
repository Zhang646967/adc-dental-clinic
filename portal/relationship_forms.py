from datetime import timedelta
from django import forms
from django.utils import timezone
from portal.models import PatientRelationship
from portal.relationships import BASES

class RelationshipForm(forms.Form):
    patient_no=forms.CharField(label='本店已建档患者编号',max_length=40)
    related_name=forms.CharField(label='关联人姓名',max_length=100)
    kind=forms.ChoiceField(label='与患者的关系',choices=PatientRelationship.KINDS)
    username=forms.CharField(label='关联人登录账号（可稍后补充）',max_length=150,required=False,
        help_text='填写已核对的账号；手机号、患者编号及姓名不会自动绑定账号。')
    note=forms.CharField(label='受理说明',max_length=500,widget=forms.Textarea(attrs={'rows':3}),help_text='记录办理事项，不填写病历、密码或完整证件号码。')

class RelationshipActionForm(forms.Form):
    note=forms.CharField(label='办理依据及结果说明',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,action,case,**kwargs):
        super().__init__(*args,**kwargs)
        if action=='LINK_ACCOUNT':
            self.fields['username']=forms.CharField(label='已核对的关联人登录账号',max_length=150)
        if action=='VERIFY':
            self.fields['basis']=forms.ChoiceField(label='核验方式',choices=BASES)
            self.fields['reference']=forms.CharField(label='内部核验依据编号',max_length=160,help_text='引用诊所保存的核验依据，不录入完整证件号码或上传证件。')
            if case.kind in {'PARENT','GUARDIAN','DELEGATE'}:
                self.fields['valid_until']=forms.DateTimeField(label='预约授权截止（北京时间）',
                    widget=forms.DateTimeInput(attrs={'type':'datetime-local'}),initial=timezone.localtime(timezone.now()+timedelta(days=90)).strftime('%Y-%m-%dT%H:%M'))
            self.fields['verified']=forms.BooleanField(label='已核对患者、关联人、账号归属与关系／委托依据；代约仅包含本店预约事项')

class RelationshipConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput,max_length=16384)
    confirmed=forms.BooleanField(label='我已复核以上内容、范围及有效期，确认保存本次决定')
