# 系统验收报告的编排与复核

[正式 PDF](../../../课程报告/课程报告_张加良_8210241102.pdf)　｜　[正文](正文.md)　｜　[业务用例索引](用例目录.json)　｜　[可编辑图源](门诊模型.drawio)　｜　[矢量图集](门诊模型.pdf)

正文采用 A4 宋体排版，表题在上、图题在下。封面、摘要、目录独立编页，正文与附录连续编号。第五章的三张画面取自获授权的岗位视图；其余七幅模型以可检索的矢量内容嵌入 PDF。

## 报告与系统对应表

| 报告位置 | 验收者核对的事项 | 同一业务的入口、凭据与边界 |
| --- | --- | --- |
| 第 3.2、5.1、5.6 节 | 原约与拟选时间各有起止和状态。确认后可回查后继 | [患者改期核对页](../../../templates/portal/reschedule_confirm.html) · [预约办理](../../../portal/rescheduling.py) · [本版两组连续改期及冲突记录](验收记录.json) |
| 第 3.3、5.2 节 | 本店两个同名档案分别核对完整患者编号 | [前台档案清单](../../../templates/patients.html) · [本店同名清单画面](screens/identity.png) |
| 第 3.4、5.3 节 | 一次就诊可同时有待确认草稿和当前确认版 | [医师检查记录工作台](../../../templates/clinical/encounter_worklist.html) · [第 2 版与草稿同页画面](screens/record.png) |
| 第 2.4、4.5 节 | 本地处方、药房调配及护理执行各有店别和独立职责 | [处方范围](../../../clinical/prescription_access.py) · [药房调配](../../../clinical/dispensing.py) · [护理范围](../../../supplies/access.py) |
| 第 4.4 节 | 原约与后继、回执及临床版本的真实关系 | [只读关系核对](核对物理关系.sql) · [实测外键与唯一性](验收记录.json) |
| 第 5.5 节 | iPhone 17 Pro Max 上 09:00 原约已替代，10:30 后继已取消，未见绿色诊断面板 | [实机版本与分项记录](验收记录.json)。大字号、读屏、原生选日和其他 iPhone 屏宽仍待实机 |
| 附录 | SU-01 至 SU-147 和 SF-01 全部保留 | [编号目录](用例目录.json) · [基于成品 PDF 的逐项核对](verify_report.py) |

## 图形约定

第一、二幅以门诊组织为研究对象，区分组织外的患者和组织内的岗位。第三幅更换为软件边界，患者、前台及医师分别为系统执行者。分析类和业务对象表达概念及多重性；物理图另以表、列、外键和唯一约束表达就诊数据，完整数据库另有字段与关系目录。七张绘图均可在 draw.io 的分页中逐项修改。方法依据见 [UMLChina《软件方法·业务用例图》](https://umlchina.com/book/softmeth_03.htm)、[系统用例图](https://umlchina.com/book/softmeth_05.htm)及 [OMG UML 2.5.1](https://www.omg.org/spec/UML/2.5.1/)。

## 来源与重建

- `正文.md` 依次列出五章。章内用 `---` 分页，`@model`、`@screen` 对应已入版的图号。`验收记录.json` 保存浏览器和微信运行条件，并逐项记录 iPhone 17 Pro Max 的扫码版本、原约与后继状态、绿色诊断面板及未验证的字号、读屏等条件。
- `用例目录.json` 保留 SU-01 至 SU-147 和 SF-01。四项医保结算相关名称明确注明“测算”，对应的机构联网和实际支付须单独启用。各用例原规约在[既有用例正文](../REPORT.md)中可按编号定位。
- `门诊模型.drawio` 是可编辑原件。已用 draw.io Desktop 32.7.4 的 PDF 导出生成七页矢量图集。使用桌面应用的导出功能或下列命令可更新图集，PDF 的创建时间会随导出变化。
- `核对物理关系.sql` 在实际 PostgreSQL 17 上以只读事务复核 8 项外键及有关唯一性。三个岗位插图来自独立验收数据，私有账号不随包分发。

在仓库根目录运行，第一条命令中的 `draw.io` 表示桌面版的可执行文件。

```sh
draw.io --export --format pdf --all-pages --crop --border 3 --theme light --output docs/report-source/acceptance/门诊模型.pdf docs/report-source/acceptance/门诊模型.drawio
python3 docs/report-source/acceptance/build_report.py
python3 docs/report-source/acceptance/verify_report.py
```

报告重建使用 Python 3、ReportLab、pypdf 和 Pillow。复核另用 pypdfium2。中文采用 macOS 宋体集合的常规与粗体字面；可用 `--songti` 指定同一字体集合。检查 PDF 的命令只读，输出文件的 SHA-256、页数、插图、书签、目录链接和用例覆盖情况。
