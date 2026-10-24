# C2.2–C2.3 连续诊疗、复诊责任与加工就绪验收

确认检查 → 方案与本人决定 → 实际分阶段治疗 → 唯一收费 → 后续责任与加工验收 → 独立核算与交付。

准确应用提交 `021a2183f52ff2170298134e610aea5d30fe28e7` 已通过[CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/40104194491)：1,104项源码规则、1,688项真实PostgreSQL／HTTP／并发。相同镜像在五家合成诊所完成610项Chrome及实际原生Page处理器联调，包含具体版本决定、三次加工周期、返工、原接诊关闭后的验收、部分不收费、改期、牙椅故障替换、实际完成、独立收退款及七角色。

五例新增开单1000元、收款1000元、退款500元、净收款500元、未收500元；原50000元历史开单和收款保留。方案、预约、联系、加工返回与实际治疗分别记录，均不凭意向提前生成收费。独立SQL核算不复用应用余额或完成选择器。

五诊所、二十账号连续三十分钟实际9000次请求，7200次非变更读取（包含签名预览）和1800次已提交合法写入，其中医师草稿900次、前台内部协调900次。p95为0.55秒，零意外失败、丢弃、重复治疗／收费、新死锁、可见OOM或服务重启。五次初始预览单独列为预热，不计入实际写入。资源限额和采样范围见[容量记录](capacity.json)。首次监测缺口使旧尝试未获整体验收，原记录保留后完整重测，见[尝试与处置](prior_attempts.json)。此结果不推定二十诊所或独立云主机容量。

加密备份恢复至独立空库，101张表、全部行／二进制CSV及历史、74个触发器定义和启用状态一致，目标库准备完成后8.857秒完成。使用同版本迁移建库；既有任意等价DDL自动结构比较限制保留。原库副本45→49迁移升级、实际本机更新及原83组记录／70份私有配置／原数据库容器卷／RC标签核对通过；十五张新临床表不向原库注入验收案例。

- [整体交付及边界](release.json) · [分项核验](verification.json) · [需求至测试](requirement_trace.json)
- [准确镜像](candidate.json) · [完整回归](regression.json) · [应用CI](application_ci.json)
- [诊疗跨端](clinical_browser.json) · [财务及七角色](finance_roles_browser.json) · [资源协调](coordination.json) · [独立业务事实](independent_business_facts.json)
- [五诊所授权患者切换](family_final_browser.json) · [关系与渠道凭据衔接](identity_statement_integration.json) · [加密恢复](release_restore.json) · [原库副本升级](copy_upgrade.json)
- [保护更新](mac_update.json) · [实际结构](mac_schema.json) · [原数据最终比对](mac_final_preservation.json) · [短时观测](mac_observation.json)
- [原系统浏览器](mac_browser.json) · [本人原生渠道](mac_native.json) · [预约代办切换](mac_relationships.json) · [匹配本地导入包](mac_local_package.json)
- [正式报告核验](report_validation.json) · [真实ER与目录](../database/README.md) · [业务合同](../C22_CONTINUITY_CONTRACT.md)、[复诊与加工合同](../C23_RECALL_LAB_CONTRACT.md)

正式报告164页，80项业务用例加SF-01、99张表、50幅图、17幅实际ER。新增SU-72—80；六章思维导图、旧规约与冻结来源保留。微信16页官方离线语法、Page模拟及实际HTTP联调分别记录，均不等于微信开发者工具运行、真机或体验版。

原回环RC演示沿用原数据库维护身份，新增生产账号检查未通过，见[权限范围](mac_runtime_role.json)。独立HTTPS部署由既有G4流程提供分离账号，并须在目标环境通过受限身份检查；当前本地结果不构成该验收。

凭据、密钥、备份、私有逐行摘要及临床／联系文字不公开。仅验证合成软件行为；专业审定、真实供应商／支付、完整质控队列、云端、24小时和更大规模仍按独立合同验收。历史UNKNOWN和Windows原资料未恢复状态保留。
