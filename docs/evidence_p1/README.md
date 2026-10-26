# P1 画像、选诊与经营核算：执行证据

画像审核 → 统一选诊预约 → 独立成本复核 → 月度经营 → 容量、恢复与保护更新。

P1.1–P1.4已完成本地及独立合成教师实例交付。准确应用提交为 `793a3ef61e19501d8f9a06e9a184293e49173645`，[完整CI通过](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40312653209)：1,127项规则、2,071项PostgreSQL测试、255项原生客户端检查。该版本镜像用于两套实际实例；随后报告、ER及证据归档属于文档更新，未改变已验收的运行代码。

| 验证对象 | 实际结果与记录 |
|---|---|
| 业务、岗位及不利路径 | [需求—规则—验收追踪](requirement_trace.md)、[完整CI及准确检出日志](application_ci.json) |
| 实际浏览器 | [隔离环境36项](browser.json)；[原实例27项](mac_profiles_browser.json)、[教师HTTPS27项](teacher_profiles_browser.json)，均逐店确认二十店可选医师、适配服务、实际出诊日及资源；[原七角色](mac_seven_roles.json)、[教师七角色](teacher_seven_roles.json) |
| 小程序 | [255项基础检查、12个P1页面处理器场景及23页官方离线编译](native.json)；[可见导入包与报告摘要](visible_handoff.json)。不是微信平台、真机或真实短信验收 |
| 五店既有业务基准 | [9000请求/1800合法写入/p95 0.326秒](capacity_five_clinics.json)；[1063项独立业务核对](oracle_five_clinics.json)、[敏感读取审计逐项核对](sensitive_read_oracle.json)、[资源与OOM](resources_five_clinics.json) |
| 二十店混合负载 | [9000请求/1800合法草稿写入/p95 0.753秒](capacity_twenty_clinics.json)、[每店90次唯一写入及66张业务表不变](oracle_twenty_clinics.json) |
| 原库升级演练 | [原加密备份独立恢复后62→64迁移](original_copy_upgrade.json)，128组旧业务数据、密码及原迁移字节保留 |
| 含新历史的恢复 | [142表11962行加密独立恢复](populated_recovery.json)，包括80张图片、89个画像版本、65笔成本、81项分摊、25份月报；逐表行、二进制字节及110项触发器一致，空库准备后15.266秒 |
| 两套实际保护更新 | [原实例](mac_update.json)、[教师实例](teacher_update.json)；[最新五服务及六项健康条件](installed_services.json)。原数据库卷、密码、RC标签与70份原私有配置保留 |
| 课程配置与更新后备份 | [逐店课程配置](course_configuration.json)、[原实例逐项新增及原数据核对](mac_configuration_verification.json)、[教师实例](teacher_configuration_verification.json)；[两套更新后加密备份的解密与归档清单检查](installed_backups.json)，后者不冒充再次完整恢复 |
| 报告与数据库设计 | [报告验证](../report-source/validation.json)、[实际数据库ER](../database/README.md)、[固定名称报告](../../课程报告/README.md) |

容量测试分别连续30分钟，20账号同时发起、平均约5请求/秒，80%读取、20%合法写入；均无意外失败、重复效果、丢弃请求及OOM。普通请求p95小于5秒。五店沿用原患者建档与记录写入基准；二十店涵盖公开画像、经营查询与各店主管真实草稿保存。它们是两类有界工作负载，不能等同于所有临床/财务操作的二十店商业容量承诺；Docker各服务限额也不等同于独立2GB云主机验收。

已修复并重复验证：医师本人汇总反向关联导致500、内部宽表窄屏溢出、公开资料长文字放大溢出；压测登录准备增加当前店明确选择，计时包含客户端排队。历史候选CI的旧清单失败及改正见[历史](history.json)，不改写为一次通过。

每套实例新增60名医师、80项服务及80件资产（其中40椅位）、未来十四天854段出诊和长沙轮诊；原有资料保留。20条既有资源策略通过业务操作启用并增加版本，具体新增账户、专业授权、治理与审计数量单列。另新增61笔合成管理成本、21份月报及65项分摊，均不制造治疗、账单或现金事实。后续排班仍由前台维护。

月度利润按完成期账单减已确认成本计算；缺资料明确“待核算”，不能将未核验现金余额用净收款替代。成本、采购付款、折旧及医保资金分配口径独立，修订保留历史。

**验收边界：**课程合成资料；真实微信/短信等待平台配置；教师地址依赖Mac及临时隧道；独立云服务器尚未购买。大陆无代理访问、24小时持续观察及专业临床/商业资质均未由本轮建立。原UNKNOWN/UNDETERMINED及Windows历史数据恢复UNRESOLVED继续保留。恢复按已验证的同版本迁移建库路径执行，任意等价DDL自动识别的限制不变。
