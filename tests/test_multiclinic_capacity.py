"""PostgreSQL scope equivalence, bounded aggregates and current HTTP authority.

Synthetic functional/query-growth checks. Real load evidence is separate.
"""
from datetime import date,timedelta
from decimal import Decimal as D
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Q
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from accounts.models import RoleAssignment,UserAccount
from accounts.policies import bindings,clinic_ids
from patients.models import Patient
from patients.selectors import visible_patients
from patients.services import create_patient
from scheduling.models import Visit,AvailabilitySlot
from finance.daily_facts import page_day_facts,day_facts
from finance.daily_services import prepare_close,confirm_close,prepare_close_review,confirm_close_review
from tests.test_care_finance_equipment import CFEFixture,activate
from tests.workspace_client import WorkspaceClient

class MultiClinicPatientTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe()
    def ids(self,u):return set(visible_patients(u).values_list('pk',flat=True))
    def history(self,patient,clinic=None,dentist=None,count=1):
        clinic=clinic or self.a;dentist=dentist or self.d1
        start=self.t+timedelta(days=4)
        slot=AvailabilitySlot.objects.create(clinic=clinic,dentist=dentist,starts_at=start,ends_at=start+timedelta(hours=8))
        Visit.objects.bulk_create([Visit(patient=patient,clinic=clinic,dentist=dentist,availability_slot=slot,scheduled_start=start+timedelta(minutes=30*i),scheduled_end=start+timedelta(minutes=30*(i+1)),status='NO_SHOW') for i in range(count)])
    def test_origin_clinic_is_visible_without_visits(self):
        self.assertEqual(self.ids(self.front),{self.p1.pk});self.assertEqual(self.ids(self.front2),{self.p2.pk})
    def test_shared_historical_patient_preserves_access_without_duplicates(self):
        self.history(self.p2,count=10)
        self.assertEqual(self.ids(self.front),{self.p1.pk,self.p2.pk});self.assertEqual(visible_patients(self.front).count(),2)
    def test_doctor_assignment_across_clinics_preserved(self):
        self.history(self.p2,clinic=self.b);self.assertEqual(self.ids(self.doctor),{self.p2.pk})
    def test_doctor_same_clinic_unassigned_patient_rejected(self):
        self.history(self.p1,dentist=self.d2);self.assertEqual(self.ids(self.doctor),set())
    def test_only_active_role_not_union_of_assigned_roles(self):
        RoleAssignment.objects.create(user=self.doctor,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        self.history(self.p2,clinic=self.b)
        activate(self.doctor,'FRONT_DESK',self.a);self.assertEqual(self.ids(self.doctor),{self.p1.pk})
        activate(self.doctor,'DENTIST');self.assertEqual(self.ids(self.doctor),{self.p2.pk})
    def test_current_clinic_narrows_multiple_grants(self):
        activate(self.front,'FRONT_DESK',self.b);self.assertEqual(self.ids(self.front),{self.p2.pk})
    def test_revocation_is_rechecked_on_next_query(self):
        self.assertIn(self.p1.pk,self.ids(self.front));RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        self.assertEqual(self.ids(self.front),set())
    def test_disabled_user_has_no_patient_scope(self):
        UserAccount.objects.filter(pk=self.front.pk).update(is_active=False);self.assertEqual(self.ids(self.front),set())
    def test_current_doctor_relation_reloaded_from_database(self):
        self.history(self.p1);UserAccount.objects.filter(pk=self.doctor.pk).update(dentist=self.d2)
        self.assertEqual(self.ids(self.doctor),set())
    def test_anonymous_other_roles_no_medical_directory(self):
        for u in (AnonymousUser(),self.manager,self.fin,self.hq,self.tech,self.pa):self.assertEqual(self.ids(u),set())
    def test_set_membership_matches_legacy_scope_for_all_roles(self):
        self.history(self.p2,count=8)
        for u in (self.front,self.front2,self.doctor,self.manager,self.fin,self.hq,self.pa,self.tech):
            clinics=clinic_ids(u,('FRONT_DESK',));scope=Q(created_in_clinic_id__in=clinics)|Q(visits__clinic_id__in=clinics)
            d=bindings(u).filter(role='DENTIST',scope_kind='SELF_DENTIST',user__dentist__isnull=False).values_list('user__dentist_id',flat=True).first()
            if d is not None:scope|=Q(visits__dentist_id=d)
            self.assertEqual(self.ids(u),set(Patient.objects.filter(scope).distinct().values_list('pk',flat=True)))
    def test_pagination_and_search_do_not_leak_foreign_rows(self):
        for i in range(30):Patient.objects.create(name='OWN-'+str(i),created_in_clinic=self.a,date_of_birth=date(2000,1,1),billing_address='synthetic',phone='000',emergency_name='synthetic',emergency_phone='000')
        c=WorkspaceClient();c.force_login(self.front)
        first=c.get('/patients/');second=c.get('/patients/?page=2');self.assertEqual(first.context['page'].paginator.count,31)
        for response in (first,second,c.get('/patients/?q='+self.p2.patient_no)):
            self.assertEqual(response.status_code,200);self.assertNotContains(response,self.p2.name)
        self.assertIn(c.get('/patients/'+str(self.p2.pk)+'/').status_code,(403,404))
    def test_concurrent_cross_clinic_create_cannot_expand_grant(self):
        before=Patient.objects.count()
        def run(i):
            try:
                return create_patient(actor=self.actor_copy(self.front),clinic_id=(self.a if i==0 else self.b).pk,details=dict(name='SYNTHETIC-RACE-'+str(i),date_of_birth=date(2000,1,1),billing_address='synthetic',phone='000',email='',emergency_name='synthetic',emergency_phone='000'),allergy_status='UNKNOWN').created_in_clinic_id
            except PermissionDenied:return 'DENIED'
        self.assertEqual(self.race(run),[self.a.pk,'DENIED']);self.assertEqual(Patient.objects.count(),before+1)

class MultiClinicDailyTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe()
    def submit(self,day):
        p=prepare_close(actor=self.manager,business_date=day,declared=day_facts(self.manager._adc_workspace.clinic_id,day)['totals'],evidence='Synthetic four-leg evidence',reason='Synthetic handover')
        row=confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        p=prepare_close_review(actor=self.fin,close_id=row.pk,decision='approve',reason='Independent synthetic verification')
        return confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[0]
    def test_empty_page_does_not_query(self):
        with self.assertNumQueries(0):self.assertEqual(page_day_facts([]),{})
    def test_empty_cash_pair_is_exact_zero_snapshot(self):
        pair=(self.a.pk,self.today);self.assertEqual(page_day_facts([pair])[pair],day_facts(*pair))
    def test_duplicates_share_one_grouped_query(self):
        pair=(self.a.pk,self.today)
        with self.assertNumQueries(1):got=page_day_facts([pair,pair])
        self.assertEqual(list(got),[pair])
    def test_bounded_pairs_fail_before_query(self):
        for pairs in ([(self.a.pk,self.today)]*21,[(True,self.today)],[(self.a.pk,'2026-01-01')],[(self.a.pk,)],[(0,self.today)]):
            with self.assertNumQueries(0),self.assertRaises(ValueError):page_day_facts(pairs)
    def test_all_gross_legs_and_pending_equal_individual_facts(self):
        v,invoice=self.billed();self.approve(self.cash(invoice,amount='100.01'));self.approve(self.cash(invoice,kind='REFUND',amount='20.01'))
        self.approve(self.expense(self.asset(acquisition_cost='9.99')));self.expense(self.asset(asset_code='PENDING',acquisition_cost='3.21'))
        pair=(self.a.pk,self.today);facts=page_day_facts([pair])[pair];self.assertEqual(facts,day_facts(*pair))
        self.assertEqual(facts['pending'],1);self.assertEqual(facts['totals']['RECEIPT'],'100.01');self.assertEqual(facts['totals']['REFUND'],'20.01');self.assertEqual(facts['totals']['EQUIPMENT_EXPENSE'],'9.99')
    def test_exact_pairs_do_not_cross_clinic_date_product(self):
        from finance.cash_services import prepare_cash,confirm_cash_request
        previous=self.today-timedelta(days=1)
        for clinic,day,code in [(self.a,previous,'EQ-A'),(self.b,self.today,'EQ-B')]:
            if clinic==self.b:RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
            activate(self.manager,'MANAGER',clinic);asset=self.asset(asset_code=code);event=asset.events.get(sequence=0)
            p=prepare_cash(actor=self.manager,source_type='equipment',source_id=event.pk,kind='EQUIPMENT_EXPENSE',occurred_on=day,reason='Synthetic date isolation',**self.evidence())
            self.approve(confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0])
        pairs=[(self.a.pk,self.today),(self.b.pk,previous)]
        got=page_day_facts(pairs);self.assertEqual(set(got),set(pairs))
        for pair in pairs:self.assertEqual(got[pair],day_facts(*pair));self.assertEqual(got[pair]['posted_count'],0)
    def test_twenty_row_page_has_no_per_row_query_growth(self):
        for i in range(20):self.submit(self.today-timedelta(days=i))
        c=WorkspaceClient();c.force_login(self.fin);c.get('/finance/daily-closes/')
        with CaptureQueriesContext(connection) as one:r=c.get('/finance/daily-closes/?day='+self.today.isoformat())
        self.assertEqual(len(r.context['rows']),1)
        with CaptureQueriesContext(connection) as many:r=c.get('/finance/daily-closes/')
        self.assertEqual(len(r.context['rows']),20);self.assertEqual(len(many),len(one))
        self.assertEqual(sum('FROM "adc_cash_entry"' in q['sql'] for q in many),1)
    def test_changed_flags_use_current_facts_without_rewriting_snapshot(self):
        row=self.submit(self.today);snapshot=row.snapshot;self.approve(self.expense(self.asset()))
        c=WorkspaceClient();c.force_login(self.manager);r=c.get('/finance/daily-closes/');self.assertTrue(r.context['rows'][0].changed)
        row.refresh_from_db();self.assertEqual(row.snapshot,snapshot)
    def test_latest_versions_and_clinic_filter_preserved(self):
        first=self.submit(self.today);second=self.submit(self.today)
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b);activate(self.manager,'MANAGER',self.b);other=self.submit(self.today)
        c=WorkspaceClient();c.force_login(self.manager);r=c.get('/finance/daily-closes/');self.assertEqual([x.pk for x in r.context['rows']],[second.pk])
        self.assertEqual(c.get('/finance/daily-closes/'+str(other.pk)+'/').status_code,404)
        c=WorkspaceClient();c.force_login(self.fin);r=c.get('/finance/daily-closes/');self.assertEqual({x.pk for x in r.context['rows']},{second.pk,other.pk})
    def test_revoked_clinic_cannot_keep_cached_day_access(self):
        self.submit(self.today);c=WorkspaceClient();c.force_login(self.manager);self.assertEqual(c.get('/finance/daily-closes/').status_code,200)
        RoleAssignment.objects.filter(user=self.manager,clinic=self.a).update(is_active=False)
        self.assertIn(c.get('/finance/daily-closes/').status_code,(302,403,409))
