# 系统验收报告的编排与复核

[正式 PDF](../../../课程报告/课程报告_张加良_8210241102.pdf)　｜　[正文](正文.md)　｜　[业务用例索引](用例目录.json)　｜　[可编辑图源](门诊模型.drawio)　｜　[矢量图集](门诊模型.pdf)　｜　[逐图核对](逐图核对.md)

正文采用 A4 宋体排版，表题在上、图题在下。封面、摘要、目录与图目录独立编页，正文与附录连续编号。正文内嵌 47 张可检索的矢量模型图，第五章另收录六幅实际岗位操作画面。

## 报告与系统对应表

| 报告位置 | 验收者核对的事项 | 同一业务的入口、凭据与边界 |
| --- | --- | --- |
| 第 1.2、5.11 节 | 从仓库进入患者或员工登录，选择岗位、登录并找到可办业务；患者预约回执对应就诊 #9 | [门诊入口](https://lijiahao.duckdns.org/experience/) · [按岗位核对](../../TEACHER_WALKTHROUGH.md) · [交付记录](../../../RELEASE_CURRENT.md) |
| 第 3.2、5.1、5.6 节 | 原约与拟选时间各有起止和状态。确认后可回查后继 | [患者改期核对页](../../../templates/portal/reschedule_confirm.html) · [预约办理](../../../portal/rescheduling.py) · [本版两组连续改期及冲突记录](验收记录.json) |
| 第 3.3、5.2 节 | 本店两个同名档案分别核对完整患者编号 | [前台档案清单](../../../templates/patients.html) · [本店同名清单画面](screens/identity.png) |
| 第 3.4、5.3 节 | 一次就诊可同时有待确认草稿和当前确认版 | [医师检查记录工作台](../../../templates/clinical/encounter_worklist.html) · [第 2 版与草稿同页画面](screens/record.png) |
| 第 2.4、4.5 节 | 本地处方、药房调配及护理执行各有店别和独立职责 | [处方范围](../../../clinical/prescription_access.py) · [药房调配](../../../clinical/dispensing.py) · [护理范围](../../../supplies/access.py) |
| 第 4.4 节 | 原约与后继、回执及临床版本的真实关系 | [只读关系核对](核对物理关系.sql) · [实测外键与唯一性](验收记录.json) |
| 第 5.4、5.8、5.9 节 | 门店开通检查项目后，独立审核、发布、本人站内提醒与复诊预约按同一笔业务回查 | [正式配置岗位核对记录](../../evidence_site_examination/chain.json) · [检查审核与发布](../../../clinical/examinations.py) · [患者提醒](../../../portal/report_notices.py) · [报告复诊](../../../portal/report_followup.py) |
| 第 5.10 节 | 已租香港服务器内部按同版复核三岗、复诊时间与前台权限，该项验收当日的公网入口仍为原版本 | [服务器独立资料库的就诊、报告和复诊编号](../../evidence_site_examination/server.json) |
| 第 1.2、5.6 节 | 5359979a 的首页「找门店」按直线距离显示附近门店，缺少坐标时显示「距离未知」，拒绝定位后可手选城市 | [门店入口和距离提示](../../../clients/wechat/miniprogram/pages/discovery/index.wxml) · [预约与目录实测记录](验收记录.json) |
| 第 5.7 节 | 前版同次就诊回查、前台登记及授权不足时的办理结果 | [分项记录](验收记录.json) · [专业授权范围](../../../clinical/authority.py) |
| 第 5.5 节 | iPhone 17 Pro Max 在先前版本上看到 09:00 原约已替代、10:30 后继已取消，未见绿色诊断面板 | [手机实测版本及分项记录](验收记录.json) |
| 第 5.6 节 | 保留 7d3a9022 的九档字号和只读核验。更新版 684388b5 在核对页逐行列出原约和新安排，可展开编号与原因 | [各屏宽与字号下的实测值及本版手机验收范围](验收记录.json) · [微信患者端的预约详情](../../../clients/wechat/miniprogram/pages/visit/index.wxml) |
| 第 2.5 至 3.11 节 | 对照现状、目标及岗位责任，核对电话接待、候补、出诊调整和季度资料 | [业务与需求](business_additions.md) · [用例与业务模型的逐图核对](逐图核对.md#逐张核对) |
| 第四章后半 | 核对预约与药房批次、医疗告知、归档补正、费用和资金关系 | [临床模型](clinical_additions.md) · [物理关系](er_additions.md) · [原版专题明细](逐图核对.md#原版-44-张专题物理图的精确对应) |
| 第 5.12 至 5.16 节 | 逐项从需求找到可观察结果和证据，包括处方、护理、退款和预收抵扣 | [分项结果和证据](verification_additions.md) |
| 附录 | SU-01 至 SU-147 和 SF-01 均逐项给出完整规约 | [编号目录](用例目录.json) · [基于成品 PDF 的逐项核对](verify_report.py) |

## 图形约定

第二章以门诊组织为边界，区分业务执行者和业务工人。第三章以软件为边界，将直接操作软件的岗位列为系统执行者。第四章的分析类图说明对象和业务关系，物理关系图标注表名、外键和唯一性。逐图核对表列明每张图对应的职责、消息、条件或约束及其依据。序列图以交接消息、激活条及条件分支说明协作，按读回与提交分别标注。方法参见 [UMLChina 业务用例](https://umlchina.com/book/softmeth_03.htm)、[业务序列](https://umlchina.com/book/softmeth_04.htm)、[系统用例](https://umlchina.com/book/softmeth_05.htm)、[分析类图](https://umlchina.com/book/softmeth_08.html)和 [OMG UML 2.5.1](https://www.omg.org/spec/UML/2.5.1/)。

## 来源与重建

- `正文.md` 依次列出五章，并编入[业务和需求](business_additions.md)、[系统及状态设计](architecture_additions.md)、[临床设计](clinical_additions.md)、[物理关系](er_additions.md)和[验证结果](verification_additions.md)。章内以 `---` 划分页，`@model`、`@screen` 链接源图。`验收记录.json` 保留前版 iPhone 实测、不同字号与改期页面核对和附近门店核对。表 5-6 读取其中的已测字号档位。
- 构建时从 [原用例规约](../REPORT.md)读取逐项表格，从[设计原稿](../report_source.json)读取专题设计。`用例目录.json` 保留 SU-01 至 SU-147 和 SF-01。四项医保结算相关名称明确注明“测算”，对应的机构联网和实际支付须单独启用。各用例原规约在[既有用例正文](../REPORT.md)中可按编号定位。
- `门诊模型.drawio` 是 draw.io Desktop 的可编辑原件，已按图导出为 47 页矢量图集。使用桌面应用的导出功能或下列命令可更新图集，PDF 的创建时间会随导出变化。
- `核对物理关系.sql` 在 PostgreSQL 17 上以只读事务复核 8 项外键及有关唯一性。新增 10 张物理关系图中的 53 条外键逐条对照[已观察的数据库结构快照](../../database/schema_snapshot.json)，核对指向、可空性和唯一性。图 5-4 至图 5-6 的报告编号、复诊编号、时间、读态和原图校验值见[运行记录](../../evidence_site_examination/chain.json)。

在仓库根目录运行，第一条命令中的 `draw.io` 表示桌面版的可执行文件。

```sh
draw.io --export --format pdf --all-pages --crop --border 4 --theme light --output docs/report-source/acceptance/门诊模型.pdf docs/report-source/acceptance/门诊模型.drawio
python3 docs/report-source/acceptance/build_report.py
python3 docs/report-source/acceptance/verify_report.py
```

报告重建使用 Python 3、ReportLab、pypdf 和 Pillow。复核另用 pypdfium2。中文采用 macOS 宋体集合的常规与粗体字面；可用 `--songti` 指定同一字体集合。检查 PDF 的命令只读，输出文件的 SHA-256、页数、插图、书签、目录链接和用例覆盖情况。
