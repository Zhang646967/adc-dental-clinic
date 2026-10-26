"""Explicit P1 synthetic preparation through owned business commands.

Never reset an existing password, rewrite old visits or invent historical care.
Credentials are supplied by the private operator, never returned in the manifest.
"""
from datetime import date,datetime,time,timedelta
from io import BytesIO
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from adc_core.rules import RuleError

SURNAMES=('陈','林','许','沈','顾','周','叶','陆','江','程','宋','苏','何','孟','白','唐','温','钟','黎','郭')
PERSONAS=(
    ('知远','综合评估与方案沟通','从口腔检查出发，解释检查发现，与患者共同确定下一步就诊安排。',('CHECKUP','RESTORATION')),
    ('沐青','预防护理与牙周维护','关注日常清洁和牙龈状况，帮助患者建立可持续的口腔维护习惯。',('PREVENTION','CHECKUP')),
    ('书宁','连续复诊与疗程复核','重视治疗前后的解释与复查，围绕既定方案协调分阶段就诊。',('FOLLOWUP','ORTHODONTICS')),
)


def illustration(kind,index):
    """Original geometric pictograms, not photographs or real-person likenesses."""
    from PIL import Image,ImageDraw
    palettes=[('#e8eee4','#426653','#c1d1bf'),('#eae6db','#71614c','#d2c5ac'),('#e3ecee','#47616c','#b9ccd2')]
    background,ink,soft=palettes[index%3]
    image=Image.new('RGB',(700,700) if kind=='doctor' else (1100,660),background);d=ImageDraw.Draw(image)
    if kind=='doctor':
        d.ellipse((170,115,530,475),fill=soft);d.ellipse((255,155,445,345),fill=ink)
        d.rounded_rectangle((165,350,535,645),radius=140,fill=ink)
        d.polygon([(250,370),(350,460),(450,370),(400,645),(300,645)],fill='#fbfcf8')
        d.line((345,470,345,625),fill=soft,width=7)
    else:
        d.rounded_rectangle((70,110,1030,570),radius=30,fill='#fbfcf8')
        d.rectangle((100,155,1000,210),fill=ink)
        for x in (130,360,590):d.rounded_rectangle((x,260,x+170,495),radius=8,fill=soft)
        d.rounded_rectangle((825,265,950,570),radius=10,fill=ink)
        d.line((70,570,1030,570),fill=ink,width=8)
        d.ellipse((20,415,155,550),fill=soft);d.rectangle((75,525,100,610),fill=ink)
    out=BytesIO();image.save(out,'PNG');return out.getvalue()


