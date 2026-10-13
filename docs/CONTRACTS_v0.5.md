# 从课程原则到可检查的模块契约
NOTE5：关注点分离、抽象、简单性、受限可见性；优先隐藏困难且可能变化的决策。这里不把“模块多”或“继承多”当成质量证据。

| 公开接口 | 前置条件 | 后置/失败保证 | 隐藏的决策 |
|---|---|---|---|
| scheduling.services.create_appointment | 有效前台范围、可用患者与未来出诊时段 | 成功1条预约+事件；冲突/审计失败无半条记录 | 预约校验与异常转换 |
| scheduling.services.create_visit_locked | 内部协调器先授权并开启事务、锁住时段 | 创建初始Visit；不提供独立外部授权 | 两端共用创建细节 |
| care.services.complete_visit | 负责牙医、到诊、信息/治疗合法 | 一个闭合结果与唯一账单；重试同结果 | 完成次序、金额与快照 |
| care.ledger.income_by_dentist | 授权财务调用方；有效时区边界；同一读取事务 | 返回牙医粒度不可变收入行，无患者/临床字段 | 当前版本存储关系 |
| finance.policies.calculate_profit | 收入与成本已授权、同一截面、明确粒度 | 完整才返回利润/基金；缺失列出原因 | 非负成本、缺失、总体基金政策 |
| finance.services.save_cost | 有效FINANCE CHAIN、季度修订号匹配 | 草稿保存+审计；旧确认失效；失败回滚 | 成本编辑生命周期 |
| care.corrections.review_correction | 独立财务账号、原牙医授权仍有效、基版未过期 | 发布完整新版本并切换同一单号；失败保持旧版 | 更正审核和事务顺序 |
| operations.selectors.operation_report | 主管本店/HQ全链、日期合法 | 授权范围计数、分母、缺失、查询时间 | 时间成熟度与统计聚合 |
| assistants.provider.classify | 服务器配置，调用方已处理同意、配额与输入 | 受限意图或显式ProviderError | 第三方请求字段、超时与解析 |
| adc_core.snapshots.reporting_snapshot | PostgreSQL、当前无外层事务 | 一致只读快照；不允许写入 | 事务隔离选择 |

信息隐藏是“调用方不依赖内部表达”；授权是“用户是否允许做某动作”。前者不自动产生后者。Python模块公开函数仍是内部契约，不是任意可被用户调用的HTTP入口。模型/数据库不是秘密，但不要让每个页面都复制当前版本、季度或并发处理逻辑。

关键写入遵守：授权→按约定顺序锁定→比较业务修订号→校验→写入→审计→提交。数据库约束、事务、幂等分别验证。报表只读快照并不等于永久财务关账；新的成本或账单更正会改变以后查询结果。
