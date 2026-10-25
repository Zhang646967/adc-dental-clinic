"""Current-clinic public profile commands. Existing business directories stay separate."""
from django.db import transaction
from django.core.exceptions import PermissionDenied
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from equipment.policies import manager_clinic
from registry.branch_forms import DirectoryForm,FIELDS
from registry.directory_models import ClinicDirectory,ClinicDirectoryRevision
from scheduling.resource_models import DepartmentHours,ResourcePolicy
from scheduling.resources import lock_physical

CONTRACT='adc.clinic.directory.v1'


def values(row):
    if not row:return {}
    return {key:str(getattr(row,key)) if key in ('latitude','longitude','map_latitude','map_longitude') and
        getattr(row,key) is not None else getattr(row,key) for key in FIELDS}


def validated(clinic,fields,instance=None):
    form=DirectoryForm(fields,instance=instance)
    form.instance.clinic_id=clinic
    if not form.is_valid():raise RuleError('；'.join(str(e) for errors in form.errors.values() for e in errors))
    if form.cleaned_data['is_published'] and not DepartmentHours.objects.filter(
            department__clinic_id=clinic,department__is_active=True).exists():
        raise RuleError('请先配置科室开放时间，门店不能在营业时间未知时公开。')
    return form


def prepare_directory(*,actor,fields):
    clinic=manager_clinic(actor)
    row=ClinicDirectory.objects.filter(clinic_id=clinic).first()
    form=validated(clinic,fields,row)
    # ModelForm validation updates its instance in memory only.
    clean=values(form.instance)
    policy=ResourcePolicy.objects.filter(clinic_id=clinic).first()
    data={'clinic':clinic,'revision':row.revision if row else 0,'fields':clean,
        'policy_revision':policy.revision if policy else None}
    return {'fields':clean,'display_fields':[(form.fields[k].label,clean[k]) for k in FIELDS],
        'proposal_token':proposal(actor,CONTRACT,('MANAGER',),data)}


@transaction.atomic
def confirm_directory(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对并确认发布资料。')
    payload=read_proposal(actor,CONTRACT,('MANAGER',),proposal_token)
    clinic=manager_clinic(actor,lock=True)
    data=payload['data']
    if data['clinic']!=clinic:raise PermissionDenied
    lock_physical(clinic)
    prior=ClinicDirectoryRevision.objects.filter(operation_id=payload['operation'],actor=actor,directory__clinic_id=clinic).first()
    if prior:return prior.directory,True
    policy=ResourcePolicy.objects.select_for_update().filter(clinic_id=clinic).first()
    if (policy.revision if policy else None)!=data['policy_revision']:raise RuleError('营业或资源资料已变化，请重新预览。')
    row=ClinicDirectory.objects.select_for_update().filter(clinic_id=clinic).first()
    if (row.revision if row else 0)!=data['revision']:raise RuleError('门店资料已有更新，请重新预览。')
    form=validated(clinic,data['fields'],row)
    row=form.save(commit=False);row.revision=data['revision']+1;row.save()
    ClinicDirectoryRevision.objects.create(directory=row,revision=row.revision,snapshot=values(row),
        actor=actor,operation_id=payload['operation'])
    if policy:
        policy.revision+=1;policy.save(update_fields=['revision'])
    emit(actor,'CLINIC_DIRECTORY_UPDATED',row,summary={'revision':row.revision,'published':row.is_published})
    return row,False
