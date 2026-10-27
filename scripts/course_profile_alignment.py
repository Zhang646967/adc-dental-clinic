"""P1.5 course catalogue alignment through existing reviewed business commands."""
from datetime import datetime,time,timedelta
from io import BytesIO
import colorsys
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from adc_core.rules import RuleError


def scene_image(index,scene):
    from PIL import Image,ImageDraw
    rgb=lambda h,s,v:tuple(round(x*255) for x in colorsys.hsv_to_rgb(h%1,s,v))
    hue=(index*0.061+0.36)%1
    ink=rgb(hue,.65,.40);soft=rgb(hue,.18,.89);paper=(247,249,242)
    image=Image.new('RGB',(1000,640),paper);d=ImageDraw.Draw(image)
    if scene=='portrait':
        d.ellipse((205,40,795,630),fill=soft)
        d.rounded_rectangle((295,315,705,660),radius=140,fill=ink)
        d.ellipse((386,115,614,355),fill=(227+index%15,199+index%20,169+index%25))
        d.pieslice((372,95,629,278),180,360,fill=(47+index%40,57+index%25,49+index%30))
        if index%2==0:
            for x in (412,516):d.rounded_rectangle((x,215,x+78,260),radius=12,outline=ink,width=6)
            d.line((490,230,516,230),fill=ink,width=5)
        d.polygon([(365,365),(500,455),(635,365),(573,638),(425,638)],fill=paper)
        d.line((500,460,500,620),fill=soft,width=8)
    elif scene=='front':
        d.rounded_rectangle((75,120,925,555),radius=25,fill=soft)
        d.rectangle((90,135,910,225),fill=ink);d.text((130,160),'ADC DENTAL',fill=paper,stroke_width=1)
        for x in (120,340):d.rounded_rectangle((x,270,x+175,515),radius=10,fill=paper)
        d.rounded_rectangle((590,260,860,555),radius=10,fill=ink)
        d.line((720,270,720,545),fill=soft,width=7)
        d.line((60,560,940,560),fill=ink,width=7)
    elif scene=='reception':
        d.rectangle((65,80,935,545),fill=soft)
        for x in (110,300,490):d.rounded_rectangle((x,110,x+145,320),radius=12,fill=paper)
        d.rounded_rectangle((170,340,850,570),radius=28,fill=ink)
        d.rectangle((155,330,865,365),fill=paper);d.text((210,400),'ADC',fill=paper,stroke_width=2)
        d.ellipse((725,130,865,270),fill=ink);d.rectangle((790,240,810,335),fill=ink)
    else:
        d.rounded_rectangle((50,65,950,580),radius=22,fill=soft)
        for x in (145,570):
            d.rounded_rectangle((x,170,x+165,365),radius=40,fill=ink)
            d.polygon([(x+5,340),(x+160,340),(x+205,490),(x-40,490)],fill=ink)
            d.rectangle((x+65,460,x+95,550),fill=ink)
            d.line((x+180,150,x+240,150,x+240,390),fill=paper,width=14)
            d.ellipse((x+150,120,x+210,175),fill=paper)
        d.line((65,570,935,570),fill=ink,width=6)
    output=BytesIO();image.save(output,'PNG');return output.getvalue()


