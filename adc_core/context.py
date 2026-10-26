from django.conf import settings
from django.urls import reverse
from accounts.policies import has_role,bindings
from workspaces.rules import ROLES, CLINIC_ROLES
from workspaces.context import token_for, available_roles,channel_roles

NAV={
 'PATIENT':[('portal_home','服务首页'),('portal_slots','预约时间'),('portal_appointments','我的预约与账单'),('waitlist','我的候补'),('portal_assistant','操作问答')],
 'FRONT_DESK':[('patient_relationships','患者关系与代约'),('schedule_calendar','日周排班'),('availability_list','出诊维护'),('schedule_plans','候补排班'),('reception_list','电话接待与联系'),('resource_candidates','服务与资源查询'),('resource_coordination_list','资源故障协调'),('cash_receivables','应收核对'),('cash_list','收款与退款核对'),('frontdesk_home','接待首页'),('visits','预约与到诊'),('front_coordination_list','出诊协调'),('coordination_task_list','协调任务'),('notification_inbox','站内消息'),('patients','患者档案'),('patient_lookup','跨店患者识别'),('visit_create','创建预约'),('waitlist','候补协调'),('staff_assistant','操作问答')],
 'DENTIST':[('doctor_home','接诊首页'),('visits','本人接诊'),('patients','相关患者'),('corrections','我的更正申请'),('staff_assistant','操作问答')],
 'MANAGER':[('service_content_home','患者服务内容'),('resource_summary','接待与资源汇总'),('resource_catalogue','诊疗资源目录'),('resource_coordination_list','资源影响清单'),('reconciliation_home','渠道对账与差异'),('payment_accounts','本店渠道账户'),('maintenance_list','维护工单与验收'),('daily_close_list','日结对账与交接'),('equipment_list','设备管理'),('equipment_expenses','设备费用逐笔核对'),('equipment_cost_queue','费用补正审核'),('manager_home','本店概览'),('visits','预约运营'),('coordination_task_list','协调任务'),('notification_inbox','站内消息'),('waitlist','本店候补'),('operations_dashboard','本店运营分析'),('staff_assistant','操作问答')],
 'HQ':[('resource_summary','接待与资源汇总'),('reconciliation_home','渠道对账汇总'),('maintenance_list','维护工单与验收'),('daily_close_list','日结对账与交接'),('cash_receivables','应收汇总'),('cash_list','现金账汇总'),('equipment_expenses','设备费用汇总'),('equipment_cost_queue','费用补正查阅'),('equipment_list','设备概览'),('hq_home','总部概览'),('operations_dashboard','跨店运营'),('finance_quarters','季度财务查阅'),('catalogue_list','治疗价格目录'),('staff_assistant','操作问答')],
 'FINANCE':[('payment_accounts','渠道账户'),('reconciliation_home','渠道对账'),('maintenance_list','维护工单与验收'),('daily_close_list','日结对账与交接'),('cash_receivables','应收与退款余额'),('cash_list','现金账与独立审核'),('equipment_expenses','设备费用逐笔核对'),('equipment_cost_queue','费用补正审核'),('equipment_list','设备台账查阅'),('finance_home','财务首页'),('finance_quarters','季度成本与核对'),('catalogue_list','治疗价格目录'),('corrections','更正审核'),('staff_assistant','操作问答')],
 'SYSADMIN':[('technical_home','技术首页'),('directory_home','基础资料目录'),('account_manage_list','账号与授权')],
}

for _role in ('DENTIST','MANAGER'):
    NAV[_role].insert(0,('clinical_authority_home','专业操作范围'))
NAV['DENTIST'].insert(0,('clinical_worklist','检查记录工作台'))
NAV['DENTIST'].insert(1,('clinical_doctor_lab_queue','加工验收工作台'))
NAV['PATIENT'].append(('portal_history','我的健康自述'))
NAV['PATIENT'].append(('portal_plans','我的治疗计划'))
NAV['FRONT_DESK'].insert(5,('clinical_next_list','后续就诊安排'))
NAV['MANAGER'].append(('branch_directory_maintain','门店公开资料'))
NAV['FRONT_DESK'].insert(6,('clinical_recalls','复诊随访与责任'))
NAV['FRONT_DESK'].insert(7,('clinical_labs','加工件送返协调'))
for _role in ('MANAGER','HQ'):NAV[_role].append(('clinical_coordination_summary','复诊与准备汇总'))
for _role in ('FRONT_DESK', 'MANAGER', 'FINANCE', 'HQ'):
    NAV[_role].append(('insurance_home', '医保资料与模拟待遇'))
