from django import forms
from django.utils import timezone
from portal.medical_models import MedicalProxy


class ProxyMaterialsForm(forms.Form):
    patient_no=forms.CharField(label='已核对患者编号',max_length=40)
    username=forms.CharField(label='已核对代理账号',max_length=150)
    delegate_name=forms.CharField(label='代理人姓名（按材料核对）',max_length=100)
    kind=forms.ChoiceField(label='独立医疗代理依据类型',choices=[('GUARDIAN','未成年监护'),('WRITTEN','成年患者书面委托')])
    plan=forms.IntegerField(label='本店本患者方案编号',min_value=1)
    steps=forms.CharField(label='本次授权的稳定步骤编号',help_text='按医师列明的步骤编号填写，逗号分隔；不填写临床正文。',max_length=500)
    identity_reference=forms.CharField(label='身份材料核对编号',min_length=4,max_length=500,help_text='只登记材料编号，不录入证件全文。')
    authority_reference=forms.CharField(label='监护／书面委托原件编号',min_length=4,max_length=500)
    applicability=forms.CharField(label='需要代理的具体情形及材料范围',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':3}),help_text='简要说明办理情形，不在前台表单录入病史或诊疗文字。')
    valid_from=forms.DateTimeField(label='依据生效时间（北京时间）',widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))
    valid_until=forms.DateTimeField(label='依据截止时间（北京时间）',widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))
    def clean_steps(self):
        try:
            values=sorted(set(int(v.strip()) for v in self.cleaned_data['steps'].replace('，',',').split(',') if v.strip()))
            if not 1<=len(values)<=30 or min(values)<1:raise ValueError
            return values
        except ValueError:raise forms.ValidationError('请填写1至30个有效步骤编号。')
    def values(self):
        d=dict(self.cleaned_data)
        for k in ('valid_from','valid_until'):d[k]=d[k].isoformat()
        return d


class ProxyActionForm(forms.Form):
    action=forms.ChoiceField(label='本次办理',choices=[])
    note=forms.CharField(label='办理／核验依据',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    applicable=forms.BooleanField(label='负责医师已核对本次医疗代理适用情形、范围与期限',required=False)
    def __init__(self,*args,role,state=None,**kwargs):
        super().__init__(*args,**kwargs)
        choices={'FRONT_DESK':[('MATERIALS_OK','资料核对完成，提交医师'),('SUSPEND','暂停并交重新核对'),('REVOKE','明确撤销')],
            'DENTIST':[('APPROVE','确认本次医疗代理适用性'),('RETURN','退回补充材料'),('REJECT','不通过'),('ESCALATE','转独立专业复核'),('REVOKE','明确撤销')],
            'PATIENT':[('REVOKE','明确撤销／放弃本项授权')]}
        allowed={'MATERIALS':{'MATERIALS_OK','REVOKE'},'DOCTOR':{'APPROVE','RETURN','REJECT','ESCALATE','REVOKE'},'REVIEW':{'APPROVE','RETURN','REJECT','REVOKE'},'RETURNED':{'REVOKE'},'ACTIVE':{'SUSPEND','REVOKE'},'SUSPENDED':{'REVOKE'},'REJECTED':set(),'REVOKED':set()}
        self.fields['action'].choices=[c for c in choices[role] if state is None or c[0] in allowed.get(state,set())]
        if role!='DENTIST':self.fields.pop('applicable')
