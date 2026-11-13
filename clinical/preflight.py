"""Pre-treatment evidence is not actual treatment or a financial transaction."""
from datetime import datetime
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.policies import require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.authority import require_reviewer, professional_scope, visit_service_id
from clinical.authority_services import lock_people
from clinical.consent_models import MedicalConsent, ConsentVersion, ConsentEvent
from clinical.preflight_models import TreatmentControlPolicy, ClinicalConsentRule, TreatmentPreflight, ProcedureGap, ProcedureGapReview
from clinical.plan_locks import lock_plan_visit
from clinical.plan_models import PlanStepVersion
from clinical.consent_models import ConsentEvent
from clinical.consent_selectors import details as consent_details
from clinical import consents
from registry.models import Clinic, TreatmentType
from scheduling import resources

CONTRACT='adc.treatment-preflight.c32c.v1'
RULE_CONTRACT='adc.treatment-control.c32c.v1'
REVIEW_CONTRACT='adc.treatment-gap-review.c32c.v1'


def enabled(clinic_id):
    return TreatmentControlPolicy.objects.filter(clinic_id=clinic_id).exists()


def note(value,label='核对说明',limit=1000):
    return consents.text(value,label,limit,True)


@transaction.atomic
def prepare_rule(*,actor,clinic_id,treatment_id=None,mode=None,reference,explanation='',activate=False):
    require_writable(actor);require_reviewer(actor,clinic_id)
    if not activate and mode not in dict(ClinicalConsentRule.MODES):raise RuleError('请选择明确的临床沟通／同意要求。')
    item=TreatmentType.objects.get(pk=treatment_id,is_active=True) if not activate else None
    last=ClinicalConsentRule.objects.filter(clinic_id=clinic_id,treatment_type=item).order_by('-number').first() if item else None
    data=dict(clinic=clinic_id,item=item.pk if item else None,mode=mode,reference=note(reference,'规则／启用依据',500),
        explanation=note(explanation) if not activate else '',activate=activate,previous=last.pk if last else None)
    return dict(proposal_token=proposal(actor,RULE_CONTRACT,('DENTIST',),data),data=data)


