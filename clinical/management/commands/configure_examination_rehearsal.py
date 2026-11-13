from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import RoleAssignment, UserAccount
from accounts.policies import require_writable
from care.audit import emit
from clinical.authority import professional_scope, require_reviewer
from clinical.examination_models import ExaminationDuty, ExaminationProject
from scheduling.resource_models import BookingService


class Command(BaseCommand):
    help = 'Register a text examination project and its duties in a synthetic course instance.'

    def add_arguments(self, parser):
        parser.add_argument('--synthetic-only', action='store_true', required=True)
        parser.add_argument('--operator', required=True)
        parser.add_argument('--service', type=int, required=True)
        parser.add_argument('--code', required=True)
        actions = parser.add_subparsers(dest='action', required=True)
        provision = actions.add_parser('provision')
        provision.add_argument('--name', required=True)
        provision.add_argument('--examiner', required=True)
        provision.add_argument('--reviewer', required=True)
        revoke = actions.add_parser('revoke')
        revoke.add_argument('--user', required=True)
        revoke.add_argument('--duty', choices=ExaminationDuty.Kind.values, required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.ADC_CLINICAL_SYNTHETIC or settings.ADC_READ_ONLY:
            raise CommandError('请在可写的课程合成环境配置检查职责。')
        code = options['code'].strip()
        if not 1 <= len(code) <= 40:
            raise CommandError('项目代码长度须为 1 至 40 字符。')
        names = [options['operator']]
        provision = options['action'] == 'provision'
        names.extend([options['examiner'], options['reviewer']] if provision else [options['user']])
        users = {user.username: user for user in UserAccount.objects.select_for_update()
                 .filter(username__in=names).order_by('pk')}
        if len(users) != len(names):
            raise CommandError('请使用不同且已存在的技术、检查和审核账号。')
        operator = users[options['operator']]
        require_writable(operator)
        if not RoleAssignment.objects.select_for_update().filter(user=operator, role='SYSADMIN',
                scope_kind='TECHNICAL', is_active=True).first():
            raise CommandError('需要有效的技术管理身份。')
        service = BookingService.objects.select_related('department').filter(pk=options['service']).first()
        if not service:
            raise CommandError('找不到指定的本店预约服务。')

        if provision:
            name = options['name'].strip()
            if not 1 <= len(name) <= 100 or not service.is_active:
                raise CommandError('请填写有效项目名称，并核对预约服务处于开放状态。')
            examiner, reviewer = users[options['examiner']], users[options['reviewer']]
            clinic_id = service.department.clinic_id
            try:
                professional_scope(examiner.pk, clinic_id, service.pk, 'RECORD', lock=True)
                require_reviewer(reviewer, clinic_id, lock=True)
                professional_scope(reviewer.pk, clinic_id, service.pk, 'READ', lock=True)
            except PermissionDenied as exc:
                raise CommandError(str(exc)) from exc
            project, created = ExaminationProject.objects.get_or_create(service=service, code=code, defaults={'name': name})
            if not project.is_active or project.name != name:
                raise CommandError('现有项目名称或启用状态不同，请核对项目代码。')
            if created:
                emit(operator, 'EXAMINATION_PROJECT_PROVISIONED', project)
            for user, kind in [(examiner, ExaminationDuty.Kind.EXECUTE), (reviewer, ExaminationDuty.Kind.REVIEW)]:
                duty, added = ExaminationDuty.objects.select_for_update().get_or_create(project=project, user=user, kind=kind)
                if not duty.is_active:
                    duty.is_active = True
                    duty.save(update_fields=['is_active'])
                    added = True
                if added:
                    emit(operator, 'EXAMINATION_DUTY_PROVISIONED', duty, summary={'kind': kind})
            self.stdout.write(f'已核对课程检查项目 #{project.pk} 的职责。')
        else:
            duty = ExaminationDuty.objects.select_for_update().filter(project__service=service, project__code=code,
                user=users[options['user']], kind=options['duty'], is_active=True).first()
            if duty:
                duty.is_active = False
                duty.save(update_fields=['is_active'])
                emit(operator, 'EXAMINATION_DUTY_REVOKED', duty, summary={'kind': duty.kind})
            self.stdout.write('已核对检查职责的撤销状态。')
