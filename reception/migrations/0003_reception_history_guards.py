from django.db import migrations
SQL=r'''
CREATE FUNCTION adc_reception_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'reception communications are append-only' USING ERRCODE='23514'; END $$;
CREATE TRIGGER reception_communication_history BEFORE UPDATE OR DELETE ON adc_reception_communication FOR EACH ROW EXECUTE FUNCTION adc_reception_history_guard();
CREATE FUNCTION adc_reception_case_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'reception cases are retained' USING ERRCODE='23514'; END IF;
 IF (NEW.clinic_id,NEW.created_by_id,NEW.created_at)
  IS DISTINCT FROM (OLD.clinic_id,OLD.created_by_id,OLD.created_at)
  OR NEW.revision<>OLD.revision+1 OR (OLD.state IN ('BOOKED','UNBOOKED','WITHDRAWN') AND
  (NEW.state,NEW.patient_id,NEW.visit_id,NEW.wait_request_id,NEW.reason_code) IS DISTINCT FROM (OLD.state,OLD.patient_id,OLD.visit_id,OLD.wait_request_id,OLD.reason_code)) THEN
  RAISE EXCEPTION 'reception identity or concluded outcome is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER reception_case_history BEFORE UPDATE OR DELETE ON adc_reception_case FOR EACH ROW EXECUTE FUNCTION adc_reception_case_guard();
'''
REVERSE='''DROP TRIGGER reception_case_history ON adc_reception_case; DROP FUNCTION adc_reception_case_guard();
DROP TRIGGER reception_communication_history ON adc_reception_communication; DROP FUNCTION adc_reception_history_guard();'''
def refuse_history_reverse(apps,schema_editor):
    if apps.get_model('reception','ReceptionCase').objects.exists():raise RuntimeError('Reception history exists; restore an independent empty database instead.')
class Migration(migrations.Migration):
    dependencies=[('reception','0002_initial')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,refuse_history_reverse)]
