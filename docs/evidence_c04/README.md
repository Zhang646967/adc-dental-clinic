# C0.4 患者找店与登录分流交付

公开找店 → 主动定位或选城 → 明确门店与服务 → 患者通道 → 合法就诊人 → 原预约确认。

**本地合成软件已交付。** [准确版本与范围](release.json)区分业务应用f9df57d、一次性准备工具ba611d4、后续文档提交。两次准确实现CI分别通过1,104项源码规则及1,714／1,715项PostgreSQL、HTTP与并发；工具修复另有27项旧服务资料回归。原服务编号复用，应用镜像不因工具跟进而替换。

- [业务合同](../C04_PATIENT_DISCOVERY_CONTRACT.md)、[同镜像取证](candidate.json)、[应用CI](application-ci.json)及[准备工具CI](preparation-tool-ci.json)。
- [77项隔离浏览器与原生处理器](browser-results.json)、[资料发布跟进](profile-browser-results.json)和[独立预约／资金核对](independent-business-facts.json)。四店形成四个唯一预约，无治疗、账单或资金事实。
- [原系统保护更新](mac-update.json)、[42项原系统七角色与跨端预览](mac-browser-results.json)、[二十店正常命令配置](mac-network.json)及[最终资料保护](mac-final-preservation.json)。原98组记录及70份配置保留；仅列明的服务展示及资源版本更新，原诊疗财务无新增。
- [填充后103表、1,752行加密独立恢复](release-restore.json)、[原库副本追加升级](copy-upgrade.json)、[更新后加密备份](mac-after-backup.json)。恢复采用已验证的同版本迁移路径，保留自动结构比对的既有边界。
- [实际原系统SQL与ER比对](mac-schema.json)：52份迁移，原49份不变；103表、993个ORM字段、285外键、75触发器。
- [正式报告](../../课程报告/README.md)：169页、82业务用例及SF-01、18幅实际ER。固定Word／PDF文件名不变；[内容](report_validation.json)与[169页排版复核](report_visual.json)通过。
- [17页小程序本地工程](mac-local-package.json)、[官方离线WXML／WXSS](native_offline.json)与[实际处理器](native_source.json)；这些不等于微信平台或真机运行。

八省会二十店是明确标识的合成目录，长沙四店具有可约配置，其他十六店仅展示资料。二十店目录不证明二十店容量；既有五店三十分钟容量保留其原版本和范围。

本次更新前原通知worker已退出，退出码1、OOMKilled=false，根因仍为UNDETERMINED；[历史事实](worker-before.json)及原私有日志保留。新worker及六项监测已有[短时新鲜健康样本](mac-observation.json)，不倒推旧间隔或24小时。原回环课程库保留维护身份，[独立HTTPS数据库角色验收](mac-runtime-role.json)未执行。

C1-WX本地身份与C6.1医保合成流程继续推进；C6.2等待定点机构条件。无AppID及真实医保接口，微信平台、云端、专业验收及Windows原数据恢复边界保留。

思维导图：公开资料版本 → {城市、主动定位、营业与服务} → 分流登录 → 授权患者 → 统一预约 → {原承诺、临床财务保持、独立恢复}。