for _role in ('DENTIST','FRONT_DESK','MANAGER','PATIENT'):
    NAV[_role].append(('clinical_referrals','跨店转诊'))

for _role in ('DENTIST','MANAGER'):NAV[_role].append(('profile_home','医师与门店画像'))
for _role in ('DENTIST','MANAGER','FRONT_DESK','FINANCE','HQ'):NAV[_role].append(('management_home','工作与经营分析'))

NAV['FRONT_DESK'].append(('profile_coordination','医师任职与原约协调'))
NAV['MANAGER'].append(('profile_coordination','接诊范围协调'))
for _role in ('FINANCE','HQ'):NAV[_role].append(('management_chain','全链经营汇总'))

def navigation(request):
    user=request.user;ctx=getattr(request,'workspace',None)
    role=ctx.role if ctx else '';clinic=ctx.clinic if ctx and ctx.clinic_id else None
    choose_clinic=role in CLINIC_ROLES and clinic is None
    items=[] if choose_clinic else NAV.get(role,[])
    data={'can_front':has_role(user,'FRONT_DESK'),'can_manage':has_role(user,'MANAGER'),
      'is_dentist':has_role(user,'DENTIST'),'build_version':settings.ADC_VERSION,'adc_read_only':settings.ADC_READ_ONLY,
      'environment_label':settings.ADC_PUBLIC_ENVIRONMENT_LABEL,
      'can_finance':bindings(user).filter(role__in=['FINANCE','HQ'],scope_kind='CHAIN').exists(),
      'can_operations':role in ('MANAGER','HQ') and not choose_clinic,
      'can_correct':role in ('DENTIST','FINANCE'),'can_assist':role in ('FRONT_DESK','DENTIST','MANAGER','HQ','FINANCE'),
      'workspace_role':role,'workspace_label':ROLES.get(role,('选择工作身份',''))[0],
      'workspace_scope':clinic.name if clinic else ('请先选择诊所' if choose_clinic else {'DENTIST':'本人负责接诊','PATIENT':'本人资料','HQ':'全链授权汇总','FINANCE':'全链财务','SYSADMIN':'基础资料、账号与技术配置'}.get(role,'')),
      'workspace_can_switch_role':len(channel_roles(user,ctx) if ctx else available_roles(user)) > 1,
      'workspace_needs_clinic':choose_clinic,'workspace_has_clinics':role in CLINIC_ROLES,
      'workspace_token_value':token_for(ctx) if ctx else '',
      'workspace_revision':ctx.revision if ctx else 0,
      'workspace_home':reverse(ROLES[role][1]) if role in ROLES else reverse('select_role'),
      'workspace_nav':[{'url':reverse(n),'label':label,'active':getattr(request,'resolver_match',None) and request.resolver_match.url_name==n} for n,label in items],
      'base_template':'portal/base.html' if role=='PATIENT' else 'base.html'}
    if role=='PATIENT':
        from portal.policies import patient_access
        from django.core.exceptions import PermissionDenied
        try:
            access=patient_access(user)
            data.update(patient_subject=access.patient.name,patient_delegated=access.delegated,
                patient_capacity=(access.source.relationship.get_kind_display()+' · '+access.source.relationship.clinic.name) if access.delegated else '本人',
                workspace_scope='预约代办' if access.delegated else '本人资料')
            if access.delegated:
                data['workspace_nav']=[item for item in data['workspace_nav'] if item['url'] not in (reverse('clinical_referrals'),reverse('portal_history'),reverse('portal_plans'))]
                for item in data['workspace_nav']:
                    if item['label']=='我的预约与账单':item['label']='当前患者预约'
        except PermissionDenied:pass
    return data
