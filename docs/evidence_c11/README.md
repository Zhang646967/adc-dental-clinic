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

本地候选结果不代替准确提交 CI、目标安装或独立恢复。后续执行结果单独添加对应文件；仅以文件中真实状态为准。

已修复：撤销岗位后的错误页导航递归、关系详情长业务编号的窄屏溢出、小程序切换后的旧确认及迟到响应混用、确认页对运输签名刷新的错误失效判断。官方模板编译检查修正患者选择表达式。历史诊疗、资金和关系决定不被这些修复覆盖。

尚未执行：微信运行时／真机／体验版、独立云端、当前版本新容量、连续24小时、专业临床资质验收。历史 Windows 原数据恢复仍为 UNRESOLVED。离线编译不是微信平台上线。
