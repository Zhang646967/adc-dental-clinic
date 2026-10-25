"""Explicit synthetic branch preparation; all business effects use owned commands.

An operator supplies existing accounts, two explicitly selected original clinics,
and four dentists. No account passwords, real addresses or map credentials are
embedded. Existing clinic identity, money, patients and appointment promises are
retained. Directory-only branches deliberately have no bookable services.
"""
import os
from datetime import datetime,time,timedelta
from django.utils import timezone
from adc_core.rules import RuleError

# Approximate district centres are synthetic sorting points, not operating sites.
BRANCHES=(
 ('CS_WY','湖南省','长沙','芙蓉区','五一广场',28.194000,112.976000),
 ('CS_MX','湖南省','长沙','岳麓区','梅溪湖',28.180000,112.900000),
 ('CS_YH','湖南省','长沙','雨花区','雨花',28.137000,113.034000),
 ('CS_XS','湖南省','长沙','长沙县','星沙',28.238000,113.084000),
 ('WH_GG','湖北省','武汉','洪山区','光谷',30.500000,114.410000),
 ('WH_HK','湖北省','武汉','江汉区','汉口',30.600000,114.270000),
 ('WH_ZN','湖北省','武汉','武昌区','中南',30.540000,114.330000),
 ('CD_TF','四川省','成都','武侯区','天府',30.590000,104.060000),
 ('CD_JS','四川省','成都','成华区','建设路',30.670000,104.110000),
 ('CD_JX','四川省','成都','青羊区','金沙',30.680000,104.010000),
 ('GZ_TH','广东省','广州','天河区','天河',23.130000,113.330000),
 ('GZ_YX','广东省','广州','越秀区','越秀',23.140000,113.270000),
 ('GZ_PY','广东省','广州','番禺区','番禺',22.940000,113.380000),
 ('HZ_WL','浙江省','杭州','拱墅区','武林',30.280000,120.160000),
 ('HZ_BJ','浙江省','杭州','滨江区','滨江',30.210000,120.210000),
 ('NJ_XJ','江苏省','南京','秦淮区','新街口',32.040000,118.780000),
 ('NJ_HX','江苏省','南京','建邺区','河西',32.000000,118.720000),
 ('XA_GX','陕西省','西安','雁塔区','高新',34.210000,108.870000),
 ('XA_JK','陕西省','西安','未央区','经开',34.340000,108.940000),
 ('ZZ_ZD','河南省','郑州','金水区','郑东',34.770000,113.740000),
)


