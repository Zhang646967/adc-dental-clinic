"""Owned plan, decision, actual-work and next-visit facts."""
from django.db import models
from django.db.models import Q,F
from clinical.tooth_rules import PERMANENT,PRIMARY


class TreatmentPlan(models.Model):
    origin_encounter=models.ForeignKey('clinical.ClinicalEncounter',on_delete=models.PROTECT)
    opened_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    opened_at=models.DateTimeField(auto_now_add=True)
    revision=models.PositiveIntegerField(default=0)
    class Meta:db_table='adc_treatment_plan'


class PlanDraft(models.Model):
    plan=models.OneToOneField(TreatmentPlan,on_delete=models.PROTECT,related_name='draft')
    source_record=models.ForeignKey('clinical.ClinicalRecordVersion',on_delete=models.PROTECT)
    base_version=models.ForeignKey('clinical.PlanVersion',null=True,blank=True,on_delete=models.PROTECT)
    saved_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    payload=models.JSONField(default=dict)
    saved_at=models.DateTimeField(auto_now=True)
    class Meta:db_table='adc_plan_draft'


class PlanVersion(models.Model):
    plan=models.ForeignKey(TreatmentPlan,on_delete=models.PROTECT,related_name='versions')
    revision=models.PositiveIntegerField()
    previous=models.OneToOneField('self',null=True,blank=True,on_delete=models.PROTECT,related_name='next_version')
    source_record=models.ForeignKey('clinical.ClinicalRecordVersion',on_delete=models.PROTECT)
    recorded_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    recorded_at=models.DateTimeField(auto_now_add=True)
    summary=models.CharField(max_length=3000)
    discussion_note=models.CharField(max_length=2000,blank=True)
    disclosures=models.JSONField(default=dict,db_default={})
    amendment_reason=models.CharField(max_length=500,blank=True)
    class Meta:
        db_table='adc_plan_version'
        constraints=[models.UniqueConstraint(fields=['plan','revision'],name='plan_version_revision_unique'),
            models.CheckConstraint(condition=Q(revision=1,previous__isnull=True)|Q(revision__gt=1,previous__isnull=False),name='plan_version_previous_required'),
            models.CheckConstraint(condition=~Q(previous=F('id')),name='plan_version_not_self'),
            models.CheckConstraint(condition=Q(previous__isnull=True)|~Q(amendment_reason=''),name='plan_version_amendment_reason')]


class TreatmentStep(models.Model):
    plan=models.ForeignKey(TreatmentPlan,on_delete=models.PROTECT,related_name='steps')
    step_key=models.UUIDField(unique=True)
    created_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:db_table='adc_treatment_step'


class PlanStepVersion(models.Model):
    version=models.ForeignKey(PlanVersion,on_delete=models.PROTECT,related_name='steps')
    step=models.ForeignKey(TreatmentStep,on_delete=models.PROTECT,related_name='versions')
    sequence=models.PositiveSmallIntegerField()
    treatment_type=models.ForeignKey('registry.TreatmentType',on_delete=models.PROTECT)
    service=models.ForeignKey('scheduling.BookingService',on_delete=models.PROTECT)
    description=models.CharField(max_length=1000)
    goal=models.CharField(max_length=1000)
    tooth=models.PositiveSmallIntegerField(null=True,blank=True)
    surface=models.CharField(max_length=6,blank=True)
    estimated_quantity=models.DecimalField(max_digits=12,decimal_places=3)
    estimated_unit_price=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    estimate_note=models.CharField(max_length=500,blank=True)
    alternative_group=models.CharField(max_length=32,blank=True)
    charge_basis=models.CharField(max_length=20,choices=[('PER_EXECUTION','按实际已提供项目计费'),('ON_COMPLETION','分次步骤完成时计费')],default='PER_EXECUTION')
    requires_lab=models.BooleanField(null=True,blank=True,default=None)
    definition_snapshot=models.JSONField(null=True,blank=True,default=None)
    class Meta:
        db_table='adc_plan_step_version'
        ordering=['sequence']
        constraints=[models.UniqueConstraint(fields=['version','step'],name='plan_step_version_unique'),
            models.UniqueConstraint(fields=['version','sequence'],name='plan_step_sequence_unique'),
            models.CheckConstraint(condition=Q(sequence__gte=1,sequence__lte=30),name='plan_step_sequence_bounded'),
            models.CheckConstraint(condition=Q(estimated_quantity__gt=0),name='plan_estimate_quantity_positive'),
            models.CheckConstraint(condition=Q(charge_basis__in=['PER_EXECUTION','ON_COMPLETION']),name='plan_charge_basis_valid'),
            models.CheckConstraint(condition=Q(estimated_unit_price__isnull=True)|Q(estimated_unit_price__gte=0),name='plan_estimate_price_nonnegative'),
            models.CheckConstraint(condition=Q(tooth__isnull=True,surface='')|Q(tooth__in=list(PERMANENT)+list(PRIMARY)),name='plan_step_location_valid')]


