"""Retain resource promises and reject cross-clinic physical claims in PostgreSQL."""
from django.db import migrations
SQL=r'''
CREATE FUNCTION adc_resource_plan_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c bigint; vc bigint; oc bigint;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'resource plans are retained' USING ERRCODE='23514'; END IF;
 SELECT d.clinic_id INTO c FROM adc_treatment_room r JOIN adc_department d ON d.id=r.department_id WHERE r.id=NEW.room_id;
 IF NOT EXISTS(SELECT 1 FROM adc_booking_service s JOIN adc_department d ON d.id=s.department_id WHERE s.id=NEW.service_id AND d.clinic_id=c) THEN
  RAISE EXCEPTION 'resource service clinic mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.visit_id IS NOT NULL THEN SELECT clinic_id INTO vc FROM adc_visit WHERE id=NEW.visit_id; END IF;
 IF NEW.offer_id IS NOT NULL THEN SELECT r.clinic_id INTO oc FROM adc_wait_offer o JOIN adc_wait_request r ON r.id=o.request_id WHERE o.id=NEW.offer_id; END IF;
 IF (vc IS NOT NULL AND vc<>c) OR (oc IS NOT NULL AND oc<>c) THEN RAISE EXCEPTION 'resource promise clinic mismatch' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND ((NEW.service_id,NEW.room_id,NEW.snapshot,NEW.version,NEW.reason,NEW.recorded_by_id,NEW.created_at,NEW.offer_id)
   IS DISTINCT FROM (OLD.service_id,OLD.room_id,OLD.snapshot,OLD.version,OLD.reason,OLD.recorded_by_id,OLD.created_at,OLD.offer_id)
   OR (NOT OLD.is_current AND NEW.is_current) OR (OLD.visit_id IS NOT NULL AND NEW.visit_id IS DISTINCT FROM OLD.visit_id)
   OR (OLD.visit_id IS NULL AND NEW.visit_id IS NOT NULL AND OLD.offer_id IS NULL)) THEN
  RAISE EXCEPTION 'resource plan snapshot is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER resource_plan_history BEFORE INSERT OR UPDATE OR DELETE ON adc_resource_plan FOR EACH ROW EXECUTE FUNCTION adc_resource_plan_guard();

CREATE FUNCTION adc_resource_claim_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c bigint; a bigint;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'resource claims are retained' USING ERRCODE='23514'; END IF;
 SELECT d.clinic_id INTO c FROM adc_resource_plan p JOIN adc_treatment_room r ON r.id=p.room_id JOIN adc_department d ON d.id=r.department_id WHERE p.id=NEW.plan_id;
 SELECT clinic_id INTO a FROM adc_equipment_asset WHERE id=NEW.asset_id;
 IF a<>c THEN RAISE EXCEPTION 'resource asset clinic mismatch' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND ((NEW.plan_id,NEW.asset_id,NEW.starts_at,NEW.ends_at) IS DISTINCT FROM (OLD.plan_id,OLD.asset_id,OLD.starts_at,OLD.ends_at)
   OR (NOT OLD.active AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)) OR
   (NEW.kind<>OLD.kind AND NOT (OLD.kind='HOLD' AND NEW.kind='FIRM' AND EXISTS(SELECT 1 FROM adc_resource_plan WHERE id=NEW.plan_id AND visit_id IS NOT NULL)))) THEN
  RAISE EXCEPTION 'resource claim history is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER resource_claim_history BEFORE INSERT OR UPDATE OR DELETE ON adc_resource_claim FOR EACH ROW EXECUTE FUNCTION adc_resource_claim_guard();
CREATE FUNCTION adc_resource_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'resource actions are append-only' USING ERRCODE='23514'; END $$;
CREATE TRIGGER resource_action_history BEFORE UPDATE OR DELETE ON adc_resource_action FOR EACH ROW EXECUTE FUNCTION adc_resource_action_guard();
'''
REVERSE='''DROP TRIGGER resource_action_history ON adc_resource_action; DROP FUNCTION adc_resource_action_guard();
DROP TRIGGER resource_claim_history ON adc_resource_claim; DROP FUNCTION adc_resource_claim_guard();
DROP TRIGGER resource_plan_history ON adc_resource_plan; DROP FUNCTION adc_resource_plan_guard();'''
def refuse_history_reverse(apps,schema_editor):
    if apps.get_model('scheduling','ResourcePlan').objects.exists():raise RuntimeError('Resource history exists; restore to an independent empty database instead.')
class Migration(migrations.Migration):
    dependencies=[('scheduling','0003_department_bookingservice_departmenthours_and_more')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,refuse_history_reverse)]
