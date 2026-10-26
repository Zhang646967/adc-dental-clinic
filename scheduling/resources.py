"""Single physical-resource admission contract for bookings, offers and check-in.

Lock order: availability slots; patient/dentist advisory locks; equipment rows in
primary-key order. Equipment maintenance uses the same equipment row lock.
Queries are observations. Only claim_locked creates a promise in a transaction.
"""
from collections import defaultdict
from datetime import timedelta
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from adc_core.rules import RuleError
from equipment.models import EquipmentAsset
from scheduling.resource_models import (ResourcePolicy, BookingService, ResourceBinding,
    DepartmentHours, ResourceBlock, ResourceClaim, ResourcePlan, ResourceCoordination)


def policy(clinic_id):
    return ResourcePolicy.objects.filter(clinic_id=clinic_id).first()


def enabled(clinic_id):
    row = policy(clinic_id)
    return row is not None and row.state == 'ENABLED'


def lock_physical(clinic_id):
    if not connection.in_atomic_block:
        raise RuntimeError('Physical-resource locks require a transaction')
    # Bounded course deployment; a clinic has a small asset directory. Keeping
    # selection and maintenance on the same ordered rows also prevents phantoms
    # between choosing a shared device and recording its claim.
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s,%s)', [7103, int(clinic_id)])
    return list(EquipmentAsset.objects.select_for_update().filter(clinic_id=clinic_id).order_by('pk'))


def release_expired_locked(clinic_id):
    now = timezone.now()
    ResourceClaim.objects.filter(asset__clinic_id=clinic_id, active=True, kind='HOLD', expires_at__lte=now).update(
        active=False, released_at=now, release_reason='HOLD_EXPIRED')


class ResourceCalendar:
    """Read a bounded clinic interval once; enumerate stable resource bundles."""
    def __init__(self, clinic_id, start, end, *, ignore_visit=None, ignore_offer=None, preparing=False):
        self.clinic_id = clinic_id
        self.policy = policy(clinic_id)
        self.ready = self.policy is not None and (self.policy.state == 'ENABLED' or preparing)
        self.bindings = list(ResourceBinding.objects.filter(asset__clinic_id=clinic_id,
            is_active=True).select_related('asset', 'room__department').order_by('asset_id'))
        self.hours = defaultdict(list)
        for h in DepartmentHours.objects.filter(department__clinic_id=clinic_id):
            self.hours[h.department_id, h.weekday].append((h.opens_at, h.closes_at))
        self.blocks = list(ResourceBlock.objects.filter(clinic_id=clinic_id, is_active=True,
            starts_at__lt=end, ends_at__gt=start))
        claims = ResourceClaim.objects.filter(asset__clinic_id=clinic_id, active=True,
            starts_at__lt=end, ends_at__gt=start).filter(Q(kind='FIRM') | Q(expires_at__gt=timezone.now()))
        if ignore_visit: claims = claims.exclude(plan__visit_id=ignore_visit)
        if ignore_offer: claims = claims.exclude(plan__offer_id=ignore_offer)
        self.busy = defaultdict(list)
        self.eligible_dentists = {}
        self.requirements = {}
        from registry.profile_models import ClinicProfilePolicy,DentistClinicAffiliation
        self.roster_enforced=ClinicProfilePolicy.objects.filter(clinic_id=clinic_id,roster_enforced=True).exists()
        self.affiliations={a.dentist_id:a for a in DentistClinicAffiliation.objects.filter(clinic_id=clinic_id)} if self.roster_enforced else {}
        for asset_id, a, b in claims.values_list('asset_id', 'starts_at', 'ends_at'):
            self.busy[asset_id].append((a, b))

    def bundles(self, service, dentist_id, start, end, *, selected=None, limit=10, requirements=None):
        if self.roster_enforced:
            from registry.profile_services import valid_affiliation
            if not valid_affiliation(self.affiliations.get(dentist_id),start,end):return []
        if not self.ready:
            raise RuleError('本店诊疗资源尚在核对中，暂不能新增预约；已有预约和邀约请通过协调入口办理。')
        if service.pk not in self.eligible_dentists:
            self.eligible_dentists[service.pk]=set(service.dentists.filter(is_active=True).values_list('pk',flat=True))
        if (not service.is_active or not service.department.is_active or
                service.department.clinic_id != self.clinic_id or
                dentist_id not in self.eligible_dentists[service.pk]):
            raise RuleError('该服务、科室或医师适配已变化，请重新选择服务和出诊。')
        if end - start != timedelta(minutes=service.duration_minutes):
            raise RuleError('预约起止时间必须与服务配置时长一致（已包含准备和周转）。')
        local_a, local_b = timezone.localtime(start), timezone.localtime(end)
        if (local_a.date() != local_b.date() or not any(a <= local_a.time() and local_b.time() <= b
                for a, b in self.hours[service.department_id, local_a.weekday()])):
            return []
        blocks = [b for b in self.blocks if b.starts_at < end and start < b.ends_at]
        if any(b.department_id == service.department_id for b in blocks): return []
        if requirements is None:
            if service.pk not in self.requirements:self.requirements[service.pk]=list(service.requirements.order_by('category'))
            requirements=self.requirements[service.pk]
        def usable(binding, room):
            asset = binding.asset
            return (asset.state == 'IN_SERVICE' and (binding.shared or binding.room_id == room.pk) and
                not any(a < end and start < b for a, b in self.busy[asset.pk]) and
                not any(b.asset_id == asset.pk or b.room_id == room.pk for b in blocks))
        results = []
        for chair in self.bindings:
            if (chair.shared or chair.asset.category != 'CHAIR' or chair.room.department_id != service.department_id or
                    not chair.room.is_active or not usable(chair, chair.room)):
                continue
            room = chair.room
            resources = [chair]
            for requirement in requirements:
                candidates = [b for b in self.bindings if b.asset.category == requirement.category and usable(b, room)]
                if selected is not None: candidates = [b for b in candidates if b.asset_id in selected]
                if len(candidates) < requirement.quantity: break
                resources.extend(candidates[:requirement.quantity])
            else:
                ids = [b.asset_id for b in resources]
                if selected is not None and sorted(ids) != sorted(selected): continue
                results.append(self.snapshot(service, room, resources, start, end))
                if len(results) >= limit: break
        return results

    def snapshot(self, service, room, bindings, start, end):
        from registry.branch_projection import public_contact
        return {'contract': 'ADC-RESOURCES-1', 'clinic': self.clinic_id, 'policy_revision': self.policy.revision,
            'service': {'id': service.pk, 'code': service.code, 'name': service.name, 'duration': service.duration_minutes},
            'public_clinic': public_contact(service.department.clinic),
            'department': {'id': service.department_id, 'name': service.department.name},
            'room': {'id': room.pk, 'code': room.code, 'name': room.name},
            'resources': [{'id': b.asset_id, 'code': b.asset.asset_code, 'name': b.asset.name,
                'category': b.asset.category, 'asset_version': b.asset.lock_version} for b in bindings],
            'start': start.isoformat(), 'end': end.isoformat()}


