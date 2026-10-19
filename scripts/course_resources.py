"""Explicit synthetic course resource preparation through normal business commands.

Called from an identified course deployment. Does not change patients, clinical
records, financial facts or original appointments. Existing live promises need
separate manager verification; activation refuses until that work is complete.
"""
import os
from datetime import time
from django.utils import timezone
from adc_core.rules import RuleError


def prepare_clinic(*,actor,clinic_id,dentist_ids):
    from equipment.services import prepare_registration,confirm_equipment
    from scheduling.resource_config import prepare_config,confirm_config,readiness
    from scheduling.resource_models import ResourcePolicy,Department,TreatmentRoom,BookingService,ResourceBinding
    if os.environ.get('ADC_RC_SYNTHETIC')!='1':raise RuleError('课程合成资源仅可在明确标记的课程实例中登记。')
    if ResourcePolicy.objects.filter(clinic_id=clinic_id).exists():raise RuleError('本店已有资源配置，请从资源目录核对，不能覆盖原配置。')
    if actor._adc_workspace.clinic_id!=clinic_id:raise RuleError('请使用该店主管工作台。')
    result={'clinic':clinic_id,'synthetic':True,'assets':[],'actions':[]}
    def config(kind,fields=None):
        p=prepare_config(actor=actor,kind=kind,fields=fields)
        a,_=confirm_config(actor=actor,proposal_token=p['proposal_token'],confirmed=True)
        result['actions'].append(a.pk);return a.result.get('id')
    config('start')
    department=config('department',{'code':'COURSE_GENERAL','name':'课程合成综合科','is_active':True})
    rooms=[config('room',{'department':department,'code':'COURSE_R'+str(i),'name':'课程合成诊室'+str(i),'is_active':True}) for i in (1,2)]
    for day in range(7):config('hours',{'department':department,'weekday':day,'opens_at':'08:00','closes_at':'20:00'})
    for index,category,room,shared in [(1,'CHAIR',rooms[0],False),(2,'CHAIR',rooms[0],False),(3,'CHAIR',rooms[1],False),
                                       (4,'IMAGING',None,True),(5,'STERILIZER',None,True)]:
        code='COURSE-C'+str(clinic_id)+'-'+str(index)
        p=prepare_registration(actor=actor,asset_code=code,name='课程合成'+{'CHAIR':'牙椅','IMAGING':'影像设备','STERILIZER':'消毒设备'}[category]+str(index),
            category=category,location='课程合成资源配置',acquired_on=timezone.localdate(),acquisition_cost=None,next_service_due=None,
            note='明确标注的课程合成资料；用于预约资源演示，不代表真实设备采购、成本或临床认证。')
        asset,_=confirm_equipment(actor=actor,proposal_token=p['proposal_token'],confirmed=True)
        config('binding',{'asset':asset.pk,'room':room or '', 'shared':shared,'is_active':True})
        result['assets'].append(asset.pk)
    services=[]
    for code,name,duration,imaging,sterilizer in [('CONSULT','课程合成初诊咨询',30,0,0),('REVIEW','课程合成复诊核对',15,0,0),
        ('IMAGING','课程合成影像评估',45,1,0),('CARE','课程合成治疗预约',60,0,1)]:
        services.append(config('service',{'department':department,'code':'COURSE_'+code,'name':name,'duration_minutes':duration,
            'dentists':list(dentist_ids),'is_active':True,'imaging':imaging,'sterilizer':sterilizer,'other':0}))
    result.update(department=department,rooms=rooms,services=services,readiness=readiness(clinic_id))
    if not result['readiness']['unmapped_visits'] and not result['readiness']['unmapped_offers']:
        config('activate');result['enabled']=True
    else:result['enabled']=False
    return result
