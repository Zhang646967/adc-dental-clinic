"""Bounded de-identified read projections; authority stays in current workspace."""
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from adc_core.snapshots import reporting_snapshot
from finance.cash_models import CashEntry
from finance.reconciliation_models import PaymentAccount, CashEvidenceVersion, StatementBatch, StatementLine, ReconciliationMatch
from finance.evidence_policies import reconciliation_scope
from finance.reconciliation_services import ACTIVE

def scoped(qs,clinic,path):
    return qs.filter(**{path:clinic}) if clinic is not None else qs

def evidence_summary(clinic=None,day=None):
    cash=CashEntry.objects.filter(state='POSTED')
    if clinic is not None:cash=cash.filter(clinic_id=clinic)
    if day is not None:cash=cash.filter(occurred_on=day)
    approved=CashEvidenceVersion.objects.filter(cash_entry_id=OuterRef('pk'),state='APPROVED')
    confirmed=ReconciliationMatch.objects.filter(cash_entry_id=OuterRef('pk'),state='CONFIRMED')
    cash=cash.annotate(has_evidence=Exists(approved),has_match=Exists(confirmed))
    return cash.aggregate(posted=Count('pk'),evidenced=Count('pk',filter=Q(has_evidence=True)),matched=Count('pk',filter=Q(has_match=True)))

def dashboard(actor,page='1'):
    with reporting_snapshot():
        clinic=reconciliation_scope(actor,detail=False)
        data=dict(summary=evidence_summary(clinic),clinic=clinic)
        statements=scoped(StatementLine.objects.all(),clinic,'account__clinic_id')
        active=ReconciliationMatch.objects.filter(line_id=OuterRef('pk'),state__in=ACTIVE)
        data['statement_count']=statements.count()
        data['unmatched_count']=statements.annotate(active=Exists(active)).filter(active=False).count()
        if actor._adc_workspace.role=='HQ':return data
        data['batches']=Paginator(scoped(StatementBatch.objects.select_related('account__clinic','created_by'),clinic,'account__clinic_id').order_by('-pk'),20).get_page(page)
        matches=scoped(ReconciliationMatch.objects.select_related('line__account__clinic','prepared_by'),clinic,'cash_entry__clinic_id')
        data['matches']=Paginator(matches.order_by('-pk'),20).get_page(page)
        data['pending_evidence']=list(scoped(CashEvidenceVersion.objects.select_related('account__clinic','prepared_by').filter(state='PENDING',initial=False),clinic,'cash_entry__clinic_id').order_by('pk')[:20])
        return data

def line_scope(actor):
    clinic=reconciliation_scope(actor)
    return scoped(StatementLine.objects.select_related('account__clinic','batch__created_by'),clinic,'account__clinic_id')

def match_scope(actor):
    clinic=reconciliation_scope(actor)
    return scoped(ReconciliationMatch.objects.select_related('line__account__clinic','cash_entry','evidence','prepared_by','reviewed_by','invalidated_by'),clinic,'cash_entry__clinic_id')

def candidates(actor,line):
    clinic=reconciliation_scope(actor)
    if clinic is not None and line.account.clinic_id!=clinic:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    newer=CashEvidenceVersion.objects.filter(cash_entry_id=OuterRef('cash_entry_id'),state='APPROVED',version__gt=OuterRef('version'))
    active=ReconciliationMatch.objects.filter(cash_entry_id=OuterRef('cash_entry_id'),state__in=ACTIVE)
    kinds=['RECEIPT','EXPENSE_REVERSAL'] if line.direction=='IN' else ['REFUND','EQUIPMENT_EXPENSE']
    if line.currency!='CNY':return []
    return list(CashEvidenceVersion.objects.filter(account_id=line.account_id,reference=line.reference,state='APPROVED',
        cash_entry__state='POSTED',cash_entry__amount=line.amount,cash_entry__kind__in=kinds,
        cash_entry__clinic_id=line.account.clinic_id).annotate(newer=Exists(newer),active=Exists(active)).filter(newer=False,active=False)
        .select_related('cash_entry').order_by('cash_entry_id')[:20])
