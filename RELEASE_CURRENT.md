# 当前患者端跟进：登录反馈修复与独立业务联调

原生源码`f4020475277daa5d0d7eaac45594d85bcacb62ea`通过[准确完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/41065280427)，267原生检查／28账号处理场景及12项真实页面处理函数＋HTTP检查通过。后端仍为下方已验收C3.1应用，未切换镜像或改数据库；原微信绑定与密码保留。

[WorkBuddy接续](docs/WORKBUDDY_FOLLOWUP_20261030.md) · [证据](docs/evidence_wb_followup/README.md)。新双工程包含18000真实微信测试和18315独立合成业务测试，专用账号私下交付。工具／平台、手机、第二身份、固定HTTPS和密钥文件化分别保留未完成状态。以下C3.1继续是当前运行后端。

---

# 当前 C3.1：初复诊病历文书已交付

实际接诊 → 完整文书 → 医师确认 → 历史比较／追加更正 → 责任待办。

应用`90ddb5c7ca5f6dfbc4357ef958f37715a8867719`、镜像`sha256:3b17edf500e0f90b7e0ac71470179227d0f8579227b3d7729d32de75bd8a9d43`已保护更新本机18000；[准确完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/41015873261)通过。[分项结果](docs/evidence_c31/README.md)记录1,158规则、2,132PG、34专项、35精确镜像Chrome及21项原安装检查。

65份迁移，原64份保持字节；146表／402外键／114触发器／33实际ER。两次加密独立恢复与原系统副本升级通过。原139组数据、密码、私有配置、数据库卷和RC标签保留；正式报告240页、120业务用例加SF-01，文件名不变。

[病历业务合同](docs/C31_CLINICAL_DOCUMENT_CONTRACT.md) · [C3后续路线](docs/C3_RECORD_CONSENT_ARCHIVE_PLAN.md) · [WorkBuddy部署任务](docs/WORKBUDDY_C31_TASK.md)。小程序业务源码和独立教师实例未更新；真实微信一个账号的既有本地结果保留，手机／第二账号／体验版由部署方分别验收。C3.2治疗知情同意、可靠电子签名及C3.3归档尚未完成，不据此标记临床商用资格。

---

# 历史WX1：本机真实微信与网站确认已交付

下一阶段系统本体开发见[C3规划](docs/C3_RECORD_CONSENT_ARCHIVE_PLAN.md)：病历文书→医疗同意→归档与受控副本；原制定时状态PLANNED；C3.1当前交付见本页顶部，C3.2及后续尚待实施。WorkBuddy继续只负责小程序部署。

真实微信登录 → 同一ADC账号 → 原患者权限 → 部署专责交接。

应用`379286ecedafe334ae821886c53fc2e51bbe2c2b`、镜像`sha256:17e868bae12944d6ad5dc13af964d615b8ca8dd2836c59cb6c7208c3cdd390ec`已保护更新本机；[准确提交完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40999423309)通过。真实微信首次／重复登录及网站小程序码确认已使用一个真实账号在官方开发者工具完成，网站通过实际本机网关复测；未使用模拟手机号、验证码或平台响应。实际手机、第二微信账号、教师体验版和固定云端仍待验收。真实短信保持关闭。

原账号密码、业务历史、64份迁移和RC标签保留。142表／388外键／110启用触发器保持不变；加密独立恢复核对139组业务与认证记录，恢复后再使未完成认证挑战失效。原生客户端与交接c6d1e15的代码相同；独立教师实例未在本轮更新。正式课程报告文件保留，当前更新是认证运行及交接材料。

[WorkBuddy后端就绪回传](docs/WX1_BACKEND_READY.md) · [分项证据](docs/evidence_wx_live/README.md) · [机器可读结果](docs/evidence_wx_live/release.json)。历史D1及其他交付如下，按其原时点解释。

---

# 历史D1：独立上线准备已交付

应用`b6a8169ec62a18926b18171b98165a657b205c1d`，准确[完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40694177966)通过1,156规则／2,096PG。arm64与amd64镜像见[发布包身份](docs/evidence_d1/builds.json)。本机及独立教师实例已保护更新。报告228页，文件名不变。

[当前分项证据](docs/evidence_d1/README.md) · [部署／升级／备份／恢复](docs/D1_CLOUD_RELEASE.md)。二十店空库初始化及重复调用、80能力组合、同卷升级回退、142表加密恢复及ER一致性已通过；实际服务器、真实COS／微信／短信、手机和24小时持续观察仍未通过。服务器尚未购买。原Windows数据恢复UNRESOLVED。

后续文档变更保持准确应用字节／镜像不变，文档CI不替代完整CI。

# P1.5 历史交付 小程序患者入口与完整画像

二十店实际能力 → 选店选医 → 患者授权 → 统一预约与就诊 → 本人结算 → 验证交付。

本地软件已完成交付：准确应用`5eea097b31874fd08258a02296cb24f10b0cce4c`、[完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40437905634)通过1,127项源码规则／2,092项PostgreSQL测试；原系统与独立合成教师实例运行同一镜像。二十店四类基础服务共80组有实际医师／资源，60名课程医师及各店三幅图经版本审核；前台继续维护排班。

小程序24页，统一主页、预约、就诊、我的。轻量索引约58.2KiB；网站／小程序筛选和替代一致，医师／服务／实际日期贯通登录及患者切换，新增本人结算与历史版本；监护代约不扩大临床或账单权限。教师HTTPS真实工具82项筛选及42项二十店预约检查通过，21条新测试预约全部为取消或改期前身，原诊疗财务不变；隔离候选工具82／56／11项另存。两套系统各60项真实浏览器及七角色登录通过。

二十店二十账号30分钟9,000请求／1,800合法写入，p95为0.513秒，零失败、重复效果或OOM。明确同版本迁移来源的142表25,846行加密空库恢复14.358秒；首次等价DDL摘要停止及比较限制保留。原139组数据、70份配置、密码、数据卷与RC标签保留；新增配置单列，测试后再次加密备份核验。两套实例64迁移、142表、388外键、110触发器与31幅实际ER一致。

