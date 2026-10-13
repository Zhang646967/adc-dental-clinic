-- All these guards are authored candidates and require real PostgreSQL acceptance.
-- Local migration owner can create btree_gist; production role separation is future work.
ALTER TABLE adc_invoice ADD CONSTRAINT invoice_same_visit_fk
  FOREIGN KEY (current_record_version_id, visit_id)
  REFERENCES adc_visit_record_version (id, visit_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE adc_treatment_record ADD CONSTRAINT line_amount_exact
  CHECK (line_amount = round(quantity * unit_price, 2));
ALTER TABLE adc_visit_record_version ADD CONSTRAINT snapshots_are_objects
  CHECK (jsonb_typeof(allergy_review_snapshot) = 'object' AND jsonb_typeof(billing_header_snapshot) = 'object');

CREATE FUNCTION adc_check_visit_slot() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s adc_availability_slot%ROWTYPE;
BEGIN
  SELECT * INTO s FROM adc_availability_slot WHERE id=NEW.availability_slot_id FOR UPDATE;
  IF NOT FOUND OR s.dentist_id<>NEW.dentist_id OR s.clinic_id<>NEW.clinic_id
     OR NEW.scheduled_start<s.starts_at OR NEW.scheduled_end>s.ends_at THEN
    RAISE EXCEPTION 'visit does not match its availability slot' USING ERRCODE='23514';
  END IF;
  IF TG_OP='INSERT' AND NOT s.is_active THEN
    RAISE EXCEPTION 'new booking uses an inactive slot' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (NEW.patient_id,NEW.dentist_id,NEW.clinic_id,NEW.availability_slot_id,NEW.scheduled_start,NEW.scheduled_end,NEW.replaces_visit_id,NEW.visit_no)
       IS DISTINCT FROM (OLD.patient_id,OLD.dentist_id,OLD.clinic_id,OLD.availability_slot_id,OLD.scheduled_start,OLD.scheduled_end,OLD.replaces_visit_id,OLD.visit_no) THEN
      RAISE EXCEPTION 'booking identity is immutable; reschedule creates a successor' USING ERRCODE='23514';
    END IF;
    IF OLD.status IN ('COMPLETED','CLOSED_NO_TREATMENT') AND
       (NEW.status,NEW.attended,NEW.attended_at,NEW.completed_at) IS DISTINCT FROM
       (OLD.status,OLD.attended,OLD.attended_at,OLD.completed_at) THEN
      RAISE EXCEPTION 'published visit identity/times cannot be rewritten' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER visit_slot_guard BEFORE INSERT OR UPDATE ON adc_visit
  FOR EACH ROW EXECUTE FUNCTION adc_check_visit_slot();

CREATE FUNCTION adc_protect_slot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.clinic_id,NEW.dentist_id,NEW.starts_at,NEW.ends_at) IS DISTINCT FROM
     (OLD.clinic_id,OLD.dentist_id,OLD.starts_at,OLD.ends_at)
     AND EXISTS (SELECT 1 FROM adc_visit WHERE availability_slot_id=OLD.id) THEN
    RAISE EXCEPTION 'referenced availability identity/times are immutable in v0.3' USING ERRCODE='23514';
  END IF;
  IF NOT NEW.is_active AND EXISTS (SELECT 1 FROM adc_visit WHERE availability_slot_id=OLD.id AND status IN ('SCHEDULED','CHECKED_IN')) THEN
    RAISE EXCEPTION 'resolve unfinished bookings before disabling availability' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER slot_history_guard BEFORE UPDATE ON adc_availability_slot
  FOR EACH ROW EXECUTE FUNCTION adc_protect_slot();

CREATE FUNCTION adc_protect_published_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state='PUBLISHED' THEN
    RAISE EXCEPTION 'published versions are append-only' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (OLD.visit_id,OLD.revision_no) IS DISTINCT FROM (NEW.visit_id,NEW.revision_no) THEN
      RAISE EXCEPTION 'version identity is immutable' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  RETURN OLD;
END $$;
CREATE TRIGGER published_version_guard BEFORE UPDATE OR DELETE ON adc_visit_record_version
  FOR EACH ROW EXECUTE FUNCTION adc_protect_published_version();

CREATE FUNCTION adc_protect_published_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_id bigint; new_id bigint; s text;
BEGIN
  IF TG_OP<>'INSERT' THEN old_id=OLD.record_version_id; END IF;
  IF TG_OP<>'DELETE' THEN new_id=NEW.record_version_id; END IF;
  -- Lock parents in ascending order. Completion must use the same parent lock protocol.
  FOR s IN SELECT state FROM adc_visit_record_version WHERE id IN (old_id,new_id) ORDER BY id FOR UPDATE LOOP
    IF s='PUBLISHED' THEN
      RAISE EXCEPTION 'cannot change lines of a published version' USING ERRCODE='23514';
    END IF;
  END LOOP;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER published_line_guard BEFORE INSERT OR UPDATE OR DELETE ON adc_treatment_record
  FOR EACH ROW EXECUTE FUNCTION adc_protect_published_line();

CREATE FUNCTION adc_protect_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit events are append-only for normal DML' USING ERRCODE='23514';
END $$;
CREATE TRIGGER audit_history_guard BEFORE UPDATE OR DELETE ON adc_audit_event
  FOR EACH ROW EXECUTE FUNCTION adc_protect_audit();

