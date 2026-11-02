"""Patient-visible copies use selected frozen clinical sections, never the staff archive package."""
from clinical.archive_display import label,flatten
from clinical import record_copies as commands

GROUPS={
 'DOCUMENT':['document','clinical_source'],
 'TREATMENT':['plan_versions','steps','scheme_decisions','actuals','preflights','gaps','gap_reviews','laboratory','laboratory_reviews'],
 'CONSENT':['medical_notices','medical_events'],
 'FEES':['fee']}
PRIVATE={'source','operation_id','scope_digest','source_cursor','digest','contract','approval_scope',
 'identity_reference','authority_reference','verification','patient_snapshot','logistics_note','review_note'}


def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in PRIVATE and not k.endswith('_by') and not k.endswith('_id')}
    if isinstance(value,list):return [clean(v) for v in value]
    return value


def packet(row):
    records=[];sources=[]
    for item in commands.items(row):
        snapshot=item.package.manifest['source_snapshot'];sections=[]
        for group in item.sections:
            for key in GROUPS[group]:
                value=clean(snapshot.get(key))
                sections.append(dict(title=label(key),rows=list(flatten(value)) if value else [('资料情况','本固定版本无此类记录；不推定已实施或资料齐备。')]))
        missing=[x['message'] for x in snapshot.get('issues',[])]
        records.append(dict(header=snapshot['header'],sections=sections,kind=item.package.submission.kind,missing=missing))
        sources.append(dict(visit=item.visit_id,package=item.package_id,package_number=item.package.number,
            source_pdf_sha256=item.package.pdf_sha256,document_version=item.package.manifest.get('document_version'),sections=list(item.sections)))
    return dict(request=row.pk,purpose=row.purpose,recipient=row.recipient_name,kind=row.get_kind_display(),
        clinic=row.clinic.name,records=records,sources=sources)


def data(row):
    can_pickup=row.state in ('READY','DELIVERED') and row.pickup_until is not None
    from django.utils import timezone
    expired=bool(row.pickup_until and row.pickup_until<=timezone.now())
    return dict(id=row.pk,patient=row.patient.name,clinic=row.clinic.public_contact['name'],kind=row.get_kind_display(),
        recipient=row.recipient_name,purpose=row.purpose,state=row.state,
        status_label='领取期限已到，请联系门店重新核验' if expired and can_pickup else row.get_state_display(),
        revision=row.revision,created_at=row.created_at.isoformat(),pickup_until=row.pickup_until.isoformat() if row.pickup_until else None,
        message={'PDF_RENDER_FAILED':'文件生成暂时中断，请联系门店按原申请重试。','IDENTITY_SCOPE_OR_REVIEW_CHANGED':'核验依据已变化，请联系门店停止旧领取并重新核验申请。'}.get(row.generation_error,row.patient_message),can_pickup=can_pickup and not expired,
        can_resubmit=row.state=='NEED_INFO',can_withdraw=row.state in commands.OPEN,
        items=[dict(visit=i.visit_id,visit_no=i.visit.visit_no,package_number=i.package.number if i.package_id else None,
            kind=i.package.submission.get_kind_display() if i.package_id else '待负责医师完成固定材料',sections=[commands.SECTIONS[k] for k in i.sections]) for i in commands.items(row)],
        file=dict(sha256=row.file.sha256,bytes=len(row.file.pdf)) if hasattr(row,'file') else None,
        history=[dict(action={'SUBMIT':'本人提出申请','REGISTER':'前台登记本用途代理申请','VERIFY':'身份与用途核验',
            'REVIEW':'独立医务审核','RESUBMIT':'补充材料办理说明','WITHDRAW':'申请人撤回','REVOKE':'领取权撤销',
            'GENERATION_READY':'副本已生成','GENERATION_FAILED':'生成失败待处置','RETRY':'明确重试生成',
            'CLAIM':'领取确认','FILE_RESPONSE':'服务端已生成文件响应，阅读情况未知'}.get(e.action,e.action),
            at=e.created_at.isoformat(),state=e.snapshot.get('state')) for e in row.events.order_by('pk')])
