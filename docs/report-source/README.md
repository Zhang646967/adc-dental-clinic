# 报告源文件与复现说明

课程案例与note → 业务合同和模型 → 执行证据 → 受保护交付。当前正式报告为2026-10-18的R2.4.2故障演练与界面优化版，应用 `1977b4bc2d8787711966c19439a5a272c9a9f1ca`，已通过[准确CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39184693082)并更新Mac。[验收与交付](../evidence_r242/README.md) · [界面调研](../UI_UX_STUDY.md)。

- [正式PDF](../../课程报告/课程报告_张加良_8210241102.pdf) · [正式Word](../../课程报告/课程报告_张加良_8210241102.docx)
- [可在线阅读正文](REPORT.md) · [格式合同](FORMAT_REFERENCE.md) · [结构/排版/隐私核验](validation.json)
- [需求至测试](../evidence_r242/requirement_trace.json) · [依赖处置手册](../R242_DEPENDENCY_DRILLS.md) · [下一阶段计划](../R24_ACCEPTANCE_PLAN.md)

## 当前内容与格式

沿用用户86页大学课程PDF的版式，来源按摘要标识，私有原文只读。当前报告81页，包括大学封面、中英文摘要、两页目录、六章、参考文献和两份完整用例附录。中文为正文，英文摘要及必要技术术语保留。

SU-01—38和SF-01共39份完整规约、AT-01—25、原19幅模型图均保留。现有56张编号表、24幅图，每章附思维导图；49项目录与实际页码一致。旧界面截图保留版本范围，新增UX1空输入登录截图。

## 本轮证据和历史边界

当前完整回归1,046项源码/规则与1,152项真实PostgreSQL/HTTP/并发；四类实际依赖中断28项、应用换址7项和真实浏览器60项通过。Mac计划更新应用/worker/observer/网关，数据库容器保留；48项原持久事实、70份配置、原卷和RC标签一致。原观测加密保留后建立新源码观察。

[baseline.json](baseline.json)分别保留R1/R2.1/R2.2、两批R2.3、R2.4.1与当前R2.4.2/UX1结果和证据摘要。R2.3恢复24项、51表29,144行、15.868秒及R2.2资金/权限场景保留其历史执行范围；没有把本轮收款数据集当成非零退款或设备冲回场景。

R1五店二十账号、三十分钟容量日期为2026-10-15。本轮未重做容量、真实24小时或加密空库恢复；R2.4.3/2.4.4和R2.5另验。服务器未购买，Windows原数据恢复未解决。UX研究为官方文档、启发式观察和工程验证，尚非用户访谈、效率实验或完整WCAG认证。

## 源文件与复现

`report_source.json`为可编辑正文，`build_report.py`只从冻结的RC1 Word保留模型和完整规约，不访问数据库或凭据。`baseline.json`保留各代范围，`toc_pages.json`保存最终PDF页码，`validation.json`记录检查与文件摘要。

```sh
python docs/report-source/build_report.py --output /absolute/draft/folder
```

Python需要python-docx，PDF渲染使用LibreOffice和Poppler；字体为Noto Serif CJK SC、Noto Sans CJK SC和Liberation Serif，PDF字体全部嵌入。新导出后重核目录、重建并检查所有页面。`draw_operations_flow.py`保留责任图生成来源，通知截图保留R2.2日期，`workbench-login.png`来自当前真实Chrome空输入页面。

正式Word/PDF只放顶层课程报告目录，文件名固定。冻结R5/RC1报告、原模型、30份迁移及RC标签不改。报告文档随后同步不重启已验收应用。

思维导图：原案例和规约 → 当前责任合同 → 分阶段证据 → 源码与CI → 课程报告 → GitHub与Mac同步。
