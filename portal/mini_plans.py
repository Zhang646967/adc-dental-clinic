"""Own released plan facts. Appointment delegation confers no clinical decision."""
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.proposals import read_proposal
from clinical import plans
from clinical.plan_forms import DecisionForm,ConfirmPlanActionForm
from clinical.plan_selectors import patient_plan_rows,self_plan_details
from portal.mini_api import endpoint,result,validated


def decision_data(row):
    return dict(id=row.pk,decision=row.decision,label=row.get_decision_display(),source_label=row.get_source_display(),note=row.note,recorded_at=row.recorded_at.isoformat()) if row else None


def plan_data(details):
    p,v=details['plan'],details['version'];rows=[]
    for s in details['steps']:
        rows.append(dict(id=s.pk,sequence=s.sequence,description=s.description,goal=s.goal,treatment=s.saved_catalogue_name,unit=s.saved_unit,
            service=dict(id=s.service_id,name=s.saved_service_name),definition_retained=s.definition_retained,planned_duration=s.planned_duration,
            tooth=s.tooth,surface=s.surface,estimated_quantity=str(s.estimated_quantity),
            estimated_unit_price=str(s.estimated_unit_price) if s.estimated_unit_price is not None else None,
            estimate_amount=str(s.estimate_amount) if s.estimate_amount is not None else None,estimate_note=s.estimate_note,
            alternative_group=s.alternative_group,charge_basis=s.charge_basis,charge_basis_label=s.get_charge_basis_display(),
            lab_requirement=s.requires_lab,readiness=dict(ready=s.readiness['ready'],label=s.readiness['reason']) if details['is_current'] else None,
            decision=decision_data(s.current_decision),decision_history=[decision_data(d) for d in s.decision_history],completed=s.is_completed,
            actual_history=[dict(id=a.pk,observed_at=a.observed_at.isoformat(),progress_label=a.get_progress_display(),mode_label=a.get_charge_mode_display(),state=a.state,state_label=a.get_state_display()) for a in s.actual_history]))
    return dict(id=p.pk,clinic=p.origin_encounter.visit.clinic.name,version=v.revision,is_current=details['is_current'],summary=v.summary,
        discussion_note=v.discussion_note,recorded_at=v.recorded_at.isoformat(),versions=[r.revision for r in details['versions']],estimate=details['estimate'],steps=rows,
        instructions=[dict(id=r.pk,service_id=r.service_id,service=r.service.name,earliest_on=r.earliest_on.isoformat(),latest_on=r.latest_on.isoformat(),purpose=r.clinical_purpose,
            completion_label=r.get_completion_rule_display(),followup_state=r.recall.get_state_display() if hasattr(r,'recall') else '前台待接续联系') for r in details['instructions']])


@endpoint()
def listing(request):
    rows=patient_plan_rows(request.user);page=Paginator(rows,20).get_page(request.GET.get('page'));data=[]
    for p in page:
        v=plans.current_version(p)
        data.append(dict(id=p.pk,clinic=p.origin_encounter.visit.clinic.name,version=v.revision,summary=v.summary,recorded_at=v.recorded_at.isoformat()))
    return result(request,dict(rows=data,page=page.number,pages=page.paginator.num_pages))


@endpoint()
def detail(request,pk):
    return result(request,plan_data(self_plan_details(request.user,pk,revision=request.GET.get('revision'))))


@sensitive_post_parameters()
@endpoint(('POST',))
def decision_preview(request,pk,step_id):
    d=self_plan_details(request.user,pk)
    if not any(s.pk==step_id for s in d['steps']):raise PermissionDenied('请从本人当前方案的具体步骤核对。')
    values=validated(DecisionForm(request.POST));p=plans.prepare_decision(actor=request.user,step_id=step_id,fields=values)
    return result(request,dict(proposal_token=p['proposal_token'],plan=pk,step=step_id,version=p['step'].version.revision,
        description=p['step'].description,values=p['values']))


@sensitive_post_parameters()
@endpoint(('POST',))
def decision_confirm(request,pk,step_id):
    values=validated(ConfirmPlanActionForm(request.POST))
    data=read_proposal(request.user,plans.DECISION_CONTRACT,('PATIENT',),values['proposal_token'])['data']
    if (data['plan'],data['step'],data['source'])!=(pk,step_id,'SELF'):raise PermissionDenied('请在原本人方案步骤核对本次决定。')
    row,replay=plans.confirm_decision(actor=request.user,**values)
    return result(request,dict(decision=decision_data(row),replayed=replay,plan=pk))