正式报告227页、113业务用例加SF-01、132表67图，Word／PDF文件名固定。可见小程序工程、ZIP、私有账号说明及当前开发预览码已交付。**手机实机按用户安排后置，不标全部验收通过。** 真实微信／短信、正式体验版、独立云端、大陆无代理与24小时观察分别待验收；历史UNKNOWN／UNDETERMINED和Windows恢复UNRESOLVED保留。

[患者办理与小程序位置](docs/P15_MINIPROGRAM_GUIDE.md) · [业务合同及追踪](docs/P15_PATIENT_ALIGNMENT.md) · [逐项证据](docs/evidence_p15/README.md) · [机器可读交付](docs/evidence_p15/release.json)。最后文档提交保持已验证应用代码和镜像不变。

---

# 历史交付 P1 画像、选诊与月度经营

资料完善 → 独立审核 → 二十店选诊预约 → 成本复核与经营分析 → 验证交付。

P1.1–P1.4本地交付完成。准确应用 `793a3ef61e19501d8f9a06e9a184293e49173645` 已通过[完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40312653209)：1,127项规则、2,071项PostgreSQL测试及255项原生基础检查；同镜像运行在原本机与独立合成教师实例。

八城二十店均可选诊，新增60名医师、80项服务、40椅位及十四天排班；长沙包含轮诊。医师本人提交、各店主管审核版本；前台维护排班。月度成本独立复核、直接归属、工时分摊、缺失/零费用区分与修订月报已贯通，成本不产生付款。原业务及账号密码保留，课程新增配置单独列明。

五店和二十店均通过20账号、30分钟、9000请求及1800合法写入测试，p95分别0.326秒、0.753秒，无意外失败、重复效果或OOM。142表11962行加密独立恢复及原62→64迁移演练通过。两套实际实例各27项浏览器及七角色登录通过。

报告224页、112项业务用例及SF-01、131表67图；31幅实际ER对应142表、388外键、110触发器。原62迁移字节与RC标签保留。23页小程序开发联调包、固定名称Word/PDF及私有账号说明已放下载目录。

[试用路线](docs/P1_TRIAL_GUIDE.md) · [设计与指标合同](docs/P1_PROFILE_MANAGEMENT.md) · [分项证据](docs/evidence_p1/README.md) · [机器可读状态](docs/evidence_p1/release.json)。

真实微信/短信平台配置、独立云主机、大陆无代理访问及24小时观察仍待条件；课程测试不等同临床或商业资格。旧UNKNOWN/UNDETERMINED与Windows数据恢复UNRESOLVED保留。此前WX1及其他发布记录如下，按其时点解释。

---

# 历史交付 WX1 微信与患者账号协同

小程序登录 → 网站扫码确认 → 手机核验 → 原授权业务 → 保护更新与真实平台待验收。

