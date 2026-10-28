# D1 需求到执行追踪

| 业务问题／约束 | 模块责任与可观察规则 | 测试与执行记录 |
|---|---|---|
| 空库缺少最新20店能力 | bootstrap_course_release只使用既有所有者命令；完成事件后重复调用不重置密码；部分未完成保留进度不盲目重跑 | test_cloud_course_release、test_cloud_release；initialization.json、capability.json |
| 新版本发布丢失历史 | g4_release只替换镜像／来源；维护窗口备份；不恢复旧数据库 | test_cloud_release；upgrade_rollback.json |
| 不同恢复路径结构不一致 | restore --schema-mode migration-built先比较每表结构，再恢复数据并完整比较；不放宽原比较器 | test_recovery_restore；encrypted_restore.json、execution_notes.json |
| 异地副本不可证明可用 | g4_offsite完整回读后才发布清单；失败保留上个点；独立下载及空库恢复分别留证 | test_cloud_offsite；sdk_compatibility.json、encrypted_restore.json；真实COS未配置 |
| 监测进程因时钟间断不能恢复 | operations识别同源有效正向间断，归档后从UNKNOWN取得两次新样本；坏记录和外来来源不自动重置 | test_operations、test_observer_clock_resume；observer_repair.json |
| 更新影响岗位和数据 | 七岗位保留权限，独立复核及患者授权沿用原合同；禁止将咨询身份视为病历权限 | 原完整2096PG回归、mac_roles.json、teacher_roles.json；139组逐行与密码核对 |
| 商用要求与演示证据混淆 | 版本、镜像、迁移、通知和备份状态分别呈现；监测失效不能显示健康 | release.json、pending状态；真实云端／平台单独验收 |
| 正式报告与实际ER不一致 | 无表变更，四库实际核对31ER和完整字段／外键；正文集中分析设计 | schema_er.json、报告validation.json |
