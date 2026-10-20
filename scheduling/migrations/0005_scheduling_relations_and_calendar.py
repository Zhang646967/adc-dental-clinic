"""Bind resource locations and promises to their actual business source.

No history is fabricated or rewritten. Interval checks use the retained visit or
invitation, rather than today's editable service duration.
"""
from django.db import migrations,models

SQL=r'''
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM adc_resource_binding b JOIN adc_equipment_asset a ON a.id=b.asset_id
 LEFT JOIN adc_treatment_room r ON r.id=b.room_id LEFT JOIN adc_department d ON d.id=r.department_id
 WHERE (b.room_id IS NOT NULL AND d.clinic_id<>a.clinic_id) OR (a.category='CHAIR' AND b.shared)) THEN
 RAISE EXCEPTION 'Review existing resource binding clinic/chair relationships before migration'; END IF;
 IF EXISTS(SELECT 1 FROM adc_resource_block b LEFT JOIN adc_department d ON d.id=b.department_id
 LEFT JOIN adc_treatment_room r ON r.id=b.room_id LEFT JOIN adc_department rd ON rd.id=r.department_id
 LEFT JOIN adc_equipment_asset a ON a.id=b.asset_id
 WHERE coalesce(d.clinic_id,rd.clinic_id,a.clinic_id)<>b.clinic_id) THEN
 RAISE EXCEPTION 'Review existing resource block clinic relationships before migration'; END IF;
 IF EXISTS(SELECT 1 FROM adc_resource_plan p JOIN adc_booking_service s ON s.id=p.service_id
 JOIN adc_treatment_room r ON r.id=p.room_id WHERE s.department_id<>r.department_id) THEN
 RAISE EXCEPTION 'Review existing resource plan departments before migration'; END IF;
 IF EXISTS(SELECT 1 FROM adc_resource_plan p JOIN adc_visit v ON v.id=p.visit_id
 JOIN adc_wait_offer o ON o.id=p.offer_id JOIN adc_wait_request w ON w.id=o.request_id JOIN adc_availability_slot os ON os.id=o.slot_id
 WHERE (v.patient_id,v.clinic_id,v.dentist_id,v.availability_slot_id,v.scheduled_start,v.scheduled_end)
 IS DISTINCT FROM (w.patient_id,w.clinic_id,os.dentist_id,o.slot_id,o.starts_at,o.ends_at)) THEN
 RAISE EXCEPTION 'Review existing dual-source resource promises before migration'; END IF;
 IF EXISTS(SELECT 1 FROM adc_resource_claim c JOIN adc_resource_plan p ON p.id=c.plan_id
 LEFT JOIN adc_visit v ON v.id=p.visit_id LEFT JOIN adc_wait_offer o ON o.id=p.offer_id
 WHERE (c.starts_at,c.ends_at) IS DISTINCT FROM (coalesce(v.scheduled_start,o.starts_at),coalesce(v.scheduled_end,o.ends_at))) THEN
 RAISE EXCEPTION 'Review existing full-interval resource claims before migration'; END IF;
END $$;

CREATE FUNCTION adc_scheduling_relation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_start timestamptz;source_end timestamptz;
BEGIN
 IF TG_TABLE_NAME='adc_resource_binding' THEN
  IF EXISTS(SELECT 1 FROM adc_equipment_asset a LEFT JOIN adc_treatment_room r ON r.id=NEW.room_id
    LEFT JOIN adc_department d ON d.id=r.department_id WHERE a.id=NEW.asset_id AND
    ((NEW.room_id IS NOT NULL AND d.clinic_id<>a.clinic_id) OR (a.category='CHAIR' AND NEW.shared))) THEN
   RAISE EXCEPTION 'resource binding clinic/chair mismatch' USING ERRCODE='23514',CONSTRAINT='binding_clinic_chair_relation'; END IF;
 ELSIF TG_TABLE_NAME='adc_resource_block' THEN
  IF coalesce((SELECT clinic_id FROM adc_department WHERE id=NEW.department_id),
    (SELECT d.clinic_id FROM adc_treatment_room r JOIN adc_department d ON d.id=r.department_id WHERE r.id=NEW.room_id),
    (SELECT clinic_id FROM adc_equipment_asset WHERE id=NEW.asset_id)) IS DISTINCT FROM NEW.clinic_id THEN
   RAISE EXCEPTION 'resource block clinic mismatch' USING ERRCODE='23514',CONSTRAINT='block_clinic_relation'; END IF;
 ELSIF TG_TABLE_NAME='adc_resource_plan' THEN
  IF (SELECT department_id FROM adc_booking_service WHERE id=NEW.service_id) IS DISTINCT FROM
    (SELECT department_id FROM adc_treatment_room WHERE id=NEW.room_id) THEN
   RAISE EXCEPTION 'resource plan department mismatch' USING ERRCODE='23514',CONSTRAINT='plan_department_relation'; END IF;
  IF NEW.visit_id IS NOT NULL AND NEW.offer_id IS NOT NULL AND EXISTS(
    SELECT 1 FROM adc_visit v,adc_wait_offer o JOIN adc_wait_request w ON w.id=o.request_id JOIN adc_availability_slot os ON os.id=o.slot_id
    WHERE v.id=NEW.visit_id AND o.id=NEW.offer_id AND
    (v.patient_id,v.clinic_id,v.dentist_id,v.availability_slot_id,v.scheduled_start,v.scheduled_end)
      IS DISTINCT FROM (w.patient_id,w.clinic_id,os.dentist_id,o.slot_id,o.starts_at,o.ends_at)) THEN
   RAISE EXCEPTION 'resource plan visit/offer mismatch' USING ERRCODE='23514',CONSTRAINT='plan_source_relation'; END IF;
 ELSIF TG_TABLE_NAME='adc_resource_claim' THEN
  SELECT coalesce(v.scheduled_start,o.starts_at),coalesce(v.scheduled_end,o.ends_at) INTO source_start,source_end
   FROM adc_resource_plan p LEFT JOIN adc_visit v ON v.id=p.visit_id LEFT JOIN adc_wait_offer o ON o.id=p.offer_id WHERE p.id=NEW.plan_id;
  IF (NEW.starts_at,NEW.ends_at) IS DISTINCT FROM (source_start,source_end) THEN
   RAISE EXCEPTION 'resource claim source interval mismatch' USING ERRCODE='23514',CONSTRAINT='claim_source_interval_relation'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER binding_business_relation BEFORE INSERT OR UPDATE ON adc_resource_binding FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard();
CREATE TRIGGER block_business_relation BEFORE INSERT OR UPDATE ON adc_resource_block FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard();
CREATE TRIGGER plan_business_relation BEFORE INSERT OR UPDATE ON adc_resource_plan FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard();
CREATE TRIGGER claim_business_relation BEFORE INSERT OR UPDATE ON adc_resource_claim FOR EACH ROW EXECUTE FUNCTION adc_scheduling_relation_guard();
'''
REVERSE='''DROP TRIGGER claim_business_relation ON adc_resource_claim;
DROP TRIGGER plan_business_relation ON adc_resource_plan;
DROP TRIGGER block_business_relation ON adc_resource_block;
DROP TRIGGER binding_business_relation ON adc_resource_binding;
DROP FUNCTION adc_scheduling_relation_guard();'''
class Migration(migrations.Migration):
    dependencies=[('scheduling','0004_resource_history_guards'),('coordination','0004_frontdesk_followup_and_offer_index')]
    operations=[migrations.AddIndex(model_name='availabilityslot',index=models.Index(fields=['clinic','starts_at'],name='slot_clinic_start_idx')),
        migrations.RunSQL(SQL,REVERSE)]
