from django import forms
from django.core.validators import validate_email
from patients.contact_rules import CONTACT_FIELDS, REASONS, normalize_details, ContactInputError

class ContactEditForm(forms.Form):
    state_token = forms.CharField(widget=forms.HiddenInput, max_length=16000)
    phone = forms.CharField(label='联系电话', max_length=32, strip=False, widget=forms.TextInput(attrs={'type':'tel','autocomplete':'off'}))
    # EmailField forces strip=True. Keep the contact policy's original input
    # intact and validate it without silently trimming surrounding whitespace.
    email = forms.CharField(label='邮箱（选填，可清空）', required=False, max_length=254,
                            strip=False, validators=[validate_email], widget=forms.EmailInput)
    billing_address = forms.CharField(label='当前账单地址', max_length=255, strip=False)
    emergency_name = forms.CharField(label='紧急联系人', max_length=80, strip=False)
    emergency_phone = forms.CharField(label='紧急联系电话', max_length=32, strip=False, widget=forms.TextInput(attrs={'type':'tel','autocomplete':'off'}))
    reason_code = forms.ChoiceField(label='更正依据', choices=[('', '请选择')] + list(REASONS.items()))
    def clean(self):
        data = super().clean()
        allowed = set(self.fields) | {'csrfmiddlewaretoken', 'workspace_token'}
        if set(self.data) - allowed:
            self.add_error(None, '请求含非联络字段，请使用当前表单重新填写。')
        if all(k in data for k in CONTACT_FIELDS):
            try:
                data.update(normalize_details({k: data[k] for k in CONTACT_FIELDS}))
            except ContactInputError as exc:
                self.add_error(exc.field, str(exc))
        return data

class ContactConfirmForm(forms.Form):
    proposal_token = forms.CharField(widget=forms.HiddenInput, max_length=16000)
    confirmed = forms.BooleanField(label='我已与患者核对差异，确认只更正上述联络资料，不修改身份、过敏及已发布账单')
    def clean(self):
        data = super().clean()
        if set(self.data) - (set(self.fields) | {'csrfmiddlewaretoken','workspace_token'}):
            self.add_error(None, '确认步骤不能直接改写字段。请返回重新填写，再核对差异。')
        return data
