# B1.5.3 患者页面与候补渠道验收

患者服务中心 → 小程序候补 → 网站前台发布 → 患者明确选择 → 同一保存结果。

已实现首页专业化布局、概览与邀约提醒，以及原生候补登记、邀约新增／替换、拒绝、退出、历史和人工协助。前台排班职责、原资源命令和39份迁移保持不变。

| 执行范围 | 记录 |
|---|---|
| 1,052规则、1,402 PostgreSQL／HTTP／并发，含25项新增 | [完整本地回归](regression.json) |
| 五店实际Page逻辑与HTTP适配，Chrome前台发布，患者网站读回 | [258项联调](client_bridge.json) |
| 唯一后继、两类接受、拒绝退出、占用、500笔原账务与50,000元实收 | [48项独立数据库核对](business_facts.json) |
| 九页原生模板、样式和93项源代码／传输 | [官方离线语法编译](native_compiler.json) |
| 桌面与390px大字号患者网站 | [桌面页面](patient-service-desktop.png)、[窄屏页面](patient-service-390.png) |
| 数据结构与历史边界 | [迁移保留](migration_preservation.json)、[分项准备状态](readiness.json) |

Page联调执行实际客户端事件，`wx.request`由真实HTTP适配器承接，没有模拟业务成功；网站截图并非微信界面。微信IDE界面预览、JS桥运行时、手机及体验版继续未验收。[准确提交CI](application_ci.json)及[本机交付](delivery.json)已追加；[加密独立恢复](encrypted_restore.json)核对69张表、30,196条记录及42项触发器。原生运行、手机与云端范围继续独立。

这里的48项核对依据已知合成种子和明确的操作结果；本机原资料保护另按逐行指纹比较。历史容量、公网、24小时观察和Windows原数据恢复均不因页面与渠道更新而自动通过。

本机更新后，七角色及患者入口浏览器检查、原生只读／预览与[实际数据库ER比对](mac_schema.json)通过。原66组业务资料与70份配置保持不变；[加密前后保护](mac_backup.json)与[当前运行状态](mac_final_state.json)单独记录。当前正常不是24小时连续运行证据。

更新前原监测进程已退出，原因未确定，原未知区间及事件文件加密保留，见mac_update.json中的UNKNOWN_OBSERVER_UNAVAILABLE。升级后当前六项条件和主机采集正常；不把当前正常改写为此前持续正常。
