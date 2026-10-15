"""Append-only cash facts, correct source lineage and independent terminal review."""
from django.db import migrations

SQL=r"""
CREATE FUNCTION adc_cash_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE i adc_invoice%ROWTYPE; a adc_equipment_asset%ROWTYPE; e adc_equipment_event%ROWTYPE;
        original adc_cash_entry%ROWTYPE; clinic bigint; vstate text; vvisit bigint;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'cash history cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.state<>'PENDING' OR NEW.lock_version<>0 OR NEW.review_reason<>'' THEN
      RAISE EXCEPTION 'cash entry starts as an unreviewed request' USING ERRCODE='23514';
    END IF;
  ELSE
    IF OLD.state<>'PENDING' OR NEW.state NOT IN ('POSTED','REJECTED') OR NEW.lock_version<>1
       OR (NEW.operation_id,NEW.clinic_id,NEW.invoice_id,NEW.based_record_version_id,NEW.equipment_event_id,
           NEW.reversal_of_id,NEW.kind,NEW.amount,NEW.occurred_on,NEW.reason,NEW.prepared_by_id,NEW.prepared_at)
         IS DISTINCT FROM
          (OLD.operation_id,OLD.clinic_id,OLD.invoice_id,OLD.based_record_version_id,OLD.equipment_event_id,
           OLD.reversal_of_id,OLD.kind,OLD.amount,OLD.occurred_on,OLD.reason,OLD.prepared_by_id,OLD.prepared_at)
       OR btrim(NEW.review_reason)='' OR NEW.reviewed_at<NEW.prepared_at THEN
      RAISE EXCEPTION 'cash request facts and terminal decisions are immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.invoice_id IS NOT NULL THEN
    SELECT * INTO i FROM adc_invoice WHERE id=NEW.invoice_id;
    SELECT clinic_id INTO clinic FROM adc_visit WHERE id=i.visit_id;
    SELECT state,visit_id INTO vstate,vvisit FROM adc_visit_record_version WHERE id=NEW.based_record_version_id;
    IF clinic IS DISTINCT FROM NEW.clinic_id OR vstate IS DISTINCT FROM 'PUBLISHED' OR vvisit IS DISTINCT FROM i.visit_id
       OR (NEW.state<>'REJECTED' AND i.current_record_version_id<>NEW.based_record_version_id) THEN
      RAISE EXCEPTION 'cash request requires its own current published bill' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO e FROM adc_equipment_event WHERE id=NEW.equipment_event_id;
    SELECT * INTO a FROM adc_equipment_asset WHERE id=e.asset_id;
    IF a.clinic_id IS DISTINCT FROM NEW.clinic_id OR e.kind NOT IN ('REGISTER','SERVICE')
       OR e.cost IS NULL OR e.cost<=0 OR NEW.amount<>e.cost THEN
      RAISE EXCEPTION 'equipment cash request requires its matching recorded fee' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.reversal_of_id IS NOT NULL THEN
    SELECT * INTO original FROM adc_cash_entry WHERE id=NEW.reversal_of_id;
    IF NOT FOUND OR original.state<>'POSTED' OR original.reversal_of_id IS NOT NULL OR original.amount<>NEW.amount
       OR original.clinic_id<>NEW.clinic_id OR original.invoice_id IS DISTINCT FROM NEW.invoice_id
       OR original.equipment_event_id IS DISTINCT FROM NEW.equipment_event_id
       OR NOT ((original.kind='RECEIPT' AND NEW.kind='REFUND') OR (original.kind='REFUND' AND NEW.kind='RECEIPT')
               OR (original.kind='EQUIPMENT_EXPENSE' AND NEW.kind='EXPENSE_REVERSAL')) THEN
      RAISE EXCEPTION 'invalid cash reversal lineage' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.kind='EXPENSE_REVERSAL' THEN
    RAISE EXCEPTION 'expense reversal requires its original entry' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER cash_entry_history BEFORE INSERT OR UPDATE OR DELETE ON adc_cash_entry
  FOR EACH ROW EXECUTE FUNCTION adc_cash_history_guard();
"""
REVERSE="DROP TRIGGER cash_entry_history ON adc_cash_entry; DROP FUNCTION adc_cash_history_guard();"
def refuse_history_reverse(apps,schema_editor):
    if apps.get_model('finance','CashEntry').objects.exists():
        raise RuntimeError('Cash history exists; retain the schema and restore a separate trusted copy instead.')

class Migration(migrations.Migration):
    dependencies=[('finance','0003_cashentry'),('equipment','0002_history_guards')]
    operations=[migrations.RunSQL(SQL,REVERSE),migrations.RunPython(migrations.RunPython.noop,refuse_history_reverse)]
