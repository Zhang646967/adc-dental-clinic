"""Owned profile commands. Publication and professional authorization are distinct."""
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from django.db import connection, transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from accounts.policies import require_writable
from workspaces.context import require_active
from equipment.policies import manager_clinic
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from registry.models import Dentist
from registry.profile_models import (PublicProfile, ProfileVersion, ProfileMedia,
    DentistClinicAffiliation, ClinicProfilePolicy, ProfileAction)
from registry.profile_forms import DentistProfileForm, ClinicProfileForm, AffiliationForm

CONTRACT = 'adc.public-profile.p1'


def roster_lock(clinic_id):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s,%s)', [7118, int(clinic_id)])


def valid_affiliation(row, start, end):
    return bool(row and row.state == 'ACTIVE' and row.starts_on <= timezone.localtime(start).date()
        and (row.ends_on is None or row.ends_on >= timezone.localtime(end).date()))


def require_affiliation(clinic_id, dentist_id, start, end, *, lock=False):
    if lock:
        if not connection.in_atomic_block:
            raise RuntimeError('Roster write checks require the business transaction')
        roster_lock(clinic_id)
    if not ClinicProfilePolicy.objects.filter(clinic_id=clinic_id, roster_enforced=True).exists():
        return
    row = DentistClinicAffiliation.objects.filter(clinic_id=clinic_id, dentist_id=dentist_id).first()
    if not valid_affiliation(row, start, end):
        raise RuleError('该医师不在本店有效接诊范围，请由前台协调其他医师或时间；原预约保持。')


def owner(actor, kind, *, lock=False):
    if lock: require_writable(actor)
    if kind == 'dentist':
        require_active(actor, ('DENTIST',))
        if not actor.dentist_id:
            raise PermissionDenied('当前账号未关联医师。')
        if lock:
            Dentist.objects.select_for_update().get(pk=actor.dentist_id, is_active=True)
        return {'dentist_id': actor.dentist_id}
    if kind == 'clinic':
        clinic = manager_clinic(actor, lock=lock)
        if lock: roster_lock(clinic)
        return {'clinic_id': clinic}
    raise RuleError('画像类型无效。')


def content_values(kind, fields):
    form = (DentistProfileForm if kind == 'dentist' else ClinicProfileForm)(fields)
    if not form.is_valid():
        raise RuleError('；'.join(str(x) for errors in form.errors.values() for x in errors))
    data = form.cleaned_data
    raw = data.pop('media_ids', '')
    if isinstance(raw, str):
        try: media_ids = [int(x) for x in raw.split(',') if x.strip()]
        except ValueError as exc: raise RuleError('图片编号无效。') from exc
    else: raise RuleError('图片编号无效。')
    if len(set(media_ids)) != len(media_ids) or len(media_ids) > (1 if kind == 'dentist' else 3):
        raise RuleError('医师保留一张头像，门店最多三张图片。')
    data['media_ids'] = media_ids
    if kind == 'dentist':
        since = data['practicing_since']
        if since and (since > timezone.localdate() or since.year < 1900):
            raise RuleError('请核对从业起始日期。')
        data['practicing_since'] = since.isoformat() if since else None
        data['credential_status'] = 'UNVERIFIED'
    return data


def validate_images(profile, content):
    ids = content.get('media_ids', [])
    if ids and (profile is None or ProfileMedia.objects.filter(profile=profile, pk__in=ids).count() != len(ids)):
        raise RuleError('图片不属于当前资料，请重新选择。')


def prepare_profile(*, actor, kind, action, fields=None):
    lookup = owner(actor, kind)
    if action not in ('SAVE', 'SUBMIT', 'PUBLISH', 'WITHDRAW') or (kind == 'dentist' and action in ('PUBLISH', 'WITHDRAW')):
        raise RuleError('请通过本店主管审核医师介绍。')
    row = PublicProfile.objects.filter(**lookup).first()
    content = content_values(kind, fields) if action in ('SAVE', 'SUBMIT') else (row.draft if row else {})
    validate_images(row, content)
    if action == 'PUBLISH' and (not row or not row.submitted_version_id):
        raise RuleError('请先提交待发布版本。')
    data = {'kind':kind, 'action':action, 'owner':lookup, 'revision':row.revision if row else 0,
        'content':content, 'version':row.submitted_version_id if row else None}
    return {'data':data, 'proposal_token':proposal(actor, CONTRACT, ('DENTIST','MANAGER'), data)}