def prepare_profiles(*,technical_actor,operator_password,manager,frontdesk,passwords,reviewer=None):
    if not settings.ADC_CLINICAL_SYNTHETIC:raise RuleError('课程画像仅可准备在明确的合成实例中。')
    from accounts.models import UserAccount,RoleAssignment
    from accounts.governance import require_technical,create_account,change_account,target_token
    from registry.models import Dentist
    from registry.directory_models import ClinicDirectory
    from registry.directory_services import prepare_registration,confirm_directory_change
    from registry.profile_models import PublicProfile,DentistClinicAffiliation,ClinicProfilePolicy
    from registry import profile_services as profiles
    from scheduling.resource_models import ResourcePolicy,Department,DepartmentHours,TreatmentRoom,BookingService,ServicePresentation,ResourceBinding
    from scheduling.resource_config import prepare_config,confirm_config
    from scheduling.slot_creation import prepare_slot_creation,confirm_slot_creation
    from scheduling.models import AvailabilitySlot
    from scheduling.service_content import draft_from_guide
    from equipment.models import EquipmentAsset
    from equipment.services import prepare_registration as asset_preview,confirm_equipment
    from workspaces.models import WorkspaceContext
    require_technical(technical_actor)
    branches=list(ClinicDirectory.objects.filter(is_published=True,synthetic=True).select_related('clinic').order_by('clinic_id'))
    if len(branches)!=20:raise RuleError('请先核对已准备的八城二十店目录，本工具不推断或更换原门店。')
    now=timezone.now();today=timezone.localdate();result={'synthetic':True,'clinics':[],'new_accounts':[],'new_dentists':[]}
    def workspace(actor,role,clinic=None):
        actor.refresh_from_db();actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role=role,clinic=clinic,login_channel='STAFF')
    def grant(actor,role,clinic=None):
        if RoleAssignment.objects.filter(user=actor,role=role,clinic=clinic,is_active=True).exists():return
        change_account(actor=technical_actor,target_id=actor.pk,token=target_token(technical_actor,actor),action='grant',
            operator_password=operator_password,reason='P1课程合成门店职责准备',role=role,clinic_id=clinic.pk if clinic else None)
    def config(kind,fields=None,target=None):
        p=prepare_config(actor=manager,kind=kind,fields=fields,target=target)
        event,_=confirm_config(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        return event.result.get('id')
    for index,branch in enumerate(branches):
        clinic=branch.clinic;grant(manager,'MANAGER',clinic);grant(frontdesk,'FRONT_DESK',clinic)
        workspace(manager,'MANAGER',clinic)
        staff=[]
        for position,(given,focus,summary,specialties) in enumerate(PERSONAS):
            code=f'P1-C{clinic.pk:03}-D{position+1}'
            dentist=Dentist.objects.filter(employee_no=code).first()
            if not dentist:
                p=prepare_registration(actor=technical_actor,kind='dentist',reason_code='SOURCE_RECORD',details=dict(
                    employee_no=code,name=SURNAMES[index]+given,date_of_birth=f'{1980+index%10}-06-01',
                    home_address='P1课程合成员工档案，非真实住址',phone='000-0000-'+f'{3000+index*3+position}',
                    email=code.lower()+'@example.invalid'))
                event=confirm_directory_change(actor=technical_actor,proposal_token=p.proposal_token,operator_password=operator_password,confirmed=True)
                dentist=Dentist.objects.get(pk=event.object_id);result['new_dentists'].append(dentist.pk)
            username=f'p1_c{clinic.pk:03}_doctor{position+1}'
            actor=UserAccount.objects.filter(username=username).first()
            if not actor:
                actor=create_account(actor=technical_actor,username=username,password=passwords[username],operator_password=operator_password,
                    dentist_id=dentist.pk,reason='P1课程合成医师试用账号，非真实专业资格')
                result['new_accounts'].append(actor.pk)
            if actor.dentist_id!=dentist.pk or not actor.is_active:raise RuleError('已有课程账号与人员不符或已停用，请人工核对。')
            grant(actor,'DENTIST');staff.append((actor,dentist,position,focus,summary,specialties))
        # Explicitly cover previously published shifts as well as the new roster.
        old_ids=set(AvailabilitySlot.objects.filter(clinic=clinic,is_active=True,ends_at__gt=now).values_list('dentist_id',flat=True))
        for dentist_id in sorted(old_ids|{s[1].pk for s in staff}):
            if not DentistClinicAffiliation.objects.filter(clinic=clinic,dentist_id=dentist_id,state='ACTIVE').exists():
                p=profiles.prepare_affiliation(actor=manager,action='UPSERT',fields=dict(dentist_id=dentist_id,kind='RESIDENT',starts_on=today.isoformat(),ends_on=''))
                profiles.confirm_affiliation(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        if not ResourcePolicy.objects.filter(clinic=clinic).exists():config('start')
        department=Department.objects.filter(clinic=clinic,code='P1_CARE').first()
        if not department:department=Department.objects.get(pk=config('department',dict(code='P1_CARE',name='综合口腔与连续照护',is_active=True)))
        closes='19:00' if index%3==1 else '17:30'
        for weekday in range(7):
            if not DepartmentHours.objects.filter(department=department,weekday=weekday).exists():
                config('hours',dict(department=department.pk,weekday=weekday,opens_at='09:00',closes_at=closes))
        room=TreatmentRoom.objects.filter(department=department,code='P1_ROOM').first()
        if not room:room=TreatmentRoom.objects.get(pk=config('room',dict(department=department.pk,code='P1_ROOM',name='双椅综合诊室',is_active=True)))
        for number,category in [(1,'CHAIR'),(2,'CHAIR'),(3,'IMAGING'),(4,'STERILIZER')]:
            code=f'P1-C{clinic.pk:03}-A{number}'
            asset=EquipmentAsset.objects.filter(asset_code=code).first()
            if not asset:
                p=asset_preview(actor=manager,asset_code=code,name={'CHAIR':'综合牙椅','IMAGING':'共享影像设备','STERILIZER':'消毒设备'}[category]+str(number),
                    category=category,location='课程合成双椅诊室' if category=='CHAIR' else '课程合成共享设备区',acquired_on=today,
                    acquisition_cost=None,next_service_due=None,note='P1课程合成资源，未发生采购或资金事实')
                asset,_=confirm_equipment(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
            if not ResourceBinding.objects.filter(asset=asset,is_active=True).exists():config('binding',dict(asset=asset.pk,
                room=room.pk if category=='CHAIR' else '',shared=category!='CHAIR',is_active=True))
        specialty=('RESTORATION','ORTHODONTICS','REPLACEMENT')[index%3]
        specialty_title={'RESTORATION':'牙体修复与牙痛评估','ORTHODONTICS':'牙齿排列与矫正咨询','REPLACEMENT':'缺牙修复方案沟通'}[specialty]
        service_defs=[('CHECK','CHECKUP','初诊检查与方案沟通',30,0,0),('PREVENT','PREVENTION','牙龈评估与洁治预约',60,0,1),
            ('REVIEW','FOLLOWUP','复诊与疗程复核',15,0,0),('SPECIAL',specialty,specialty_title,45,1,0)]
        services=[]
        for suffix,category,title,duration,imaging,sterilizer in service_defs:
            service=BookingService.objects.filter(department=department,code='P1_'+suffix).first()
            if not service:
                service=BookingService.objects.get(pk=config('service',dict(department=department.pk,code='P1_'+suffix,name=title,
                    duration_minutes=duration,dentists=[s[1].pk for s in staff],is_active=True,imaging=imaging,sterilizer=sterilizer,other=0)))
            services.append((service,category,title))
        policy=ResourcePolicy.objects.get(clinic=clinic)
        if policy.state=='PREPARING':config('activate')
        for service,category,title in services:
            if not ServicePresentation.objects.filter(service=service,is_published=True).exists():
                values=draft_from_guide(category);values.update(service=service.pk,title=title,
                    summary=f'{branch.city}{branch.district}的{title}，由本店接诊团队核对需求与后续安排。',
                    fee_mode='ASSESSED',fee_amount=None,fee_note='预约不扣款；完成评估后说明具体项目与费用，经确认后办理。',is_published=True)
                old=ServicePresentation.objects.filter(service=service).first();config('service_profile',values,target=old.pk if old else None)
        from clinical.models import ClinicalReviewerAppointment,ProfessionalAuthorization
        from clinical.authority_services import prepare_authority,confirm_authority
        for reviewer_actor in (staff[0][0],staff[1][0]):
            if not ClinicalReviewerAppointment.objects.filter(user=reviewer_actor,clinic=clinic,is_active=True,valid_until__gt=now).exists():
                change_account(actor=technical_actor,target_id=reviewer_actor.pk,token=target_token(technical_actor,reviewer_actor),
                    action='clinical_reviewer',operator_password=operator_password,reason='P1课程合成独立专业审核职责',clinic_id=clinic.pk,
                    reviewer_enabled=True,reviewer_reference='P1-SYNTHETIC-REVIEWER',reviewer_from=now-timedelta(days=1),reviewer_until=now+timedelta(days=365))
        for subject,*_ in staff:
            for service,_,_ in services:
                if ProfessionalAuthorization.objects.filter(user=subject,clinic=clinic,service=service,state='APPROVED',valid_until__gt=now).exists():continue
                workspace(manager,'MANAGER',clinic)
                pending=ProfessionalAuthorization.objects.filter(user=subject,clinic=clinic,service=service,state='PENDING').first()
                if not pending:
                    p=prepare_authority(actor=manager,action='PROPOSE',fields=dict(user_id=subject.pk,service_id=service.pk,
                        source_kind='SYNTHETIC',source_reference='P1-SYNTHETIC-'+str(subject.pk)+'-'+str(service.pk),issuer='课程合成机构',
                        credential_from=now-timedelta(days=1),credential_until=now+timedelta(days=366),
                        valid_from=now-timedelta(days=1),valid_until=now+timedelta(days=365),can_read=True,can_record=True,can_refer=True))
                    pending,_=confirm_authority(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
                reviewer_actor=staff[1][0] if subject.pk==staff[0][0].pk else staff[0][0]
                workspace(reviewer_actor,'DENTIST')
                p=prepare_authority(actor=reviewer_actor,action='APPROVE',case_id=pending.pk,
                    fields={'note':'仅课程合成资料的独立范围核对，不代表真实专业资格审核。'})
                confirm_authority(actor=reviewer_actor,proposal_token=p['proposal_token'],confirmed=True)
        for actor,dentist,position,focus,summary,specialties in staff:
            workspace(actor,'DENTIST')
            if not PublicProfile.objects.filter(dentist=dentist,submitted_version__isnull=False).exists():
                image=profiles.upload_media(actor=actor,kind='dentist',uploaded=SimpleUploadedFile('profile.png',illustration('doctor',index+position)),
                    alt_text='课程合成医师示意头像，非真人照片')
                p=profiles.prepare_profile(actor=actor,kind='dentist',action='SUBMIT',fields=dict(title='主治医师' if position!=1 else '医师',
                    specialties=list(specialties),summary=focus+'，重视解释与复查',biography=summary+'在本店提供已配置的预约服务，具体诊疗方案以到诊后评估为准。',
                    practicing_since=f'{2004+index%10}-07-01',languages='普通话、英语' if index%3==0 else '普通话',
                    education='课程合成教育与进修资料，仅用于业务流程试用。',credential_reference='P1-SYNTHETIC-'+dentist.employee_no,media_ids=str(image.pk)))
                profiles.confirm_profile(actor=actor,proposal_token=p['proposal_token'],confirmed=True)
            workspace(manager,'MANAGER',clinic)
            a=DentistClinicAffiliation.objects.get(clinic=clinic,dentist=dentist)
            if not a.listing_published:
                version=PublicProfile.objects.get(dentist=dentist).submitted_version
                p=profiles.prepare_review(actor=manager,affiliation_id=a.pk,action='PUBLISH',version_id=version.pk)
                profiles.confirm_review(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
            workspace(frontdesk,'FRONT_DESK',clinic)
            for delta in range(1,15):
                day=today+timedelta(days=delta)
                start=timezone.make_aware(datetime.combine(day,time(9)));end=timezone.make_aware(datetime.combine(day,time(17)))
                if AvailabilitySlot.objects.filter(dentist=dentist,is_active=True,starts_at__lt=end,ends_at__gt=start).exists():continue
                p=prepare_slot_creation(actor=frontdesk,clinic_id=clinic.pk,dentist_id=dentist.pk,start=start,end=end)
                confirm_slot_creation(actor=frontdesk,proposal_token=p['proposal_token'],confirmed=True)
        workspace(manager,'MANAGER',clinic)
        if not PublicProfile.objects.filter(clinic=clinic,published_version__isnull=False).exists():
            image=profiles.upload_media(actor=manager,kind='clinic',uploaded=SimpleUploadedFile('clinic.png',illustration('clinic',index)),
                alt_text=f'{branch.display_name}课程合成门店示意图，非实景照片')
            label=('家庭综合照护','城市复诊与预防','方案沟通与连续复查')[index%3]
            p=profiles.prepare_profile(actor=manager,kind='clinic',action='SUBMIT',fields=dict(summary=f'{label}，就近安排检查、护理与复查。',
                biography=f'{branch.display_name}位于{branch.city}{branch.district}服务片区，围绕{label}提供预约服务。前台协调医师与椅位，医师解释检查与治疗安排，费用经实际评估另行确认。',
                transport=f'按{branch.entrance}到诊；当前交通及门址为课程示意，非真实营业地点。',parking='停车条件由前台在到诊前核对；课程示意资料。',
                accessibility='YES' if index%3!=2 else 'UNKNOWN',accessibility_note='请在预约时说明行动协助需求，前台提前核对。',
                fee_note='服务页面说明预计时长与包含范围；预约本身不产生治疗或扣款，新增项目另行确认。',media_ids=str(image.pk)))
            profiles.confirm_profile(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
            p=profiles.prepare_profile(actor=manager,kind='clinic',action='PUBLISH')
            profiles.confirm_profile(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        if not ClinicProfilePolicy.objects.filter(clinic=clinic,roster_enforced=True).exists():
            p=profiles.prepare_affiliation(actor=manager,action='ACTIVATE')
            profiles.confirm_affiliation(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        result['clinics'].append(dict(clinic=clinic.pk,city=branch.city,doctors=[s[1].pk for s in staff],
            services=[s[0].pk for s in services],chairs=2,prepared_days=14))
    # A bounded, explicit Changsha rotation. Existing protected promises are not changed.
    changsha=[b for b in branches if b.city=='长沙']
    if len(changsha)>=2:
        source,destination=changsha[:2];visitor=UserAccount.objects.get(username=f'p1_c{source.clinic_id:03}_doctor3')
        workspace(manager,'MANAGER',destination.clinic)
        a=DentistClinicAffiliation.objects.filter(clinic=destination.clinic,dentist_id=visitor.dentist_id).first()
        if not a:
            p=profiles.prepare_affiliation(actor=manager,action='UPSERT',fields=dict(dentist_id=visitor.dentist_id,
                kind='VISITING',starts_on=today.isoformat(),ends_on=''))
            a,_=profiles.confirm_affiliation(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        if not a.listing_published:
            p=profiles.prepare_review(actor=manager,affiliation_id=a.pk,action='PUBLISH',
                version_id=PublicProfile.objects.get(dentist_id=visitor.dentist_id).submitted_version_id)
            profiles.confirm_review(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        target_services=BookingService.objects.filter(department__clinic=destination.clinic,code__startswith='P1_')
        for service in target_services:
            if not service.dentists.filter(pk=visitor.dentist_id).exists():
                required={r.category:r.quantity for r in service.requirements.all()}
                config('service',dict(department=service.department_id,code=service.code,name=service.name,
                    duration_minutes=service.duration_minutes,dentists=list(service.dentists.values_list('pk',flat=True))+[visitor.dentist_id],
                    is_active=True,imaging=required.get('IMAGING',0),sterilizer=required.get('STERILIZER',0),other=required.get('OTHER',0)),target=service.pk)
            if not ProfessionalAuthorization.objects.filter(user=visitor,clinic=destination.clinic,service=service,state='APPROVED',valid_until__gt=now).exists():
                workspace(manager,'MANAGER',destination.clinic)
                p=prepare_authority(actor=manager,action='PROPOSE',fields=dict(user_id=visitor.pk,service_id=service.pk,
                    source_kind='SYNTHETIC',source_reference='P1-SYNTHETIC-ROTATION-'+str(service.pk),issuer='课程合成机构',
                    credential_from=now-timedelta(days=1),credential_until=now+timedelta(days=366),
                    valid_from=now-timedelta(days=1),valid_until=now+timedelta(days=365),can_read=True,can_record=True,can_refer=True))
                pending,_=confirm_authority(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
                receiver=UserAccount.objects.get(username=f'p1_c{destination.clinic_id:03}_doctor1');workspace(receiver,'DENTIST')
                p=prepare_authority(actor=receiver,action='APPROVE',case_id=pending.pk,fields={'note':'课程合成轮诊范围，独立核对。'})
                confirm_authority(actor=receiver,proposal_token=p['proposal_token'],confirmed=True)
        from scheduling.availability_services import inspect_availability,prepare_availability_change,confirm_availability_change
        rotation=[]
        for delta in (2,4,6,8,10,12,14):
            day=today+timedelta(days=delta)
            start=timezone.make_aware(datetime.combine(day,time(9)));noon=timezone.make_aware(datetime.combine(day,time(12)))
            afternoon=timezone.make_aware(datetime.combine(day,time(13)));end=timezone.make_aware(datetime.combine(day,time(17)))
            if AvailabilitySlot.objects.filter(clinic=destination.clinic,dentist_id=visitor.dentist_id,is_active=True,starts_at=afternoon,ends_at=end).exists():continue
            slot=AvailabilitySlot.objects.filter(clinic=source.clinic,dentist_id=visitor.dentist_id,is_active=True,starts_at=start,ends_at=end).first()
            if not slot:continue
            workspace(frontdesk,'FRONT_DESK',source.clinic)
            snapshot,token=inspect_availability(actor=frontdesk,slot_id=slot.pk)
            if snapshot.blocked:continue
            p=prepare_availability_change(actor=frontdesk,slot_id=slot.pk,state_token=token,action='replace',
                reason_code='PLAN_CHANGED',start=start,end=noon)
            confirm_availability_change(actor=frontdesk,slot_id=slot.pk,proposal_token=p.proposal_token,confirmed=True)
            workspace(frontdesk,'FRONT_DESK',destination.clinic)
            p=prepare_slot_creation(actor=frontdesk,clinic_id=destination.clinic_id,dentist_id=visitor.dentist_id,start=afternoon,end=end)
            rotated,_=confirm_slot_creation(actor=frontdesk,proposal_token=p['proposal_token'],confirmed=True);rotation.append(rotated.pk)
        result['rotation']=dict(dentist=visitor.dentist_id,source=source.clinic_id,destination=destination.clinic_id,slots=rotation)
    return result
