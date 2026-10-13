"""Versioned, reviewed page/button directory; LLMs cannot invent these steps."""
from dataclasses import dataclass
VERSION='NAV-09A10.1'
@dataclass(frozen=True)
class Step:
    title:str
    instruction:str
    route:str
    selector:str=''
@dataclass(frozen=True)
class Guide:
    key:str
    title:str
    roles:tuple
    goal:str
    steps:tuple

def S(title,text,route,selector=''):return Step(title,text,route,selector)
GUIDES={g.key:g for g in [
 Guide('task-notices','查看任务站内消息',('MANAGER','FRONT_DESK'),'通知不是受理、患者同意或业务完成；当前身份与诊所范围仍须核对。',(
 S('查询当前收件箱','打开“站内消息”，仅查看事件发生时属于本人且当前仍获授权的所选身份/本店消息。没有消息不代表没有任务。','notification_inbox'),
 S('核对任务当前事实','按消息中的任务编号进入“查看任务当前事实”。消息记录的是历史变化，任务可能已有后续变化。','notification_inbox'),
 S('明确标记已读','需要时由本人点击“标记已读”。打开页面不会自动标记；已读不表示接受任务，也不替患者作决定。','notification_inbox'))),
 Guide('patient-book','预约一个时间',('PATIENT',),'你明确确认后，系统才创建预约。',(
 S('选择诊所和日期','打开“预约时间”，选择诊所和日期，点击“查找时间”。','portal_slots','#clinic-filter'),
 S('选择候选时段','找到合适的日期、医生和诊所，点击“选择此时段”。这一步还没有创建预约。','portal_slots','.slot-grid'),
 S('核对并确认','在“最后核对一次”页面检查完整日期和时间，勾选确认后点击“确认提交预约”。如果提示失效，返回重新选择。','portal_slots'),
 S('查看实际结果','打开“我的预约与账单”，核对刚提交的记录。只有系统保存的预约才代表成功；助手不会代你提交。','portal_appointments'))),
 Guide('patient-cancel','取消未开始的预约',('PATIENT',),'取消会保留历史，不是删除记录。',(
 S('找到目标预约','打开“我的预约与账单”，核对日期、诊所和医生，再进入对应详情。','portal_appointments'),
 S('手动确认取消','详情页若显示“取消这次预约”，点击后填写原因并确认。没有按钮时，可能已经开始或不在已预约状态，请联系前台。','portal_appointments'),
 S('核对状态','返回该预约详情，确认实际状态为“已取消”。本引导没有自行取消任何记录。','portal_appointments'))),
 Guide('patient-bill','查看自己的结算单',('PATIENT',),'开单金额不表示已付款。',(
 S('找到已就诊记录','打开“我的预约与账单”，选择需要查询的就诊记录。','portal_appointments'),
 S('打开结算单','在预约详情点击“查看结算单”。若未形成结算单，请等待医生完成接诊；不能推断为免费。','portal_appointments'),
 S('核对金额与版本','逐行查看治疗、数量、单价、小计和总金额。历史版本与当前版本有不同标记。','portal_appointments'))),
 Guide('patient-wait','登记或确认候补',('PATIENT',),'候补登记不是预约，邀约过期也不会自动预约。',(
 S('登记偏好','进入“我的候补”，点击“登记候补”，填写未来14天内的可接受时间与诊所。','waitlist'),
 S('查看邀约','在候补列表查看工作人员发出的邀约，核对医生、诊所、日期和到期时间。','waitlist'),
 S('明确接受或拒绝','打开邀约，勾选核对后，点击“接受并创建预约”或“拒绝本次邀约”。只有成功接受才会创建预约。','waitlist'),
 S('核对预约','在“我的候补”选择目标记录，点击“核对这条候补是否已转预约”。不确定上一操作结果时也先核对，不重新接受；有对应预约时再打开其详情。','portal_appointments'))),
 Guide('front-create','为患者创建预约',('FRONT_DESK',),'当前诊所范围内办理，提交前再次检查冲突。',(
 S('定位患者','先在“患者档案”或“跨店患者识别”查询。确为新患者，再选择“建立患者档案”。','patients'),
 S('填写预约','打开“创建预约”，填患者业务编号，选择出诊时段，填写开始与预计结束时间。','visit_create','#id_patient_no'),
 S('核对并提交','核对患者、医生、诊所和北京时间，点击“确认预约”。若时段被占用，请重新选择。','visit_create'),
 S('查看保存结果','到“预约与到诊”打开记录，检查预约编号和状态。','visits'))),
 Guide('front-arrive','登记患者实际到诊',('FRONT_DESK',),'到诊与治疗完成是两件事。',(
 S('打开预约','到“预约与到诊”找到目标记录，核对患者和日期后进入详情。','visits'),
 S('选择动作','在“更新预约结果”中将动作选为“登记到诊”，点击“确认执行”。只对真实到诊的演示记录操作。','visits'),
 S('检查结果','核对记录状态为“已到诊”；实际治疗由负责医生在自己的工作台填写。','visits'))),
 Guide('front-change','办理改期或取消',('FRONT_DESK',),'先核对业务状态，不随意恢复终态。',(
 S('查找目标','从“预约与到诊”打开尚未到诊的目标预约。','visits'),
 S('明确是哪一种操作','取消：选“取消预约”，填写发起方和原因；改期：点击“改期并创建后继预约”，选择新时段并说明原因。','visits'),
 S('确认并核对','亲自点击确认，再检查保存结果。改期失败时原预约应继续有效。','visits'))),
 Guide('doctor-care','复核并记录实际治疗',('DENTIST',),'仅处理本人负责的已到诊记录；本任务不要求结束接诊或生成结算单。',(
 S('找到本人接诊','从牙医工作台的“本人接诊”找到目标患者；核对后进入该条已到诊记录的接诊工作区。','doctor_home'),
 S('复核过敏资料','在“1. 复核过敏信息”如实选择已核实状态和条目，点击“保存本次复核”。不要将未知信息填成无过敏。','doctor_home'),
 S('记录实际治疗','在“2. 确认实际治疗”选择已提供的项目与数量，点击“确认并添加治疗”。误录草稿可填写原因后撤回。','doctor_home'),
 S('核对已保存明细','检查接诊页面出现了正确项目和数量。本任务到此结束；只有确实需要结束接诊时，才另外使用“完成接诊与结算”指南。','doctor_home'))),
 Guide('doctor-close','完成接诊与结算',('DENTIST',),'独立于记录治疗；仅当真实接诊确已结束时执行。',(
 S('核对接诊内容','从“本人接诊”进入已到诊记录，复核过敏与全部已提供的实际治疗；不能用预约意向代替治疗事实。','doctor_home'),
 S('进入结束确认','点击“3. 核对并关闭本次接诊”，核对结果类型、全部明细与金额。没有治疗时选择无治疗关闭并填写原因。','doctor_home'),
 S('由本人明确提交','只有确实结束接诊且数据正确时才点击确认；本指南不会自动提交。','doctor_home'),
 S('核对正式结算单','系统返回结算单后核对单号、明细、金额和版本；开单不是已经付款。','visits'))),
 Guide('doctor-correct','申请已发布账单数字更正',('DENTIST',),'保留原版，不能由自己切换财务身份审批。',(
 S('打开账单','从本人已完成就诊打开当前结算单，选择更正入口。','visits'),
 S('填写依据','本版仅支持一条原治疗行的数量或单价更正。核对差异并填写事实依据。','corrections'),
 S('等待独立审核','提交后查看“我的更正申请”。财务批准前，原版仍为当前版本。','corrections'))),
 Guide('manager-slots','查看并新增本店出诊安排',('MANAGER',),'身份不变，诊所须先选择正确。',(
 S('确认当前诊所','页首核对诊所；需要换店时使用“切换诊所”，不要手动篡改表单编号。','manager_home'),
 S('新增出诊','在“出诊安排”点击“新增出诊安排”，选择医生、开始和结束时间，然后点击“保存出诊安排”。','slot_create','#id_dentist'),
 S('核对后续可用性','成功提示说明已保存；预约仍会再次检查患者与医生的时段冲突。本版不含椅位和交通时间优化。','manager_home'))),
 Guide('manager-plan','给本店候补生成排程建议',('MANAGER',),'建议不是已发布邀约，邀约也不是已确认预约。',(
 S('检查候补','先在“本店候补”查看时间偏好；有过期邀约时，明确确认后点击“回收过期邀约”。','waitlist'),
 S('生成建议','进入“排程建议”，阅读求解范围并勾选确认，点击“生成候选安排”。','schedule_plans'),
 S('核对方案','查看医生、时间、未安排数量和算法边界；合适时勾选确认并点击“发布限时邀约”。','schedule_plans'),
 S('等待本人或前台确认','邀约默认保留15分钟或直到开始时间，以较早者为准。患者或前台明确接受后形成正式预约。','waitlist'))),
 Guide('manager-ops','查看本店运营指标',('MANAGER',),'明确分子、分母、期间与缺失，不能评价临床能力。',(
 S('确认范围','核对页面顶端当前诊所。','manager_home'),
 S('选择期间','打开“本店运营分析”，填写开始与结束日期并查询。','operations_dashboard'),
 S('解释指标','分别阅读到诊、患者取消、诊所取消、爽约与待核实；没有样本时N/A不是0%。','operations_dashboard'))),
 Guide('finance-quarter','录入季度成本并核对测算',('FINANCE',),'缺失成本不等于零，开单收入不等于实收。',(
 S('选择季度','进入“季度成本与核对”，建立或选择自然季度。','finance_quarters'),
 S('纳入相关牙医','补充季度纳入清单，包括有成本但无收入的牙医；不能只纳入有开单者。','finance_quarters'),
 S('录入并确认','逐项填写用品成本、运营费用和依据；零也要显式填写并确认。','finance_quarters'),
 S('检查完整性','确认人员范围后查看缺失项，再核对利润与总体基金测算。个人奖金政策未由本系统决定。','finance_quarters'))),
 Guide('finance-review','审核医生的账单更正',('FINANCE',),'申请和批准必须是不同账号。',(
 S('打开待审申请','在“更正审核”选择待审核记录。','corrections'),
 S('核对差异','核对原版本、更正数字、金额变化与理由；只处理本版支持的数字更正。','corrections'),
 S('明确批准或拒绝','选择动作并确认。批准后再核对当前版本；拒绝则旧版本继续有效。','corrections'))),
 Guide('hq-overview','查阅跨店运营和季度财务',('HQ',),'总部查阅不等于财务写入。',(
 S('查询运营','在总部工作台打开“跨店运营”，选择日期和诊所范围。','operations_dashboard'),
 S('查阅季度','需要财务核对时打开“季度财务查阅”；缺失信息必须保留。','finance_quarters'))),
 Guide('switch-role','切换身份或诊所',tuple(['PATIENT','FRONT_DESK','DENTIST','MANAGER','HQ','FINANCE','SYSADMIN']),'当前身份只决定工作环境，不产生新授权。',(
 S('先处理未提交内容','提交或放弃当前草稿后，点击页首“切换身份”。不同页面中未提交的字段不会被系统自动保存。','select_role'),
 S('选择已有身份','在身份选择页选择数据库已授权的身份，进入对应工作台。主管和前台还需在工作台选择诊所。','select_role'),
 S('检查页首','确认页首的身份和范围正确。旧页面的提交将被拒绝，刷新后再操作。','dashboard'))),
 Guide('display-mode','调整字号和使用帮助',tuple(['PATIENT','FRONT_DESK','DENTIST','MANAGER','HQ','FINANCE','SYSADMIN']),'不按年龄强制分流，也不要求使用聊天。',(
 S('调整字号','点击页首“大字简明模式”；再次点击可返回标准模式。','dashboard','.mode-toggle'),
 S('按步骤操作','选择一份任务指南，每次阅读当前步骤。可以暂停、返回或退出；助手不会点击业务提交按钮。','guide_index'))),
]}

