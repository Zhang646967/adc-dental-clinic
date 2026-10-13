# v0.7 需求—代码—验收追踪

教师报告的SU编号只用于本报告，不改动之前FR/UC编号。完整20份规约见use_cases_v0.7.json。原先v0.1/v0.2全部目标并不因此自动完成。

| 用户/业务需求 | 实现 | 测试与报告 |
|---|---|---|
| 始终先选择身份 | workspaces.context/views, WorkspaceLoginView | WorkspaceAcceptanceTests；SU-01 |
| 身份工作台独立 | workspaces/rules, templates/workspaces, adc_core/context | 菜单及越界测试、静态7页面；SU-01 |
| 主管进台再选门店 | authorized_clinics/activate_clinic | 同绑定与角色切换/诊所隔离测试；SU-02 |
| 旧标签不能误提交 | WorkspaceContext/revision、signed token、require_writable | staleform/role撤销/范围篡改；SU-01/02 |
| 帮助定位真实页面及手动步骤 | guidance/catalog/context/views，guidance.js | task目录路由、页面selector、noauto-submit；SU-18 |
| AI只识别/引导，不代办 | assistants/services + guidance/answers | consent、返回后上下文重查、限额、降级；SU-18 |
| 候补登记和退出 | coordination.join_waitlist/withdraw | patient/front范围、一人一有效、日期；SU-13 |
| 最大可安排数建议 | solver.maximum_matching + create_plan | 全512个3×3图与独立穷举对比；SU-14 |
| 建议不等于预约 | publish_plan、WaitOffer | draft无占位，batch原子发布，时效；SU-15 |
| 明确接受才预约 | answer_offer→create_visit_locked | owner/front确认、重复确认并发；SU-16 |
| 邀约到期与再匹配 | reservations.assert_free + expire_clinic_offers | 过期不占位、明确回收；SU-17 |
| 既有治疗财务不回退 | 旧services/ledger/policies/数据库护栏保留 | 原143项回归，其中HTTP客户端适配新选择流程 |

旧migration哈希相同与方法数只说明静态状态；数据库/浏览器端到端结论需实际执行。源码里technical工作台不包含完整账号管理CRUD；无资源椅位、短信、生产部署、支付或临床决策。
