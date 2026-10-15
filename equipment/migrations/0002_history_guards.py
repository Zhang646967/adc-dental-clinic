"""Additive equipment history guards; existing migrations are unchanged."""
from django.db import migrations

SQL = r"""
CREATE FUNCTION adc_equipment_asset_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'equipment history cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF (NEW.clinic_id,NEW.asset_code,NEW.name,NEW.category,NEW.location,NEW.acquired_on,NEW.acquisition_cost,NEW.registered_by_id,NEW.registered_at)
      IS DISTINCT FROM
     (OLD.clinic_id,OLD.asset_code,OLD.name,OLD.category,OLD.location,OLD.acquired_on,OLD.acquisition_cost,OLD.registered_by_id,OLD.registered_at)
      OR OLD.state='RETIRED' OR NEW.lock_version<>OLD.lock_version+1 THEN
    RAISE EXCEPTION 'equipment identity or revision is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER equipment_asset_history BEFORE UPDATE OR DELETE ON adc_equipment_asset
  FOR EACH ROW EXECUTE FUNCTION adc_equipment_asset_guard();

CREATE FUNCTION adc_equipment_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a adc_equipment_asset%ROWTYPE; p adc_equipment_event%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'equipment events are append-only' USING ERRCODE='23514';
  END IF;
  SELECT * INTO a FROM adc_equipment_asset WHERE id=NEW.asset_id FOR UPDATE;
  IF NOT FOUND OR NEW.sequence<>a.lock_version OR NEW.next_state<>a.state
      OR NEW.next_service_due IS DISTINCT FROM a.next_service_due
      OR NEW.performed_on>(current_timestamp AT TIME ZONE 'Asia/Shanghai')::date THEN
    RAISE EXCEPTION 'equipment event and current asset disagree' USING ERRCODE='23514';
  END IF;
  IF NEW.sequence=0 THEN
    IF NEW.kind<>'REGISTER' OR NEW.previous_state<>'' OR NEW.next_state<>'IN_SERVICE'
       OR NEW.performed_on<>a.acquired_on OR NEW.cost IS DISTINCT FROM a.acquisition_cost
       OR NEW.recorded_by_id<>a.registered_by_id THEN
      RAISE EXCEPTION 'invalid equipment registration event' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO p FROM adc_equipment_event WHERE asset_id=a.id AND sequence=NEW.sequence-1;
    IF NOT FOUND OR NEW.previous_state<>p.next_state OR NEW.performed_on<p.performed_on
       OR NOT ((NEW.kind='MAINTENANCE' AND p.next_state='IN_SERVICE' AND NEW.next_state='MAINTENANCE')
           OR (NEW.kind='SERVICE' AND p.next_state IN ('IN_SERVICE','MAINTENANCE') AND NEW.next_state='IN_SERVICE')
           OR (NEW.kind='RETIRE' AND p.next_state IN ('IN_SERVICE','MAINTENANCE') AND NEW.next_state='RETIRED')) THEN
      RAISE EXCEPTION 'invalid equipment transition history' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER equipment_event_history BEFORE INSERT OR UPDATE OR DELETE ON adc_equipment_event
  FOR EACH ROW EXECUTE FUNCTION adc_equipment_event_guard();

CREATE FUNCTION adc_equipment_final_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a adc_equipment_asset%ROWTYPE; n bigint;
BEGIN
  SELECT * INTO a FROM adc_equipment_asset WHERE id=NEW.id;
  SELECT count(*) INTO n FROM adc_equipment_event WHERE asset_id=a.id;
  IF n<>a.lock_version+1 OR NOT EXISTS (
    SELECT 1 FROM adc_equipment_event WHERE asset_id=a.id AND sequence=a.lock_version
      AND next_state=a.state AND next_service_due IS NOT DISTINCT FROM a.next_service_due) THEN
    RAISE EXCEPTION 'equipment update requires matching retained event' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER equipment_final_consistency AFTER INSERT OR UPDATE ON adc_equipment_asset
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION adc_equipment_final_guard();
"""
REVERSE=r"""
DROP TRIGGER equipment_final_consistency ON adc_equipment_asset;
DROP TRIGGER equipment_event_history ON adc_equipment_event;
DROP TRIGGER equipment_asset_history ON adc_equipment_asset;
DROP FUNCTION adc_equipment_final_guard();
DROP FUNCTION adc_equipment_event_guard();
DROP FUNCTION adc_equipment_asset_guard();
"""
def refuse_history_reverse(apps,schema_editor):
    if apps.get_model('equipment','EquipmentAsset').objects.exists():
        raise RuntimeError('Equipment history exists; restore to an independent empty environment instead of reversing.')

class Migration(migrations.Migration):
    dependencies=[('equipment','0001_initial')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,refuse_history_reverse)]