GUIDES['patient-appointments']=Guide('patient-appointments','查找自己的预约',('PATIENT',),'本人数据范围，不查询其他患者。',(
 S('打开记录','点击“我的预约与账单”，查看本人计划时间和状态。','portal_appointments'),
 S('核对详情','打开相应记录核对诊所、日期、医生和预约状态；尚未到诊不等于取消。','portal_appointments')))
GUIDES['front-wait']=Guide('front-wait','帮助患者办理候补',('FRONT_DESK',),'与患者自助采用相同的登记和确认规则。',(
 S('确认诊所和患者','核对当前诊所，点击“登记候补”，填写患者编号、希望时间和医生偏好。','waitlist'),
 S('核对邀约','在候补列表打开有效邀约，向患者说明具体日期、医生和确认期限。','waitlist'),
 S('明确确认','取得患者明确同意后亲自点击“接受并创建预约”。不确定保存结果时，从本店候补点击只读核对按钮；不要重复办理。拒绝不会产生预约。','waitlist')))

ROLE_INTENT={
 'PATIENT':{'book':'patient-book','appointments':'patient-appointments','cancel':'patient-cancel','bill':'patient-bill','waitlist':'patient-wait'},
 'FRONT_DESK':{'appointment_policy':'front-change','overview':'front-arrive','waitlist':'front-wait','book':'front-create'},
 'DENTIST':{'care_help':'doctor-care','billing_policy':'doctor-close','correction':'doctor-correct','overview':'doctor-care'},
 'MANAGER':{'overview':'manager-ops','appointment_policy':'manager-slots','waitlist':'manager-plan','planning':'manager-plan'},
 'FINANCE':{'billing_policy':'finance-quarter','finance':'finance-quarter','correction':'finance-review','overview':'finance-quarter'},
 'HQ':{'overview':'hq-overview','finance':'hq-overview'},
}

