from django import forms

class BookingConfirmationForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput, max_length=2048)
    confirmed = forms.BooleanField(label="我已核对诊所、牙医和北京时间，确认提交此预约。")

class CancelForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(label="取消原因", max_length=500, widget=forms.Textarea(attrs={"rows":3}))
    confirmed = forms.BooleanField(label="我确认取消这一次预约；不会影响其他预约。")

class SlotFilterForm(forms.Form):
    clinic = forms.IntegerField(label="诊所编号（选填）", required=False, min_value=1)
    day = forms.DateField(label="日期（北京时间，选填）", required=False, widget=forms.DateInput(attrs={"type":"date","id":"day-filter"}))
