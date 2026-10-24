"""Exact-step physical readiness; stable lineage alone grants no acceptance."""
from datetime import datetime
from django.db.models import Q
from adc_core.rules import RuleError
from clinical.encounters import draft_digest
from clinical.continuity_models import LabCase
from clinical.plan_models import PlanStepVersion
from clinical.plans import latest_decision
from clinical.authority import visit_service_id


def step_readiness(step):
    cases=list(LabCase.objects.filter(Q(step_version=step)|Q(reviews__target_step_version=step)).distinct().order_by('pk'))
    rows=[];times=[];active=0;ready_count=0
    for case in cases:
        review=case.reviews.filter(target_step_version=step,cycle=case.cycle).order_by('-pk').first()
        accepted=case.state=='ACCEPTED' and review is not None and review.decision=='ACCEPTED'
        rows.append(dict(id=case.pk,state=case.state,cycle=case.cycle,review=review.pk if review else None,accepted=accepted))
        if case.state!='WITHDRAWN':
            active+=1
            if accepted:ready_count+=1;times.append(review.assessed_at)
    required=step.requires_lab is True or bool(cases)
    if step.requires_lab is None:ready=False;reason='此版本尚未明确加工件依赖，请医师核对并形成明确的新方案版本。'
    elif required and active==0:ready=False;reason='本步骤需要加工件，尚无有效且已临床验收的加工安排。'
    elif required and ready_count!=active:ready=False;reason='相关加工件尚未全部通过本周期对当前版本步骤的临床验收，请先协调。'
    else:ready=True;reason='加工件准备已核对。' if required else '本版本已明确无需加工件。'
    data=dict(step=step.pk,requirement=step.requires_lab,cases=rows)
    return dict(ready=ready,required=required,reason=reason,cases=rows,ready_at=max(times).isoformat() if times and ready else None,digest=draft_digest(data))


def execution_readiness(visit,row,step):
    if step:
        status=step_readiness(step)
        if not status['ready']:raise RuleError(status['reason'])
        if status['ready_at'] and datetime.fromisoformat(row['observed_at'])<datetime.fromisoformat(status['ready_at']):
            raise RuleError('实际执行时间早于已记录的加工件验收，请核对事实时间，不能把先执行写成已准备。')
        return dict(digest=status['digest'],ready_at=status['ready_at'],cases=status['cases'],step=step.pk,required=status['required'])
    matches=PlanStepVersion.objects.filter(version__plan__origin_encounter__visit__patient_id=visit.patient_id,
        version__plan__origin_encounter__visit__clinic_id=visit.clinic_id,version__next_version__isnull=True,
        treatment_type_id=row['treatment_type'],service_id=visit_service_id(visit),tooth=row['tooth'],surface=row['surface'])
    for candidate in matches:
        if candidate.requires_lab is not False or candidate.lab_cases.exists() or candidate.lab_reviews.exists():
            raise RuleError('此项目已有相关加工件依赖或待明确方案，请从对应步骤核对准备情况，不能以计划外入口跳过。')
    return dict(digest=draft_digest(dict(unplanned=True,patient=visit.patient_id,service=visit_service_id(visit))),unplanned=True,cases=[],ready_at=None)
