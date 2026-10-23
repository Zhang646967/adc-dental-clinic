# C1.1 患者关系与预约代办执行证据

2026-10-23。使用合成资料；本目录与历史 C0.3、B1.4 的容量及恢复结果分别解释。

| 范围 | 证据 | 执行结果 |
|---|---|---|
| 完整规则／数据库回归 | [regression.json](regression.json) | 1,095 规则、1,502 PostgreSQL／请求／并发；28 项新增关系授权 |
| 五店跨渠道 | [browser_native.json](browser_native.json) | 146 项真实 Chrome 与原生 Page HTTP 核对 |
| 岗位与操作 | [governance_browser.json](governance_browser.json) | 七角色、技术分配核验职责、前台受理／核验、键盘和390px大字 |
| 原生代码与编译 | [native.json](native.json) | 114 项源码／传输、26 项 Page 模拟场景、12 WXML及1 WXSS官方离线编译 |
| 独立业务事实 | [business_facts.json](business_facts.json) | 原约、后继、邀约、占用和操作来源；不产生治疗或资金 |
| 报告与 ER | [报告核验](../report-source/validation.json)、[结构视图](../database/view_manifest.json) | 63项业务用例与1项共享规约；七幅实际ER |
| 需求追踪 | [traceability.md](traceability.md) | 业务合同、用例、测试和证据对应 |

[准确应用提交](https://github.com/Zhang646967/adc-dental-clinic/commit/edcb6eb2b89ee54375afd24ea7cff364df7b87a2)的[CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39984392881)通过，1,095项规则与1,502项数据库测试的实际数量和耗时见[CI记录](application_ci_checks.json)。[同一镜像五店复验](candidate.json)通过146项跨端检查及78项独立事实核对。

[加密独立恢复](restore.json)在空PostgreSQL17中核对73表、30,162行及全部43项触发器，包含11项关系、11项授权、32条决定历史；同版本迁移建库路径的结构比较限制仍保留。[原数据库复制升级](copy_upgrade.json)证明三份追加迁移保留原67类数据、原42触发器，并只添加权限元数据及三张空业务表。

[本机保护更新](installed_update.json)使用同一镜像，原数据库容器、卷、70份私密配置、原有业务行及RC标签保留。[原账号与岗位](installed_browser.json)272项、[原生患者端](installed_native.json)13项、[患者切换](installed_relationships.json)22项检查通过。[实际结构](installed_schema.json)与ER一致；[十次健康样本](installed_observation.json)为96.54秒短时复核，不代表24小时验收。升级前已有观察器不可用状态保留为UNKNOWN，旧记录已加密归档；新版本六项应用监测与主机采集状态为HEALTHY。

[明确的合成配置增量](installed_examples.json)：正常业务命令新增一个代约账号、两项前台核验职责、两项关系/授权及四条历史；原业务行逐行核对，不新增预约、治疗或资金。[升级后加密备份](installed_backup.json)通过解密及清单核对；账号指南仅存本机私密目录。[十二页本地导入工程](local_package.json)不包含凭据。

[交付总记录](release.json)区分应用提交、实际安装和未执行的外部验收。

已修复：撤销岗位后的错误页导航递归、关系详情长业务编号的窄屏溢出、小程序切换后的旧确认及迟到响应混用、确认页对运输签名刷新的错误失效判断。官方模板编译检查修正患者选择表达式。历史诊疗、资金和关系决定不被这些修复覆盖。

尚未执行：微信运行时／真机／体验版、独立云端、当前版本新容量、连续24小时、专业临床资质验收。历史 Windows 原数据恢复仍为 UNRESOLVED。离线编译不是微信平台上线。
