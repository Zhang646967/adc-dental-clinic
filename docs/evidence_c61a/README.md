# C6.1A 本地医保准备交付

官方原件 → 独立资料复核 → 本店安排与收费适配 → 追加待遇版本 → 回归、恢复与保护交付。

本批已在原本机交付。准确应用提交6db99688fca0ff4be1e049360c3ab8eeddc03f73通过[GitHub CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40177691768)：1,106项源码规则及1,826项PostgreSQL／HTTP／并发。相同镜像通过53项Chrome业务、390px大字与键盘检查，另14项七角色HTTP；原系统更新后14项Chrome检查通过。统计是执行数量，不是覆盖百分比。

- [本地办理与私有账号说明](../C61A_LOCAL_GUIDE.md) · [需求与测试追踪](../C61A_PREPARATION_CONTRACT.md) · [完整医保合同](../C61_LOCAL_INSURANCE_CONTRACT.md)
- [交付汇总](release.json) · [准确CI](application-ci.json) · [源码阶段完整回归](regression.json) · [同镜像候选](candidate.json)
- [浏览器](browser-results.json) · [七角色HTTP](seven-role-results.json) · [独立业务核算](independent-business-facts.json)
- [加密独立恢复](release-restore.json) · [原库副本升级](copy-upgrade.json) · [本机数据与配置保护](mac-final-validation.json) · [新增课程配置](mac-course-configuration.json)
- [本机实际ER核对](mac-schema.json) · [原系统Chrome](mac-browser-results.json) · [结构快照](schema_snapshot.json) · [原54份迁移摘要](preimplementation-migrations.json)
- [报告内容及版式](report-validation.json) · [全部页面视觉范围](report-visual-review.json)

实际115张SQL表、114张ORM表、1128个ORM字段、318条SQL外键、83项触发器和56份应用迁移；原54份迁移字节保留。183页正式报告包含90项业务用例加SF-01、109张表、55幅图及22幅实际ER；原375项规约核心字段和39幅原图保留，文件名固定。

115表、2739行加密备份在独立空库使用同版本迁移恢复，逐表行和结构指纹、原件字节、规范数据、全部审阅与待遇历史及83项触发器定义／启用状态一致；空库就绪后10.617秒。该结果保留原同版本建库路径的结构比对边界，不认证任意等价DDL。

原106组数据逐行保留，70份私有配置、旧密码、数据库容器卷及RC标签不变。新增一名财务账号通过受控账号命令办理；一个湖南来源、202编码及四家长沙课程安排通过所属业务命令准备，无新增患者、治疗、账单或资金。旧收费项目未强行映射，旧患者未补造待遇。另增24权限、6内容类型、12治理／准备审计和3条授权查阅记录均单独列明。更新后数据库、72份配置及私有试用资料再加密保护。

## 故障及边界

新增路由白名单、并发来源导入与重提、拒绝后的业务接续、历史分页及目标链接问题均已修复，保留相应PG和HTTP反例。一次早期完整回归因768MiB验证库的tmpfs同时承载数据与累积WAL发生真实OOM；该次失败保留，改任务专用磁盘卷后最终完整回归无OOM或OOM kill。隔离故障不用于解释旧原系统工作进程退出原因。

浏览器初轮在有效业务步骤后被脚本错误页选择器中断；后续修正实际错误页／汇总标签及导航等待，未改应用权限。最终完整后续办理周期53项全部通过，先前成功产生的历史未删除。独立空库的首次副本演练误把初始化临时服务判为就绪，未改原库；改为等待最终TCP服务后恢复升级通过。

六项应用监测及两个独立主机样本健康，原监测与主机日志加密归档。短样本不是24小时验收。旧UNKNOWN、UNDETERMINED和Windows数据恢复UNRESOLVED保留；当前数据库权限仍为已记录的本地RC所有者，不等同独立HTTPS最小权限验收。

本批只是资料准备。C6.1B费用分担、唯一模拟结算和C6.1C基金到账、退费继续开发；实际微信、医保定点联网、云端、专业审定和新容量另验收。私有日志、密码、密钥、患者资料及加密备份不上传。

思维导图：保留原件 → {缺失、独立审阅、历史接续} → {本店日期、收费单位、待遇版本} → 当前可用或待办 → 无新增资金事实 → 分项交付。
