"""Task notices and immutable recipient ownership; old migrations are untouched."""
from django.db import migrations, models
from django.db.models import Q, F
import django.utils.timezone


def prevent_destructive_reverse(apps, schema_editor):
    alias=schema_editor.connection.alias
    if apps.get_model('notifications','NotificationOutbox').objects.using(alias).exists():
        raise RuntimeError('通知记录已使用；不能直接删除通知表降级。请按停写与备份恢复方案处理。')


GUARDS = """
CREATE FUNCTION adc_notice_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'notification event history is immutable' USING ERRCODE='23514';
  END IF;
  IF (NEW.source_event_id, NEW.task_id, NEW.clinic_id, NEW.task_revision, NEW.action,
      NEW.event_state, NEW.occurred_at, NEW.recipients)
    IS DISTINCT FROM
     (OLD.source_event_id, OLD.task_id, OLD.clinic_id, OLD.task_revision, OLD.action,
      OLD.event_state, OLD.occurred_at, OLD.recipients) THEN
    RAISE EXCEPTION 'notification source and targets are immutable' USING ERRCODE='23514';
  END IF;
  IF OLD.state IN ('DELIVERED','NO_RECIPIENTS') THEN
    RAISE EXCEPTION 'completed notification outcome cannot be rewritten' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER notice_identity_guard BEFORE UPDATE OR DELETE ON adc_notification_outbox
FOR EACH ROW EXECUTE FUNCTION adc_notice_immutable();

CREATE FUNCTION adc_inbox_ownership() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'inbox history cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NOT EXISTS (SELECT 1 FROM adc_role_assignment r JOIN adc_notification_outbox e ON e.id=NEW.event_id
       WHERE r.id=NEW.grant_id AND r.user_id=NEW.recipient_id AND r.role=NEW.role
       AND r.clinic_id=NEW.clinic_id AND r.scope_kind='CLINIC' AND e.clinic_id=NEW.clinic_id
       AND e.recipients @> jsonb_build_array(jsonb_build_object('user_id',NEW.recipient_id,'grant_id',NEW.grant_id,'role',NEW.role))) THEN
      RAISE EXCEPTION 'inbox recipient does not match original event scope' USING ERRCODE='23514';
    END IF;
  ELSIF (NEW.event_id,NEW.recipient_id,NEW.grant_id,NEW.clinic_id,NEW.role,NEW.delivered_at)
        IS DISTINCT FROM (OLD.event_id,OLD.recipient_id,OLD.grant_id,OLD.clinic_id,OLD.role,OLD.delivered_at)
        OR (OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at) THEN
    RAISE EXCEPTION 'inbox ownership and first acknowledgement are immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER inbox_ownership_guard BEFORE INSERT OR UPDATE OR DELETE ON adc_inbox_message
FOR EACH ROW EXECUTE FUNCTION adc_inbox_ownership();
"""


class Migration(migrations.Migration):
    initial=True
    dependencies=[('coordination','0002_coordination_tasks'),('accounts','0001_initial'),('care','0002_database_guards')]
    operations=[
        migrations.CreateModel(name='NotificationOutbox',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('source_event',models.OneToOneField('care.AuditEvent',on_delete=models.PROTECT,related_name='notice_outbox')),
            ('task',models.ForeignKey('coordination.CoordinationTask',on_delete=models.PROTECT)),
            ('clinic',models.ForeignKey('registry.Clinic',on_delete=models.PROTECT)),
            ('task_revision',models.PositiveBigIntegerField()),('action',models.CharField(max_length=12)),
            ('event_state',models.CharField(max_length=12)),('occurred_at',models.DateTimeField()),
            ('recipients',models.JSONField(default=list)),('state',models.CharField(max_length=16,default='PENDING')),
            ('attempts',models.PositiveSmallIntegerField(default=0)),('retry_round',models.PositiveIntegerField(default=0)),
            ('next_attempt_at',models.DateTimeField(default=django.utils.timezone.now,null=True)),
            ('completed_at',models.DateTimeField(null=True)),('delivered_count',models.PositiveIntegerField(default=0)),
            ('suppressed_count',models.PositiveIntegerField(default=0)),('error_code',models.CharField(max_length=24,default='',blank=True)),
        ],options={'db_table':'adc_notification_outbox','indexes':[
            models.Index(fields=['state','next_attempt_at','id'],name='notice_due_idx')],
            'constraints':[
                models.CheckConstraint(condition=Q(state__in=['PENDING','DELIVERED','NO_RECIPIENTS','FAILED']),name='notice_state_valid'),
                models.CheckConstraint(condition=Q(attempts__lte=5),name='notice_attempt_limit'),
                models.CheckConstraint(condition=Q(state='PENDING',next_attempt_at__isnull=False,completed_at__isnull=True) | (~Q(state='PENDING') & Q(next_attempt_at__isnull=True,completed_at__isnull=False)),name='notice_timing_valid'),
                models.CheckConstraint(condition=~Q(state='DELIVERED') | Q(delivered_count__gt=0),name='notice_delivery_nonzero'),
            ]}),
        migrations.CreateModel(name='InboxMessage',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('event',models.ForeignKey('notifications.NotificationOutbox',on_delete=models.PROTECT,related_name='messages')),
            ('recipient',models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)),
            ('grant',models.ForeignKey('accounts.RoleAssignment',on_delete=models.PROTECT)),
            ('clinic',models.ForeignKey('registry.Clinic',on_delete=models.PROTECT)),('role',models.CharField(max_length=16)),
            ('delivered_at',models.DateTimeField(default=django.utils.timezone.now)),('read_at',models.DateTimeField(null=True)),
        ],options={'db_table':'adc_inbox_message','indexes':[
            models.Index(fields=['recipient','clinic','role','read_at'],name='inbox_scope_idx')],
            'constraints':[
                models.UniqueConstraint(fields=['event','grant'],name='inbox_event_grant_unique'),
                models.CheckConstraint(condition=Q(role__in=['FRONT_DESK','MANAGER']),name='inbox_role_valid'),
                models.CheckConstraint(condition=Q(read_at__isnull=True) | Q(read_at__gte=F('delivered_at')),name='inbox_read_after_delivery'),
            ]}),
        migrations.RunSQL(GUARDS, 'DROP TRIGGER IF EXISTS inbox_ownership_guard ON adc_inbox_message; DROP FUNCTION IF EXISTS adc_inbox_ownership(); DROP TRIGGER IF EXISTS notice_identity_guard ON adc_notification_outbox; DROP FUNCTION IF EXISTS adc_notice_immutable();'),
        migrations.RunPython(migrations.RunPython.noop,prevent_destructive_reverse),
    ]