class PlanDecision(models.Model):
    step_version=models.ForeignKey(PlanStepVersion,on_delete=models.PROTECT,related_name='decisions')
    actor=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    decision=models.CharField(max_length=16,choices=[('ACCEPTED','认可此步骤'),('DEFERRED','暂缓'),('DECLINED','不选择')])
    source=models.CharField(max_length=16,choices=[('SELF','本人提交'),('MANUAL','医师记录本人表态')])
    self_access=models.ForeignKey('portal.PatientAccess',null=True,blank=True,on_delete=models.PROTECT)
    source_visit=models.ForeignKey('scheduling.Visit',null=True,blank=True,on_delete=models.PROTECT)
    reference=models.CharField(max_length=500,blank=True)
    note=models.CharField(max_length=1000,blank=True)
    operation_id=models.UUIDField(unique=True)
    recorded_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_plan_decision'
        constraints=[models.CheckConstraint(condition=Q(decision__in=['ACCEPTED','DEFERRED','DECLINED']),name='plan_decision_valid'),
            models.CheckConstraint(condition=Q(source='SELF',self_access__isnull=False,source_visit__isnull=True)|Q(source='MANUAL',self_access__isnull=True,source_visit__isnull=False),name='plan_decision_source_valid')]


class PerformedProcedure(models.Model):
    encounter=models.ForeignKey('clinical.ClinicalEncounter',on_delete=models.PROTECT,related_name='performed_procedures')
    source_record=models.ForeignKey('clinical.ClinicalRecordVersion',on_delete=models.PROTECT)
    step_version=models.ForeignKey(PlanStepVersion,null=True,blank=True,on_delete=models.PROTECT,related_name='executions')
    treatment_type=models.ForeignKey('registry.TreatmentType',on_delete=models.PROTECT)
    quantity=models.DecimalField(max_digits=12,decimal_places=3)
    tooth=models.PositiveSmallIntegerField(null=True,blank=True)
    surface=models.CharField(max_length=6,blank=True)
    progress=models.CharField(max_length=16,choices=[('PARTIAL','步骤尚待继续'),('COMPLETE','本步骤实际完成')])
    charge_mode=models.CharField(max_length=16,choices=[('CHARGE','按实际项目开单'),('NO_CHARGE','本次不另计费')])
    reason=models.CharField(max_length=1000,blank=True)
    charge_line=models.OneToOneField('care.TreatmentRecord',null=True,blank=True,on_delete=models.PROTECT,related_name='performed_source')
    charge_snapshot=models.JSONField(default=dict)
    state=models.CharField(max_length=16,choices=[('ACTIVE','有效实际记录'),('VOIDED','已更正撤回')],default='ACTIVE')
    revision=models.PositiveIntegerField(default=0)
    recorded_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    observed_at=models.DateTimeField()
    recorded_at=models.DateTimeField(auto_now_add=True)
    operation_id=models.UUIDField(unique=True)
    class Meta:
        db_table='adc_performed_procedure'
        constraints=[models.CheckConstraint(condition=Q(quantity__gt=0),name='performed_quantity_positive'),
            models.CheckConstraint(condition=Q(tooth__isnull=True,surface='')|Q(tooth__in=list(PERMANENT)+list(PRIMARY)),name='performed_location_valid'),
            models.CheckConstraint(condition=Q(progress__in=['PARTIAL','COMPLETE']),name='performed_progress_valid'),
            models.CheckConstraint(condition=Q(state__in=['ACTIVE','VOIDED']),name='performed_state_valid'),
            models.CheckConstraint(condition=Q(charge_mode='NO_CHARGE',charge_line__isnull=True)|Q(charge_mode='CHARGE',charge_line__isnull=False)|Q(charge_mode='CHARGE',state='VOIDED',charge_line__isnull=True),name='performed_charge_link_valid'),
            models.CheckConstraint(condition=Q(observed_at__lte=F('recorded_at')),name='performed_not_future'),
            models.UniqueConstraint(fields=['encounter','step_version'],condition=Q(state='ACTIVE',step_version__isnull=False),name='one_active_performed_step_per_visit')]


