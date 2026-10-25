"""Preparation commands only. These operations cannot create care, bills or cash."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone
from accounts.models import UserAccount
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from insurance.catalogue_source import load_source, SOURCE_KEY
from insurance.models import (PolicyCatalogue, PolicyItem, ClinicArrangement, FeeMapping,
                              EligibilityFact, InsuranceEvent, SCHEMES, ELIGIBILITY_STATES)
from insurance.policies import scope, preparer_active
from patients.models import Patient
from patients.selectors import visible_patients
from registry.models import Clinic, TreatmentType

PREPARE = 'adc.insurance.preparation.v1'
REVIEW = 'adc.insurance.review.v1'
DISABLE = 'adc.insurance.disable.v1'
MODELS = {'catalogue': PolicyCatalogue, 'arrangement': ClinicArrangement,
          'mapping': FeeMapping, 'eligibility': EligibilityFact}
REGIONS = [('UNKNOWN', '参保地待核实'), ('CN-11', '北京市'), ('CN-12', '天津市'), ('CN-13', '河北省'),
    ('CN-14', '山西省'), ('CN-15', '内蒙古自治区'), ('CN-21', '辽宁省'), ('CN-22', '吉林省'), ('CN-23', '黑龙江省'),
    ('CN-31', '上海市'), ('CN-32', '江苏省'), ('CN-33', '浙江省'), ('CN-34', '安徽省'), ('CN-35', '福建省'),
    ('CN-36', '江西省'), ('CN-37', '山东省'), ('CN-41', '河南省'), ('CN-42', '湖北省'), ('CN-43', '湖南省'),
    ('CN-44', '广东省'), ('CN-45', '广西壮族自治区'), ('CN-46', '海南省'), ('CN-50', '重庆市'), ('CN-51', '四川省'),
    ('CN-52', '贵州省'), ('CN-53', '云南省'), ('CN-54', '西藏自治区'), ('CN-61', '陕西省'), ('CN-62', '甘肃省'),
    ('CN-63', '青海省'), ('CN-64', '宁夏回族自治区'), ('CN-65', '新疆维吾尔自治区')]


def _people(*ids):
    list(UserAccount.objects.select_for_update().filter(pk__in=ids).order_by('pk'))


def _text(value, label, maximum=500):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise RuleError(f'请填写{label}（不超过{maximum}字）。')
    return value.strip()


def _reference(value):
    value = _text(value, '合成依据编号', 80).upper()
    if not re.fullmatch(r'SIM-[A-Z0-9_-]{1,76}', value):
        raise RuleError('课程依据编号使用 SIM- 开头的字母数字，不填写真实证件或医保号码。')
    return value


def _dates(starts_on, ends_on):
    try:
        start, end = date.fromisoformat(str(starts_on)), date.fromisoformat(str(ends_on))
    except ValueError:
        raise RuleError('请填写完整的有效起止日期。') from None
    if end < start:
        raise RuleError('截止日期不能早于开始日期。')
    return start, end


def _fee_facts(fee):
    return dict(code=fee.code, name=fee.name, unit=fee.unit_definition, active=fee.is_active)


def _published(catalogue_id, *, lock=False):
    qs = PolicyCatalogue.objects.select_for_update() if lock else PolicyCatalogue.objects
    row = qs.get(pk=catalogue_id)
    if row.state != 'CONFIRMED':
        raise RuleError('目录尚未独立核对启用或已停用，请先核对当前版本。')
    return row


def _clinic(pk, *, require_active=True):
    qs = Clinic.objects.select_for_update()
    if require_active:
        qs = qs.filter(is_active=True)
    return qs.get(pk=pk)


def _record(actor, row, operation, action, reason):
    kind = next(k for k, model in MODELS.items() if isinstance(row, model))
    snapshot = dict(state=getattr(row, 'state', ''), revision=getattr(row, 'revision', 0), clinic=getattr(row, 'clinic_id', None))
    if kind == 'catalogue':
        snapshot.update(source_digest=row.source_digest, normalized_digest=row.normalized_digest, summary=row.source_summary,
                        review_attempt=row.review_attempt, previous=row.previous_id)
    elif kind == 'eligibility':
        snapshot.update(version=row.version, previous=row.previous_id, insured_region=row.insured_region,
                        scheme=row.scheme, starts_on=str(row.starts_on), ends_on=str(row.ends_on), source=row.source)
    InsuranceEvent.objects.create(**{kind: row}, actor=actor, operation_id=operation,
        action=action, reason=reason, snapshot=snapshot)
    emit(actor, 'INSURANCE_PREPARATION_CHANGED', row,
         summary={'kind': kind, 'action': action, 'state': row.state, 'clinic_id': getattr(row, 'clinic_id', None)})


def _replay(actor, operation, kind):
    event = InsuranceEvent.objects.filter(operation_id=operation, actor=actor).first()
    return getattr(event, kind) if event and getattr(event, kind + '_id') else None


def prepare_catalogue(*, actor, source_key=SOURCE_KEY, previous_id=None, reason=''):
    scope(actor, ('FINANCE',))
    raw, data = load_source(source_key)
    existing = PolicyCatalogue.objects.filter(source_digest=data['source_sha256']).order_by('-review_attempt').first()
    if previous_id is not None:
        if not existing or existing.pk != previous_id or existing.state not in ('REJECTED', 'DISABLED'):
            raise RuleError('仅可从该来源最新的未通过或停用记录明确重新提交核对。')
        reason = _text(reason, '重新提交核对的依据')
    elif existing:
        raise RuleError(f'此来源已保留为目录 #{existing.pk}，请打开原记录继续核对，勿重复导入。')
    d = dict(kind='catalogue', source_key=source_key, source_digest=data['source_sha256'], normalized_digest=data['normalized_sha256'],
             previous=previous_id, review_attempt=existing.review_attempt + 1 if existing else 1, reason=reason)
    return dict(data=d, source=data, proposal_token=proposal(actor, PREPARE, ('FINANCE',), d))


def prepare_arrangement(*, actor, catalogue_id, starts_on, ends_on, reference):
    b = scope(actor, ('MANAGER',))
    catalogue = _published(catalogue_id)
    start, end = _dates(starts_on, ends_on)
    if start < catalogue.effective_on:
        raise RuleError('门店安排不能早于该目录的生效日期。')
    d = dict(kind='arrangement', clinic=b['clinic'], catalogue=catalogue.pk, catalogue_revision=catalogue.revision,
             starts_on=str(start), ends_on=str(end), reference=_reference(reference))
    return dict(data=d, catalogue=catalogue, proposal_token=proposal(actor, PREPARE, ('MANAGER',), d))


def prepare_mapping(*, actor, treatment_type_id, policy_item_id, policy_units_per_fee, compatibility_basis):
    b = scope(actor, ('MANAGER',))
    fee = TreatmentType.objects.get(pk=treatment_type_id, is_active=True)
    item = PolicyItem.objects.select_related('catalogue').get(pk=policy_item_id)
    catalogue = _published(item.catalogue_id)
    try:
        quantity = Decimal(str(policy_units_per_fee))
    except InvalidOperation:
        raise RuleError('请填写明确的目录单位换算数量。') from None
    if not quantity.is_finite() or not 0 < quantity < 100000000 or quantity != quantity.quantize(Decimal('0.0001')):
        raise RuleError('目录单位换算数量应为正数，最多四位小数。')
    d = dict(kind='mapping', clinic=b['clinic'], treatment_type=fee.pk, policy_item=item.pk,
             catalogue=catalogue.pk, catalogue_revision=catalogue.revision, fee_snapshot=_fee_facts(fee),
             policy_units_per_fee=str(quantity), compatibility_basis=_text(compatibility_basis, '项目含义和单位适配依据'))
    return dict(data=d, fee=fee, item=item, proposal_token=proposal(actor, PREPARE, ('MANAGER',), d))


def latest_eligibility(clinic_id, patient_id):
    return EligibilityFact.objects.filter(clinic_id=clinic_id, patient_id=patient_id).order_by('-version').first()


def prepare_eligibility(*, actor, patient_id, insured_region, scheme, state, starts_on, ends_on, reference, basis):
    b = scope(actor, ('FRONT_DESK',))
    patient = visible_patients(actor).get(pk=patient_id, is_active=True)
    start, end = _dates(starts_on, ends_on)
    if insured_region not in dict(REGIONS) or scheme not in dict(SCHEMES) or state not in dict(ELIGIBILITY_STATES):
        raise RuleError('请明确选择参保地、类型和本次模拟核对结果。')
    if state == 'VERIFIED' and (insured_region == 'UNKNOWN' or scheme == 'UNKNOWN'):
        raise RuleError('参保地或类型待核实时，应保留“待核实”，不能记为待遇已核对。')
    old = latest_eligibility(b['clinic'], patient.pk)
    d = dict(kind='eligibility', clinic=b['clinic'], patient=patient.pk, previous=old.pk if old else None,
             version=old.version + 1 if old else 1, insured_region=insured_region, scheme=scheme, state=state,
             starts_on=str(start), ends_on=str(end), reference=_reference(reference), basis=_text(basis, '本次模拟核对依据'))
    return dict(data=d, patient=patient, proposal_token=proposal(actor, PREPARE, ('FRONT_DESK',), d))


@business_errors
@transaction.atomic
def confirm_preparation(*, actor, proposal_token, confirmed, expected_kind=None, expected_patient_id=None, expected_previous_id=None):
    if confirmed is not True:
        raise RuleError('请核对资料并明确确认。')
    p = read_proposal(actor, PREPARE, ('FINANCE', 'MANAGER', 'FRONT_DESK'), proposal_token)
    d = p['data']; kind = d['kind']
    if expected_kind is not None and kind != expected_kind or expected_patient_id is not None and d.get('patient') != expected_patient_id:
        raise RuleError('确认目标与当前页面不同，请回到原记录继续。')
    if expected_previous_id is not None and d.get('previous') != expected_previous_id:
        raise RuleError('重新提交的来源与当前页面不同，请打开原目录继续。')
    roles = {'catalogue': ('FINANCE',), 'arrangement': ('MANAGER',), 'mapping': ('MANAGER',), 'eligibility': ('FRONT_DESK',)}
    _people(actor.pk); b = scope(actor, roles[kind], lock=True)
    prior = _replay(actor, p['operation'], kind)
    if prior:
        return prior, True
    if kind == 'catalogue':
        raw, data = load_source(d['source_key'])
        if (d['source_digest'], d['normalized_digest']) != (data['source_sha256'], data['normalized_sha256']):
            raise RuleError('目录来源发生变化，请重新预览。')
        # Serialize the source before reading its latest attempt, including a
        # first import where there is no catalogue row to lock yet.
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ['adc.insurance.catalogue-source:' + d['source_digest']])
        existing = PolicyCatalogue.objects.select_for_update().filter(source_digest=d['source_digest']).order_by('-review_attempt').first()
        if d['previous'] is None:
            if existing:
                raise RuleError('此来源已由另一笔操作导入，请打开已保留的目录继续办理。')
        elif not existing or existing.pk != d['previous'] or existing.state not in ('REJECTED', 'DISABLED'):
            raise RuleError('该来源已有新的核对进度，请打开最新记录，勿重复提交。')
        row = PolicyCatalogue.objects.create(region='CN-43', version_code=SOURCE_KEY, notice=data['notice'],
            previous=existing if d['previous'] else None, review_attempt=d['review_attempt'],
            effective_on=data['effective_on'], source_url=data['source_url'],
            attachment_url='https://ybj.hunan.gov.cn/ybj/first113541/firstF/f3113607/202603/33945644/files/5040a1c8a594432ba5b99d48463c32b3.docx',
            source_format=data['source_format'], parser_version=data['parser'], source_digest=data['source_sha256'],
            normalized_digest=data['normalized_sha256'], original_bytes=raw, normalized_rows=data['items'],
            source_summary={k: data[k] for k in ('physical_rows', 'unique_codes', 'identical_extra_rows', 'class_counts')}, prepared_by=actor)
        PolicyItem.objects.bulk_create([PolicyItem(catalogue=row, **{k: v[k] for k in ('code', 'name', 'unit', 'payment_class', 'pre_self_pay_percent', 'review_state', 'source_rows', 'raw_cells')}) for v in data['items']])
    else:
        if d['clinic'] != b['clinic']:
            raise PermissionDenied('请从原诊所工作区继续。')
        if kind == 'eligibility':
            Clinic.objects.get(pk=d['clinic'], is_active=True)
        else:
            _clinic(d['clinic'])
        if kind in ('arrangement', 'mapping'):
            catalogue = _published(d['catalogue'], lock=True)
            if catalogue.revision != d['catalogue_revision']:
                raise RuleError('目录已变化，请重新核对当前版本。')
        if kind == 'arrangement':
            start, end = _dates(d['starts_on'], d['ends_on'])
            if start < catalogue.effective_on:
                raise RuleError('安排不能早于目录生效。')
            row = ClinicArrangement.objects.create(clinic_id=d['clinic'], catalogue=catalogue, starts_on=start,
                ends_on=end, reference=_reference(d['reference']), prepared_by=actor)
        elif kind == 'mapping':
            fee = TreatmentType.objects.select_for_update().get(pk=d['treatment_type'], is_active=True)
            if _fee_facts(fee) != d['fee_snapshot']:
                raise RuleError('收费项目或单位已变化，请重新核对适配。')
            item = PolicyItem.objects.get(pk=d['policy_item'], catalogue=catalogue)
            row = FeeMapping.objects.create(clinic_id=d['clinic'], treatment_type=fee, policy_item=item,
                fee_snapshot=d['fee_snapshot'], policy_units_per_fee=d['policy_units_per_fee'],
                compatibility_basis=d['compatibility_basis'], prepared_by=actor)
        else:
            patient = visible_patients(actor).select_for_update().get(pk=d['patient'], is_active=True)
            old = latest_eligibility(d['clinic'], patient.pk)
            if (old.pk if old else None) != d['previous']:
                raise RuleError('患者已有新的待遇核对记录，请比较当前结果后重新预览。')
            row = EligibilityFact.objects.create(clinic_id=d['clinic'], patient=patient,
                previous=old, version=d['version'], insured_region=d['insured_region'], scheme=d['scheme'], state=d['state'],
                starts_on=d['starts_on'], ends_on=d['ends_on'], reference=d['reference'], basis=d['basis'], recorded_by=actor)
    _record(actor, row, p['operation'], 'PREPARE' if kind != 'eligibility' else 'RECORD',
            (d['reason'] or '导入已核对来源的资料，待独立复核') if kind == 'catalogue' else d.get('basis', d.get('compatibility_basis', d.get('reference', ''))))
    return row, False


def reviewed_subject(actor, kind, pk, *, lock=False):
    b = scope(actor, ('FINANCE', 'MANAGER'))
    if kind not in ('catalogue', 'arrangement', 'mapping'):
        raise RuleError('此资料不在独立复核范围。')
    if kind == 'catalogue' and b['role'] != 'FINANCE':
        raise PermissionDenied('目录发布由财务独立核对。')
    qs = MODELS[kind].objects
    if kind != 'catalogue' and b['role'] == 'MANAGER':
        qs = qs.filter(clinic_id=b['clinic'])
    if lock:
        qs = qs.select_for_update()
    return qs.get(pk=pk)


def _review_blocker(kind, row):
    role = 'FINANCE' if kind == 'catalogue' else 'MANAGER'
    if not preparer_active(row.prepared_by_id, role, getattr(row, 'clinic_id', None)):
        raise RuleError('提交人的原岗位授权已失效；请记录未通过并由现任责任人重新提交。')
    if kind != 'catalogue':
        catalogue = _published(row.catalogue_id if kind == 'arrangement' else row.policy_item.catalogue_id)
        if kind == 'arrangement':
            if row.starts_on < catalogue.effective_on:
                raise RuleError('安排日期早于目录生效。')
            if ClinicArrangement.objects.filter(clinic_id=row.clinic_id, state='CONFIRMED', starts_on__lte=row.ends_on, ends_on__gte=row.starts_on).exclude(pk=row.pk).exists():
                raise RuleError('本店该日期已有启用安排，请先核对并停用重复安排。')
        else:
            item = row.policy_item
            if not item.unit or item.payment_class == 'UNKNOWN' or item.pre_self_pay_percent is None:
                raise RuleError('原表单位或支付规则缺失，映射继续待核对；不能补造单位或基金承担。')
            if _fee_facts(row.treatment_type) != row.fee_snapshot or not row.treatment_type.is_active:
                raise RuleError('收费项目或单位已变化，请重新提交适配。')
            if FeeMapping.objects.filter(clinic_id=row.clinic_id, treatment_type_id=row.treatment_type_id, state='CONFIRMED').exclude(pk=row.pk).exists():
                raise RuleError('本店该收费项目已有启用映射，请先核对并停用旧映射。')


def prepare_review(*, actor, kind, pk, decision, reason):
    scope(actor, ('FINANCE',))
    row = reviewed_subject(actor, kind, pk)
    if row.prepared_by_id == actor.pk:
        raise PermissionDenied('独立复核须由另一账号办理，切换岗位也不能自行复核。')
    if row.state != 'DRAFT' or decision not in ('approve', 'reject'):
        raise RuleError('请打开待核对记录，并明确选择复核结果。')
    if decision == 'approve':
        _review_blocker(kind, row)
    d = dict(kind=kind, pk=row.pk, revision=row.revision, decision=decision, reason=_text(reason, '复核依据'))
    return dict(data=d, row=row, proposal_token=proposal(actor, REVIEW, ('FINANCE',), d))


@business_errors
@transaction.atomic
def confirm_review(*, actor, proposal_token, confirmed, expected_kind=None, expected_pk=None):
    if confirmed is not True:
        raise RuleError('请明确确认独立复核结果。')
    p = read_proposal(actor, REVIEW, ('FINANCE',), proposal_token); d = p['data']
    if expected_kind is not None and d['kind'] != expected_kind or expected_pk is not None and d['pk'] != expected_pk:
        raise RuleError('复核目标与当前页面不同，请回到原记录继续。')
    target = reviewed_subject(actor, d['kind'], d['pk'])
    _people(actor.pk, target.prepared_by_id); scope(actor, ('FINANCE',), lock=True)
    prior = _replay(actor, p['operation'], d['kind'])
    if prior:
        return prior, True
    if d['kind'] != 'catalogue':
        _clinic(target.clinic_id, require_active=d['decision'] == 'approve')
        PolicyCatalogue.objects.select_for_update().get(pk=target.catalogue_id if d['kind'] == 'arrangement' else target.policy_item.catalogue_id)
    row = reviewed_subject(actor, d['kind'], d['pk'], lock=True)
    if row.prepared_by_id == actor.pk:
        raise PermissionDenied('不能自行复核。')
    if row.state != 'DRAFT' or row.revision != d['revision']:
        raise RuleError('资料已由另一笔操作办理，请查看原结果。')
    if d['decision'] == 'approve':
        if d['kind'] == 'mapping':
            # Catalogue/clinic locks precede the shared fee definition lock.
            row.treatment_type = TreatmentType.objects.select_for_update().get(pk=row.treatment_type_id)
        _review_blocker(d['kind'], row)
    row.state = 'CONFIRMED' if d['decision'] == 'approve' else 'REJECTED'
    row.reviewed_by = actor; row.reviewed_at = timezone.now(); row.review_reason = d['reason']; row.revision += 1
    row.save(update_fields=['state', 'reviewed_by', 'reviewed_at', 'review_reason', 'revision'])
    _record(actor, row, p['operation'], 'REVIEW', d['reason'])
    return row, False


def prepare_disable(*, actor, kind, pk, reason):
    row = reviewed_subject(actor, kind, pk)
    if row.state != 'CONFIRMED':
        raise RuleError('仅已启用资料可停用；原记录和已发生业务均保留。')
    d = dict(kind=kind, pk=row.pk, revision=row.revision, reason=_text(reason, '停用依据'))
    return dict(data=d, row=row, proposal_token=proposal(actor, DISABLE, ('MANAGER', 'FINANCE'), d))


@business_errors
@transaction.atomic
def confirm_disable(*, actor, proposal_token, confirmed, expected_kind=None, expected_pk=None):
    if confirmed is not True:
        raise RuleError('请明确确认停用。')
    p = read_proposal(actor, DISABLE, ('MANAGER', 'FINANCE'), proposal_token); d = p['data']
    if expected_kind is not None and d['kind'] != expected_kind or expected_pk is not None and d['pk'] != expected_pk:
        raise RuleError('停用目标与当前页面不同，请回到原记录继续。')
    target = reviewed_subject(actor, d['kind'], d['pk'])
    _people(actor.pk); scope(actor, ('FINANCE',) if d['kind'] == 'catalogue' else ('MANAGER', 'FINANCE'), lock=True)
    prior = _replay(actor, p['operation'], d['kind'])
    if prior:
        return prior, True
    if d['kind'] != 'catalogue':
        _clinic(target.clinic_id, require_active=False)
        PolicyCatalogue.objects.select_for_update().get(pk=target.catalogue_id if d['kind'] == 'arrangement' else target.policy_item.catalogue_id)
    row = reviewed_subject(actor, d['kind'], d['pk'], lock=True)
    if row.state != 'CONFIRMED' or row.revision != d['revision']:
        raise RuleError('资料状态已变化，请打开当前记录。')
    row.state = 'DISABLED'; row.revision += 1; row.save(update_fields=['state', 'revision'])
    _record(actor, row, p['operation'], 'DISABLE', d['reason'])
    return row, False
