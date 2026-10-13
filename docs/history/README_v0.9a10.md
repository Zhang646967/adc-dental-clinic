# ADC v0.9.0-alpha.10

合成数据课程演示候选，父版alpha.9。本轮新增任务站内收件箱、事务内Outbox、有限后台重试和本店派发核对。消息不受理任务、不修改预约、不证明患者同意。

用户本机集中部署/验收到v1.0候选开始；本轮不需要安装。Mac迁移暂停，R4.4报告冻结。

- RELEASE_CURRENT.md：本轮实际编码能力及边界。
- docs/SU37_SU38_NOTIFICATIONS.md：新增规约。
- docs/V1_SCOPE_AND_REMAINING.md：距RC的两个剩余批次和实机/公网门槛。
- docs/TEST_REPORT.md及docs/evidence_v09a10：本轮真实开发检查，不是PG/E2E。

新notifications应用，两张表，一份新增迁移；保留父版15份迁移，总16份。旧10个模型文件不变，任务服务在审计之后增加事务内入队调用。不得只升级代码不应用模式，也不得用旧写程序处理新任务。

`compose.notifications.yaml`仅提供可选本地worker叠加，不修改默认compose，暂不要求执行。默认初始化与隔离验证/备份门槛保留。生产启动、监控和统一升级在v1.0整合批次完成。无真实患者资料、外部消息渠道或AI开销。
