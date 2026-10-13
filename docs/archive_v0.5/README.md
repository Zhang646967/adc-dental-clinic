# ADC v0.5：管理分析与受控更正
**阶段性交付候选；不是已经完成公网验收的医疗/财务生产系统。**
逻辑链：延续v0.4 → 补齐季度管理/运营分析 → 开放有限账单更正 → 明确模块契约 → 回归验证与系统报告。

## 本轮可操作功能（源码已实现）
保留患者门户、员工接诊开单、双端受限AI和标准/大字模式。
新增季度创建、纳入清单、成本草稿与确认、当前账单开单收入、利润与总体基金测算、CSV核对；新增有口径和缺失提示的运营统计；新增负责牙医申请、独立财务审核的原治疗行数量/单价更正，以及已发布历史版本查阅。

采用模块化单体，不新增微服务。`finance.policies`封装计算政策，`care.ledger`封装收入事实，`adc_core.snapshots`提供一致只读查询，`adc_core.commands`封装已识别冲突的错误翻译。模块内部约定与角色授权分别说明。

## 当前验证
147项纯/静态/模拟契约、84项新管理前端断言、87项原前端断言已通过。143项Django/PostgreSQL测试已编写，未在本生成环境执行。无真实AI调用；无公网、负载与恢复演练。详情在`docs/TEST_REPORT.md`。

## 现有Windows用户
仍在 `D:\Users\Zhang\Desktop\ADC_engineering_v0.3`，仍使用CMD。
1. `docker compose stop web`；复制现有源码作保密备份。
2. 将累计更新包内文件覆盖到原目录，`manage.py`与`UPGRADE_WINDOWS.cmd`同层；保留原`.env`和数据库卷。
3. 执行 `UPGRADE_WINDOWS.cmd`。这是v0.3/v0.4均可用的累计源码升级，但实际兼容性以完整验收门为准。

脚本先备份数据库并检查备份格式，然后构建、执行所有门槛、保留账号密码地添加门户示例、启动Web。同名备份已存在就停止；不要删库或覆盖备份绕过失败。升级失败后数据库可能已有新增迁移，不能直接运行旧代码当成安全回滚。

## 页面与账号
| 页面 | 路径 | 角色 |
|---|---|---|
| 工作台 | / | 已有员工 |
| 患者入口 | /portal/login/ | patient_demo_a / patient_demo_b |
| 季度管理 | /finance/ | finance_demo写；hq_demo读 |
| 运营分析 | /operations/ | manager_a本店；hq_demo全链 |
| 更正申请 | 已完成账单中的更正入口 | 对应doctor_a / doctor_b |
| 更正审核 | /corrections/ | finance_demo |

账号密码沿用；新增门户账号密码由初始化随机显示，自己保存，不发聊天。原财务/HQ测试账号来自v0.3 seed_demo；无需创建共享万能账号。

## AI
继续`demo`默认模式；remote配置沿用旧`.env`，本轮不读写或要求发送Key。无Key不阻止普通业务。AI只分类/导航，授权数据由服务器查询，无自动写入或临床诊断。见`docs/AI_INTERFACE.md`。

## 文件入口
- `docs/SYSTEM_REPORT_v0.5.md`：完整系统说明报告源稿。
- `docs/CONTRACTS_v0.5.md`：课程原则到模块契约。
- `docs/CHANGELOG_v0.5.md`：范围和迁移变更。
- `docs/ACCEPTANCE_v0.5.md`：多角色人工演示。
- `docs/TEST_REPORT.md`、`docs/evidence_v0.5.json`：实际检查边界。
- `docs/archive_v0.4/`：旧版文档，不是新版本结果。

## 发布边界
第一版仅合成数据、本地服务。生产配置仍阻断。完整身份核验、患者新增账号发放、预约终态纠错、治疗项目增删更正、退款/税务、个人奖金政策、密码恢复、完整目录维护、负载/安全/恢复/公网验收仍未全部覆盖。不存在“已经全量完成”的结论。