def draft_token(actor,kind):
    lookup=owner(actor,kind);row=PublicProfile.objects.filter(**lookup).first()
    return proposal(actor,CONTRACT+'.draft',('DENTIST','MANAGER'),{'kind':kind,'owner':lookup,'revision':row.revision if row else 0})


@transaction.atomic
def save_draft(*,actor,token,fields):
    """Editable draft: one submit; formal publication still reviews an exact version."""
    p=read_proposal(actor,CONTRACT+'.draft',('DENTIST','MANAGER'),token);d=p['data']
    lookup=owner(actor,d['kind'],lock=True)
    if lookup!=d['owner']:raise PermissionDenied
    previous=ProfileAction.objects.filter(operation_id=p['operation'],actor=actor).first()
    if previous:return previous.profile,True
    row,_=PublicProfile.objects.get_or_create(**lookup)
    row=PublicProfile.objects.select_for_update().get(pk=row.pk)
    if row.revision!=d['revision']:raise RuleError('草稿已有更新，请重新读取后保存。')
    content=content_values(d['kind'],fields);validate_images(row,content)
    row.draft=content;row.revision+=1;row.save()
    ProfileAction.objects.create(profile=row,clinic_id=row.clinic_id,actor=actor,action='SAVE',
        operation_id=p['operation'],snapshot={'revision':row.revision})
    emit(actor,'PUBLIC_PROFILE_CHANGED',row,summary={'action':'SAVE','revision':row.revision})
    return row,False


@transaction.atomic
def confirm_profile(*, actor, proposal_token, confirmed):
    if confirmed is not True: raise RuleError('请明确确认资料与办理动作。')
    p = read_proposal(actor, CONTRACT, ('DENTIST','MANAGER'), proposal_token); data = p['data']
    lookup = owner(actor, data['kind'], lock=True)
    if lookup != data['owner']: raise PermissionDenied
    previous = ProfileAction.objects.filter(operation_id=p['operation'], actor=actor).first()
    if previous: return previous.profile, True
    row, _ = PublicProfile.objects.get_or_create(**lookup)
    row = PublicProfile.objects.select_for_update().get(pk=row.pk)
    if row.revision != data['revision']: raise RuleError('资料已有更新，请重新核对预览。')
    action = data['action']; version = None
    if action in ('SAVE','SUBMIT'):
        fields = dict(data['content']); fields['media_ids'] = ','.join(map(str, fields['media_ids']))
        content = content_values(data['kind'], fields); validate_images(row, content)
        row.draft = content
        if action == 'SUBMIT':
            version = ProfileVersion.objects.create(profile=row, sequence=row.revision+1, content=content, submitted_by=actor)
            row.submitted_version = version
    elif action == 'PUBLISH' and data['kind'] == 'clinic':
        version = row.submitted_version
        if not version or version.pk != data['version']: raise RuleError('待发布资料已变化。')
        row.published_version = version
    elif action == 'WITHDRAW' and data['kind'] == 'clinic': row.published_version = None
    else: raise RuleError('资料动作无效。')
    row.revision += 1; row.save()
    ProfileAction.objects.create(profile=row, version=version, clinic_id=row.clinic_id, actor=actor,
        action=action, operation_id=p['operation'], snapshot={'revision':row.revision})
    emit(actor, 'PUBLIC_PROFILE_CHANGED', row, summary={'action':action, 'revision':row.revision})
    return row, False