def choose_guide(role,intent,message=''):
    if intent=='clinical':return None
    if role in ('MANAGER','FRONT_DESK') and any(x in message for x in ('协调任务','受理任务','任务复核','办理声明')):return 'manager-task' if role=='MANAGER' else 'front-task'
    if role=='MANAGER' and any(x in message for x in ('暂停新增','暂停接收','恢复接收','停止接收','停止新增')):return 'manager-intake'
    if role=='FRONT_DESK' and '出诊' in message and any(w in message for w in ('协调','停用','停诊','调整','改期','关联')):return 'front-coordination'
    if intent=='clinical':return None
    if role=='FRONT_DESK' and any(x in message for x in ('更正','修改','更新','换')) and any(x in message for x in ('联络','联系电话','联系信息','手机号','电话','邮箱','账单地址','紧急联系人')):return 'front-contact'
    if role=='FRONT_DESK' and intent=='appointment_policy' and any(x in message for x in ('创建','新预约','安排预约','帮患者预约')) and not any(x in message for x in ('取消','改期','爽约')):return 'front-create'
    if intent=='accessibility':return 'display-mode'
    if any(x in message for x in ('切换身份','切换诊所')):return 'switch-role'
    return ROLE_INTENT.get(role,{}).get(intent)

# SU-26: curated manual navigation; no patient is selected by the assistant.
GUIDES['front-contact'] = Guide('front-contact','更正患者联络资料',('FRONT_DESK',),
 '只更正本人已核对的联络资料；身份、过敏、账号绑定和历史账单不是本任务的编辑对象。', (
 S('确认诊所和患者','在前台工作台核对当前诊所，进入“患者档案”，由你选择准确的患者并核对业务编号。','patients'),
 S('填写联络变更','在患者详情进入“更正联络资料”，填写需要更正的电话、邮箱、账单地址或紧急联系人，并选择依据。','patients'),
 S('查看差异','点击“下一步：核对差异（不保存）”，核对变更前与拟保存值；此时尚未写入。','patients'),
 S('亲自确认并核对','只有与患者确认无误时才勾选确认并保存。回到同一患者档案核对实际值；结果不明确时先查看，不重复提交旧页。','patients'),
))