def prepare_alignment(*,technical_actor,operator_password,manager,frontdesk):
    if not settings.ADC_CLINICAL_SYNTHETIC:raise RuleError('仅可更新明确标注的课程合成资料。')
    from accounts.models import UserAccount
    from accounts.governance import require_technical
    from workspaces.models import WorkspaceContext
    from registry.directory_models import ClinicDirectory
    from registry.profile_models import PublicProfile,ProfileMedia,DentistClinicAffiliation
    from registry import profile_services as ps
    from scheduling.resource_models import Department,BookingService,ServicePresentation
    from scheduling.resource_config import prepare_config,confirm_config
    from scheduling.service_content import draft_from_guide
    from scheduling.models import AvailabilitySlot
    from scheduling.slot_creation import prepare_slot_creation,confirm_slot_creation
    from clinical.models import ProfessionalAuthorization
    from clinical.authority_services import prepare_authority,confirm_authority
    require_technical(technical_actor)
    branches=list(ClinicDirectory.objects.filter(is_published=True,synthetic=True).select_related('clinic').order_by('clinic_id'))
    if len(branches)!=20:raise RuleError('请先准备并核对八城二十店P1课程资料。')
    now=timezone.now();today=timezone.localdate();result={'synthetic':True,'clinics':[],'new_services':[],'new_slots':[],'published_doctors':[]}
    def workspace(actor,role,clinic=None):
        actor.refresh_from_db();actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role=role,clinic=clinic,login_channel='STAFF')
    def config(kind,fields,target=None):
        p=prepare_config(actor=manager,kind=kind,fields=fields,target=target)
        event,_=confirm_config(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
        return event.result['id']
    # Prepare capability first, then write introductions from the actual catalogue.
    for branch in branches:
        clinic=branch.clinic;workspace(manager,'MANAGER',clinic)
        department=Department.objects.get(clinic=clinic,code='P1_CARE')
        staff=[UserAccount.objects.select_related('dentist').get(username=f'p1_c{clinic.pk:03}_doctor{n}') for n in (1,2,3)]
        desired=[('P15_RESTORE','RESTORATION','牙痛评估与基础修复预约',45,[staff[0],staff[2]],1,0)]
        if branch.city=='长沙' and '星沙' in branch.display_name:
            desired.append(('P15_CHILD','CHILDREN','儿童口腔检查与护理咨询',30,[staff[1]],0,1))
        for code,category,title,duration,doctors,imaging,sterilizer in desired:
            presentations=ServicePresentation.objects.filter(service__department=department,category=category,is_published=True)
            if presentations.exists():service=presentations.first().service
            else:
                service=BookingService.objects.filter(department=department,code=code).first()
                if service is None:
                    service=BookingService.objects.get(pk=config('service',dict(department=department.pk,code=code,name=title,
                        duration_minutes=duration,dentists=[d.dentist_id for d in doctors],is_active=True,
                        imaging=imaging,sterilizer=sterilizer,other=0)))
                    result['new_services'].append(service.pk)
                values=draft_from_guide(category);values.update(service=service.pk,title=title,
                    summary=f'{branch.display_name}的{title}，先核对需求，再说明检查与后续安排。',
                    fee_mode='ASSESSED',fee_amount=None,fee_note='预约不扣款，具体治疗与费用在到诊评估后确认。',is_published=True)
                old=ServicePresentation.objects.filter(service=service).first()
                config('service_profile',values,target=old.pk if old else None)
            for subject in doctors:
                if not service.dentists.filter(pk=subject.dentist_id).exists():continue
                if ProfessionalAuthorization.objects.filter(user=subject,clinic=clinic,service=service,state='APPROVED',valid_until__gt=now).exists():continue
                workspace(manager,'MANAGER',clinic)
                p=prepare_authority(actor=manager,action='PROPOSE',fields=dict(user_id=subject.pk,service_id=service.pk,
                    source_kind='SYNTHETIC',source_reference=f'P15-SYNTHETIC-{subject.pk}-{service.pk}',issuer='课程合成机构',
                    credential_from=now-timedelta(days=1),credential_until=now+timedelta(days=366),
                    valid_from=now-timedelta(days=1),valid_until=now+timedelta(days=365),can_read=True,can_record=True,can_refer=True))
                pending,_=confirm_authority(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
                reviewer=staff[1] if subject.pk!=staff[1].pk else staff[0];workspace(reviewer,'DENTIST')
                p=prepare_authority(actor=reviewer,action='APPROVE',case_id=pending.pk,fields={'note':'课程合成范围，独立核对，非真实专业资格。'})
                confirm_authority(actor=reviewer,proposal_token=p['proposal_token'],confirmed=True)
        workspace(frontdesk,'FRONT_DESK',clinic)
        for subject in staff:
            for offset in range(1,15):
                day=today+timedelta(days=offset);a=timezone.make_aware(datetime.combine(day,time.min));b=a+timedelta(days=1)
                if AvailabilitySlot.objects.filter(clinic=clinic,dentist_id=subject.dentist_id,is_active=True,starts_at__lt=b,ends_at__gt=a).exists():continue
                start=timezone.make_aware(datetime.combine(day,time(9)));end=timezone.make_aware(datetime.combine(day,time(17)))
                # Preserve an already published cross-clinic rotation rather than overlap it.
                if AvailabilitySlot.objects.filter(dentist_id=subject.dentist_id,is_active=True,starts_at__lt=end,ends_at__gt=start).exists():continue
                p=prepare_slot_creation(actor=frontdesk,clinic_id=clinic.pk,dentist_id=subject.dentist_id,start=start,end=end)
                slot,_=confirm_slot_creation(actor=frontdesk,proposal_token=p['proposal_token'],confirmed=True);result['new_slots'].append(slot.pk)
        result['clinics'].append(dict(clinic=clinic.pk,name=branch.display_name,base_categories=list(
            ServicePresentation.objects.filter(service__department=department,is_published=True).values_list('category',flat=True))))
    methods=('解释检查发现并逐项讨论选择','结合日常习惯制定维护建议','先梳理既往治疗再安排复核',
        '用分阶段安排降低就诊沟通负担','关注患者对时间和费用的疑问','以清楚的到诊准备说明帮助首次就诊')
    for index,branch in enumerate(branches):
        clinic=branch.clinic
        presentations=list(ServicePresentation.objects.filter(service__department__clinic=clinic,is_published=True).select_related('service'))
        special=next((p.category for p in presentations if p.category in ('ORTHODONTICS','REPLACEMENT')),None)
        for position in range(3):
            actor=UserAccount.objects.select_related('dentist').get(username=f'p1_c{clinic.pk:03}_doctor{position+1}')
            workspace(actor,'DENTIST');profile=PublicProfile.objects.select_related('submitted_version').get(dentist=actor.dentist)
            current=profile.submitted_version.content
            specialties=[['CHECKUP','RESTORATION'],['PREVENTION','CHECKUP'],['FOLLOWUP',special or 'RESTORATION']][position]
            if position==1 and any(p.category=='CHILDREN' for p in presentations):specialties.append('CHILDREN')
            focus=['综合检查与牙体问题沟通','预防护理与牙龈维护','连续复诊与'+('正畸咨询' if special=='ORTHODONTICS' else '缺牙修复沟通' if special else '治疗后复核')][position]
            method=methods[(index+position*2)%len(methods)]
            alt=actor.dentist.name+'的课程示意头像，非真人照片'
            media=ProfileMedia.objects.filter(profile=profile,alt_text=alt).first()
            if media is None:media=ps.upload_media(actor=actor,kind='dentist',uploaded=SimpleUploadedFile('portrait.png',scene_image(index*3+position,'portrait')),alt_text=alt)
            fields=dict(title=current['title'],specialties=specialties,summary=focus+'；'+method,
                biography=f'{actor.dentist.name}在{branch.city}{branch.district}参与{focus}。接诊时{method}。\n'
                    f'沟通重点包括{["不适经过、检查结果和基础修复选择","清洁习惯、牙龈状况与后续维护","既往治疗进度、复查要点与后续阶段"][position]}。'
                    '具体可预约服务按各店已发布安排展示，实际诊疗与费用在面诊后确认。\n'
                    f'到诊建议：{["整理近期不适变化和希望解决的问题","准备常用清洁方式及近期护理情况","携带可提供的既往治疗资料并说明本次复核诉求"][(index+position)%3]}。',
                practicing_since=current.get('practicing_since') or '',languages=current['languages'],
                education=f'课程合成教育与进修资料：{focus}方向，重视{method}。非真实执业学历证明。',
                credential_reference='P15-SYNTHETIC-'+actor.dentist.employee_no,media_ids=str(media.pk))
            desired=ps.content_values('dentist',fields)
            if desired!=current:
                p=ps.prepare_profile(actor=actor,kind='dentist',action='SUBMIT',fields=fields)
                profile,_=ps.confirm_profile(actor=actor,proposal_token=p['proposal_token'],confirmed=True)
            version=profile.submitted_version
            for affiliation in DentistClinicAffiliation.objects.filter(dentist=actor.dentist,state='ACTIVE',listing_published=True):
                if affiliation.published_version_id==version.pk:continue
                workspace(manager,'MANAGER',affiliation.clinic)
                p=ps.prepare_review(actor=manager,affiliation_id=affiliation.pk,action='PUBLISH',version_id=version.pk)
                ps.confirm_review(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
            result['published_doctors'].append(actor.dentist_id)
        workspace(manager,'MANAGER',clinic)
        profile=PublicProfile.objects.select_related('published_version').get(clinic=clinic)
        images=[]
        for scene,label in [('front','门头'),('reception','接待'),('room','双椅诊室')]:
            alt=branch.display_name+' · '+label+'课程示意，非实景照片'
            media=ProfileMedia.objects.filter(profile=profile,alt_text=alt).first()
            if media is None:media=ps.upload_media(actor=manager,kind='clinic',uploaded=SimpleUploadedFile(scene+'.png',scene_image(index,scene)),alt_text=alt)
            images.append(media.pk)
        old=profile.published_version.content
        positioning='家庭预防与儿童就诊' if any(p.category=='CHILDREN' for p in presentations) else '正畸咨询与连续复诊' if special=='ORTHODONTICS' else '综合检查与缺牙修复沟通' if special=='REPLACEMENT' else '基础检查与牙体健康维护'
        fields=dict(summary=f'{branch.district}的{positioning}门店，基础服务齐备，预约前可核对团队与出诊。',
            biography=f'{branch.display_name}面向{branch.city}{branch.district}的就诊需求，提供初诊检查、预防护理、牙痛评估与基础修复预约、复诊服务。'
                f'本店重点为{positioning}，接诊团队和特色服务按页面公示核对。\n'
                '诊室按两把椅位安排，影像及消毒设备统一协调。预约需同时满足服务、医师和物理资源条件；介绍和出诊公示不代表已为患者占位。',
            transport=f'先核对{branch.display_name}详情中的地址与接待入口。当前为课程合成门店，交通路线为示意；真实运营时由本店前台维护公交、地铁及入口信息。',
            parking=f'{branch.district}门店停车条件为课程待核对项，预约后可向前台确认停车点、收费及步行入口。',
            accessibility=old.get('accessibility','UNKNOWN'),accessibility_note=old.get('accessibility_note','请提前向前台说明协助需求。'),
            fee_note='预约本身不扣款。服务页说明预计时长和费用口径，实际治疗与新增项目在评估后确认；已完成就诊可由本人查看结算单。',
            media_ids=','.join(map(str,images)))
        if ps.content_values('clinic',fields)!=old:
            p=ps.prepare_profile(actor=manager,kind='clinic',action='SUBMIT',fields=fields)
            ps.confirm_profile(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
            p=ps.prepare_profile(actor=manager,kind='clinic',action='PUBLISH')
            ps.confirm_profile(actor=manager,proposal_token=p['proposal_token'],confirmed=True)
    return result


def prepare_family_sample(*,technical_actor,operator_password,frontdesk,guardian_password):
    """One synthetic verified guardian case; no automatic chart/account merge."""
    if not settings.ADC_CLINICAL_SYNTHETIC:raise RuleError('仅可准备课程合成家庭案例。')
    from django.db import transaction
    from datetime import date
    from accounts.models import UserAccount,RoleAssignment
    from accounts.governance import require_technical,create_account,change_account,target_token
    from registry.directory_models import ClinicDirectory
    from patients.services import create_patient
    from portal.models import PatientRelationship,PatientAppointmentGrant
    from portal import relationships as rel
    from workspaces.models import WorkspaceContext
    require_technical(technical_actor)
    branch=ClinicDirectory.objects.get(city='长沙',display_name__contains='星沙',synthetic=True,is_published=True)
    existing=PatientRelationship.objects.filter(clinic=branch.clinic,delegate_user__username='p15_guardian').first()
    if existing:
        return dict(patient=existing.patient_id,relationship=existing.pk,
            active=PatientAppointmentGrant.objects.filter(relationship=existing,is_active=True,valid_until__gt=timezone.now()).exists(),created=False)
    with transaction.atomic():
        guardian=create_account(actor=technical_actor,username='p15_guardian',password=guardian_password,
            operator_password=operator_password,reason='P1.5课程合成监护代约账号，不绑定本人病历')
        grant=RoleAssignment.objects.get(user=frontdesk,clinic=branch.clinic,role='FRONT_DESK',is_active=True)
        if not grant.can_verify_patient_relationships:
            change_account(actor=technical_actor,target_id=frontdesk.pk,token=target_token(technical_actor,frontdesk),
                action='identity_reviewer',grant_id=grant.pk,reviewer_enabled=True,operator_password=operator_password,
                reason='P1.5星沙课程监护关系核验职责')
        frontdesk._adc_workspace=WorkspaceContext.objects.create(user=frontdesk,role='FRONT_DESK',clinic=branch.clinic,login_channel='STAFF')
        child=create_patient(actor=frontdesk,clinic_id=branch.clinic_id,details=dict(name='课程儿童·星沙',date_of_birth=date(2018,5,16),
            billing_address='课程合成家庭地址，非真实住址',phone='00000004101',email='',emergency_name='课程监护人',emergency_phone='00000004102'),
            allergy_status='UNKNOWN')
        token=rel.prepare_create(actor=frontdesk,patient_no=child.patient_no,related_name='课程监护人',kind='PARENT',
            username=guardian.username,note='课程合成家庭关系受理，非真实身份依据')
        case,_=rel.confirm(actor=frontdesk,token=token,confirmed=True)
        token=rel.prepare_action(actor=frontdesk,case_id=case.pk,action='VERIFY',basis='GUARDIAN_CONFIRMED',
            reference='P15-SYNTHETIC-GUARDIAN-XINGSHA',note='已由前台核对课程合成监护依据，仅授予本店预约代办',
            valid_until=timezone.now()+timedelta(days=30))
        rel.confirm(actor=frontdesk,token=token,confirmed=True)
    return dict(patient=child.pk,relationship=case.pk,active=True,created=True)