CREATE FUNCTION adc_validate_visit(p_id bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE v adc_visit%ROWTYPE; i adc_invoice%ROWTYPE; r adc_visit_record_version%ROWTYPE;
        n bigint; successor_count bigint; total numeric; bad bigint;
BEGIN
  SELECT * INTO v FROM adc_visit WHERE id=p_id;
  IF NOT FOUND THEN RETURN; END IF;
  SELECT count(*) INTO successor_count FROM adc_visit WHERE replaces_visit_id=p_id;
  IF (v.status='RESCHEDULED') IS DISTINCT FROM (successor_count=1) THEN
    RAISE EXCEPTION 'rescheduling requires exactly one successor' USING ERRCODE='23514';
  END IF;
  IF v.replaces_visit_id IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM adc_visit p WHERE p.id=v.replaces_visit_id AND p.id<v.id AND p.patient_id=v.patient_id AND p.status='RESCHEDULED') THEN
      RAISE EXCEPTION 'invalid rescheduling history' USING ERRCODE='23514';
    END IF;
  END IF;
  SELECT * INTO i FROM adc_invoice WHERE visit_id=p_id;
  IF v.status NOT IN ('COMPLETED','CLOSED_NO_TREATMENT') THEN
    IF FOUND THEN RAISE EXCEPTION 'unfinished visit cannot have an invoice' USING ERRCODE='23514'; END IF;
    IF EXISTS (SELECT 1 FROM adc_visit_record_version WHERE visit_id=p_id AND state='PUBLISHED') THEN
      RAISE EXCEPTION 'unfinished visit cannot have published content' USING ERRCODE='23514';
    END IF;
    RETURN;
  END IF;
  IF NOT FOUND THEN RAISE EXCEPTION 'closed visit requires an invoice' USING ERRCODE='23514'; END IF;
  SELECT * INTO r FROM adc_visit_record_version WHERE id=i.current_record_version_id;
  IF NOT FOUND OR r.visit_id<>p_id OR r.state<>'PUBLISHED' THEN
    RAISE EXCEPTION 'invoice requires a published version of the same visit' USING ERRCODE='23514';
  END IF;
  SELECT count(*),coalesce(sum(line_amount),0),count(*) FILTER(WHERE confirmed_by_id IS NULL OR confirmed_at IS NULL)
    INTO n,total,bad FROM adc_treatment_record WHERE record_version_id=r.id;
  IF total<>r.total_amount OR bad<>0 THEN
    RAISE EXCEPTION 'published total or confirmation inconsistent' USING ERRCODE='23514';
  END IF;
  IF v.status='COMPLETED' AND (r.outcome<>'TREATED' OR n=0) THEN
    RAISE EXCEPTION 'treated completion requires actual treatment lines' USING ERRCODE='23514';
  END IF;
  IF v.status='CLOSED_NO_TREATMENT' AND (r.outcome<>'NO_TREATMENT' OR n<>0 OR total<>0 OR btrim(r.no_treatment_reason)='') THEN
    RAISE EXCEPTION 'no-treatment closure requires zero lines/amount and a reason' USING ERRCODE='23514';
  END IF;
END $$;

CREATE FUNCTION adc_check_visit_final() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_visit bigint; new_visit bigint; parent_id bigint;
BEGIN
  IF TG_TABLE_NAME='adc_visit' THEN
    IF TG_OP<>'INSERT' THEN old_visit=OLD.id; END IF;
    IF TG_OP<>'DELETE' THEN new_visit=NEW.id; END IF;
  ELSIF TG_TABLE_NAME='adc_treatment_record' THEN
    IF TG_OP<>'INSERT' THEN SELECT visit_id INTO old_visit FROM adc_visit_record_version WHERE id=OLD.record_version_id; END IF;
    IF TG_OP<>'DELETE' THEN SELECT visit_id INTO new_visit FROM adc_visit_record_version WHERE id=NEW.record_version_id; END IF;
  ELSE
    IF TG_OP<>'INSERT' THEN old_visit=OLD.visit_id; END IF;
    IF TG_OP<>'DELETE' THEN new_visit=NEW.visit_id; END IF;
  END IF;
  IF old_visit IS NOT NULL THEN PERFORM adc_validate_visit(old_visit); END IF;
  IF new_visit IS NOT NULL AND new_visit IS DISTINCT FROM old_visit THEN PERFORM adc_validate_visit(new_visit); END IF;
  -- Inserting a successor must also validate the predecessor at the same commit.
  IF TG_TABLE_NAME='adc_visit' THEN
    IF TG_OP<>'DELETE' THEN
      IF NEW.replaces_visit_id IS NOT NULL THEN
        PERFORM adc_validate_visit(NEW.replaces_visit_id);
      END IF;
    END IF;
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER adc_visit_final_consistency
AFTER INSERT OR UPDATE OR DELETE ON adc_visit DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final();

CREATE CONSTRAINT TRIGGER adc_visit_record_version_final_consistency
AFTER INSERT OR UPDATE OR DELETE ON adc_visit_record_version DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final();

CREATE CONSTRAINT TRIGGER adc_treatment_record_final_consistency
AFTER INSERT OR UPDATE OR DELETE ON adc_treatment_record DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final();

CREATE CONSTRAINT TRIGGER adc_invoice_final_consistency
AFTER INSERT OR UPDATE OR DELETE ON adc_invoice DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION adc_check_visit_final();