准确应用`117e9d7ca3d7066e352f5264d067636c4719f0b4`已通过[完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40279432272)，1,122项规则及2,005项PostgreSQL测试通过；同一镜像已安装到原本机18000和[独立合成教师HTTPS](https://waves-heath-jason-chamber.trycloudflare.com)。原账号密码、70份私有配置、数据卷和RC标签保留。

20页小程序已更新到可见下载目录并保留用户AppID及工具私有设置。正式报告202页、101业务用例加SF-01、27幅实际ER，与131表、356外键、103触发器一致。原库副本、含扫码与短信历史的演练库及教师131表2,073行加密独立恢复均通过。

**WX1真实平台总目标尚未全通过**：AppSecret、本人开发工具操作及CloudBase免费短信条件仍待补齐；真实微信、真机扫码和实际短信均未执行。临时Mac隧道、独立云端、正式体验版和商用资格分别验收。[分项证据](docs/evidence_wx1/README.md) · [联调指南](docs/WX1_GUIDE.md)。

# 历史交付：患者入口与可见试用包

准确应用 `99aa4b4920f8e99b743aea04f6c303a688b635e2` 已安装到原本机18000和独立合成教师实例。手机号验证码是同页登录／注册主入口；密码登录同页展开，患者页没有员工入口或独立大字模式，门店卡片删除重复联系／位置按钮。[使用与小程序位置](docs/PATIENT_ENTRY_GUIDE.md) · [实际证据](docs/evidence_patient_entry/README.md) · [当前教师网站](https://ordering-designed-sports-salaries.trycloudflare.com)。

完整CI1,122规则／1,972PG通过；两套系统真实Chrome与七角色登录通过。126组原业务记录和密码保留；原60迁移、数据库卷和RC标签不变，显式启用本地合成验证码。当前130表／353外键／103启用触发器。更新后教师130表／1996行加密空库恢复13.156秒。

19页原生小程序已交付到可见下载目录，官方离线编译通过；工具首次扫码和服务端口设置待所有者完成。真实微信、真实短信、IDE／真机／体验版、独立云端与24小时验收保持未完成。正式课程报告保持C6.1版，本次专项说明独立交付。

# 历史教师试用：患者快捷登录与独立公网环境

准确应用`fb4fe431d49aa8c6b808770218c2fe1491314f40`已在独立合成教师实例交付；完整CI1120规则／1970PG、33项公网浏览器、130表加密恢复通过。[试用入口](https://courier-block-salon-festival.trycloudflare.com) · [办理及真实配置](docs/WECHAT_SMS_TEACHER_TEST.md) · [执行记录](docs/evidence_patient_auth/README.md)。

当前可用合成验证码注册／换绑及原患者、排班、预约业务；真实微信和短信待实际平台条件。此实例依赖Mac临时隧道，用户明确不设置邮箱门槛，业务账号授权保留。原18000系统、193页C6.1报告及历史验收分别保持原范围，当前登录ER与专项说明已更新。

# 历史交付：C6.1B/C 本地结算与基金清算

原费用 → 唯一模拟结算 → 独立复核 → 基金分配与差异责任 → 原单撤销 → 保护交付。

准确应用`bc9d02837eba0c5f4b987b893d9f6af1ad577aff`已在本机交付，完整CI、1,117项规则／1,935项PG、359项浏览器、五店二十账号三十分钟9,000请求，以及129表加密恢复与原库副本升级通过。原112组业务、70份私有配置、账号密码、数据库卷和RC标签保留。193页报告、96业务用例加SF-01及26幅实际ER同步。[交付证据](docs/evidence_c61bc/README.md) · [办理指南](docs/C61BC_LOCAL_GUIDE.md)。

C0.4、C1-WX、C6.1A/B/C的既定本地流程已完成。真实微信、医保机构、云端、二十店业务容量、24小时及专业验收仍待对应条件；历史UNKNOWN、UNDETERMINED与Windows恢复UNRESOLVED保留。

# Historical delivery: C6.1A

官方目录原件 → 独立资料复核 → 本店安排与收费适配 → 患者待遇版本 → 原费用结算准备。

准确应用6db99688fca0ff4be1e049360c3ab8eeddc03f73已在原本机交付，CI、1,106项规则／1,826项PG、53项同镜像Chrome及14项七角色HTTP、115表2739行加密恢复、原库副本升级及保护更新通过。原106组数据、70配置、旧密码、数据库容器卷和RC标签保留；课程配置与新审计单独列明。183页正式报告、90项业务用例加SF-01与22幅实际ER同步。[交付证据](docs/evidence_c61a/README.md) · [本地办理](docs/C61A_LOCAL_GUIDE.md)。

C6.1B/C资金闭环继续开发。真实微信、医保机构、云端、专业、新容量及24小时分别验收；历史UNKNOWN、UNDETERMINED及Windows资料未恢复状态保留。

## Historical delivery

# Historical delivery: C1-WX

本地账号 → 联络来源 → 本人申请 → 独立前台核验 → 明确进入 → 原预约、改期与候补。

应用d0a05fe准确CI通过1,104项规则及1,765项PostgreSQL／HTTP／并发；同镜像67项跨端与权限、109表1,932行加密恢复、原库副本升级、本机保护更新及175页报告通过。原100组业务、70份配置、账号密码和数据库卷保留，三处前台核验职责正常维护。见[完整证据](docs/evidence_c1wx/README.md)、[本地使用](docs/C1WX_LOCAL_GUIDE.md)。

C6.1本地医保继续实施。真实微信、医保机构、云端、专业、二十店容量及24小时分别验收；历史UNKNOWN与Windows资料恢复状态保留。

## Historical delivery

# Historical delivery: C0.4

公开找店 → 按需登录 → 授权患者 → 原统一预约 → 数据保护与恢复。

本地合成软件已交付：应用f9df57d、准备工具ba611d4的准确CI通过，应用镜像保持不变；77项隔离跨端、42项原系统检查、103表加密恢复、原库副本升级与保护更新完成。八省会二十店展示，长沙四店可约；原诊疗财务及70份配置保持。169页正式报告、82业务用例及18幅实际ER已同步。见[完整证据及边界](docs/evidence_c04/README.md)、[本地使用](docs/C04_LOCAL_GUIDE.md)。

C1-WX和C6.1继续实施；微信平台、实际医保、云端、专业、二十店容量及24小时另行验收，历史UNKNOWN与Windows资料恢复状态保留。

## Historical delivery

# Current delivery: C2.2–C2.3

确认检查 → 方案与本人决定 → 分阶段实际治疗与唯一开单 → 复诊责任与加工就绪 → 收退款、对账与保护交付。

C1.1—C2.3分批本地软件开发与交付已完成。最新应用`021a2183f52ff2170298134e610aea5d30fe28e7`通过准确CI、1,104项源码规则、1,688项真实数据库／请求／并发、五诊所610项跨端／财务检查，以及新的二十账号三十分钟9000请求容量。加密101表恢复、原库副本升级、本机保护更新和164页正式报告通过；原83组记录、70份私有配置、数据库容器卷和RC标签保留。见[完整证据](docs/evidence_c23/release.json)。

此次完成的是有明确业务合同的合成软件范围。真实专业审定、微信平台／体验版、云端、24小时及二十诊所容量仍单独验收；更宽的牙周、质控队列、签署归档、药事与材料保持后续计划。历史UNKNOWN和Windows资料未恢复状态保留。

以下保留原日期与范围。

# Historical delivery: C1.2

专业证据与期限 → 独立审核 → 限定门店／服务／动作 → 跨店身份核对 → 指定医师接收 → 本人终止披露。

C1.2已在合成本机环境交付，准确应用提交、五诊所跨端验收、加密独立恢复、原库副本升级及原系统更新通过。报告为134页、67项业务用例加SF-01，九幅ER与本机80表／205条外键／50项触发器一致。详见[执行证据](docs/evidence_c12/release.json)及[C1.1–C2.3进度](docs/C1_C2_PROGRESS.md)。

C2.1、C2.2、C2.3继续开发；真实专业、微信平台、云端、新临床容量及24小时运行不由合成验收推定。历史UNKNOWN与Windows资料未恢复状态保留。

---

# C1.1 患者关系与预约代办 2026-10-23

前台关系受理与核验、明确职责和有效期授权、网站与小程序就诊人切换已实现。共用预约、改期、取消和候补，代约不扩大病历、账单或临床同意权限。[业务说明](docs/C11_PATIENT_RELATIONSHIPS.md) · [执行证据](docs/evidence_c11/README.md)。本地完整回归、准确提交CI、同镜像五店衔接、加密独立恢复、原数据库复制升级及本机更新均通过。应用提交 `edcb6eb2b89ee54375afd24ea7cff364df7b87a2`，原数据与70份配置保留。三份追加迁移保留原40份；真实ER为73表、181条外键、43项触发器，报告新增SU-60—63。

以下历史保留原日期和范围。

# C0.3 patient-channel acceptance 2026-10-23

[Executed regression and protected delivery contract](docs/C03_RELEASE_ACCEPTANCE.md) · [Evidence](docs/evidence_c03/README.md). C0/C0.2 now have actual local PostgreSQL and browser evidence. Clinical workspace route shadowing is fixed. [Exact application CI](docs/evidence_c03/application_ci.json), [restore](docs/evidence_c03/encrypted_restore.json) and [protected installation](docs/evidence_c03/delivery.json) passed. The final documentation commit leaves the tested application code/image unchanged; the historical candidate records below keep their original execution limits.

# C0 patient service implementation 2026-10-22

Patient needs → published service scope and fees → clinic/team → available time → explicit booking.

[C0 implementation and release status](docs/C0_SERVICE_RELEASE.md) records the customer service pages, clinic-owned publication/preview, multi-role continuation and visit reason. 1,090 local rule/source checks pass. Forty-one new Django cases and five updated entry cases are authored but unrun. Docker access and dependency-network restrictions block framework/database execution here; the running local system has not been updated. This is a source candidate, not a commercial release. All 39 historic migrations remain unchanged; one additive migration is pending execution.

# Commercial V2 product program 2026-10-22

The user selected independent deployment per dental chain and full clinical
replacement, including electronic records and prescriptions. The
[master plan](docs/COMMERCIAL_V2_MASTER_PLAN.md),
[inspected baseline](docs/COMMERCIAL_V2_BASELINE.md) and
[acceptance backlog](docs/COMMERCIAL_V2_BACKLOG.json) now govern development.
Customer experience, professional authority, structured dental care, signatures,
prescribing/fulfilment, traceability, financial integration and supported
production operation are explicit release requirements.

This increment changes planning/instructions only. Application behavior,
migrations and the running Mac are unchanged. The preceding local entry
increment and its unexecuted/deployment limits remain recorded below.

# B1.6 系统入口与本人核验 2026-10-22

加入公开只读入口、同源业务导航、六条带预期和异常的跨岗位路线、岗位筛选及仅在本页保留的人工核对记录。便携入口替换旧Windows说明，复用相同目录连接本机系统。未新增迁移或业务权限。

本地1,060项源码/规则与JavaScript语法检查通过；新增Django检查尚未运行；GitHub上传因自动审批无法核实目标仓库授权而被拒绝，本阶段CI未运行。当前会话的Docker、本地监听与文件浏览器权限受限，原运行实例未更新，本阶段浏览器及原实例新页面验收仍待执行。已有员工登录页已实际打开。见[业务与验证边界](docs/B16_ENTRY_AND_VERIFICATION.md)。

本人反馈修复 → 目标环境回归及保护更新 → 微信IDE与真机 → 教师HTTPS云端，按各自条件推进。下文保留已交付历史。

# B1.5.3 患者页面与小程序候补衔接 2026-10-21

患者服务中心集中展示下一次就诊、候补进展与待确认邀约，网站和原生渠道使用一致的办理层级。小程序支持候补登记、邀约新增／替换、拒绝、退出及历史；前台继续在网站明确发布。修复跨店服务误用、邀约改期表单衔接和服务名称快照显示；原39份迁移、69表和六幅ER保持一致。

已通过1,052项规则、1,402项PostgreSQL／HTTP／并发、五店258项跨端联调、48项独立事实及九页官方离线语法编译。见[业务说明](docs/B153_PATIENT_SERVICE_CENTRE.md)与[证据](docs/evidence_b153/README.md)。课程报告保留固定文件名与完整规约，本机更新先加密保护资料、配置和历史。

准确应用提交CI已通过，本机已使用同一验证镜像更新；原66组业务资料、70份配置和数据库容器保留。加密备份独立恢复69表、30,196条记录及42项触发器；详见本阶段交付证据。

原B1.5.2微信平台试用仍等待注册AppID、IDE实际预览、真机、体验成员与合适域名；云服务器尚未购买。既有容量、观察和历史恢复按原证据保留，当前页面改进不构成商用认证。以下为原阶段记录。

# B1.5.1 原生患者小程序与教师交付准备 2026-10-21

已加入原生工程 `clients/wechat` 和受控患者接口 `/api/mini/v1/`，支持课程账号登录、服务时段、预约、普通改期、取消、历史及人工协助。所有写入复用现有业务命令；网站／小程序并发争用同一椅位只能保留一个有效预约。39份既有迁移、69表结构和历史记录保留。

已执行32项真实接口与并发、60项源代码／传输、6项独立导入包、五店65项实际Page逻辑联调、35项真实Chrome网站读回及48项独立业务事实。完整既有回归通过，准确应用提交CI与本机交付证据已追加至[本阶段记录](docs/evidence_b15/README.md)。本机更新先加密保护原数据和配置，固定课程报告文件名。

教师使用原生患者小程序和完整员工网站；后续云端仅分配课程账号使用。小程序账号尚未注册，服务器尚未购买，微信工具编译／真机／体验版以及独立云端验收未完成。[交付顺序与域名要求](docs/COURSE_TEACHER_DELIVERY.md)已经单独列明。既有容量结果和未完成事项保留原状态。

以下内容是前一阶段记录。

# ADC v1.0.0-rc.1：批次A/B交付与范围冻结

## B1.4 患者自助改期 — 2026-10-21

患者本人从待就诊清单选择本店同服务候选，核对原新医师、时间与时长后明确确认。普通改期、本人有效邀约、资源占用、唯一后继及确认回执同事务保存；失败保留原约，真正取消继续原因跟进。前台仍负责排班，历史接待和接受事实保留。[业务合同](docs/B14_PATIENT_RESCHEDULING.md) · [执行证据](docs/evidence_b14/README.md)。

1046项规则、1345项数据库／HTTP／并发、五店173项浏览器、两店68项临床收款及45项独立业务核算通过。五店20患者三十分钟9000请求，900次实际改期，p95 0.453秒；零意外失败、重复、可见OOM或重启。加密恢复69表36349行和42项触发器一致。最终应用`428070b`已通过[准确提交CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39536764923)并更新本机；[交付证据](docs/evidence_b14/delivery.json)记录66组原记录和70份配置保留。

课程报告保留58业务用例与1共享核验，将SU-40标为已实现，新增改期序列及第六幅实际ER；原39份迁移不变。小程序、公开注册、跨店自助改期、独立公网与真实24小时观察仍单独推进。以下按日期保留历史事实。

## B1.3.1 前台排班与数据库关系优化 — 2026-10-20

前台当前店负责出诊新建／调整、接收控制及候补发布，新增日周排班和调班跟进期限；主管继续资源目录与独立复核。修复维修页旧权限依赖及非整点空档取整，追加同店、科室、双来源及完整区间约束，原37份迁移不变。[业务与后续](docs/FRONT_DESK_SCHEDULING_PLAN.md) · [执行证据](docs/evidence_b131/README.md)。

1046项规则、1299项真实数据库／HTTP／并发、五店293项浏览器及42项独立业务核算通过。三十分钟五店20账号9000请求p95 0.349秒、零意外失败／重复／OOM；四处显示修正另有范围明确的源码等价核对。加密恢复69表32356行及42项触发器一致。最终应用`2c45d6d`已通过[准确提交CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39464670340)并更新本机；[交付证据](docs/evidence_b131/delivery.json)记录66组原记录、70份配置与原卷保留。

正式报告新增SU-58日周排班及第五幅ER，并同步五幅旧岗位图、职责和验证。患者自助改期、小程序、公网和真实24小时继续按后续门槛推进。以下按日期保留历史事实。

## 前台排班与数据库设计规划 — 2026-10-20

用户明确日常排班由前台负责，下一实施改为[B1.3.1前台排班与数据库设计优化](docs/FRONT_DESK_SCHEDULING_PLAN.md)，其后再做B1.4患者自助改期。当前出诊维护、接收控制及候补发布仍要求主管；本次交付规划及报告，没有把权限迁移写成已实现。

新增[真实数据库ER](docs/database/README.md)、完整字段／170条实际外键目录和可复现源文件，结构基线为当前69表。正式报告113页、76表32图、57项业务用例及1项共享核验；第4.13节补充ER，第4.14节细化排班职责，第6.2节调整开发顺序。当前运行应用及B1.2＋B1.3验收边界保持原记录。以下按交付日期保留历史事实。

## B1.2＋B1.3 电话接待与诊疗资源协同 — 2026-10-19

核心业务`43b5037`验收后，最后界面及报告版本`63c2733`通过[准确提交完整CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39235771285)并更新本机。交付独立接待及沟通历史、完整建档与明确同意、统一服务／资源核验、邀约暂占转正、维修影响、同时间兼容替换和到诊实际占用核验。[业务合同](docs/B12_B13_RECEPTION_RESOURCES.md) · [完整证据](docs/evidence_b12_b13/README.md)。

1,046项源码、1,256项真实PostgreSQL／HTTP／并发检查通过，新增56项；五店真实Chrome办理及41项独立业务核算、992项容量事实核算通过。三十分钟容量实测`a313aef`，9,000请求p95 0.352秒，无意外失败／重复效果／OOM；最终两处显示和负面输入修复通过有效路径等价核对，未声称另测三十分钟。最终加密独立恢复69表32,527行、空库就绪后3.459秒。

本机原51组记录、70份配置、原数据库容器／卷和RC标签保留；两店通过正常业务命令新增10台合成设备、8项服务和12个未来时段，复用2原时段。九个原有账号七角色189项授权读取检查通过，含已发布课程服务的可行候选与只读确认。一次时钟不一致造成监测退出，旧观察加密保留，明确重置及主机事件处置后恢复六项健康，连续24小时仍未通过。

正式报告108页、57业务用例＋1共享核验、75表28图；SU-39／54已实现，新增SU-57资源目录规约，教师文件名保持不变。保留原31份迁移，追加6份。下一阶段B1.4患者移动网站与自助改期；小程序、公网、安全与历史Windows原数据恢复继续保留各自未完成状态。以下为历史交付。

## B1.1 取消分析与服务改进 — 2026-10-19

已交付本机并同步GitHub。应用 `75056a7` [CI通过](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39210907593)，新增本店星期×开始时段分析、原因跟进、实际另约凭据、措施执行及另一主管复核。修复长编号手机溢出、本地化日期默认值和未完整观察窗口；负责人失效可重新分配。

[完整证据](docs/evidence_b11/README.md)：1,046源码规则、1,200数据库/请求/并发（45项新增），五店Chrome114项、42项独立核算及54表加密独立恢复；本机9账号7角色149项只读检查。48组原业务、70份配置、原数据库容器/卷及RC标签保留，仅新增3个空业务表和相应权限元数据。旧监测观察加密保留，新应用及主机观察健康；不作24小时结论。

[正式报告](课程报告/README.md)为102页、56业务用例及1共享核验，新增原因跟进和措施复核规约；重绘两张领域关系和两张独立状态图。原历史报告不修改。当前合成示例不证明真实取消规律或实际改善；独立恢复的等价SQL结构比较限制见[恢复方法](docs/evidence_b11/recovery.md)。

下一步[预约业务B1.2电话接待](docs/APPOINTMENT_BUSINESS_PLAN.md)：咨询、资源核对、候选协商、联系责任、明确同意和转正式预约。自助改期、科室资源、小程序后续实施。真实24小时、安全、公网以及Windows原始数据恢复均保留未完成状态。

## 已交付应用与工程记录


当前：R2.4.3等价容量与UX2已交付Mac。五诊所、二十账号、30分钟9,000次、1,800合法写入，p95 0.3090秒；有界财务导入与通知单独核对。优化预约编号/清单、接诊错误定位和财务分组，原30份迁移不改。[执行及交付](docs/evidence_r243/README.md) · [UX2](docs/evidence_ux2/README.md) · [课程报告](课程报告/README.md)。下一步R2.4.4真实24小时与安全复核；服务器未购买，R2.5公网及Windows原数据恢复未完成。下文保留历史交付。

## R2.4.2 业务依赖恢复与UX1界面更新 — 2026-10-18

应用 `1977b4b` 已通过[准确提交CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39184693082)并更新Mac镜像。完整回归1,046项源码/规则、1,152项真实PostgreSQL/HTTP/并发通过；四类真实依赖中断28项、应用换址7项、三种网关语法及真实浏览器60项通过。[执行证据](docs/evidence_r242/README.md)与[处置手册](docs/R242_DEPENDENCY_DRILLS.md)保留影响、责任、恢复及独立事实核对。

修复应用重建换址后网关沿用旧地址的502。界面更新统一登录与工作范围、手机导航、前台预约/患者入口和财务待审/对账/日结入口；沿用原业务权限、预览与独立复核。[研究、测量及截图](docs/evidence_ux1/README.md)区分工程检查与尚未开展的用户访谈。

Mac更新前后验证加密备份，48项原业务摘要、70份配置、原卷及RC标签一致。计划更新应用、worker、observer与网关，数据库容器保留。旧观测和主机事件加密保留，新身份建立六项健康观察；原库无故障注入或测试业务提交。Mac九账号、七角色授权读取通过93项检查。课程报告更新为81页，文件名不变。

下一步R2.4.3等价容量与UX2清单/表单细化；真实24小时、安全复核和公网另验。服务器尚未购买，Windows原始数据恢复仍未解决。以下为历史交付记录。


## R2.4.1 主机事件与故障处置 — 2026-10-18

主机工具 `837a834` 已通过[准确提交 CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39180157857)并更新 Mac。
[执行记录](docs/evidence_r241/README.md)包括 1,042 项源码/规则、1,152 项真实 PostgreSQL/HTTP/并发回归及 21 项独立主机检查，含真实 48 MiB 容器 OOM。
[私有工具与手册](docs/R241_HOST_EVENTS.md)区分停止、重启、OOM、采集不可达和观察缺口，保留认领、处置、新采样验证及关闭历史。备份结果另记，不代替恢复点凭据。

Mac 加密备份已核验，48 项业务摘要、70 份配置、原卷和 RC 标签保持一致；五个原服务未重建，应用仍是 `02a9dbc`。主机采集进程已显式启动，未安装新的定时任务，Mac 睡眠或失联仍形成观察缺口。课程报告维持固定文件名和 78 页大学课程版式。

更新时发现原监测器因时钟不一致退出：已加密保留历史、显式恢复同一监测器，并在新主机事件簿中认领、处置和验证关闭。该处置不证明24小时连续运行。

下一步为 R2.4.2 真实业务依赖故障演练。等价容量、真实 24 小时、安全复核和公网门槛仍独立；服务器尚未购买，Windows 原始数据恢复未解决。


## R2.3 independent recovery tools — 2026-10-18

Host tool `20961ba` adds a shared PostgreSQL snapshot for dump/facts, full-table
comparison before runtime startup, and authenticated restore receipts bound to
source ciphertext, original point, application, key and distinct target storage.
Encrypted monitoring history is retained as history; it never becomes current
health. Older archives remain readable without invented verification.

[Executed evidence](docs/evidence_r23/restore_acceptance.json) records 1,016 rule
checks, 1,152 PostgreSQL/HTTP/concurrency regressions and 24 real-age/PG restore
success/refusal checks. An independent empty target matched 51 tables/29,144 rows;
restore, comparison and startup took 15.868 seconds after replacement readiness.
Transport was simulated locally, not SSH/cloud protection. Exact tool CI and
protected Mac delivery are recorded [separately](docs/evidence_r23/restore_delivery.json).
The current [78-page course report](课程报告/README.md) preserves its stable name,
complete specifications and university format. All 30 migrations and business
runtime `02a9dbc` remain unchanged. [R2.4 local operational acceptance](docs/R24_ACCEPTANCE_PLAN.md)
is next; capacity/24-hour/security and real cloud readiness remain unverified.


## R2.3 first recovery-tool increment historical record — 2026-10-18

Repository navigation now separates the current [course report](课程报告/README.md),
editable report sources, business/operations documentation and historical evidence.
The teacher-facing PDF and Word use stable student-name/number filenames.

[Recovery tools](docs/R23_RECOVERY_FRESHNESS.md) now record created and
current-key-verified downloaded copies separately; complete batches are checked
before publication/pruning. Recovery age uses the original source point, and
stale server observations remain UNKNOWN. Independent restore receipts are still
unimplemented/UNKNOWN. This first tool increment does not complete R2.3 or R2.
[Executed scope](docs/evidence_r23/README.md) distinguishes synthetic real-age
checks from PostgreSQL regression and the pending restore/cloud gates.

No business migration, UI change, new grant or runtime restart is required for
this host-tool update. Running Mac application remains the accepted R2.2 image.

## R2.2 progress and condition observation — 2026-10-18

Application `02a9dbc` adds private worker/collector state and independent
observer-failure detection, preserving all 30 migrations and existing permissions.
Due work excludes future retry; responsibility acknowledgement does not erase a fault.
[Executed evidence](docs/evidence_r22/README.md) records 978 source checks,
1,145 PostgreSQL/HTTP/concurrency tests, 32 live fault checks, 869 isolated browser
assertions and a 50-model encrypted empty-target restore. [Exact application CI passed](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39134681755).
Protected Mac delivery preserves 48 durable fingerprints and 70 private files;
437 authorized-read browser assertions pass. The current report follows the
supplied university course format: bilingual abstracts, six chapters, original
models, SU-01—38 and SF-01 appendices, and executed evidence. Frozen RC files remain.

Next is R2.3 recovery freshness. Full R2 load/24-hour/security acceptance and
independent cloud remain pending; original Windows-data recovery is unresolved.

## R2.1 diagnosis and logging — 2026-10-18

Server request IDs, safe errors/logs and measured size rotation are implemented.
[R2.1 contract](docs/R21_SAFE_DIAGNOSTICS.md) and
[local acceptance](docs/evidence_r21/README.md) record unchanged permissions,
independent financial facts and encrypted restoration. Exact-commit CI and
protected Mac rollout are completed in [the delivery record](docs/evidence_r21/delivery.json).
Application `ccdcdcd` preserves 48 durable fingerprints and 70 private files;
410 Mac browser assertions pass. No migrations are added.

## Historical planning update — 2026-10-18

The application baseline is delivered R1 financial evidence at `6a06f35`.
[Current report: Word/PDF/Markdown](docs/report-source/README.md) records its
executed local acceptance and the next [R2 operational assurance plan](docs/R2_OPERATIONAL_ASSURANCE_PLAN.md).
The first coding batch is safe request correlation and structured operational
logging, followed by worker/backlog and backup/download/restore freshness.
This update changes documentation only. R2 implementation and cloud acceptance
remain pending; dated sections below retain their historical scope.

## macOS development — 2026-10-12

Source migration was resumed by the user. `v1.0.0-rc.1` preserves the supplied
Windows ZIP; `main` contains the Mac launcher and verified fixes. Use
`RC_MACOS.sh` and `docs/MACOS.md`. The Windows host was reset and no database
backup was supplied, so the Mac demo starts with synthetic data. The release
account below describes the original archive; current validation is recorded in
`docs/evidence_macos/`.

## Runtime reliability — 2026-10-13

The notification worker now shuts down at the current event's transaction
boundary on SIGTERM/Ctrl+C and checks its stop flag before admitting further
events. Real PostgreSQL child-process tests verify restart, deduplication,
termination during insertion, and rollback after SIGKILL before commit.
Mac `start` builds the current checkout before stopping the previous runtime,
so a build failure does not stop the existing demo. Business scope and all
existing models/migrations are unchanged. Worker evidence is recorded in
`docs/WORKER_PROCESS_ACCEPTANCE.md` and
`docs/RC_ACCEPTANCE_RECORD.json`.

## G3 browser acceptance — 2026-10-13

Both real browser routes passed with PostgreSQL facts and independent financial
oracles. Repairs correct care/finance control labels, permission/read-only
recovery, and READY task wording. No models or migrations changed. Seven roles,
stale/revoked contexts, lost responses, narrow Chrome layouts and keyboard
confirmation boundaries are recorded in `docs/G3_BROWSER_ACCEPTANCE.md`.
G2 original-backup recovery and G4 public deployment remain NOT_RUN.

## Course online deployment preparation — 2026-10-14

The selected next target is a one-month Hong Kong Ubuntu server, a fixed free
hostname, writable synthetic business operations and Mac backup synchronization.
New tooling provides explicit access mode, pinned builds/SSH publication,
encrypted backup/recovery and a bounded mixed workload. Existing Mac read-only
deployment and all 16 migrations remain separate. See docs/COURSE_ONLINE.md.
The server is not purchased; cloud acceptance remains NOT_RUN. The G3 status
above records its date; current G4 is PARTIAL in docs/RC_ACCEPTANCE_RECORD.json.

## Business follow-up development — 2026-10-14

The user requested improvement across the business chain after deployment
preparation. Role-specific work lists now surface overdue appointment outcomes,
unclosed care, coordination ownership/review, patient offer deadlines and
quarterly financial blockers. Appointment/correction filters retain pagination.
All links return to existing permission-checked confirmation workflows; GET
never performs a business operation. No models or migrations changed. See
docs/BUSINESS_FOLLOW_UP.md for current local evidence, separate from G3/G4 history.

## Replacement appointment workflow — 2026-10-14

Current-clinic front desk staff can find bounded replacement intervals using the
original duration, compare both arrangements and explicitly confirm. Patient and
dentist conflicts across clinics and live waitlist holds are checked. The original
is released only inside the successful transaction that creates its unique
successor. Signed previews bind the workspace, source version and admission
revision; repeat confirmation returns the saved successor's current state.
No models or migrations changed. Local validation passed 884 source checks,
793 PostgreSQL/HTTP tests, 57 complete-flow and 14 recovery-page Chrome checks,
plus an independent database oracle. See docs/RESCHEDULING_OPTIMIZATION.md.
These are local development results; historical G3/G4 and Windows recovery
statuses remain separate.

## Care, finance and equipment development — 2026-10-14

The user authorised business-process refinement and the addition of finance and
equipment functions. The assigned dentist can save draft care facts and check
completion blockers. Closed-care review shows the published treatment record and
existing bill. Receipts/refunds and equipment-fee requests require a different
finance account to approve or reject; pending requests never count as received
money. Current receivables retain the distinction between billed revenue, posted
cash and a refund balance after bill correction.

Current-clinic managers can register equipment and retain maintenance, service and
retirement history. Device changes do not automatically change appointments or
post costs. Four additive migrations create three tables and source/history
guards; the original 16 migration files remain unchanged. The existing seven
roles and quarterly cost/income policy remain intact. See
docs/CARE_FINANCE_EQUIPMENT_WORKFLOWS.md and its separate local execution evidence.
This business increment does not complete the pending cloud course acceptance.

## Historical account from the supplied Windows RC archive

候选源码基于完整alpha.10重建；中断目录中的图像不作为代码完成证据。运行基线仍为Windows v0.7，Mac暂停。此次不新增大型业务模块，而是整合可核对、可启动、可验收的课程候选。

## A：运营核对与交互
固定数据中的预期值独立保存，不调用生产算法生成expected。两行0.500×0.01分别舍入为0.01，总0.02；收入199.98与全体两位牙医成本130给出利润69.98/基金7.00；更正后收入99.99、利润-30.01，旧版本保留199.98。确认零、未填写成本、成本但无收入者、未知状态分母、季度半开区间各有明确反例。
跨模块测试定义覆盖实际治疗与发布账单、目录调价不覆盖旧账单、数字更正与季度重算，以及暂停、任务、原预约取消、通知、独立复核与出诊维护。自动服务链不等于全部界面已经操作；完整手动路线单独提供。
全局UI在原有角色工作台上增加字段错误摘要与焦点入口、只读说明，并统一“逐步操作指南/操作问答”。不自动提交、不修改用户字段值、不通过隐藏按钮替代权限。

## B：三种互不混淆的运行路径
|路径|目的|保护|
|---|---|---|
|verify|临时空库运行集中G1|独立配置/随机项目，不挂载旧卷，不读原.env；记录真实依赖|
|new-demo|新建持久合成演示|新.rc/新项目，拒绝已有RC数据卷；仅空库初始化，密码仅进私密文件|
|import-copy|演练旧合成数据升级|只接受可信私密备份；只恢复到新空RC库；不seed、不改密码，不连接原数据库|
|start/stop|管理已经准备的RC|按顺序准备schema再启Web/worker；只停止本RC服务；无删除卷操作|

导入先用pg_restore单事务恢复，然后核对一组明确旧表的稳定行摘要，应用迁移后再次比较。覆盖账号凭据及激活/牙医绑定、患者核心资料、预约、账单、版本、候补、邀约和审计。摘要没有覆盖所有表/字段，也没有取代源备份完整性、金额或授权人工核验；MD5用于同一可信副本的差异定位，不是来源认证。
所有恢复均是新副本，不进行原地降级。正式交接前必须人工冻结所有旧写入端并重新导出最终备份；演练备份不包含导出之后新增的数据。回退不能忽略新版本新增业务。

## 冻结范围与延期
保留核心接诊/结算/更正/运营、七角色与范围、资料登记维护、候补有限最大匹配、出诊维护及接收控制、责任任务、站内任务消息与有限重试、手动指南及限定候补结果核对。
多资源/CP-SAT、通勤优化、专业资格认证、真实收款/医保税务、临床AI、短信邮件、通用代理操作、Mac迁移延期。站内消息仅覆盖任务事件。

## 开发检查与未验收项
本轮799个基础方法、候补18/出诊16条JavaScript、全角色UI672/通知756/任务888条静态断言实际通过。680个PostgreSQL测试方法已编写（新增7），没有执行。16份迁移和11份模型文件保持父版字节。
当前缺少Docker/Django/psycopg/PostgreSQL；依赖获取失败。RC命令只经源合同和纯配置测试，未在Windows/Docker真正启动。真实回归、恢复、浏览器、worker故障恢复和公网仍分别属于G1/G2/G3/G4。

## 课程报告
R5是由已纠正字体/UML的R4.4继承并合并SU-26—38的完整整合稿。38份系统用例、1份共享子功能、19幅模型和2幅历史观察图；保留案例事实/分析假设/项目决定/验证状态的区分。不把微信通知恢复为编号[16]参考文献。实际日志和报告只是候选证据，不能称为部署认证。

## Finance/equipment handoffs — 2026-10-14

Receipt/refund screens now expose pending amounts and one-candidate balance effects.
Obsolete requests are identified before review, with rejection preserving history.
Equipment fees are reconciled from source events, including unrequested, unknown
and explicit-zero facts; maintenance offers an explicit manager-selected path to
existing intake, coordination and availability commands. Native date defaults use
ISO widget values. All 20 migrations remain unchanged; no schema or role expansion.
See `docs/FINANCE_EQUIPMENT_HANDOFFS.md` and
`docs/evidence_finance_equipment_followup/acceptance.json`. Independent cloud
readiness and historical Windows-data recovery retain their separate status.

## Commercial foundation — 2026-10-14

The user requested continued development toward commercial use. Equipment source
costs can now be supplemented/corrected through a manager request and independent
finance review, preserving original events and every decision. Pending cash must
be resolved and posted expense reversed before a cost amendment; a pending cost
amendment blocks new fee requests. Cash retains its exact approved cost basis.
Three additive migrations preserve all original 20 migrations. No roles, care,
bill or scheduling semantics expand. See docs/EQUIPMENT_COST_AMENDMENTS.md and
docs/COMMERCIAL_DEVELOPMENT.md for responsibilities, evidence and staged gates.
Independent cloud/course acceptance and large commercial readiness remain separate.

## Daily reconciliation — 2026-10-15

Clinic managers can prepare four-category daily cash reconciliations with explicit
evidence and discrepancy responsibility. Independent finance review requires equal
gross amounts, no pending cash and current facts. Rejected or reviewed days reopen
as retained new versions; late facts never silently rewrite earlier approvals.
Two additive migrations preserve all previous 23 migrations. See
[Daily reconciliation](docs/DAILY_RECONCILIATION.md) and its executed evidence.
Bank/payment channels, sealed accounting periods, independent cloud deployment and
commercial-scale acceptance are separate outstanding work.

## Maintenance responsibility — 2026-10-15

Clinic managers can assign stopped-equipment work orders, follow deadlines, submit
repair evidence and obtain another manager's acceptance. Every action is retained.
Acceptance creates one exact service event; fee posting and scheduling changes
remain explicit separate workflows. Cancelled managed cases cannot bypass review
through the legacy status command. Three additive migrations preserve the prior 25.
See [Maintenance work orders](docs/MAINTENANCE_WORK_ORDERS.md) for role boundaries,
legacy declaration scope, verification and remaining commercial requirements.

Maintenance local acceptance: 884 source / 1,042 PostgreSQL-HTTP-concurrency / 704 browser / 89 independent database assertions. All 45 model and association fingerprints match after an encrypted empty-target restore. See [maintenance evidence](docs/evidence_maintenance/acceptance.json). Cloud/commercial acceptance remains incomplete.
