from django.conf import settings
from django.urls import reverse
from accounts.policies import has_role,bindings
from workspaces.rules import ROLES, CLINIC_ROLES
from workspaces.context import token_for, available_roles

NAV={
 'PATIENT':[('portal_home','服务首页'),('portal_slots','预约时间'),('portal_appointments','我的预约与账单'),('waitlist','我的候补'),('portal_assistant','操作问答')],
 'FRONT_DESK':[('cash_receivables','应收核对'),('cash_list','收款与退款核对'),('frontdesk_home','接待首页'),('visits','预约与到诊'),('front_coordination_list','出诊协调'),('coordination_task_list','协调任务'),('notification_inbox','站内消息'),('patients','患者档案'),('patient_lookup','跨店患者识别'),('visit_create','创建预约'),('waitlist','候补协调'),('staff_assistant','操作问答')],
 'DENTIST':[('doctor_home','接诊首页'),('visits','本人接诊'),('patients','相关患者'),('corrections','我的更正申请'),('staff_assistant','操作问答')],
 'MANAGER':[('equipment_list','设备管理'),('equipment_expenses','设备费用逐笔核对'),('manager_home','本店概览'),('visits','预约运营'),('availability_list','出诊安排'),('coordination_task_list','协调任务'),('notification_inbox','站内消息'),('waitlist','本店候补'),('schedule_plans','排程建议'),('operations_dashboard','本店运营分析'),('staff_assistant','操作问答')],
 'HQ':[('cash_receivables','应收汇总'),('cash_list','现金账汇总'),('equipment_expenses','设备费用汇总'),('equipment_list','设备概览'),('hq_home','总部概览'),('operations_dashboard','跨店运营'),('finance_quarters','季度财务查阅'),('catalogue_list','治疗价格目录'),('staff_assistant','操作问答')],
 'FINANCE':[('cash_receivables','应收与退款余额'),('cash_list','现金账与独立审核'),('equipment_expenses','设备费用逐笔核对'),('equipment_list','设备台账查阅'),('finance_home','财务首页'),('finance_quarters','季度成本与核对'),('catalogue_list','治疗价格目录'),('corrections','更正审核'),('staff_assistant','操作问答')],
 'SYSADMIN':[('technical_home','技术首页'),('directory_home','基础资料目录'),('account_manage_list','账号与授权')],
}

def navigation(request):
    user=request.user;ctx=getattr(request,'workspace',None)
    role=ctx.role if ctx else '';clinic=ctx.clinic if ctx and ctx.clinic_id else None
    choose_clinic=role in CLINIC_ROLES and clinic is None
    items=[] if choose_clinic else NAV.get(role,[])
    data={'can_front':has_role(user,'FRONT_DESK'),'can_manage':has_role(user,'MANAGER'),
      'is_dentist':has_role(user,'DENTIST'),'build_version':settings.ADC_VERSION,'adc_read_only':settings.ADC_READ_ONLY,
      'can_finance':bindings(user).filter(role__in=['FINANCE','HQ'],scope_kind='CHAIN').exists(),
      'can_operations':role in ('MANAGER','HQ') and not choose_clinic,
      'can_correct':role in ('DENTIST','FINANCE'),'can_assist':role in ('FRONT_DESK','DENTIST','MANAGER','HQ','FINANCE'),
      'workspace_role':role,'workspace_label':ROLES.get(role,('选择工作身份',''))[0],
      'workspace_scope':clinic.name if clinic else ('请先选择诊所' if choose_clinic else {'DENTIST':'本人负责接诊','PATIENT':'本人资料','HQ':'全链授权汇总','FINANCE':'全链财务','SYSADMIN':'基础资料、账号与技术配置'}.get(role,'')),
      'workspace_can_switch_role':len(available_roles(user)) > 1,
      'workspace_needs_clinic':choose_clinic,'workspace_has_clinics':role in CLINIC_ROLES,
      'workspace_token_value':token_for(ctx) if ctx else '',
      'workspace_revision':ctx.revision if ctx else 0,
      'workspace_home':reverse(ROLES[role][1]) if role in ROLES else reverse('select_role'),
      'workspace_nav':[{'url':reverse(n),'label':label,'active':getattr(request,'resolver_match',None) and request.resolver_match.url_name==n} for n,label in items],
      'base_template':'portal/base.html' if role=='PATIENT' else 'base.html'}
    return data
