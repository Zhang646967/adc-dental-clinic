from django import forms
from registry.catalog_rules import validate_definition, CatalogInputError

class CatalogueCreateForm(forms.Form):
    code=forms.CharField(label='唯一项目编码',max_length=24,help_text='大写字母、数字、下划线或短横线；建立后本页面不改编码。')
    name=forms.CharField(label='治疗项目名称',max_length=120)
    unit=forms.CharField(label='标准单位说明',max_length=120)
    price=forms.DecimalField(label='当前标准单价（元）',min_value=0,max_digits=12,decimal_places=2)
    reason=forms.CharField(label='新增依据',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='我已核对名称、单位与价格；目录登记不是医学资质审核')
    def clean(self):
        d=super().clean()
        if all(k in d for k in ('code','name','unit')):
            try:d['code'],d['name'],d['unit']=validate_definition(d['code'],d['name'],d['unit'])
            except CatalogInputError as exc:raise forms.ValidationError(str(exc))
        return d

class CataloguePriceForm(forms.Form):
    state_token=forms.CharField(widget=forms.HiddenInput)
    price=forms.DecimalField(label='新的当前标准单价（元）',min_value=0,max_digits=12,decimal_places=2)
    reason=forms.CharField(label='调价依据',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='我确认仅修改当前目录单价；已记录的治疗和历史结算不随之改价')
