# 业务需求与测试追踪

| 需求 | 责任与规则 | 测试与可见结果 |
|---|---|---|
| R153-01 清楚办理入口 | 患者服务概览仅本人；下一就诊与邀约分开 | MiniWaitlistTests网站／概览测试；五店Chrome与Page联调 |
| R153-02 候补登记 | SU-13；服务、范围、本人、预览及明确确认；不占位 | join_preview、explicit_confirmation、cross_clinic、window、service_change |
| R153-03 可靠重试 | 原患者锁和追加审计回执；不恢复已退出记录 | registration_replay、two_previews、concurrent_registration、跨端断点重放 |
| R153-04 前台协同 | SU-14／15前台生成发布；不替患者自动接受 | 真实Chrome前台发布，原生读取同一邀约 |
| R153-05 明确接受用途 | SU-16／40；新增或替换指定本人原约 | accept_preview_replay、offer_can_replace、客户端未选择用途被阻止 |
| R153-06 拒绝与退出 | SU-13／16；不取消原约，旧版本重核 | decline_keeps、withdraw_replay、withdraw_preview_stale |
| R153-07 防越权与失效 | 原会话、CSRF、签名及事务重授权 | own_only、foreign_preview、revocation、csrf、expired、read_only |
| R153-08 双端并发 | 原命令持有出诊、患者、设备锁；唯一结果 | concurrent_website_and_native_accept、原有同椅位HTTP并发 |
| R153-09 保留历史 | 服务目录改名不改原承诺，账务与治疗独立 | retained_service_label、48项独立数据库事实 |
| R153-10 可读可操作 | 专业层级、状态文字、390px大字、键盘 | 真实Chrome检查、网站截图、官方九页语法编译另列范围 |

原始测试名见tests/test_mini_waitlist.py；既有预约与权限回归见tests/test_mini_program.py。微信实际运行及云端验收仍单独进行。
