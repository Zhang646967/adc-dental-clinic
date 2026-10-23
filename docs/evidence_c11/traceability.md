# C1.1 需求到验收追踪

| 合同 | 用例 | 不变量 | 实际验证 |
|---|---|---|---|
| C11-01 | SU-60、61 | 本店受理、明确核验职责、联系人无权、人工账号关联 | `RelationshipTests` 的 create/verify、contact/family、same_phone、reviewer、missing_account、foreign_patient；七角色及治理浏览器 |
| C11-02 | SU-62 | 仅本人或有效授权；切换与旧响应隔离 | grant-only login、switch_away_and_back、someone_elses_grant、old_web_authority；原生 selector/stale review 三场景 |
| C11-03 | SU-04、05、40 | 同患者资源互斥、唯一来源、合法重试 | delegate_booking、receipt_requires_exactly_one_authority、actual_postgres_two_actors_one_patient_compete；五店预约和改期读回 |
| C11-04 | SU-13、16、40、62 | 既有候补与预约共用事务；明确接受 | waitlist_accept、revoked_waitlist；五店前台发布、原生接受、网站结果与数据库事实 |
| C11-05 | SU-63 | 失效授权不能确认；原约与历史保留 | suspend_and_reverify、revoke_retains_booking、expiry、SQL历史不可变；五店撤销和原约核对 |
| C11-06 | SU-61、62 | 预约代办不含临床、账单和跨店权限 | delegate_cannot_read_clinical_text_or_invoice、clinic_scope；七角色页面拒绝 |
| C11-07 | 全部 | 追加迁移、真实ER、可恢复且数据保持 | 原40迁移摘要、43迁移实际执行、73表/181外键/43触发器；独立恢复和准确版本交付另记 |

完整测试定义见 `tests/test_patient_relationships.py`；浏览器、恢复、CI的执行文件按本目录登记。所有场景为合成业务验证，不把测试数量解释为覆盖率或商用合格率。
