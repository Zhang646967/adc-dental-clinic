"""Additive work-order history and exact service linkage guards."""
from django.db import migrations

SQL = r"""
CREATE FUNCTION adc_maintenance_snapshot(o adc_maintenance_order) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('state',o.state,'owner',o.assigned_to_id,'due',o.due_on::text,
 'performed',o.performed_on::text,'cost',o.cost::text,'next_due',o.next_service_due::text,
 'evidence',o.completion_note,'schedule_checked',o.schedule_checked,'submitter',o.submitted_by_id,
 'reviewer',o.reviewed_by_id,'service_event',o.service_event_id)
$$;
CREATE FUNCTION adc_maintenance_order_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a adc_equipment_asset%ROWTYPE; source adc_equipment_event%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'maintenance history cannot be deleted' USING ERRCODE='23514'; END IF;
 SELECT * INTO a FROM adc_equipment_asset WHERE id=NEW.asset_id FOR UPDATE;
 SELECT * INTO source FROM adc_equipment_event WHERE id=NEW.maintenance_event_id;
 IF source.asset_id IS DISTINCT FROM a.id OR source.kind IS DISTINCT FROM 'MAINTENANCE' OR btrim(NEW.issue)='' THEN
  RAISE EXCEPTION 'maintenance requires its own stop-use source' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'ASSIGNED' OR NEW.lock_version<>0 OR a.state<>'MAINTENANCE' OR a.lock_version<>source.sequence
     OR NEW.due_on<(now() AT TIME ZONE 'Asia/Shanghai')::date THEN
   RAISE EXCEPTION 'maintenance must start assigned against current stop-use source' USING ERRCODE='23514';
  END IF;
 ELSE
  IF OLD.state IN ('CLOSED','CANCELLED') OR NEW.lock_version<>OLD.lock_version+1
     OR (NEW.asset_id,NEW.maintenance_event_id,NEW.issue,NEW.created_by_id,NEW.created_at)
        IS DISTINCT FROM (OLD.asset_id,OLD.maintenance_event_id,OLD.issue,OLD.created_by_id,OLD.created_at)
     OR NOT ((OLD.state='ASSIGNED' AND NEW.state IN ('ASSIGNED','IN_PROGRESS','CANCELLED'))
       OR (OLD.state='IN_PROGRESS' AND NEW.state IN ('ASSIGNED','READY','CANCELLED'))
       OR (OLD.state='READY' AND NEW.state IN ('IN_PROGRESS','CLOSED'))) THEN
   RAISE EXCEPTION 'invalid maintenance transition or immutable origin' USING ERRCODE='23514';
  END IF;
  IF (NEW.assigned_to_id,NEW.due_on) IS DISTINCT FROM (OLD.assigned_to_id,OLD.due_on) AND
     (NEW.state<>'ASSIGNED' OR NEW.due_on<(now() AT TIME ZONE 'Asia/Shanghai')::date) THEN
   RAISE EXCEPTION 'assignment requires explicit new current deadline' USING ERRCODE='23514';
  END IF;
  IF NEW.state='CLOSED' AND ((NEW.performed_on,NEW.cost,NEW.next_service_due,NEW.completion_note,NEW.schedule_checked,NEW.submitted_by_id,NEW.submitted_at)
       IS DISTINCT FROM (OLD.performed_on,OLD.cost,OLD.next_service_due,OLD.completion_note,OLD.schedule_checked,OLD.submitted_by_id,OLD.submitted_at)
       OR btrim(NEW.review_reason)='' OR NEW.reviewed_at<NEW.submitted_at) THEN
   RAISE EXCEPTION 'acceptance must retain submitted repair evidence' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.state IN ('READY','CLOSED') AND
    (NEW.performed_on<source.performed_on OR NEW.performed_on>(now() AT TIME ZONE 'Asia/Shanghai')::date
     OR NEW.next_service_due<=NEW.performed_on OR btrim(NEW.completion_note)='' OR NEW.submitted_at<NEW.created_at) THEN
  RAISE EXCEPTION 'invalid repair facts' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER maintenance_order_history BEFORE INSERT OR UPDATE OR DELETE ON adc_maintenance_order
 FOR EACH ROW EXECUTE FUNCTION adc_maintenance_order_guard();
CREATE FUNCTION adc_maintenance_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE o adc_maintenance_order%ROWTYPE; p adc_maintenance_action%ROWTYPE; oldstate text; oldowner bigint;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'maintenance action immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO o FROM adc_maintenance_order WHERE id=NEW.order_id;
 IF NOT FOUND OR NEW.sequence<>o.lock_version OR NEW.snapshot IS DISTINCT FROM adc_maintenance_snapshot(o) OR btrim(NEW.note)='' THEN
  RAISE EXCEPTION 'maintenance action must match current projection' USING ERRCODE='23514';
 END IF;
 IF NEW.sequence=0 THEN
  IF NEW.action<>'OPEN' OR o.state<>'ASSIGNED' OR NEW.actor_id<>o.created_by_id THEN
   RAISE EXCEPTION 'maintenance requires original open action' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO p FROM adc_maintenance_action WHERE order_id=o.id AND sequence=NEW.sequence-1;
  oldstate=p.snapshot->>'state';oldowner=(p.snapshot->>'owner')::bigint;
  IF NOT FOUND OR NOT ((NEW.action='START' AND oldstate='ASSIGNED' AND o.state='IN_PROGRESS')
    OR (NEW.action='ASSIGN' AND oldstate IN ('ASSIGNED','IN_PROGRESS') AND o.state='ASSIGNED')
    OR (NEW.action='SUBMIT' AND oldstate='IN_PROGRESS' AND o.state='READY')
    OR (NEW.action IN ('RETURN','WITHDRAW') AND oldstate='READY' AND o.state='IN_PROGRESS')
    OR (NEW.action='APPROVE' AND oldstate='READY' AND o.state='CLOSED')
    OR (NEW.action='CANCEL' AND oldstate IN ('ASSIGNED','IN_PROGRESS') AND o.state='CANCELLED')) THEN
   RAISE EXCEPTION 'maintenance action sequence invalid' USING ERRCODE='23514';
  END IF;
  IF NEW.action<>'ASSIGN' AND (NEW.snapshot->'owner',NEW.snapshot->'due') IS DISTINCT FROM (p.snapshot->'owner',p.snapshot->'due') THEN
   RAISE EXCEPTION 'responsibility changes require assignment action' USING ERRCODE='23514';
  END IF;
  IF NEW.action='ASSIGN' AND (NEW.snapshot->'owner',NEW.snapshot->'due') IS NOT DISTINCT FROM (p.snapshot->'owner',p.snapshot->'due') THEN
   RAISE EXCEPTION 'assignment must change responsibility or deadline' USING ERRCODE='23514';
  END IF;
  IF (NEW.action IN ('START','SUBMIT','WITHDRAW') AND NEW.actor_id<>oldowner)
     OR (NEW.action IN ('RETURN','APPROVE') AND NEW.actor_id=oldowner)
     OR (NEW.action='SUBMIT' AND NEW.actor_id<>o.submitted_by_id)
     OR (NEW.action='APPROVE' AND (NEW.actor_id<>o.reviewed_by_id OR NEW.note<>o.review_reason)) THEN
   RAISE EXCEPTION 'maintenance owner and independent reviewer mismatch' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER maintenance_action_history BEFORE INSERT OR UPDATE OR DELETE ON adc_maintenance_action
 FOR EACH ROW EXECUTE FUNCTION adc_maintenance_action_guard();
CREATE FUNCTION adc_maintenance_final_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE o adc_maintenance_order%ROWTYPE; a adc_equipment_asset%ROWTYPE; source adc_equipment_event%ROWTYPE;
        step adc_maintenance_action%ROWTYPE; service adc_equipment_event%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='adc_equipment_asset' THEN
  SELECT * INTO a FROM adc_equipment_asset WHERE id=NEW.id;
  IF EXISTS (SELECT 1 FROM adc_maintenance_order w JOIN adc_equipment_event e ON e.id=w.maintenance_event_id
      WHERE w.asset_id=a.id AND w.state IN ('ASSIGNED','IN_PROGRESS','READY') AND
       (a.state<>'MAINTENANCE' OR a.lock_version<>e.sequence)) THEN
   RAISE EXCEPTION 'finish maintenance responsibility before changing equipment state' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM adc_equipment_event e JOIN adc_equipment_event stop ON stop.asset_id=e.asset_id AND stop.sequence=e.sequence-1
      WHERE e.asset_id=a.id AND e.sequence=a.lock_version AND e.kind='SERVICE' AND e.previous_state='MAINTENANCE'
       AND EXISTS (SELECT 1 FROM adc_maintenance_order w WHERE w.maintenance_event_id=stop.id)
       AND NOT EXISTS (SELECT 1 FROM adc_maintenance_order w WHERE w.maintenance_event_id=stop.id AND w.state='CLOSED' AND w.service_event_id=e.id)) THEN
   RAISE EXCEPTION 'managed repair requires independent acceptance even after cancellation' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
 END IF;
 SELECT * INTO o FROM adc_maintenance_order WHERE id=NEW.id;
 SELECT * INTO a FROM adc_equipment_asset WHERE id=o.asset_id;
 SELECT * INTO source FROM adc_equipment_event WHERE id=o.maintenance_event_id;
 SELECT * INTO step FROM adc_maintenance_action WHERE order_id=o.id AND sequence=o.lock_version;
 IF NOT FOUND OR step.snapshot IS DISTINCT FROM adc_maintenance_snapshot(o) THEN
  RAISE EXCEPTION 'maintenance requires matching retained action' USING ERRCODE='23514';
 END IF;
 IF o.state IN ('ASSIGNED','IN_PROGRESS','READY') AND (a.state<>'MAINTENANCE' OR a.lock_version<>source.sequence) THEN
  RAISE EXCEPTION 'open maintenance source no longer current' USING ERRCODE='23514';
 END IF;
 IF o.state='CLOSED' THEN
  SELECT * INTO service FROM adc_equipment_event WHERE id=o.service_event_id;
  IF NOT FOUND OR service.asset_id<>o.asset_id OR service.sequence<>source.sequence+1 OR service.kind<>'SERVICE'
    OR service.previous_state<>'MAINTENANCE' OR service.next_state<>'IN_SERVICE' OR service.recorded_by_id<>o.reviewed_by_id
    OR (service.performed_on,service.cost,service.next_service_due,service.note,service.operation_id)
     IS DISTINCT FROM (o.performed_on,o.cost,o.next_service_due,o.completion_note,step.operation_id) THEN
   RAISE EXCEPTION 'accepted maintenance requires exact service event linkage' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER maintenance_final_consistency AFTER INSERT OR UPDATE ON adc_maintenance_order
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_maintenance_final_guard();
CREATE CONSTRAINT TRIGGER maintenance_asset_consistency AFTER INSERT OR UPDATE ON adc_equipment_asset
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_maintenance_final_guard();
"""
REVERSE = 'DROP TRIGGER maintenance_asset_consistency ON adc_equipment_asset;\nDROP TRIGGER maintenance_final_consistency ON adc_maintenance_order;\nDROP TRIGGER maintenance_action_history ON adc_maintenance_action;\nDROP TRIGGER maintenance_order_history ON adc_maintenance_order;\nDROP FUNCTION adc_maintenance_final_guard(); DROP FUNCTION adc_maintenance_action_guard();\nDROP FUNCTION adc_maintenance_order_guard(); DROP FUNCTION adc_maintenance_snapshot(adc_maintenance_order);'

def refuse_reverse(apps,schema_editor):
    if apps.get_model('equipment','MaintenanceOrder').objects.exists():
        raise RuntimeError('Maintenance history exists; restore only into a separate empty environment.')

class Migration(migrations.Migration):
    dependencies=[('equipment','0005_maintenanceorder_maintenanceaction_and_more')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,refuse_reverse)]
