"""Consultation facts are not patient identity or clinical-access grants."""
from django.db import models
from django.db.models import Q

STATES = [('VERIFY','待核对'), ('CONTACT','待联系'), ('CONFIRM','待患者确认'), ('WAITLIST','候补等待'),
          ('BOOKED','已成约'), ('UNBOOKED','未成约'), ('WITHDRAWN','已撤回')]
REASONS = [('NO_RESOURCE','无合适资源'), ('DECLINED','拒绝方案'), ('UNREACHABLE','联系未果'), ('OTHER','其他')]

class ReceptionCase(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    caller_name = models.CharField(max_length=80)
    relationship = models.CharField(max_length=80)
    contact = models.CharField(max_length=120)
    patient_hint = models.CharField(max_length=80, blank=True)
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, null=True, blank=True)
    service = models.ForeignKey('scheduling.BookingService', on_delete=models.PROTECT, null=True, blank=True)
    preferred_dentist = models.ForeignKey('registry.Dentist', on_delete=models.PROTECT, null=True, blank=True)
    preferred_day = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=12, choices=STATES, default='VERIFY')
    owner = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='reception_cases')
    due_at = models.DateTimeField(null=True, blank=True)
    reason_code = models.CharField(max_length=20, choices=REASONS, blank=True)
    wait_request = models.OneToOneField('coordination.WaitRequest', on_delete=models.PROTECT, null=True, blank=True)
    visit = models.OneToOneField('scheduling.Visit', on_delete=models.PROTECT, null=True, blank=True, related_name='reception_case')
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_reception_case'
        ordering = ['due_at','created_at','pk']
        indexes = [models.Index(fields=['clinic','state','due_at'], name='reception_worklist')]
        constraints = [models.CheckConstraint(condition=Q(state__in=[x[0] for x in STATES]), name='reception_state_valid'),
            models.CheckConstraint(condition=~Q(state__in=['CONTACT','CONFIRM','WAITLIST']) | Q(due_at__isnull=False), name='reception_contact_due'),
            models.CheckConstraint(condition=Q(state='BOOKED',visit__isnull=False,patient__isnull=False) | (~Q(state='BOOKED') & Q(visit__isnull=True)), name='reception_booking_fact'),
            models.CheckConstraint(condition=~Q(state='UNBOOKED') | ~Q(reason_code=''), name='reception_unbooked_reason')]

class ReceptionCommunication(models.Model):
    case = models.ForeignKey(ReceptionCase, on_delete=models.PROTECT, related_name='communications')
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=24)
    note = models.CharField(max_length=2000)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)
    operation_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    @property
    def kind_label(self):
        return {'CREATE':'来电登记','UPDATE':'资料核实','ASSIGN':'责任交接','NOTE':'追加沟通','BOOK':'患者确认成约',
            'WAITLIST':'转入候补','WAIT_ACCEPTED':'原候补成约','LINK_WAITLIST':'核对候补成功结果','UNBOOKED':'登记未成约','WITHDRAW':'撤回接待'}.get(self.kind,self.kind)
    class Meta:
        db_table = 'adc_reception_communication' 
        ordering = ['sequence','pk']
        constraints = [models.UniqueConstraint(fields=['case','sequence'], name='reception_history_sequence')]
