"""Add coordination tasks; refusal to reverse after task history exists."""
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q, F


def guard_reverse(apps, schema_editor):
    alias = schema_editor.connection.alias
    if apps.get_model('coordination','CoordinationTask').objects.using(alias).exists():
        raise RuntimeError('协调任务已被使用，不能直接删表降级。请按停写、备份和恢复计划处理。')


TASK_GUARD_SQL = """
CREATE FUNCTION adc_protect_coord_task() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'coordination task history cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF OLD.state IN ('CLOSED','CANCELLED') THEN
    RAISE EXCEPTION 'terminal coordination tasks are immutable' USING ERRCODE='23514';
  END IF;
  IF (NEW.slot_id,NEW.created_by_id,NEW.created_at,NEW.purpose,NEW.opening_reason,NEW.creation_operation)
      IS DISTINCT FROM (OLD.slot_id,OLD.created_by_id,OLD.created_at,OLD.purpose,OLD.opening_reason,OLD.creation_operation) THEN
    RAISE EXCEPTION 'coordination task identity is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.revision <> OLD.revision + 1 THEN
    RAISE EXCEPTION 'coordination task update requires next revision' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER coordination_task_history_guard BEFORE UPDATE OR DELETE ON adc_coordination_task
FOR EACH ROW EXECUTE FUNCTION adc_protect_coord_task();
"""

class Migration(migrations.Migration):
    dependencies = [('coordination','0001_initial'),('scheduling','0002_slot_intake_control'),
                    ('care','0002_database_guards'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='CoordinationTask',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('slot',models.ForeignKey('scheduling.AvailabilitySlot', on_delete=models.PROTECT,
                             related_name='coordination_tasks')),
            ('purpose',models.CharField(max_length=12, choices=[('DEACTIVATE','为停用原出诊协调'),('REPLACE','为调整原出诊协调')])),
            ('opening_reason',models.CharField(max_length=24, choices=[('PLAN_CHANGE','出诊计划变化'),('STAFF_UNAVAILABLE','人员安排变化')])),
            ('creation_operation',models.UUIDField(unique=True, editable=False)),
            ('state',models.CharField(max_length=12, default='OPEN', choices=[('OPEN','待前台受理'),('IN_PROGRESS','前台协调中'),('READY','待主管复核'),('CLOSED','协调核对已通过'),('CANCELLED','任务已撤销')])),
            ('created_by',models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='coordination_tasks_created')),
            ('assignee',models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='coordination_tasks_assigned')),
            ('submitted_by',models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='coordination_tasks_submitted')),
            ('submitted_at',models.DateTimeField(null=True, blank=True)),
            ('submitted_digest',models.CharField(max_length=64, default='', blank=True)),
            ('closed_by',models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='coordination_tasks_closed')),
            ('closed_at',models.DateTimeField(null=True, blank=True)),
            ('revision',models.PositiveIntegerField(default=0)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('updated_at',models.DateTimeField(auto_now=True)),
        ],options={
            'db_table':'adc_coordination_task',
            'ordering':['-created_at','-id'],
            'indexes':[models.Index(fields=['state','created_at'],name='coord_task_queue_idx')],
            'constraints':[
            models.UniqueConstraint(fields=['slot'], condition=Q(state__in=['OPEN','IN_PROGRESS','READY']), name='coord_task_one_active_slot'),
            models.CheckConstraint(condition=Q(state__in=['OPEN','IN_PROGRESS','READY','CLOSED','CANCELLED']),name='coord_task_state_valid'),
            models.CheckConstraint(condition=Q(purpose__in=['DEACTIVATE','REPLACE']),name='coord_task_purpose_valid'),
            models.CheckConstraint(condition=Q(opening_reason__in=['PLAN_CHANGE','STAFF_UNAVAILABLE']),name='coord_task_reason_valid'),
            models.CheckConstraint(condition=Q(state='OPEN',assignee__isnull=True) | Q(state__in=['IN_PROGRESS','READY','CLOSED'],assignee__isnull=False) | Q(state='CANCELLED'),name='coord_task_owner_valid'),
            models.CheckConstraint(condition=(Q(state__in=['READY','CLOSED'],submitted_by__isnull=False,submitted_at__isnull=False) & ~Q(submitted_digest='')) | (~Q(state__in=['READY','CLOSED']) & Q(submitted_by__isnull=True,submitted_at__isnull=True,submitted_digest='')),name='coord_task_submit_valid'),
            models.CheckConstraint(condition=~Q(state__in=['READY','CLOSED']) | Q(submitted_by=F('assignee')),name='coord_task_submit_owner'),
            models.CheckConstraint(condition=Q(state__in=['CLOSED','CANCELLED'],closed_by__isnull=False,closed_at__isnull=False) | (~Q(state__in=['CLOSED','CANCELLED']) & Q(closed_by__isnull=True,closed_at__isnull=True)),name='coord_task_close_valid'),
            models.CheckConstraint(condition=~Q(state='CLOSED') | ~Q(closed_by=F('submitted_by')),name='coord_task_separate_review'),
        ],
        }),
        migrations.RunSQL(TASK_GUARD_SQL,'DROP TRIGGER IF EXISTS coordination_task_history_guard ON adc_coordination_task; DROP FUNCTION IF EXISTS adc_protect_coord_task();'),
        migrations.RunPython(migrations.RunPython.noop,guard_reverse),
    ]
