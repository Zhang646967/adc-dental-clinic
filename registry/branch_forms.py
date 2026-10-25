"""Clinic manager's explicit public fields; no patient or employee projection."""
from django import forms
from registry.directory_models import ClinicDirectory

FIELDS = ('display_name','province','city','district','address','entrance','public_phone',
    'latitude','longitude','map_latitude','map_longitude','coordinate_source','synthetic','is_published')


class DirectoryForm(forms.ModelForm):
    class Meta:
        model=ClinicDirectory
        fields=FIELDS
        labels={'display_name':'对外门店名称','province':'省份','city':'城市','district':'区或县',
            'address':'详细地址','entrance':'楼层及入口','public_phone':'公开联系电话',
            'latitude':'距离计算纬度（WGS-84）','longitude':'距离计算经度（WGS-84）',
            'map_latitude':'地图导航纬度（GCJ-02）','map_longitude':'地图导航经度（GCJ-02）',
            'coordinate_source':'坐标来源与核对依据','synthetic':'合成测试门店（拦截拨号和导航）','is_published':'公开门店资料'}

    def clean(self):
        data=super().clean()
        for a,b in [('latitude','longitude'),('map_latitude','map_longitude')]:
            if (data.get(a) is None)!=(data.get(b) is None):self.add_error(a,'请成对填写同一坐标系的经纬度。')
        if any(data.get(k) is not None for k in ('latitude','map_latitude')) and not data.get('coordinate_source'):
            self.add_error('coordinate_source','请说明坐标来源和坐标系，不能将两种坐标直接混用。')
        phone=data.get('public_phone','')
        if phone and (sum(c.isdigit() for c in phone)<7 or not all(c in '+- ()0123456789' for c in phone)):self.add_error('public_phone','请填写可展示的联系电话，测试电话也使用号码格式。')
        return data


class DirectoryConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='已核对门店名称、联系方式、营业来源及对外发布状态')
