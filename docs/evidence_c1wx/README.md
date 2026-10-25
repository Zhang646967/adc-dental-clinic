# C1-WX 本地患者账号与本人核验交付

本地凭证 → 患者渠道账号 → 联络来源 → 本人申请 → 独立前台决定 → 明确激活 → 原预约／改期／候补。

**本地合成软件已交付。** [准确版本与适用范围](release.json)记录应用d0a05fe及[准确CI](application-ci.json)：1,104项源码规则和1,765项PostgreSQL、HTTP与并发。源码检出提交由CI元数据确认；[接受镜像](candidate.json)另核对源码标签及769份实际功能文件。首次打包清单错误与修正见[保留记录](ci-packaging-followup.json)。

同一镜像通过网站18项、小程序实际Page处理器与真实后端34项、七岗位14项及当前店隔离1项，共67项。原系统另通过18项读取／会话检查和完整私有凭证签发工具；19页官方离线WXML及WXSS通过。小程序处理器验证使用Node传输桥及模拟明确同意，不能称为微信运行时验收。

本轮修复390px大字模式长账号溢出，补齐暂停后复核原本人关联。恢复启用同一PatientAccess行，不换绑、不新建患者；安全停用账号仍须先技术恢复，审核账号不能与申请人相同。旧登录测试更新为“账号可以申请复核、患者业务仍拒绝”，没有放宽患者权限。

- [需求追踪](traceability.md)、[独立业务核算](independent-business-facts.json)、[七岗位](seven-role-results.json)、[当前店隔离](cross-clinic-results.json)。
- [109表及全部记录的加密独立恢复](release-restore.json)，含六张新表和77项触发器定义／启用状态；[原52迁移副本升级](copy-upgrade.json)。
- [保护更新](mac-update.json)、[100组原记录与70份配置](mac-final-preservation.json)、[实际安装结构](mac-schema.json)、[升级后加密备份](mac-after-backup.json)。新增三处职责标志、三条治理审计和三条正常清单读取审计分别核对；没有注入患者、预约或资金测试资料。
- [预演监测处置](observer-followup.json)：8eb到d0的私有升级漏重置观测身份，原记录已加密保留，按既有命令重置后重新取得六项健康。没有推断更早的UNKNOWN或原worker退出原因。
- [正式报告内容](report-validation.json)与[逐页视觉核对](report-visual-review.json)：175页、86业务用例及SF-01、105表、53图、20幅真实ER，355项既有规约字段保留。

主机采集工具另有[9e77fd0修复](host-tool-followup.json)，准确CI通过1,106项规则及1,765项PG用例，37项针对检查与真实Docker复现通过。临时维护事件不再误作Web重启，同时保留全历史截断识别。原应用镜像不变，768份其余功能文件一致，主机工具单独按提交核对；[原告警处置](maintenance-disposition.json)与[同一历史上的升级](mac-host-tool-update.json)均保留，不删除原误报记录。

真实微信／手机号、开发者工具运行／体验版、真实医保、公网、24小时、专业及二十店容量仍单独验收。历史Windows资料恢复保持UNRESOLVED；原本地RC数据库owner身份保留，不冒充独立HTTPS运行账号分离通过。

使用资料：[业务合同](../C1WX_ACCOUNT_CONTRACT.md)、[本地试用](../C1WX_LOCAL_GUIDE.md)、[当前数据库设计](../database/README.md)。下一批继续湖南目录及合成医保闭环；尚无AppID和机构接口不妨碍本地软件开发。

思维导图：身份来源与账号 → 本人及联络核验 → 不同账号决定 → 原患者授权 → 统一资源与保留历史。
