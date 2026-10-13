# v0.9.0-alpha.8：出诊新增接收控制

父版alpha.7。用户本机验收留到v1.0，不再要求本轮运行命令。Mac迁移暂停。报告R4.4保持冻结。

## 已编码
主管：出诊安排→原出诊详情→核对并暂停新增 / 核对并恢复接收→说明依据→预览→明确确认。
患者/前台的新预约与改入目标、排程枚举和新邀约发布均接入暂停控制。已经发布的有效邀约保留，仍可按原期限接受；已有预约继续按原业务规则到诊、治疗、取消和改出。
前台协调页显示主管保存的真实接收状态，没有获得控制按钮或批量取消权限。

新增接收修订号与签名预览联动：暂停/恢复使旧门户确认和旧草案失效；同次成功操作重放不撤销后续合法变化。替代出诊继承原暂停标志，不隐式恢复。

## 不是简单把is_active改成false
暂停保持出诊is_active=true，不释放牙医原出诊时间，不使原预约/邀约失效。
可以暂停进行中但尚未结束的有效出诊，含义仅为不新增，不中断诊疗。临床停诊、批量改期、患者通知、协调工单和执业资格认证未在本轮完成。

## 模式变化
新增scheduling/migrations/0002_slot_intake_control.py：AvailabilitySlot.booking_paused（默认False）和intake_revision（默认0）。
原13份迁移保持原字节；原数据升级后沿用从前的接收行为，is_active仍独立生效。暂停/恢复使用过后，反向删列会被保护规则拒绝。
旧应用不知道暂停字段，不能在启用新能力后混跑旧版或仅覆盖回旧代码。“数据库迁移可反向”不等于“任意降级安全”。

## 修改位置
- scheduling/intake_rules.py：纯规则、精确邀约例外、签名载荷合同。
- scheduling/intake_services.py、intake_forms.py、intake_views.py：主管预览、确认、行锁、审计及恢复反馈。
- scheduling/services.py：共同预约创建入口默认禁止暂停时段；原邀约例外仅在内部重读真实记录、核验权限和精确关联后成立。
- coordination/services.py：候选过滤、发布重验、草案修订、保留有效邀约直至原子接受。
- portal/services.py、scheduling/selectors.py：普通选时过滤与门户旧确认失效。
- scheduling/availability_services.py：快照增加新维度；替代继承暂停。
- 前台协调/主管页面、患者选时/邀约提示、guide manager-intake同步更新。

## 实际检查边界
635个基础方法通过；新接收页面498条静态断言通过，既有六组静态界面回归通过；Node两组18/16条通过。
554个Django/PostgreSQL测试方法已编写，新增58个，但本轮未执行。环境与日志见TEST_REPORT.md。新迁移未实际应用到数据库，不称为稳定发布。

## 本轮交付策略
交付完整源码与累计更新归档供保存，不要求用户现在部署。
现有升级脚本仍保留隔离检查和私密备份门槛，不能把“等到v1.0集中验收”实现为删除安全检查。
到v1.0再统一生成操作指引、收集本机结果和处理升级问题。此刻不操作旧实例、不要求导出数据库、不请求API Key。

技术机制参考（与项目决定分开）：
Django 5.2 transactions / QuerySet select_for_update / Migration Operations；PostgreSQL 17 explicit locking。
https://docs.djangoproject.com/en/5.2/topics/db/transactions/
https://docs.djangoproject.com/en/5.2/ref/models/querysets/
https://docs.djangoproject.com/en/5.2/ref/migration-operations/
https://www.postgresql.org/docs/17/explicit-locking.html
检索2026-10-08。官方机制不是本应用已验收通过的证明。