def prepare_affiliation(*, actor, action, fields=None, affiliation_id=None):
    clinic = manager_clinic(actor)
    row = DentistClinicAffiliation.objects.filter(pk=affiliation_id, clinic_id=clinic).first() if affiliation_id else None
    data = {'clinic':clinic, 'action':action, 'id':row.pk if row else None,
        'revision':row.revision if row else 0}
    if action == 'UPSERT':
        form = AffiliationForm(fields)
        if not form.is_valid(): raise RuleError('请核对医师、接诊类型和有效日期。')
        f = form.cleaned_data
        if not Dentist.objects.filter(pk=f['dentist_id'], is_active=True).exists(): raise RuleError('医师不存在或已停用。')
        if f['ends_on'] and f['ends_on'] < f['starts_on']: raise RuleError('结束日期不能早于开始日期。')
        old = DentistClinicAffiliation.objects.filter(clinic_id=clinic, dentist_id=f['dentist_id']).first()
        if row and row.dentist_id != f['dentist_id']: raise RuleError('不能改写任职医师。')
        data.update(id=old.pk if old else None, revision=old.revision if old else 0,
            dentist=f['dentist_id'], kind=f['kind'], starts_on=f['starts_on'].isoformat(),
            ends_on=f['ends_on'].isoformat() if f['ends_on'] else None)
    elif action == 'END':
        if not row: raise RuleError('请在本店选择有效任职关系。')
    elif action == 'ACTIVATE':
        policy = ClinicProfilePolicy.objects.filter(clinic_id=clinic).first()
        data['policy_revision'] = policy.revision if policy else 0
    else: raise RuleError('任职动作无效。')
    return {'data':data, 'proposal_token':proposal(actor, CONTRACT+'.roster', ('MANAGER',), data)}


@transaction.atomic
def confirm_affiliation(*, actor, proposal_token, confirmed):
    if confirmed is not True: raise RuleError('请确认任职安排及原预约协调责任。')
    p = read_proposal(actor, CONTRACT+'.roster', ('MANAGER',), proposal_token); d = p['data']
    clinic = manager_clinic(actor, lock=True)
    if clinic != d['clinic']: raise PermissionDenied
    roster_lock(clinic)
    old = ProfileAction.objects.filter(operation_id=p['operation'], actor=actor).first()
    if old: return old.affiliation or ClinicProfilePolicy.objects.get(clinic_id=clinic), True
    row = None
    if d['action'] == 'ACTIVATE':
        from scheduling.models import AvailabilitySlot, Visit
        from coordination.models import WaitOffer
        now = timezone.now()
        spans = list(AvailabilitySlot.objects.filter(clinic_id=clinic, is_active=True, ends_at__gt=now)
            .values_list('dentist_id','starts_at','ends_at'))
        spans += list(Visit.objects.filter(clinic_id=clinic, status__in=['SCHEDULED','CHECKED_IN'], scheduled_end__gt=now)
            .values_list('dentist_id','scheduled_start','scheduled_end'))
        spans += [(x.slot.dentist_id,x.starts_at,x.ends_at) for x in WaitOffer.objects.filter(
            request__clinic_id=clinic, state='PENDING', expires_at__gt=now).select_related('slot')]
        affiliations = {x.dentist_id:x for x in DentistClinicAffiliation.objects.filter(clinic_id=clinic)}
        if any(not valid_affiliation(affiliations.get(i), a, b) for i,a,b in spans):
            raise RuleError('未来出诊、原预约或有效邀约仍有未覆盖任职，请先核对协调清单。')
        policy, _ = ClinicProfilePolicy.objects.get_or_create(clinic_id=clinic)
        if policy.revision != d['policy_revision']: raise RuleError('任职控制已有更新，请重新预览。')
        policy.roster_enforced=True; policy.revision+=1; policy.save()
        result=policy
    else:
        row = DentistClinicAffiliation.objects.select_for_update().filter(pk=d['id'], clinic_id=clinic).first()
        if (row.revision if row else 0) != d['revision']: raise RuleError('任职已有更新，请重新预览。')
        if d['action'] == 'UPSERT':
            if not row: row = DentistClinicAffiliation(clinic_id=clinic, dentist_id=d['dentist'])
            row.kind=d['kind']; row.starts_on=date.fromisoformat(d['starts_on'])
            row.ends_on=date.fromisoformat(d['ends_on']) if d['ends_on'] else None; row.state='ACTIVE'
        elif row: row.state='ENDED'; row.listing_published=False
        else: raise RuleError('本店任职关系不存在。')
        row.revision+=1; row.save(); result=row
    ProfileAction.objects.create(affiliation=row, clinic_id=clinic, actor=actor,
        action=d['action'], operation_id=p['operation'], snapshot=d)
    emit(actor,'CLINIC_ROSTER_CHANGED',result,summary={'action':d['action'],'clinic_id':clinic})
    return result, False


