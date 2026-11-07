"""Provision only named synthetic catalogue rows and dated nursing duties."""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from accounts.policies import require_writable
from care.audit import emit
from clinical.prescription_models import PrescriptionCatalogueItem
from registry.models import Clinic
from supplies.access import enabled
from supplies.models import NursingDuty, StockItem


class Command(BaseCommand):
    help='Configure the stock and nursing rehearsal for a named synthetic clinic.'

    def add_arguments(self,parser):
        parser.add_argument('--synthetic-only',action='store_true',required=True)
        parser.add_argument('--operator',required=True)
        parser.add_argument('--clinic',required=True)
        actions=parser.add_subparsers(dest='action',required=True)
        item=actions.add_parser('item')
        item.add_argument('--kind',choices=['MATERIAL','IMPLANT'],required=True)
        item.add_argument('--code',required=True)
        item.add_argument('--name',required=True)
        item.add_argument('--unit',required=True)
        drug=actions.add_parser('drug')
        drug.add_argument('--catalogue-code',required=True)
        duty=actions.add_parser('nurse')
        duty.add_argument('--user',required=True)
        duty.add_argument('--duty',choices=NursingDuty.Kind.values,required=True)
        duty.add_argument('--revoke',action='store_true')

    @transaction.atomic
    def handle(self,*args,**options):
        if not enabled():
            raise CommandError('须在明确启用批次与护理演练的合成实例操作。')
        clinic=Clinic.objects.filter(clinic_code=options['clinic'],is_active=True).first()
        if clinic is None:
            raise CommandError('请填写当前可用的合成诊所代码。')
        names=[options['operator']]
        if options['action']=='nurse':
            if options['user']==options['operator']:
                raise CommandError('维护人员与护理人员须为不同账号。')
            names.append(options['user'])
        users={u.username:u for u in UserAccount.objects.select_for_update().filter(
            username__in=names,is_active=True,
        ).order_by('pk')}
        if len(users)!=len(names):
            raise CommandError('请核对操作员及目标账号均已启用。')
        actor=users[options['operator']]
        require_writable(actor)
        if not RoleAssignment.objects.filter(user=actor,role='SYSADMIN',scope_kind='TECHNICAL',is_active=True).exists():
            raise CommandError('需要有效技术管理授权。')
        if options['action']=='nurse':
            self._duty(actor,users[options['user']],clinic,options)
            return
        if options['action']=='drug':
            source=PrescriptionCatalogueItem.objects.filter(
                clinic=clinic,code=options['catalogue_code'],is_active=True,
            ).first()
            if source is None:
                raise CommandError('请先登记本店合成药品目录。')
            fields=dict(kind='DRUG',code=source.code,name=source.name,unit=source.quantity_unit,prescription_item=source)
        else:
            fields=dict(kind=options['kind'],prescription_item=None)
            for field,limit in [('code',30),('name',100),('unit',16)]:
                value=options[field].strip()
                if not 1<=len(value)<=limit:
                    raise CommandError(f'{field} 须填写 1 至 {limit} 字。')
                fields[field]=value
        Clinic.objects.select_for_update().get(pk=clinic.pk)
        item,created=StockItem.objects.get_or_create(clinic=clinic,code=fields['code'],defaults=fields)
        if any(getattr(item,k)!=v for k,v in fields.items()):
            raise CommandError('本店已有同编号的库存条目，请先核对原记录。')
        if created:
            emit(actor,'STOCK_ITEM_CONFIGURED',item,summary={'clinic':clinic.pk,'kind':item.kind})
        self.stdout.write('合成库存条目已核对。')

    def _duty(self,actor,user,clinic,options):
        now=timezone.now()
        rows=NursingDuty.objects.select_for_update().filter(user=user,clinic=clinic,kind=options['duty'],revoked_at__isnull=True)
        if options['revoke']:
            duty=rows.first()
            if duty:
                duty.revoked_at=now
                duty.save(update_fields=['revoked_at'])
                emit(actor,'NURSING_DUTY_REVOKED',duty,summary={'kind':duty.kind})
            self.stdout.write('护理职责撤销状态已核对。')
            return
        grant,created=RoleAssignment.objects.get_or_create(user=user,clinic=clinic,role='NURSE',scope_kind='CLINIC')
        if not grant.is_active:
            raise CommandError('本店护理身份已停用，请核对原授权。')
        if created:
            emit(actor,'ROLE_ASSIGNED',grant,summary={'role':'NURSE','scope':'CLINIC'})
        duty,created=rows.get_or_create(user=user,clinic=clinic,kind=options['duty'],revoked_at__isnull=True,
            defaults={'reference':'C5-SYNTHETIC-REHEARSAL','valid_from':now,'valid_until':now+timedelta(days=30)})
        if duty.valid_until<=now:
            raise CommandError('原职责已到期，请先撤销旧职责后登记。')
        if created:
            emit(actor,'NURSING_DUTY_CONFIGURED',duty,summary={'kind':duty.kind})
        self.stdout.write('合成护理职责已核对。')
