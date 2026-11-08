"""C5 real PostgreSQL batch, nursing and traceability acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from adc_core.rules import RuleError
from care.models import Invoice, TreatmentRecord
from clinical import dispensing
from clinical.archive_display import sections
from clinical.archive_sources import capture
from clinical.pharmacy_models import DispenseMovement
from finance.cash_models import CashEntry
from registry.models import TreatmentType
from supplies import nursing, stock
from supplies.models import NursingDuty, NursingExecution, StockItem, StockLot, StockMovement
from tests.test_dispensing import DispensingFixture
from tests.test_treatment_continuity import PlanFixture
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext


class SupplyFixture(DispensingFixture,PlanFixture):
    def setup_supplies(self):
        self.setup_dispensing()
        self.v=self.visit
        self.item=TreatmentType.objects.create(code='C5-ACTUAL',name='合成实际诊疗',unit_definition='次',standard_unit_price='80.00')
        self.nurse=UserAccount.objects.create_user(username='synthetic_nurse')
        self.provision('nurse','--user',self.nurse.username,'--duty','EXECUTE')
        self.provision('nurse','--user',self.nurse.username,'--duty','STERILITY')
        self.ctx(self.nurse,'NURSE',self.a)
        self.provision('item','--kind','MATERIAL','--code','C5-MATERIAL','--name','合成耗材','--unit','件')
        self.provision('drug','--catalogue-code','C41-SIM-A')
        self.material=StockItem.objects.get(code='C5-MATERIAL',clinic=self.a)
        self.drug=StockItem.objects.get(code='C41-SIM-A',clinic=self.a)

    def provision(self,*args):
        return call_command('configure_supplies_rehearsal','--synthetic-only','--operator',self.tech.username,
                            '--clinic',self.a.clinic_code,*args,stdout=StringIO())

    def receive(self,item,quantity=5,actor=None,code='C5-LOT'):
        actor=actor or self.manager
        _,token=stock.prepare(actor,'RECEIPT',dict(item=item.pk,code=code,quantity=quantity,
            expires_on=(timezone.localdate()+timedelta(days=30)).isoformat(),reference='C5-SYNTHETIC-RECEIPT',
            reason='按合成到货凭据核对'))
        return stock.confirm(actor,token,True)[0]

    def inventory(self,actor,kind,lot,**values):
        _,token=stock.prepare(actor,kind,dict(values,lot=lot.pk,reason='核对本批次原始凭据'))
        return stock.confirm(actor,token,True)[0]

    def work_token(self,kind,**values):
        self.visit.refresh_from_db()
        return nursing.prepare(self.nurse,self.visit,kind,dict(values,observed_at=timezone.now().isoformat(),
            reason='据实记录本次合成护理'))[1]

    def work(self,kind,**values):
        return nursing.confirm(self.nurse,self.work_token(kind,**values),True)[0]

    def pack(self,code='C5-PACK'):
        now=timezone.now()
        _,token=nursing.prepare_pack(self.nurse,self.a.pk,'RELEASE',dict(code=code,reference='C5-SYNTHETIC-CYCLE',
            processed_at=(now-timedelta(minutes=10)).isoformat(),valid_until=(now+timedelta(days=1)).isoformat()))
        return nursing.confirm_pack(self.nurse,token,True)[0]

    def dispense_with_lot(self,quantity=4,stocked=5):
        line=self.priced()
        lot=self.receive(self.drug,stocked,self.rx_user).lot
        issue=self.perform('ISSUE',line_id=line.pk,quantity=quantity,lot_id=lot.pk)
        return line,lot,issue


@override_settings(ADC_CLINICAL_SYNTHETIC=True,ADC_PRESCRIPTION_REHEARSAL=True,ADC_DISPENSING_REHEARSAL=True,
                   ADC_STOCK_REHEARSAL=True)
class BatchTraceTests(SupplyFixture,TransactionTestCase):
    def setUp(self):
        self.setup_supplies()

    def test_normal_inventory_http_preview_duplicate_and_scope(self):
        manager=WorkspaceClient()
        manager.force_login(self.manager)
        self.assertContains(manager.get(reverse('stock_queue')),'登记到货')
        url=reverse('stock_receive')
        values=dict(item=self.material.pk,code='C5-NORMAL',quantity=8,
                    expires_on=(timezone.localdate()+timedelta(days=30)).isoformat(),
                    reference='C5-DELIVERY-1',reason='核对已实际收到的八件')
        preview=manager.post(url,values)
        self.assertContains(preview,'C5-NORMAL')
        self.assertFalse(StockLot.objects.exists())
        data=dict(action='confirm',proposal_token=preview.context['form'].initial['proposal_token'],confirmed='on')
        self.assertEqual(manager.post(url,data).status_code,302)
        self.assertEqual(manager.post(url,data).status_code,302)
        self.assertEqual(StockMovement.objects.count(),1)
        self.assertContains(manager.get(reverse('stock_queue')),'在库 8')
        front=WorkspaceClient()
        front.force_login(self.front)
        self.assertEqual(front.get(reverse('stock_detail',args=[StockLot.objects.get().pk])).status_code,403)
        with self.assertRaisesMessage(RuleError,'请选择本店已登记'):
            self.receive(self.drug,actor=self.manager)

    def test_ward_admin_and_quarantined_return_keep_issue_and_batch(self):
        line,lot,issue=self.dispense_with_lot()
        self.assertEqual((issue.requires_batch,stock.available(lot)),(True,1))
        event=self.work('ADMINISTER',issue=issue.pk,quantity=2)
        self.assertEqual(event.issue_id,issue.pk)
        with self.assertRaisesMessage(RuleError,'已实际给药'):
            self.perform('RETURN',line_id=line.pk,issue_id=issue.pk,quantity=3)
        returned=self.perform('RETURN',line_id=line.pk,issue_id=issue.pk,quantity=1)
        self.assertEqual((returned.stock_movement.kind,returned.stock_movement.lot_id),('QUARANTINE',lot.pk))
        self.assertEqual(stock.available(lot),1)
        self.assertFalse(Invoice.objects.exists() or CashEntry.objects.exists() or TreatmentRecord.objects.exists())
        recall=self.inventory(self.rx_user,'RECALL',lot,reference='C5-SYNTHETIC-RECALL')
        self.assertEqual(recall.lot_id,lot.pk)
        with self.assertRaisesMessage(RuleError,'批次已召回'):
            self.perform('ISSUE',line_id=line.pk,quantity=1,lot_id=lot.pk)
        with self.assertRaisesMessage(RuleError,'批次已召回'):
            self.work('ADMINISTER',issue=issue.pk,quantity=1)
        pharmacy=WorkspaceClient()
        pharmacy.force_login(self.rx_user)
        detail=pharmacy.get(reverse('stock_detail',args=[lot.pk]))
        self.assertContains(detail,'按批次追溯')
        self.assertContains(detail,self.visit.patient.patient_no)
        self.assertContains(detail,'退药隔离')
        snapshot = capture(self.visit)
        saved = snapshot['nursing'][0]
        self.assertEqual((saved['issue_id'], saved['issue__stock_movement__lot__code']), (issue.pk, lot.code))
        self.assertEqual((saved['issue__line__name_snapshot'], saved['issue__line__unit_snapshot']),
                         (line.name_snapshot, line.unit_snapshot))
        rendered = next(section['rows'] for section in sections(snapshot) if section['title'] == '实际护理与批次追溯')
        self.assertIn(('条目1 · 原发药批号', lot.code), rendered)

    def test_material_sterility_and_exception_reference_actual_care(self):
        lot=self.receive(self.material,quantity=6).lot
        pack=self.pack()
        with self.assertRaisesMessage(RuleError,'本次有效的实际治疗'):
            self.work('MATERIAL',performed=999,lot=lot.pk,quantity=1)
        actual=self.actual()
        used=self.work('MATERIAL',performed=actual.pk,lot=lot.pk,quantity=2)
        self.assertEqual((used.stock_movement.lot_id,stock.available(lot)),(lot.pk,4))
        sterile=self.work('STERILE',performed=actual.pk,pack=pack.pk)
        self.assertEqual(sterile.sterile_pack_id,pack.pk)
        with self.assertRaisesMessage(RuleError,'未使用的无菌包'):
            self.work('STERILE',performed=actual.pk,pack=pack.pk)
        unused=self.pack('C5-HELD-PACK')
        _,token=nursing.prepare_pack(self.nurse,self.a.pk,'HOLD',dict(pack=unused.pk,reason='演练包装破损'))
        nursing.confirm_pack(self.nurse,token,True)
        with self.assertRaisesMessage(RuleError,'未使用的无菌包'):
            self.work('STERILE',performed=actual.pk,pack=unused.pk)
        self.work('ESCALATE')
        snapshot=capture(self.visit)
        self.assertEqual([row['kind'] for row in snapshot['nursing']],['MATERIAL','STERILE','ESCALATE'])
        self.assertEqual(snapshot['nursing'][0]['stock_movement__lot__code'],lot.code)
        self.assertEqual(TreatmentRecord.objects.count(),1)
        self.assertFalse(Invoice.objects.exists() or CashEntry.objects.exists())

    def test_waste_reversal_expiry_and_insufficient_receipt_reversal(self):
        receipt=self.receive(self.material,quantity=5)
        waste=self.inventory(self.manager,'WASTE',receipt.lot,quantity=2)
        with self.assertRaisesMessage(RuleError,'库存不足以冲回'):
            self.inventory(self.manager,'REVERSE',receipt.lot,movement=receipt.pk)
        self.inventory(self.manager,'REVERSE',receipt.lot,movement=waste.pk)
        self.assertEqual(stock.available(receipt.lot),5)
        with self.assertRaisesMessage(RuleError,'未冲回'):
            self.inventory(self.manager,'REVERSE',receipt.lot,movement=waste.pk)
        expired=StockLot.objects.create(item=self.drug,code='C5-EXPIRED',expires_on=timezone.localdate()-timedelta(days=1))
        line=self.priced()
        with self.assertRaisesMessage(RuleError,'过有效期'):
            self.perform('ISSUE',line_id=line.pk,lot_id=expired.pk,quantity=1)
        self.inventory(self.manager,'REVERSE',receipt.lot,movement=receipt.pk)
        self.assertEqual(stock.available(receipt.lot),0)
        self.assertEqual(receipt.lot.movements.count(),4)

    def race(self,items):
        barrier=Barrier(2,timeout=10)
        def run(item):
            actor,fn,token=item
            close_old_connections()
            try:
                fresh=UserAccount.objects.get(pk=actor.pk)
                fresh._adc_workspace=WorkspaceContext.objects.get(pk=actor._adc_workspace.pk)
                barrier.wait()
                return fn(fresh,token,True)[0].pk
            except RuleError as exc:
                return str(exc)
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run,items))

    def test_two_postgresql_issues_cannot_oversell_one_lot(self):
        line=self.priced()
        lot=self.receive(self.drug,quantity=5,actor=self.rx_user).lot
        tokens=[self.plan('ISSUE',line_id=line.pk,lot_id=lot.pk,quantity=3) for _ in range(2)]
        results=self.race([(self.rx_user,dispensing.confirm,token) for token in tokens])
        self.assertEqual(sum(isinstance(row,int) for row in results),1)
        self.assertTrue(any('可用数量不足' in str(row) for row in results))
        self.assertEqual(stock.available(lot),2)

    def test_admin_return_race_keeps_shared_physical_limit(self):
        line,lot,issue=self.dispense_with_lot()
        a=self.work_token('ADMINISTER',issue=issue.pk,quantity=3)
        b=self.plan('RETURN',line_id=line.pk,issue_id=issue.pk,quantity=3)
        results=self.race([(self.nurse,nursing.confirm,a),(self.rx_user,dispensing.confirm,b)])
        self.assertEqual(sum(isinstance(row,int) for row in results),1)
        self.assertEqual(stock.available(lot),1)
        self.assertEqual(NursingExecution.objects.filter(issue=issue).count()+issue.returns.count(),1)

    def test_nursing_scope_revocation_and_original_patient_isolation(self):
        token=self.work_token('ESCALATE')
        self.provision('nurse','--user',self.nurse.username,'--duty','EXECUTE','--revoke')
        with self.assertRaises(PermissionDenied):
            nursing.confirm(self.nurse,token,True)
        client=WorkspaceClient()
        client.force_login(self.nurse)
        self.assertRedirects(client.get(reverse('nursing_queue')),reverse('sterile_packs'))
        self.assertEqual(client.get(reverse('nursing_detail',args=[self.visit.pk])).status_code,403)
        self.assertFalse(NursingExecution.objects.exists())
        outsider=UserAccount.objects.create_user(username='synthetic_nurse_elsewhere')
        RoleAssignment.objects.create(user=outsider,clinic=self.b,role='NURSE',scope_kind='CLINIC')
        NursingDuty.objects.create(user=outsider,clinic=self.b,kind='EXECUTE',reference='C5-SYNTHETIC',
            valid_from=timezone.now()-timedelta(hours=1),valid_until=timezone.now()+timedelta(hours=1))
        client.force_login(outsider)
        self.assertEqual(client.get(reverse('nursing_detail',args=[self.visit.pk])).status_code,404)

    def test_db_rejects_traced_issue_without_stock_and_history_rewrite(self):
        line=self.priced()
        lot=self.receive(self.drug,actor=self.rx_user).lot
        duty=self.rx_user.prescriptionduty_set.get(clinic=self.a,kind='DISPENSE')
        with self.assertRaisesMessage(DatabaseError,'Traced dispensing needs its stock movement'),transaction.atomic():
            DispenseMovement.objects.create(line=line,kind='ISSUE',quantity=2,actor=self.rx_user,duty=duty,
                reason='受控缺来源负例',requires_batch=True,operation_id=uuid4())
        self.assertEqual(stock.available(lot),5)
        with self.assertRaises(DatabaseError),transaction.atomic():
            StockMovement.objects.update(quantity=10)
        executor=MigrationExecutor(connections['default'])
        with self.assertRaisesMessage(RuntimeError,'Stock or nursing trace history exists'):
            executor.migrate([('supplies','0001_c5_batch_nursing')])
        self.assertEqual(stock.available(lot),5)