def prepare_review(*, actor, affiliation_id, action, version_id=None, note=''):
    clinic=manager_clinic(actor)
    row=DentistClinicAffiliation.objects.get(pk=affiliation_id,clinic_id=clinic)
    if action not in ('PUBLISH','RETURN','WITHDRAW'): raise RuleError('审核动作无效。')
    version=ProfileVersion.objects.filter(pk=version_id,profile__dentist_id=row.dentist_id).first() if version_id else None
    if action!='WITHDRAW' and not version: raise RuleError('请选择该医师的已提交版本。')
    if action=='RETURN' and not note.strip(): raise RuleError('退回时请写明需要修改的内容。')
    d={'clinic':clinic,'affiliation':row.pk,'revision':row.revision,'version':version.pk if version else None,
        'action':action,'note':note.strip()[:500],
        'profile_revision':version.profile.revision if version else None}
    return {'data':d,'proposal_token':proposal(actor,CONTRACT+'.review',('MANAGER',),d)}


@transaction.atomic
def confirm_review(*, actor, proposal_token, confirmed):
    if confirmed is not True: raise RuleError('请明确确认本次审核决定。')
    p=read_proposal(actor,CONTRACT+'.review',('MANAGER',),proposal_token); d=p['data']
    clinic=manager_clinic(actor,lock=True)
    if clinic!=d['clinic']: raise PermissionDenied
    roster_lock(clinic)
    prior=ProfileAction.objects.filter(operation_id=p['operation'],actor=actor).first()
    if prior:return prior.affiliation,True
    row=DentistClinicAffiliation.objects.select_for_update().get(pk=d['affiliation'],clinic_id=clinic)
    if row.revision!=d['revision']: raise RuleError('该医师介绍或任职已有更新，请重新审核。')
    version=ProfileVersion.objects.filter(pk=d['version'],profile__dentist_id=row.dentist_id).first()
    if version:
        profile=PublicProfile.objects.select_for_update().get(pk=version.profile_id)
        if profile.revision!=d['profile_revision']:raise RuleError('医师已更新提交资料，请重新审核当前版本。')
    if d['action']=='PUBLISH':
        if not version or row.state!='ACTIVE': raise RuleError('任职已结束或提交版本不存在。')
        if version.submitted_by_id==actor.pk: raise RuleError('本人提交的医师介绍需要另一位主管审核。')
        validate_images(version.profile,version.content)
        row.published_version=version; row.listing_published=True
    elif d['action']=='WITHDRAW': row.listing_published=False
    elif d['action']=='RETURN':
        if not version or version.submitted_by_id==actor.pk: raise RuleError('请由其他主管审核已提交资料。')
    else: raise RuleError('审核动作无效。')
    row.revision+=1;row.save()
    ProfileAction.objects.create(profile=version.profile if version else None,version=version,affiliation=row,
        clinic_id=clinic,actor=actor,action=d['action'],operation_id=p['operation'],note=d['note'],snapshot=d)
    emit(actor,'PUBLIC_PROFILE_REVIEWED',row,summary={'action':d['action'],'revision':row.revision})
    return row,False


@transaction.atomic
def upload_media(*, actor, kind, uploaded, alt_text):
    lookup=owner(actor,kind,lock=True)
    if uploaded.size>5*1024*1024: raise RuleError('图片请控制在5MiB以内。')
    try:
        raw=uploaded.read()
        with Image.open(BytesIO(raw)) as source:
            if source.format not in ('JPEG','PNG','WEBP') or source.width*source.height>25_000_000:
                raise RuleError('请使用尺寸合理的JPEG、PNG或WebP图片。')
            image=ImageOps.exif_transpose(source).convert('RGB'); image.thumbnail((1400,1400))
            out=BytesIO();image.save(out,format='JPEG',quality=82,optimize=True)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
        raise RuleError('图片无法读取，请重新导出后上传。') from exc
    payload=out.getvalue()
    if len(payload)>1024*1024: raise RuleError('图片内容过大，请缩小尺寸后上传。')
    row,_=PublicProfile.objects.get_or_create(**lookup)
    media=ProfileMedia.objects.create(profile=row,image=payload,digest=sha256(payload).hexdigest(),
        width=image.width,height=image.height,alt_text=str(alt_text).strip()[:160],uploaded_by=actor)
    return media