class NextVisitInstruction(models.Model):
    source_record=models.ForeignKey('clinical.ClinicalRecordVersion',on_delete=models.PROTECT)
    step_version=models.ForeignKey(PlanStepVersion,null=True,blank=True,on_delete=models.PROTECT)
    service=models.ForeignKey('scheduling.BookingService',on_delete=models.PROTECT)
    earliest_on=models.DateField()
    latest_on=models.DateField()
    clinical_purpose=models.CharField(max_length=1000)
    booking_note=models.CharField(max_length=500,blank=True)
    completion_rule=models.CharField(max_length=24,choices=[('UNSPECIFIED','原记录尚未明确完成目标'),('EXAM_CONFIRMED','后续实际接诊关闭且检查已确认'),('STEP_COMPLETED','指定版本步骤实际完成并关闭接诊')],default='UNSPECIFIED')
    state=models.CharField(max_length=16,choices=[('OPEN','待安排后续'),('WITHDRAWN','已明确撤回指示')],default='OPEN')
    revision=models.PositiveIntegerField(default=0)
    recorded_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    recorded_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_next_visit_instruction'
        constraints=[models.CheckConstraint(condition=Q(earliest_on__lte=F('latest_on')),name='next_visit_window_valid'),
            models.CheckConstraint(condition=Q(completion_rule__in=['UNSPECIFIED','EXAM_CONFIRMED'])|Q(completion_rule='STEP_COMPLETED',step_version__isnull=False),name='next_visit_completion_rule_valid'),
            models.CheckConstraint(condition=Q(state__in=['OPEN','WITHDRAWN']),name='next_visit_state_valid')]


class PlanAppointment(models.Model):
    instruction=models.ForeignKey(NextVisitInstruction,on_delete=models.PROTECT,related_name='appointment_links')
    visit=models.ForeignKey('scheduling.Visit',on_delete=models.PROTECT)
    linked_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    linked_at=models.DateTimeField(auto_now_add=True)
    operation_id=models.UUIDField(unique=True)
    class Meta:
        db_table='adc_plan_appointment'
        constraints=[models.UniqueConstraint(fields=['instruction','visit'],name='next_visit_link_unique')]


class PlanEvent(models.Model):
    actor=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    operation_id=models.UUIDField(unique=True)
    action=models.CharField(max_length=32)
    plan=models.ForeignKey(TreatmentPlan,null=True,blank=True,on_delete=models.PROTECT,related_name='events')
    encounter=models.ForeignKey('clinical.ClinicalEncounter',null=True,blank=True,on_delete=models.PROTECT)
    decision=models.ForeignKey(PlanDecision,null=True,blank=True,on_delete=models.PROTECT)
    performed=models.ForeignKey(PerformedProcedure,null=True,blank=True,on_delete=models.PROTECT)
    instruction=models.ForeignKey(NextVisitInstruction,null=True,blank=True,on_delete=models.PROTECT)
    note=models.CharField(max_length=1000,blank=True)
    snapshot=models.JSONField(default=dict)
    recorded_at=models.DateTimeField(auto_now_add=True)
    class Meta:db_table='adc_plan_event'
