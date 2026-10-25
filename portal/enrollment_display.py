DETAIL_LABELS=(('name','患者姓名'),('date_of_birth','出生日期'),('phone','联络号码'),('billing_address','账单／联系地址'),('email','电子邮箱'),('emergency_name','紧急联系人'),('emergency_phone','紧急联系电话'),('patient_reference','原患者编号'))


def detail_rows(details):
    return [dict(label=label,value=details.get(key) or '未填写') for key,label in DETAIL_LABELS]


ACTION_LABELS={'SUBMIT':'提交申请','APPROVE':'核验通过并关联','NEED_INFO':'退回补充资料','REJECT':'未通过','WITHDRAW':'患者撤回'}
