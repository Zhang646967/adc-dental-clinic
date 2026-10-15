"""Additive daily history guards and shared cash/date serialization."""
from django.db import migrations, models

SQL = r"""
CREATE FUNCTION adc_daily_facts(c bigint, d date) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object(
   'cursor', jsonb_build_array(count(*),coalesce(max(id),0),coalesce(sum(lock_version),0)),
   'pending', count(*) FILTER (WHERE state='PENDING'),
   'posted_count', count(*) FILTER (WHERE state='POSTED'),
   'totals',jsonb_build_object(
     'RECEIPT',coalesce(sum(amount) FILTER (WHERE state='POSTED' AND kind='RECEIPT'),0)::numeric(30,2)::text,
     'REFUND',coalesce(sum(amount) FILTER (WHERE state='POSTED' AND kind='REFUND'),0)::numeric(30,2)::text,
     'EQUIPMENT_EXPENSE',coalesce(sum(amount) FILTER (WHERE state='POSTED' AND kind='EQUIPMENT_EXPENSE'),0)::numeric(30,2)::text,
     'EXPENSE_REVERSAL',coalesce(sum(amount) FILTER (WHERE state='POSTED' AND kind='EXPENSE_REVERSAL'),0)::numeric(30,2)::text))
 FROM adc_cash_entry WHERE clinic_id=c AND occurred_on=d
$$;
CREATE FUNCTION adc_daily_cash_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('adc.daily-close:' || NEW.clinic_id::text || ':' || NEW.occurred_on::text,0));
 RETURN NEW;
END $$;
CREATE TRIGGER aaa_daily_cash_lock BEFORE INSERT OR UPDATE ON adc_cash_entry FOR EACH ROW EXECUTE FUNCTION adc_daily_cash_lock();
CREATE FUNCTION adc_daily_close_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior adc_daily_close%ROWTYPE; facts jsonb; value text;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'daily close history cannot be deleted' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('adc.daily-close:' || NEW.clinic_id::text || ':' || NEW.business_date::text,0));
 IF TG_OP='INSERT' THEN
   IF NEW.state<>'PENDING' OR NEW.lock_version<>0 OR NEW.business_date>(now() AT TIME ZONE 'Asia/Shanghai')::date
      OR btrim(NEW.evidence)='' OR btrim(NEW.reason)='' THEN
     RAISE EXCEPTION 'daily close starts with current dated evidence pending review' USING ERRCODE='23514';
   END IF;
   SELECT * INTO prior FROM adc_daily_close WHERE clinic_id=NEW.clinic_id AND business_date=NEW.business_date ORDER BY version DESC LIMIT 1;
   IF NEW.previous_id IS DISTINCT FROM prior.id OR NEW.version<>coalesce(prior.version,0)+1 OR prior.state='PENDING' THEN
     RAISE EXCEPTION 'daily close requires latest terminal predecessor' USING ERRCODE='23514';
   END IF;
   IF jsonb_typeof(NEW.declared) IS DISTINCT FROM 'object' THEN
     RAISE EXCEPTION 'invalid declared amounts' USING ERRCODE='23514';
   END IF;
   IF NOT (NEW.declared ?& ARRAY['RECEIPT','REFUND','EQUIPMENT_EXPENSE','EXPENSE_REVERSAL'])
      OR (SELECT count(*) FROM jsonb_object_keys(NEW.declared))<>4 THEN
     RAISE EXCEPTION 'all four independent amounts required' USING ERRCODE='23514';
   END IF;
   FOR value IN SELECT jsonb_each_text.value FROM jsonb_each_text(NEW.declared) LOOP
     IF value IS NULL OR value !~ '^(0|[1-9][0-9]{0,25})\.[0-9]{2}$' THEN
       RAISE EXCEPTION 'invalid declared amount format' USING ERRCODE='23514';
     END IF;
   END LOOP;
 ELSE
   IF OLD.state<>'PENDING' OR NEW.state NOT IN ('APPROVED','REJECTED') OR NEW.lock_version<>1
      OR (NEW.operation_id,NEW.clinic_id,NEW.business_date,NEW.version,NEW.previous_id,NEW.snapshot,NEW.declared,NEW.evidence,NEW.reason,NEW.prepared_by_id,NEW.prepared_at)
        IS DISTINCT FROM (OLD.operation_id,OLD.clinic_id,OLD.business_date,OLD.version,OLD.previous_id,OLD.snapshot,OLD.declared,OLD.evidence,OLD.reason,OLD.prepared_by_id,OLD.prepared_at)
      OR btrim(NEW.review_reason)='' OR NEW.reviewed_at<NEW.prepared_at THEN
      RAISE EXCEPTION 'daily close facts and terminal decisions are immutable' USING ERRCODE='23514';
   END IF;
 END IF;
 IF TG_OP='INSERT' OR NEW.state='APPROVED' THEN
   facts=adc_daily_facts(NEW.clinic_id,NEW.business_date);
   IF NEW.snapshot IS DISTINCT FROM facts THEN RAISE EXCEPTION 'daily close snapshot stale' USING ERRCODE='23514'; END IF;
   IF NEW.state='APPROVED' AND ((facts->>'pending')::bigint<>0 OR NEW.declared IS DISTINCT FROM facts->'totals') THEN
      RAISE EXCEPTION 'unresolved daily discrepancy or pending cash' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER daily_close_history BEFORE INSERT OR UPDATE OR DELETE ON adc_daily_close FOR EACH ROW EXECUTE FUNCTION adc_daily_close_guard();
"""
REVERSE = 'DROP TRIGGER daily_close_history ON adc_daily_close; DROP FUNCTION adc_daily_close_guard(); DROP TRIGGER aaa_daily_cash_lock ON adc_cash_entry; DROP FUNCTION adc_daily_cash_lock(); DROP FUNCTION adc_daily_facts(bigint,date);'

def refuse_reverse(apps,schema_editor):
    if apps.get_model('finance','DailyClose').objects.exists():
        raise RuntimeError('Daily history exists; retain schema and restore a separate empty environment.')

class Migration(migrations.Migration):
    dependencies=[('finance','0006_dailyclose'),('equipment','0004_cost_history_guards')]
    operations=[
        migrations.AddIndex(model_name='cashentry',index=models.Index(fields=['clinic','occurred_on'],name='cash_clinic_day_idx')),
        migrations.RunSQL(SQL,REVERSE),
        migrations.RunPython(migrations.RunPython.noop,refuse_reverse),
    ]
