from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_http_methods,require_GET
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.http_support import EXPECTED_ERRORS,add_error
from portal import relationships as svc
from portal.relationship_forms import RelationshipForm,RelationshipActionForm,RelationshipConfirmForm
from portal.policies import subject_choices,patient_access,SubjectRequired

LABELS={'LINK_ACCOUNT':'补充关联账号','VERIFY':'核验并确认范围','REJECT':'核验未通过','SUSPEND':'暂停代约','REVOKE':'撤销关系与代约','WITHDRAW':'撤回受理'}

@login_required
@require_GET
def listing(request):
    qs=svc.cases(request.user).order_by('-created_at','-pk')
    state=request.GET.get('state','')
    if state in {'PENDING','VERIFIED','SUSPENDED','REJECTED','REVOKED','WITHDRAWN'}:qs=qs.filter(state=state)
    page=Paginator(qs,20).get_page(request.GET.get('page'))
    return render(request,'portal/relationships/list.html',{'page':page})

@login_required
@require_GET
def detail(request,pk):
    case=get_object_or_404(svc.cases(request.user),pk=pk)
    actions=[]
    if case.state=='PENDING':
        if not case.delegate_user_id:actions.append('LINK_ACCOUNT')
        actions+=['VERIFY','REJECT','WITHDRAW']
    elif case.state=='VERIFIED':actions+=['SUSPEND','REVOKE']
    elif case.state=='SUSPENDED':actions+=['VERIFY','REVOKE']
    events=list(case.events.select_related('actor').order_by('pk'))
    from datetime import datetime
    for event in events:
        event.action_label={'CREATE':'登记关系',**LABELS}.get(event.action,event.action)
        event.state_label=dict(svc.PatientRelationship.STATES).get(event.resulting_state,event.resulting_state)
        event.basis_label=dict(svc.BASES).get(event.basis,event.basis)
        event.until=datetime.fromisoformat(event.snapshot['valid_until']) if event.snapshot.get('valid_until') else None
    return render(request,'portal/relationships/detail.html',{'case':case,'events':events,
        'grant':svc.PatientAppointmentGrant.objects.filter(relationship=case).first(),
        'actions':[(a,LABELS[a]) for a in actions]})

@sensitive_post_parameters('related_name','username','note','reference','proposal_token')
@login_required
@require_http_methods(['GET','POST'])
def create(request):
    svc.require_contact_actor(request.user)
    form=RelationshipForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:token=svc.prepare_create(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'portal/relationships/confirm.html',{'title':'核对关系受理','values':[(f.label,form.cleaned_data.get(n,'')) for n,f in form.fields.items()],
            'form':RelationshipConfirmForm(initial={'proposal_token':token})})
    return render(request,'portal/relationships/form.html',{'form':form,'title':'登记患者关系','description':'正式代约前须完成建档和关系核验；登记联系人不会自动授予访问权。'})

@sensitive_post_parameters('username','note','reference','proposal_token')
@login_required
@require_http_methods(['GET','POST'])
def action(request,pk,action):
    case=get_object_or_404(svc.cases(request.user),pk=pk)
    if action not in LABELS:
        from django.http import Http404
        raise Http404
    if action in {'VERIFY','REJECT'}:svc.reviewer(request.user)
    form=RelationshipActionForm(request.POST or None,action=action,case=case)
    if request.method=='POST' and form.is_valid():
        d=dict(form.cleaned_data);d.pop('verified',None)
        try:token=svc.prepare_action(actor=request.user,case_id=pk,action=action,**d)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'portal/relationships/confirm.html',{'title':LABELS[action],'case':case,
            'values':[(f.label,form.cleaned_data.get(n,'')) for n,f in form.fields.items() if n!='verified'],
            'form':RelationshipConfirmForm(initial={'proposal_token':token})})
    return render(request,'portal/relationships/form.html',{'case':case,'form':form,'title':LABELS[action],
        'description':'暂停或撤销会阻止后续代办，已有预约、候补与历史仍保留，由前台继续协调。'})

@sensitive_post_parameters('proposal_token')
@login_required
@require_http_methods(['POST'])
def confirm(request):
    form=RelationshipConfirmForm(request.POST)
    if form.is_valid():
        try:case,replay=svc.confirm(actor=request.user,token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'已保存关系办理结果。' if not replay else '本次操作已办理，以下是当前结果。')
            return redirect('patient_relationship_detail',pk=case.pk)
    return render(request,'portal/relationships/confirm.html',{'title':'核验结果需要重新确认','form':form})

@login_required(login_url='portal_login')
@require_http_methods(['GET','POST'])
def subjects(request):
    problem=''
    if request.method=='POST':
        try:
            svc.select_subject(actor=request.user,key=request.POST.get('subject',''))
        except EXPECTED_ERRORS as exc:problem=str(exc)
        else:
            request.session.pop('adc_guide',None);request.session.pop('adc_booking_intent',None)
            messages.success(request,'已切换就诊人，请按页面上的姓名和授权范围重新办理。')
            return redirect('portal_home')
    current=None
    try:
        access=patient_access(request.user);current=access.pk if access.delegated else 'self'
    except SubjectRequired:pass
    rows=subject_choices(request.user)
    from datetime import datetime
    from django.utils import timezone
    for row in rows:
        if row['expires']:row['expires']=timezone.localtime(datetime.fromisoformat(row['expires'])).strftime('%Y-%m-%d %H:%M')
    return render(request,'portal/subjects.html',{'subjects':rows,'selected':current,'problem':problem})