def prepare_network(*,technical_actor,operator_password,manager,frontdesk,
                    existing_clinic_ids,dentist_ids,first_day=None):
    """Explicit one-time preparation; each owned command commits its own effect.

    A stopped preparation retains its audited progress for normal UI completion.
    It is not a whole-network transaction and never retries by overwriting rows.
    """
    from accounts.governance import change_account,target_token,require_technical
    from accounts.models import RoleAssignment
    from registry.models import Clinic,Dentist
    from registry.directory_models import ClinicDirectory
    from registry.directory_services import prepare_registration,confirm_directory_change
    from registry.branch_services import prepare_directory,confirm_directory
    from scheduling.resource_config import prepare_config,confirm_config
    from scheduling.resource_models import ResourcePolicy,BookingService
    from scheduling.models import AvailabilitySlot
    from scheduling.slot_creation import prepare_slot_creation,confirm_slot_creation
    from scripts.course_resources import prepare_clinic
    from workspaces.models import WorkspaceContext
    if os.environ.get('ADC_RC_SYNTHETIC')!='1':
        raise RuleError('仅允许明确标记的合成实例准备课程门店。')
    require_technical(technical_actor)
    if len(existing_clinic_ids)!=2 or len(set(existing_clinic_ids))!=2:
        raise RuleError('请明确选择两家原有诊所；不推断或覆盖其他诊所。')
    if len(dentist_ids)!=4 or len(set(dentist_ids))!=4:
        raise RuleError('四家可预约门店须分别提供四名已登记的有效医师。')
    if Clinic.objects.filter(pk__in=existing_clinic_ids,is_active=True).count()!=2 or Dentist.objects.filter(pk__in=dentist_ids,is_active=True).count()!=4:
        raise RuleError('选定诊所或医师已失效。')
    if Clinic.objects.filter(clinic_code__startswith='COURSE_NET_').exists() or ClinicDirectory.objects.exists():
        raise RuleError('已有门店准备记录，请使用正常维护入口继续，不能批量覆盖。')
    first_day=first_day or timezone.localdate()+timedelta(days=1)
    if first_day<=timezone.localdate():raise RuleError('出诊起始日须位于未来。')
    result=[]
    def workspace(user,role,clinic):
        user._adc_workspace=WorkspaceContext.objects.create(user=user,role=role,clinic_id=clinic,login_channel='STAFF')
    def grant(user,role,clinic):
        if not RoleAssignment.objects.filter(user=user,role=role,clinic_id=clinic,is_active=True).exists():
            change_account(actor=technical_actor,target_id=user.pk,token=target_token(technical_actor,user),
                action='grant',role=role,clinic_id=clinic,operator_password=operator_password,
                reason='课程合成门店网络：明确配置本店运营职责')
    for index,(code,province,city,district,area,lat,lon) in enumerate(BRANCHES):
        name=f'ADC口腔·{city}{area}门店'
        address=f'{province}{city}市{district}{area}合成口腔中心{index+1:02d}号（课程虚构门址）'
        phone='000-0000-'+str(1000+index)
        if index<2:clinic=Clinic.objects.get(pk=existing_clinic_ids[index])
        else:
            p=prepare_registration(actor=technical_actor,kind='clinic',reason_code='SOURCE_RECORD',
                details=dict(clinic_code='COURSE_NET_'+code,name=name,postal_address=address,
                    supervisor_name='合成门店负责人',phone=phone,email=code.lower()+'@example.invalid',area_sqm='200.00'))
            action=confirm_directory_change(actor=technical_actor,proposal_token=p.proposal_token,
                operator_password=operator_password,confirmed=True)
            clinic=Clinic.objects.get(pk=action.object_id)
        grant(manager,'MANAGER',clinic.pk);workspace(manager,'MANAGER',clinic.pk)
        def config(kind,fields=None):
            p=prepare_config(actor=manager,kind=kind,fields=fields)
            action,_=confirm_config(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
            return action.result.get('id')
        if index<4:
            if not ResourcePolicy.objects.filter(clinic=clinic).exists():
                prepare_clinic(actor=manager,clinic_id=clinic.pk,dentist_ids=[dentist_ids[index]])
            services=BookingService.objects.filter(department__clinic=clinic,is_active=True,department__is_active=True,
                dentists__pk=dentist_ids[index]).distinct()
            if not services.exists():raise RuleError('选定医师尚未适配本店服务，请先核对原配置。')
            for service in services:
                title={15:'复诊核对',30:'初诊咨询',45:'影像评估',60:'治疗预约'}.get(service.duration_minutes,service.name)
                config('service_profile',dict(service=service.pk,category='OTHER',title=title,
                    summary='核对就诊需要与适合的诊疗安排',suitable_for='希望了解本店服务或按既有指示安排复诊的患者',
                    visit_content='医师核对实际需要；预约意向不构成诊断或治疗完成',
                    limitations='具体项目与费用经实际评估另行确认；本实例仅使用合成资料',
                    preparation='准备已有就诊资料，按预约起止时间到店',fee_mode='ASSESSED',fee_amount=None,
                    fee_note='实际项目另行核对，预约本身不产生收费',is_published=True))
            grant(frontdesk,'FRONT_DESK',clinic.pk);workspace(frontdesk,'FRONT_DESK',clinic.pk)
            for delta in range(14):
                day=first_day+timedelta(days=delta)
                start=timezone.make_aware(datetime.combine(day,time(9)));end=timezone.make_aware(datetime.combine(day,time(17)))
                overlapping=AvailabilitySlot.objects.filter(dentist_id=dentist_ids[index],is_active=True,starts_at__lt=end,ends_at__gt=start)
                if overlapping.exists():continue # Retain all existing commitments and shifts.
                p=prepare_slot_creation(actor=frontdesk,clinic_id=clinic.pk,dentist_id=dentist_ids[index],start=start,end=end)
                confirm_slot_creation(actor=frontdesk,proposal_token=p['proposal_token'],confirmed=True)
        else:
            config('start')
            department=config('department',dict(code='COURSE_GENERAL',name='综合科',is_active=True))
            for weekday in range(7):config('hours',dict(department=department,weekday=weekday,opens_at='09:00',closes_at='17:00'))
        workspace(manager,'MANAGER',clinic.pk)
        p=prepare_directory(actor=manager,fields=dict(display_name=name,province=province,city=city,district=district,
            address=address,entrance='合成口腔中心二层接待处；非真实经营门址',public_phone=phone,
            latitude=str(lat),longitude=str(lon),map_latitude=None,map_longitude=None,
            coordinate_source='课程合成区域近似点，WGS84；不用于真实导航或距离承诺',synthetic=True,is_published=True))
        row,_=confirm_directory(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        result.append(dict(clinic=clinic.pk,code=code,city=city,name=name,profile_revision=row.revision,
            resource_mode=ResourcePolicy.objects.get(clinic=clinic).state,booking_configuration_prepared=index<4))
    return result