# v0.9a5: directory tasks are manual SYSADMIN-only navigation, not external AI actions.
GUIDES['technical-directory'] = Guide('technical-directory','登记诊所或牙医基础资料',('SYSADMIN',),
 '资料登记、账号授权和出诊安排是不同任务；仅使用合成资料。',(
 S('先查重复','在“基础资料目录”选择诊所、牙医或资格类别，按编码或名称查找原记录；不要换编号重复登记。','directory_home'),
 S('填写并预览','选择“登记新的…”填写资料及登记依据，点击“预览并核对（尚不保存）”。','directory_home'),
 S('确认再保存','在核对页检查目标和全部资料，输入自己的技术管理密码并明确确认后保存；不确定结果时先按原编码查询。','directory_home'),
 S('分别办理后续事项','登记牙医后可核对资格关联；需要登录的账号另去“账号与授权”创建并授权，出诊由主管另行安排。','account_manage_list')))
GUIDES['technical-qualifications'] = Guide('technical-qualifications','登记或更正牙医资格关联',('SYSADMIN',),
 '关联只是登记事实，不判断执业许可、治疗适配性或有效期。',(
 S('定位牙医','在基础资料目录查到具体牙医，核对员工编号与姓名，查看资格关联记录。','directory_home'),
 S('明确登记或撤回','新增／恢复时选择已经登记的资格类别与相应依据；误关联使用“预览撤回误关联”，不是删除历史。','directory_home'),
 S('核对并确认','预览页明确当前关联和拟执行动作，输入自己的技术管理密码后确认。旧页失效时重新读取，不覆盖他人修改。','directory_home'),
 S('核对当前状态','成功后查看同一牙医的关联状态；没有自动取消预约、停用账号或认证专业资格。','directory_home')))

