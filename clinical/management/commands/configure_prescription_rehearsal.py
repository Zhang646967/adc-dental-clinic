from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from accounts.policies import require_writable
from care.audit import emit
from clinical.prescription_access import rehearsal_enabled
from clinical.prescription_models import PrescriptionCatalogueItem, PrescriptionDuty
from registry.models import Clinic


class Command(BaseCommand):
    help = 'Configure or revoke explicitly synthetic C4.1 duties in an enabled rehearsal.'

    def add_arguments(self, parser):
        parser.add_argument('--synthetic-only', action='store_true', required=True)
        parser.add_argument('--operator', required=True)
        parser.add_argument('--clinic', required=True)
        actions = parser.add_subparsers(dest='action', required=True)
        provision = actions.add_parser('provision')
        provision.add_argument('--prescriber', required=True)
        provision.add_argument('--pharmacist', required=True)
        dispensing = actions.add_parser('dispensing')
        dispensing.add_argument('--pharmacist', required=True)
        dispensing.add_argument('--price', action='append', default=[], metavar='CODE=CNY')
        revoke = actions.add_parser('revoke')
        revoke.add_argument('--user', required=True)
        revoke.add_argument('--duty', choices=PrescriptionDuty.Kind.values, required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if not rehearsal_enabled():
            raise CommandError('须在明确启用处方演练的合成实例操作。')
        clinic = Clinic.objects.filter(clinic_code=options['clinic'], is_active=True).first()
        if clinic is None:
            raise CommandError('请提供当前可用的演练诊所代码。')
        names = [options['operator']]
        if options['action'] == 'provision':
            names.extend([options['prescriber'], options['pharmacist']])
            if len(set(names)) != 3:
                raise CommandError('维护人员、开方医师和药师须使用三个不同账号。')
        elif options['action']=='dispensing':
            names.append(options['pharmacist'])
            if names[0]==names[1]:
                raise CommandError('维护人员和发药药师须为不同账号。')
        else:
            names.append(options['user'])
        accounts = {user.username: user for user in UserAccount.objects.select_for_update()
                    .filter(username__in=names, is_active=True).order_by('pk')}
        if len(accounts) != len(set(names)):
            raise CommandError('请核对操作员和目标账号均已创建并启用。')
        operator = accounts[options['operator']]
        if not RoleAssignment.objects.filter(user=operator, role='SYSADMIN', scope_kind='TECHNICAL', is_active=True).exists():
            raise CommandError('操作员需要有效技术管理权限。')
        require_writable(operator)
        now = timezone.now()
        if options['action']=='dispensing':
            self._configure_dispensing(operator, accounts[options['pharmacist']], clinic, now, options['price'])
            return
        if options['action'] == 'revoke':
            duty = PrescriptionDuty.objects.select_for_update().filter(
                clinic=clinic, user=accounts[options['user']], kind=options['duty'], revoked_at__isnull=True,
            ).first()
            if duty:
                duty.revoked_at = now
                duty.save(update_fields=['revoked_at'])
                emit(operator, 'PRESCRIPTION_DUTY_REVOKED', duty, summary={'kind': duty.kind})
            self.stdout.write('已核对处方职责的撤销状态。')
            return

        doctor = accounts[options['prescriber']]
        if not doctor.dentist_id or not RoleAssignment.objects.filter(
            user=doctor, role='DENTIST', scope_kind='SELF_DENTIST', is_active=True,
        ).exists():
            raise CommandError('开方人须已有有效医师身份和人员关联。')
        reviewer = accounts[options['pharmacist']]
        for user, kind in [(doctor, PrescriptionDuty.Kind.PRESCRIBE), (reviewer, PrescriptionDuty.Kind.REVIEW)]:
            duty, created = PrescriptionDuty.objects.get_or_create(
                user=user, clinic=clinic, kind=kind, revoked_at__isnull=True,
                defaults={'reference': 'C41-SYNTHETIC-REHEARSAL', 'valid_from': now, 'valid_until': now + timedelta(days=30)},
            )
            if duty.valid_until <= now:
                raise CommandError('原职责已到期，请先撤销旧职责后再登记。')
            if created:
                emit(operator, 'PRESCRIPTION_DUTY_PROVISIONED', duty, summary={'kind': kind})
        grant, created = RoleAssignment.objects.get_or_create(
            user=reviewer, clinic=clinic, role='PHARMACIST', scope_kind='CLINIC',
        )
        if not grant.is_active:
            raise CommandError('药师工作身份已停用，请先核对原授权。')
        if created:
            emit(operator, 'ROLE_ASSIGNED', grant, summary={'role': 'PHARMACIST', 'scope': 'CLINIC'})
        for code, name, route, unit in [
            ('C41-SIM-A', '合成目录条目甲', 'ORAL', '演练片'),
            ('C41-SIM-B', '合成目录条目乙', 'LOCAL', '演练份'),
        ]:
            PrescriptionCatalogueItem.objects.get_or_create(
                clinic=clinic, code=code,
                defaults={'name': name, 'strength': '课程虚构规格', 'route': route, 'dose_unit': unit, 'quantity_unit': unit},
            )
        self.stdout.write('合成处方目录和三十天岗位职责已核对。')


    def _configure_dispensing(self, operator, user, clinic, now, prices):
        from clinical.dispensing import enabled
        if not enabled():
            raise CommandError('须明确启用合成发药演练。')
        if not RoleAssignment.objects.filter(
            user=user, clinic=clinic, role='PHARMACIST', scope_kind='CLINIC', is_active=True,
        ).exists():
            raise CommandError('请先登记有效的本店药师工作身份。')
        duty, created = PrescriptionDuty.objects.get_or_create(
            user=user, clinic=clinic, kind=PrescriptionDuty.Kind.DISPENSE, revoked_at__isnull=True,
            defaults={'reference':'C42-SYNTHETIC-REHEARSAL', 'valid_from':now, 'valid_until':now+timedelta(days=30)},
        )
        if duty.valid_until <= now:
            raise CommandError('原发药职责已到期，请先撤销再登记。')
        if created:
            emit(operator,'PRESCRIPTION_DUTY_PROVISIONED',duty,summary={'kind':duty.kind})
        catalogue = {row.code:row for row in PrescriptionCatalogueItem.objects.select_for_update().filter(
            clinic=clinic, is_active=True,
        ).order_by('pk')}
        updated = set()
        for entry in prices:
            code, separator, amount = entry.partition('=')
            if not separator or code in updated or code not in catalogue:
                raise CommandError('每个本店启用的目录代码只能填写一次单价。')
            try:
                price = Decimal(amount)
            except InvalidOperation as exc:
                raise CommandError('请填写有效的人民币单价。') from exc
            if not price.is_finite() or not 0 < price <= Decimal('99999999.99') or price.as_tuple().exponent < -2:
                raise CommandError('单价须大于零，最多两位小数。')
            row = catalogue[code]
            if row.rehearsal_unit_price != price:
                row.rehearsal_unit_price = price
                row.save(update_fields=['rehearsal_unit_price'])
                emit(operator,'PHARMACY_PRICE_CONFIGURED',row,summary={'currency':'CNY'})
            updated.add(code)
        self.stdout.write('合成发药职责和指定单价已核对。')
