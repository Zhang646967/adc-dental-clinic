# 系统验收报告的编排与复核

[正式 PDF](../../../课程报告/课程报告_张加良_8210241102.pdf)　｜　[正文](正文.md)　｜　[业务用例索引](用例目录.json)　｜　[可编辑图源](门诊模型.drawio)　｜　[矢量图集](门诊模型.pdf)

正文采用 A4 宋体排版，表题在上、图题在下。封面、摘要、目录独立编页，正文与附录连续编号。第五章的三张画面取自获授权的岗位视图；其余七幅模型以可检索的矢量内容嵌入 PDF。

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