def service_for(clinic_id, service_id):
    if not service_id:
        raise RuleError('请先选择预约服务；原固定30分钟表单不能用于已启用资源控制的诊所。')
    return BookingService.objects.select_related('department').get(pk=service_id, department__clinic_id=clinic_id)


def choose_bundle(*, slot, start, end, service_id=None, expected=None, ignore_visit=None,
                  ignore_offer=None, locked=False, preparing=False):
    if locked:
        lock_physical(slot.clinic_id)
        release_expired_locked(slot.clinic_id)
        from registry.profile_services import require_affiliation
        require_affiliation(slot.clinic_id,slot.dentist_id,start,end,lock=True)
    row = policy(slot.clinic_id)
    if row is None:
        if service_id or expected:
            raise RuleError('本店尚未准备诊疗资源，请先由主管完成配置。')
        return None  # Historical clinics retain the explicitly documented legacy contract.
    service = service_for(slot.clinic_id, service_id)
    calendar = ResourceCalendar(slot.clinic_id, start, end, ignore_visit=ignore_visit,
        ignore_offer=ignore_offer, preparing=preparing)
    selected = [r['id'] for r in expected['resources']] if expected else None
    bundles = calendar.bundles(service, slot.dentist_id, start, end, selected=selected, limit=1)
    if not bundles:
        raise RuleError('该时间暂无兼容椅位或必要设备，或科室已关闭。请重新查询，原预约仍保留。')
    result = bundles[0]
    if expected is not None and result != expected:
        raise RuleError('服务、资源位置或设备状态已经变化，请重新查询并确认。')
    return result


def claim_locked(*, actor, snapshot, start, end, visit=None, offer=None, reason='患者明确确认', version=1):
    if snapshot is None: return None
    if not connection.in_atomic_block: raise RuntimeError('Claims require atomic booking')
    plan = ResourcePlan.objects.create(visit=visit, offer=offer, service_id=snapshot['service']['id'],
        room_id=snapshot['room']['id'], snapshot=snapshot, recorded_by=actor, reason=reason, version=version)
    ResourceClaim.objects.bulk_create([ResourceClaim(plan=plan, asset_id=r['id'], starts_at=start, ends_at=end,
        kind='HOLD' if offer and not visit else 'FIRM', expires_at=offer.expires_at if offer and not visit else None)
        for r in snapshot['resources']])
    return plan


def release_visit_locked(visit, reason):
    lock_physical(visit.clinic_id)
    ResourceClaim.objects.filter(plan__visit=visit, active=True).update(active=False,
        released_at=timezone.now(), release_reason=reason)