@business_errors
@transaction.atomic
def confirm_rule(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确确认规则版本或诊所启用；不得自动推定项目要求。')
    p=read_proposal(actor,RULE_CONTRACT,('DENTIST',),proposal_token);d=p['data'];lock_people(actor)
    reviewer=require_reviewer(actor,d['clinic'],lock=True);clinic=Clinic.objects.select_for_update().get(pk=d['clinic'],is_active=True)
    read_proposal(actor,RULE_CONTRACT,('DENTIST',),proposal_token)
    if d['activate']:
        prior=TreatmentControlPolicy.objects.filter(clinic=clinic).first()
        if prior:return prior,True
        items=set(TreatmentType.objects.filter(is_active=True).values_list('pk',flat=True))
        covered=set(ClinicalConsentRule.objects.filter(clinic=clinic).values_list('treatment_type_id',flat=True))
        if not items<=covered:raise RuleError('仍有在用实际项目缺少规则；请逐项发布，未知项目应明确为需专业判断。')
        row=TreatmentControlPolicy.objects.create(clinic=clinic,activated_by=actor,reference=d['reference'])
        emit(actor,'TREATMENT_CONTROL_ACTIVATED',row,summary={'clinic':clinic.pk})
    else:
        prior=ClinicalConsentRule.objects.filter(operation_id=p['operation']).first()
        if prior:return prior,True
        item=TreatmentType.objects.select_for_update().get(pk=d['item'],is_active=True)
        latest=ClinicalConsentRule.objects.filter(clinic=clinic,treatment_type=item).order_by('-number').first()
        if latest and latest.reference==d['reference'] and latest.mode==d['mode'] and latest.explanation==d['explanation'] and latest.published_by_id==actor.pk and latest.pk!=d['previous']:
            return latest,True
        if (latest.pk if latest else None)!=d['previous']:raise RuleError('规则已有新版本，请重新核对。')
        row=ClinicalConsentRule.objects.create(clinic=clinic,treatment_type=item,number=(latest.number+1 if latest else 1),
            mode=d['mode'],reference=d['reference'],explanation=d['explanation'],published_by=actor,reviewer=reviewer,operation_id=p['operation'])
        emit(actor,'CLINICAL_CONSENT_RULE_PUBLISHED',row,summary={'rule':row.pk,'mode':row.mode})
    return row,False


def state(visit,record,row,step,*,communication='',lock=False):
    """Caller serializes visit/people/resources for confirmation; reads never repair."""
    if lock:TreatmentType.objects.select_for_update().get(pk=row['treatment_type'])
    rule=ClinicalConsentRule.objects.filter(clinic_id=visit.clinic_id,treatment_type_id=row['treatment_type']).order_by('-number').first()
    if rule is None:raise RuleError('实际项目尚无已发布规则，请交本店专业审核医师核对。')
    if rule.mode=='REVIEW':raise RuleError('此项目规则要求进一步专业判断，请先由本店专业审核医师明确并发布适用规则。')
    professional_scope(visit.dentist.useraccount.pk,visit.clinic_id,step.service_id if step else visit_service_id(visit),'RECORD',lock=lock)
    resources.check_in_resources_locked(visit)
    resource=resources.current_plan(visit)
    from clinical.lab_readiness import execution_readiness
    readiness=execution_readiness(visit,row,step)
    data=dict(patient_identity=consents.patient_snapshot(visit.patient),visit=visit.pk,patient=visit.patient_id,doctor=visit.dentist_id,record=record.pk,step=step.pk if step else None,
        rule=rule.pk,item=row['treatment_type'],tooth=row['tooth'],surface=row['surface'],quantity=row['quantity'],
        resource=resource.pk if resource else None,readiness=readiness,consent_version=None,decision=None,proxy_version=None,
        communication=communication if rule.mode=='COMMUNICATION' else '')
    from clinical.examination_followup import treatment_basis
    reports = treatment_basis(visit, step, lock=lock)
    if reports:
        data['examination_basis'] = reports
    if step:
        from clinical.plans import latest_decision
        chosen=latest_decision(step);data['scheme_decision']=chosen.pk if chosen else None
        if chosen and chosen.proxy_version_id:
            from portal.medical_authority import verify_version
            verify_version(chosen.proxy_version,step=step,lock=lock);data['proxy_version']=chosen.proxy_version_id
    existing=MedicalConsent.objects.filter(step=step.step).first() if step else None
    if existing and rule.mode=='COMMUNICATION':
        notice=consents.latest(existing)
        consents.current_scope(step,visit.patient,notice,lock=lock)
        decision=notice.events.filter(action__in=consents.DECISIONS).order_by('-sequence').first()
        if existing.events.filter(action='QUESTION',answer__isnull=True).exists() or not decision or decision.action!='AGREED':
            raise RuleError('本步骤已有医疗决定办理，请先处理待答疑问、拒绝、暂缓或撤回，不能用沟通类规则跳过。')
        data.update(consent_version=notice.pk,decision=decision.pk,proxy_version=notice.proxy_version_id)
    if rule.mode=='COMMUNICATION':
        note(communication,'本次沟通及身份核对依据')
    else:
        if step is None:raise RuleError('此项目需具体同意，请先形成准确方案步骤、告知和决定，再核对开治。')
        case=MedicalConsent.objects.filter(step=step.step).first();version=consents.latest(case)
        if version is None or version.step_version_id!=step.pk:raise RuleError('缺少本步骤当前医疗告知，请由负责医师先办理。')
        consents.current_scope(step,visit.patient,version,lock=lock)
        if case.events.filter(action='QUESTION',answer__isnull=True).exists():raise RuleError('仍有未答复医疗疑问，请先答复再由本人或适格代理明确决定。')
        decision=version.events.filter(action__in=consents.DECISIONS).order_by('-sequence').first()
        if decision is None or decision.action!='AGREED':raise RuleError('当前告知尚无有效同意，或已经拒绝、暂缓、撤回；请继续医疗沟通。')
        data.update(consent_version=version.pk,decision=decision.pk,proxy_version=version.proxy_version_id)
    return data


def dependencies(visit_id,step_id=None):
    ids=[]
    if step_id:
        step=PlanStepVersion.objects.filter(pk=step_id).first()
        version=consents.latest(MedicalConsent.objects.filter(step=step.step).first()) if step else None
        if version:
            ids.append(version.prepared_by_id)
            if version.proxy_version_id:ids.append(version.proxy_version.proxy.delegate_id)
        if step:
            from clinical.plans import latest_decision
            choice=latest_decision(step)
            if choice and choice.proxy_version_id:ids.append(choice.proxy_version.proxy.delegate_id)
    return sorted(set(ids))


def prepare(*,actor,visit_id,fields,communication=''):
    from clinical.executions import execution_fields,actual_ready,checked_step
    from clinical.encounter_selectors import encounter_details
    d=encounter_details(actor,visit_id)
    row=execution_fields(fields)
    with transaction.atomic():
        require_writable(actor)
        lock_people(actor,*dependencies(visit_id,row['step_version']))
        plan_id=PlanStepVersion.objects.get(pk=row['step_version']).version.plan_id if row['step_version'] else None
        visit,patient,head,record,plan=lock_plan_visit(actor,visit_id,plan_id)
        if not enabled(visit.clinic_id):raise RuleError('本店尚未正式启用治疗前核对，请先由有职责的审核医师核对规则并启用。')
        actual_ready(visit);step=checked_step(visit,row,plan)
        snapshot=state(visit,record,row,step,communication=communication)
    data=dict(visit=visit_id,plan=plan_id,values=row,communication=communication,snapshot=snapshot,
        patient_name=visit.patient.name,clinic_name=visit.clinic.name,item_name=TreatmentType.objects.get(pk=row['treatment_type']).name,doctor_name=visit.dentist.name)
    return dict(proposal_token=proposal(actor,CONTRACT,('DENTIST',),data),data=data)


@business_errors
@transaction.atomic
def confirm(*,actor,proposal_token,confirmed):
    from clinical.executions import actual_ready,checked_step
    if confirmed is not True:raise RuleError('请明确完成本次开治前核对；核对不会创建治疗或费用。')
    p=read_proposal(actor,CONTRACT,('DENTIST',),proposal_token);d=p['data'];row=d['values']
    lock_people(actor,*dependencies(d['visit'],row['step_version']))
    visit,patient,head,record,plan=lock_plan_visit(actor,d['visit'],d['plan'])
    read_proposal(actor,CONTRACT,('DENTIST',),proposal_token)
    prior=TreatmentPreflight.objects.filter(operation_id=p['operation']).first()
    if prior:return prior,True
    actual_ready(visit);step=checked_step(visit,row,plan)
    current=state(visit,record,row,step,communication=d['communication'],lock=True)
    if current!=d['snapshot']:raise RuleError('患者、授权、告知、项目或资源已变化，请重新进行治疗前核对。')
    result=TreatmentPreflight.objects.create(visit=visit,source_record=record,step_version=step,rule_id=current['rule'],
        consent_version_id=current['consent_version'],consent_decision_id=current['decision'],proxy_version_id=current['proxy_version'],
        snapshot=current,communication=d['communication'],checked_by=actor,operation_id=p['operation'])
    emit(actor,'TREATMENT_PREFLIGHT_CONFIRMED',result,visit=visit,summary={'preflight':result.pk,'rule':result.rule_id})
    return result,False


def execution_check(visit,record,row,step,check_id,*,lock=False):
    if not enabled(visit.clinic_id):
        from clinical.examination_followup import linked_orders
        if linked_orders(visit).exists():
            raise RuleError('请先完成本店开治控制的配置及本次报告依据核对。')
        return None
    if not check_id:raise RuleError('本店已启用治疗前核对，请先完成本次核对并选择其编号；已发生缺材料的治疗走明确补记。')
    check=TreatmentPreflight.objects.get(pk=check_id,visit=visit,checked_by__dentist_id=visit.dentist_id)
    current=state(visit,record,row,step,communication=check.communication,lock=lock)
    if check.snapshot!=current:raise RuleError('原开治核对的适用依据已变化，请重新核对；实际已发生的事实请明确补记。')
    if datetime.fromisoformat(row['observed_at'])<check.checked_at:raise RuleError('实际时间早于开治核对，不能倒签；请核对事实并走已发生补记。')
    return check


def prepare_review(*,actor,gap_id,note_text):
    gap=ProcedureGap.objects.select_related('performed__encounter__visit').get(pk=gap_id)
    require_reviewer(actor,gap.performed.encounter.visit.clinic_id)
    service=gap.performed.step_version.service_id if gap.performed.step_version_id else visit_service_id(gap.performed.encounter.visit)
    professional_scope(actor.pk,gap.performed.encounter.visit.clinic_id,service,'READ')
    if actor.pk==gap.recorded_by_id:raise PermissionDenied('缺口须由另一名有职责的审核医师复核。')
    return dict(proposal_token=proposal(actor,REVIEW_CONTRACT,('DENTIST',),dict(gap=gap.pk,note=note(note_text,'缺口复核结论'))))


@business_errors
@transaction.atomic
def confirm_review(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请确认只是复核历史缺口，不构成事前核对或补签。')
    p=read_proposal(actor,REVIEW_CONTRACT,('DENTIST',),proposal_token);lock_people(actor)
    gap=ProcedureGap.objects.select_for_update().select_related('performed__encounter__visit').get(pk=p['data']['gap'])
    reviewer=require_reviewer(actor,gap.performed.encounter.visit.clinic_id,lock=True)
    service=gap.performed.step_version.service_id if gap.performed.step_version_id else visit_service_id(gap.performed.encounter.visit)
    professional_scope(actor.pk,gap.performed.encounter.visit.clinic_id,service,'READ',lock=True)
    if gap.recorded_by_id==actor.pk:raise PermissionDenied('不能复核本人补记的缺口。')
    read_proposal(actor,REVIEW_CONTRACT,('DENTIST',),proposal_token)
    prior=ProcedureGapReview.objects.filter(gap=gap).first()
    if prior:
        if str(prior.operation_id)!=str(p['operation']):raise RuleError('此缺口已有复核结论，请查看保留记录。')
        return prior,True
    result=ProcedureGapReview.objects.create(gap=gap,reviewer=reviewer,actor=actor,note=p['data']['note'],operation_id=p['operation'])
    gap.state='REVIEWED';gap.save(update_fields=['state'])
    emit(actor,'PROCEDURE_GAP_REVIEWED',result,summary={'gap':gap.pk,'performed':gap.performed_id})
    return result,False
