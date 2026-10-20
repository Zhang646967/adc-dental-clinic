# ADC v1.0.0-rc.1：批次A/B交付与范围冻结

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