def release_offer_locked(offer, reason):
    lock_physical(offer.request.clinic_id)
    ResourceClaim.objects.filter(plan__offer=offer, active=True, kind='HOLD').update(active=False,
        released_at=timezone.now(), release_reason=reason)


def accept_offer_resources_locked(actor, offer, visit):
    plan = ResourcePlan.objects.filter(offer=offer, is_current=True).first()
    if plan is None:
        if policy(visit.clinic_id): raise RuleError('原邀约缺少已核实的资源方案，请联系前台协调，未创建第二次预约。')
        return
    plan.visit = visit
    plan.save(update_fields=['visit'])
    plan.claims.filter(active=True).update(kind='FIRM', expires_at=None)


def validate_reserved_resources_locked(offer):
    """An offer retains its promised duration/catalogue snapshot, even after edits."""
    clinic_id = offer.request.clinic_id
    lock_physical(clinic_id)
    return inspect_reserved_resources(offer)


def inspect_reserved_resources(offer):
    """Read-only inspection; confirmation obtains the physical locks before repeating it."""
    clinic_id = offer.request.clinic_id
    if policy(clinic_id) is None: return None
    plan = ResourcePlan.objects.filter(offer=offer, is_current=True).select_related('service').first()
    if plan is None:
        raise RuleError('原邀约尚未核实资源，请联系前台协调；原承诺仍保留。')
    ids = [r['id'] for r in plan.snapshot['resources']]
    if not plan_location_valid(plan):raise RuleError('原邀约资源位置或启用状态已变化，请联系前台核对兼容替换。')
    if (plan.claims.filter(active=True, kind='HOLD', expires_at__gt=timezone.now()).count() != len(ids) or
            EquipmentAsset.objects.filter(pk__in=ids, state='IN_SERVICE').count() != len(ids) or
            ResourceBlock.objects.filter(clinic_id=clinic_id, is_active=True,
                starts_at__lt=offer.ends_at, ends_at__gt=offer.starts_at).filter(
                Q(asset_id__in=ids) | Q(room_id=plan.room_id) | Q(department_id=plan.service.department_id)).exists()):
        raise RuleError('原邀约资源当前不可用，请联系前台协调；没有改变患者意愿或创建额外预约。')
    return plan


def current_plan(visit):
    return ResourcePlan.objects.filter(visit=visit, is_current=True).first()


def check_in_resources_locked(visit):
    row = policy(visit.clinic_id)
    if row is None: return
    lock_physical(visit.clinic_id)
    plan = current_plan(visit)
    if plan is None:
        raise RuleError('该预约尚未核实椅位和设备，请先进入资源协调。')
    ids = list(plan.claims.values_list('asset_id', flat=True))
    if not plan_location_valid(plan):raise RuleError('椅位或设备位置已变化，请先进入资源协调。')
    if EquipmentAsset.objects.filter(pk__in=ids).exclude(state='IN_SERVICE').exists():
        raise RuleError('预约设备当前不可用，请进入资源协调并明确确认兼容替换后再登记到诊。')
    if ResourceClaim.objects.filter(asset_id__in=ids, plan__is_current=True,
            plan__visit__status='CHECKED_IN').exclude(plan__visit=visit).exists():
        raise RuleError('上一位患者仍在使用预约椅位或设备，请进入资源协调；不得重复接诊或自动搬迁患者。')
    # Recheck planned closures without reinterpreting a later service duration edit.
    if ResourceBlock.objects.filter(clinic_id=visit.clinic_id, is_active=True,
            starts_at__lt=visit.scheduled_end, ends_at__gt=visit.scheduled_start).filter(
            Q(asset_id__in=ids) | Q(room_id=plan.room_id) | Q(department_id=plan.service.department_id)).exists():
        raise RuleError('预约资源有排程停用，请先核实协调结果再到诊。')


def record_asset_impact_locked(asset, reason, start=None, end=None):
    """Equipment owns state; scheduling records promises needing coordination."""
    now = timezone.now()
    claims = ResourceClaim.objects.filter(asset=asset, active=True, plan__is_current=True).filter(
        Q(plan__visit__status='CHECKED_IN') | Q(plan__visit__status='SCHEDULED', ends_at__gt=now) |
        Q(plan__offer__state='PENDING', plan__offer__expires_at__gt=now))
    if start is not None and end is not None:claims=claims.filter(starts_at__lt=end,ends_at__gt=start)
    for plan in ResourcePlan.objects.filter(pk__in=claims.values('plan_id')):
        ResourceCoordination.objects.get_or_create(plan=plan, asset=asset, state__in=['OPEN', 'CONTACT'],
            defaults={'state': 'OPEN', 'reason': reason})


def plan_location_valid(plan):
    ids=[r['id'] for r in plan.snapshot['resources']]
    if not plan.room.is_active or not plan.room.department.is_active:return False
    return ResourceBinding.objects.filter(asset_id__in=ids,is_active=True).filter(Q(shared=True)|Q(room_id=plan.room_id)).count()==len(ids)
