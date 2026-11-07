from django import forms

from supplies.models import StockItem, SterilePack


class BasisForm(forms.Form):
    reason=forms.CharField(label='事实与依据',max_length=500,widget=forms.Textarea(attrs={'rows':2}))


class ReceiptForm(BasisForm):
    item=forms.ModelChoiceField(label='库存条目',queryset=StockItem.objects.none())
    code=forms.CharField(label='批号',max_length=60)
    expires_on=forms.DateField(label='有效期至',widget=forms.DateInput(attrs={'type':'date'}))
    quantity=forms.IntegerField(label='实际入库数量',min_value=1,max_value=1000000)
    reference=forms.CharField(label='到货凭据编号',max_length=120)
    field_order=['item','code','expires_on','quantity','reference','reason']

    def __init__(self,*args,items,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['item'].queryset=items


class LotActionForm(BasisForm):
    def __init__(self,*args,kind,movements=(),**kwargs):
        super().__init__(*args,**kwargs)
        if kind=='RECALL':
            self.fields['reference']=forms.CharField(label='召回依据编号',max_length=120)
        elif kind=='WASTE':
            self.fields['quantity']=forms.IntegerField(label='实际报损数量',min_value=1,max_value=1000000)
        else:
            self.fields['movement']=forms.TypedChoiceField(label='需要冲回的到货或报损记录',coerce=int,choices=[
                (row.pk,f'#{row.pk} · {row.get_kind_display()} · {row.quantity}') for row in movements
            ])
        self.order_fields(['reference','quantity','movement','reason'])


def _date_time(label):
    return forms.DateTimeField(label=label,widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M:%S',attrs={'type':'datetime-local','step':'1'}))


class ExecutionForm(BasisForm):
    observed_at=_date_time('实际发生时间（北京时间）')

    def __init__(self,*args,kind,actuals=(),lots=(),packs=(),issues=(),**kwargs):
        super().__init__(*args,**kwargs)
        if kind in ('MATERIAL','STERILE'):
            self.fields['performed']=forms.TypedChoiceField(label='对应本次实际治疗',coerce=int,choices=[
                (row.pk,f"实际记录 #{row.pk} · {row.charge_snapshot['name']}") for row in actuals
            ])
        if kind=='MATERIAL':
            self.fields['lot']=forms.TypedChoiceField(label='本店耗材批次',coerce=int,choices=[
                (lot.pk,f'{lot.item.name} · {lot.code} · 可用 {lot.available} {lot.item.unit}') for lot in lots
            ])
        if kind=='STERILE':
            self.fields['pack']=forms.TypedChoiceField(label='本店已放行的无菌包',coerce=int,choices=[
                (row.pk,f'{row.code} · {row.process_reference}') for row in packs
            ])
        if kind=='ADMINISTER':
            self.fields['issue']=forms.TypedChoiceField(label='本次已发药品',coerce=int,choices=[
                (row.pk,f'#{row.pk} · {row.line.name_snapshot} · {row.quantity} {row.line.unit_snapshot}')
                for row in issues
            ])
        if kind in ('MATERIAL','ADMINISTER'):
            self.fields['quantity']=forms.IntegerField(label='实际数量',min_value=1,max_value=1000000)
        self.order_fields(['observed_at','performed','lot','pack','issue','quantity','reason'])


class PackReleaseForm(forms.Form):
    code=forms.CharField(label='无菌包编号',max_length=60)
    reference=forms.CharField(label='灭菌批次与放行依据',max_length=120)
    processed_at=_date_time('实际灭菌时间（北京时间）')
    valid_until=_date_time('有效截止时间（北京时间）')


class PackHoldForm(BasisForm):
    pack=forms.ModelChoiceField(label='需停用的本店无菌包',queryset=SterilePack.objects.none())

    def __init__(self,*args,packs,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['pack'].queryset=packs
        self.fields['pack'].label_from_instance=lambda row: row.code
        self.order_fields(['pack','reason'])
