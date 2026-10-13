# v0.5 变更记录

| 编号 | 本次设计补充[D] | 对应课程材料 | 验证入口 |
|---|---|---|---|
| CR-05-01 | 季度纳入清单及成本确认、缺失阻断、利润基金和CSV | NOTE3需求可测试；NOTE5政策封装 | FinancialAcceptanceTests |
| CR-05-02 | 运营统计先明确事实粒度、时间范围和分母 | NOTE3黑箱行为；NOTE5关注点分离 | OperationsAcceptanceTests |
| CR-05-03 | 原行数量/价格更正，完整新版本，双角色审核 | NOTE3状态前后条件；NOTE4历史与控制 | CorrectionAcceptanceTests |
| CR-05-04 | 公开内部命令/只读账单事实接口，减少跨模块私有调用 | NOTE5信息隐藏、受限可见性 | checks/test_management_rules.py |
| CR-05-05 | 系统报告、累计升级、版本安全诊断 | NOTE2增量；NOTE3追踪 | gate + system_status |

新增迁移：finance.0002_quarter_lock_version（非空默认0）；care.0003_correction_publication_guard（更正发布与终态历史保护）。不删除、重写旧迁移，不新增逻辑实体，沿用24个领域对象。

范围不是完整更正：一次申请只改当前版本的一条原治疗行的数量或单价；不改患者/诊所/负责牙医/已确认完成时间/项目身份/结果类型。原版保留，旧账单时间归属不变，历史季度以当前资料重述。Q-02只得到有限实现，不等于预约终态更正或退款已解决。

没有新API供应商，没有调用外部AI，没有修订基金的未定个人分配/负利润政策，没有承诺临床质量判断。所有新增应用方式是本项目设计，而非案例或教师原文规定。