GUIDES['manager-availability']=Guide('manager-availability','调整或停用未来空闲出诊',('MANAGER',),
 '只处理当前店未开始且无有效占用的时段；不代患者改期，不删除历史。',(
 S('核对原安排','进入“出诊安排”，找到牙医和完整日期，点击“查看安排与影响”。','availability_list'),
 S('查看是否存在占用','有预约、接诊或有效邀约时，按详情中的协调步骤处理，再重新读取；主管不能借此取消预约。','availability_list'),
 S('填写拟变更','满足条件时选择“调整未来空闲时段”或“停用原时段”，填写时间与依据，点击“预览影响，尚不保存”。','availability_list'),
 S('人工确认并查结果','核对新旧时间与历史保护提示，明确确认后从原记录查看状态和替代编号；回执未知时先查询，不重复新增。','availability_list')))

GUIDES['front-coordination']=Guide('front-coordination','按出诊协调预约与邀约',('FRONT_DESK',),
    '先核实主管计划与患者意思；只读列表不暂停接收预约，不表示停诊任务已经下达。',(
    S('确定原出诊','在当前诊所输入主管提供的出诊编号，核对牙医与原时间。','front_coordination_list'),
    S('分类核对关联','进入所选出诊，分别查看已预约、受保护接诊及邀约期限；查询未知不等于没有预约。','front_coordination_list'),
    S('进入原业务入口','需要变更时逐条进入原预约或邀约详情，核实患者意思后明确确认；不取消受保护接诊。','front_coordination_list'),
    S('返回并重新核对','用页面中的返回链接读取原出诊当前状态。无阻断时请主管另行核验，不能把旧查询结果当作停用许可。','front_coordination_list'),
))

GUIDES['manager-intake']=Guide('manager-intake','暂停或恢复出诊新增接收',('MANAGER',),
 '停止新增不等于取消已有预约；有效邀约仍可在原期限内确认。',(
 S('找到本店出诊','在主管工作台选择诊所，进入“出诊安排”，核对出诊编号、牙医、日期和当前接收状态。','availability_list'),
 S('选择接收控制','在出诊详情选择“核对并暂停新增”或“核对并恢复接收”，选择已核对的依据。','availability_list'),
 S('预览后明确确认','逐项核对拟保存状态、既有预约与有效邀约保留规则；预览尚未保存，只有亲自确认才生效。','availability_list'),
 S('核对并分别协调','返回原出诊确认当前状态。前台仍在自己的工作台按原流程协调；有效邀约接受后仍会增加关联预约，最终维护需再次核验。','availability_list')))


GUIDES['manager-task']=Guide('manager-task','发起和复核出诊协调任务',('MANAGER',),
 '任务不改变预约或接收状态；复核人与提交复核的前台必须为不同账号。',(
 S('核对并暂停新增','从本店出诊核对计划，确需协调时先明确暂停新增，再发起协调任务。有效旧邀约仍可确认。','availability_list'),
 S('明确发起任务','在原出诊详情进入“发起协调任务”，选择停用或调整目标和依据；预览后亲自确认。','availability_list'),
 S('独立复核或退回','从“协调任务”查看当前关联事实。仍有预约、有效邀约或事实变化时，不可通过复核；原受理人无法继续时可退回队列。','coordination_task_list'),
 S('分别办理出诊维护','协调复核通过不等于原出诊已停用；返回原出诊，通过原维护命令重新检查并确认。撤销任务也不会自动恢复接收。','availability_list')))
GUIDES['front-task']=Guide('front-task','受理并办理出诊协调任务',('FRONT_DESK',),
 '先明确本人责任，再按原流程处理；办理声明不证明患者同意。',(
 S('受理准确任务','在当前店“协调任务”核对原出诊和主管目标，选择受理、核对依据并确认。','coordination_task_list'),
 S('按原流程协调','进入任务中的关联出诊入口，核实患者意思，分别进入原预约或邀约页面。不得为清空排班取消受保护接诊。','front_coordination_list'),
 S('记录本人声明','返回任务，记录明确对象的联络或办理声明。不要填写姓名、电话或病史；声明不会改变原预约记录。','coordination_task_list'),
 S('核对后提交复核','只有重新查询未发现阻断且仍暂停新增时，才能提交主管复核；需要交接时退回待受理队列，不直接标记已完成。','coordination_task_list')))
