# 课程报告源与PDF修订

业务分析 → 用例及状态 → 实际数据库设计 → 分项验证 → PDF交付。

[正式PDF](../../课程报告/课程报告_张加良_8210241102.pdf)为当前报告唯一交付格式，姓名学号文件名保持不变。报告293页、147业务用例加SF-01、166表、87图、44实际ER、110目录项。旧Word按2026-11-01版本保留，不再更新；历史编排工具`build_report.py`留作来源，不用于当前发布，也不再从Word转换PDF。

- [正文](REPORT.md)：可检索内容；`report_source.json`维护章节，`business_use_cases.json`维护用例规约。
- [本次PDF修订范围](pdf_revision.json)：确定基线、物理第144页／正文第138页、第5.23及5.24节。
- [内容及版式核对](validation.json)：PDF与历史Word分别标识，不混用哈希。
- [真实数据库ER与字段目录](../database/README.md)：80份迁移、167SQL表、489外键、139触发器；本次无变化。
- [回传审核](../WORKBUDDY_C33B_REVIEW.md)及[分项执行证据](../evidence_c33b/README.md)：正常入口官方工具通过，原生picker、设备和手机缺项分别记录。

## 本次修订复现

`update_pdf_report.py`直接生成PDF替换页，从指定Git基线取得其他页，保留其内容流、书签及页码；不创建Word。需要ReportLab与pypdf。中文字体优先系统宋体，缺少时用仓库已有字体；不复制系统字体文件进源码。

```sh
python docs/report-source/update_pdf_report.py --repo . --output /tmp/课程报告.pdf --proof /tmp/报告核对.json
```

本次仅更新第5.24节及该共享页版式，其他292页内容流保持；新页字体嵌入、边界及最终渲染另行检查。复现成功不等于视觉审核，也不证明官方工具、手机、医疗专业或云端验收通过。后续内容增加时按实际修订重排和核对，不能把本次单页规则套用到所有章节。

原用例、图片、引用、历史报告及生成工具保留Git历史。正文保留note中的可测试需求、岗位交接、信息隐藏与职责分离原则，部署过程和账号资料不进入正文。

思维导图：结构化源 → 准确基线 → 直接PDF修订 → 书签／内容／渲染核对 → 分项证据。

第 5.18 节的单页修订由 `update_pdf_report.py --spec docs/report-source/pdf_core_ux_revision.json` 从指定基线重现。页数、书签和其他 292 页的内容流已校验。
