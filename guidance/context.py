from django.urls import reverse
from guidance.catalog import GUIDES,VERSION

def guide_context(request):
    ctx=getattr(request,'workspace',None)
    if not ctx:return {}
    if request.GET.get('guide')=='off':
        request.session.pop('adc_guide',None);return {}
    state=request.session.get('adc_guide',{})
    if state.get('context')!=str(ctx.pk) or state.get('revision')!=ctx.revision or state.get('catalog_version')!=VERSION:
        state={}
        request.session.pop('adc_guide',None)
    key=request.GET.get('guide',state.get('key',''));g=GUIDES.get(key)
    if not g or ctx.role not in g.roles:return {}
    try:index=int(request.GET.get('step',state.get('step','1')))-1
    except (ValueError,TypeError):return {}
    if not 0<=index<len(g.steps):return {}
    value={'key':key,'step':index+1,'context':str(ctx.pk),'revision':ctx.revision,'catalog_version':VERSION}
    if request.session.get('adc_guide')!=value:request.session['adc_guide']=value
    def url(step=None,exit=False):
        params=request.GET.copy();params['guide']='off' if exit else key
        if step is not None:params['step']=str(step)
        if exit:params.pop('step',None)
        return request.path+'?'+params.urlencode()
    step=g.steps[index]
    current_name=getattr(getattr(request,'resolver_match',None),'url_name',None)
    detail_families={'front-contact':{'patient_detail','patient_contact_edit','patient_contact_confirm'},'doctor-care':{'care_workspace'},'doctor-close':{'care_workspace','care_complete','invoice_detail'},'patient-bill':{'portal_visit','portal_invoice'},'patient-cancel':{'portal_visit','portal_cancel'},'front-arrive':{'visit_detail'},'front-change':{'visit_detail','visit_reschedule'},'doctor-correct':{'correction_create','correction_detail'},'finance-quarter':{'quarter_detail','quarter_cost'},'finance-review':{'correction_detail'},'patient-wait':{'wait_offer'},'front-wait':{'wait_offer'},'manager-plan':{'schedule_plan'}}
    target=url(index+1) if current_name in detail_families.get(key,set()) else reverse(step.route)+'?guide='+key+'&step='+str(index+1)
    return {'guide_panel':{'key':key,'title':g.title,'version':VERSION,'instruction':step.instruction,
        'number':index+1,'total':len(g.steps),'selector':step.selector,
        'task_url':reverse('guide_task',args=[key]),'exit_url':url(exit=True),
        'previous':url(index) if index else '',
        'next':url(index+2) if index+1<len(g.steps) else '',
        'target':target}}
