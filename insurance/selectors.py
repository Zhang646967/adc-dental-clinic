from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone
from adc_core.rules import RuleError
from insurance.models import PolicyCatalogue, ClinicArrangement, FeeMapping, EligibilityFact
from insurance.policies import scope
from insurance.services import latest_eligibility, _fee_facts


def catalogues(actor):
    b = scope(actor)
    qs = PolicyCatalogue.objects.defer('original_bytes', 'normalized_rows').order_by('-pk')
    if b['role'] == 'HQ':
        raise PermissionDenied('总部查阅汇总，不读取目录复核明细。')
    return qs if b['role'] == 'FINANCE' else qs.filter(state__in=['CONFIRMED', 'DISABLED'])


def catalogue_detail(actor, pk, *, page=1, query='', issue=''):
    row = catalogues(actor).get(pk=pk)
    if issue not in ('', 'unknown', 'unit'):
        raise RuleError('目录问题筛选无效。')
    query = query.strip()[:80]
    items = row.items.order_by('code')
    if query:
        items = items.filter(Q(code__icontains=query) | Q(name__icontains=query))
    if issue == 'unknown':
        items = items.filter(payment_class='UNKNOWN')
    elif issue == 'unit':
        items = items.filter(unit__isnull=True)
    return dict(catalogue=row, page=Paginator(items, 20).get_page(page), query=query, issue=issue,
                previous_catalogue=catalogues(actor).filter(pk=row.previous_id).first() if row.previous_id else None,
                next_catalogue=catalogues(actor).filter(previous_id=row.pk).first(),
                events=row.events.select_related('actor').order_by('-pk'))


def mapping_blocker(row):
    if row.policy_item.catalogue.state != 'CONFIRMED':
        return '目录未启用或已停用'
    if not row.policy_item.unit:
        return '原目录单位缺失，待核对'
    if row.policy_item.payment_class == 'UNKNOWN' or row.policy_item.pre_self_pay_percent is None:
        return '原支付规则未知，待核对'
    if _fee_facts(row.treatment_type) != row.fee_snapshot or not row.treatment_type.is_active:
        return '收费项目或单位已变化，需重新适配'
    return ''


def dashboard(actor, *, arrangements_page=1, mappings_page=1):
    b = scope(actor)
    arrangements = ClinicArrangement.objects.select_related('clinic', 'catalogue').order_by('-pk')
    mappings = FeeMapping.objects.select_related('clinic', 'treatment_type', 'policy_item__catalogue').order_by('-pk')
    eligibilities = EligibilityFact.objects.all()
    if b['role'] in ('FRONT_DESK', 'MANAGER'):
        arrangements = arrangements.filter(clinic_id=b['clinic'])
        mappings = mappings.filter(clinic_id=b['clinic'])
        eligibilities = eligibilities.filter(clinic_id=b['clinic'])
    counts = dict(arrangements=arrangements.count(), pending_arrangements=arrangements.filter(state='DRAFT').count(),
                  confirmed_mappings=mappings.filter(state='CONFIRMED').count(), eligibility_versions=eligibilities.count())
    if b['role'] == 'HQ':
        return dict(aggregate_only=True, counts=counts)
    today = timezone.localdate()
    active = arrangements.filter(state='CONFIRMED', catalogue__state='CONFIRMED', starts_on__lte=today, ends_on__gte=today).first() if b['clinic'] else None
    a_page = Paginator(arrangements, 20).get_page(arrangements_page)
    m_page = Paginator(mappings, 20).get_page(mappings_page)
    rows = list(m_page.object_list)
    for row in rows:
        row.blocker = mapping_blocker(row)
    return dict(aggregate_only=False, counts=counts, catalogues=catalogues(actor),
                arrangements=list(a_page.object_list), mappings=rows, active_arrangement=active,
                arrangements_page=a_page, mappings_page=m_page)


def eligibility_at(clinic_id, patient_id, on):
    """Internal projection; caller owns patient/financial authorization."""
    row = latest_eligibility(clinic_id, patient_id)
    if not row:
        return None, '未登记模拟待遇'
    if row.state != 'VERIFIED':
        return row, row.get_state_display()
    if not row.starts_on <= on <= row.ends_on:
        return row, '模拟待遇不在有效期内'
    arrangement = ClinicArrangement.objects.filter(clinic_id=clinic_id, clinic__is_active=True,
        state='CONFIRMED', catalogue__state='CONFIRMED', starts_on__lte=on, ends_on__gte=on).select_related('catalogue').first()
    if not arrangement:
        return row, '本店该日期没有已核对启用的模拟安排'
    if row.insured_region != arrangement.catalogue.region:
        return row, '参保地与本店目录地区不同，需单独核对异地适用条件'
    return row, ''
