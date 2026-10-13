# ADC v0.5 实际检查记录
记录时刻（UTC）：2026-09-27T00:03:50.447189+00:00

结果按证据层次区分。以下检查在生成环境执行；不代表用户电脑已升级。

| 检查 | 数量及结果 | 限制 |
|---|---:|---|
| 纯规则、静态结构、模拟HTTP契约 | 147个test方法通过 | 原101＋新增46；无真实模型调用 |
| 新管理页面Chromium断言 | 84/84通过 | 4种固定合成页面×3宽度×2模式及JS检查；源模板转换，非Django运行 |
| 原患者/员工/助手前端回归 | 87/87通过 | 同样是显式固定数据/接口替身，不是端到端 |
| Python compileall / 两个JS语法 | 通过 | 不验证Django导入和模型元类 |
| v0.4既有迁移原文 | 逐文件哈希一致 | 本轮仅追加两份迁移 |
| 新版Django/PostgreSQL测试 | 143项已编写，未运行 | 原86＋新增55集成＋2并发 |
| 真实AI、公网、负载、安全审计、恢复演练 | 未执行 | 不能标为发布通过 |

生成环境没有Django/PostgreSQL/Docker；PyPI与Debian源DNS访问失败。没有用SQLite替代真实数据库。
旧v0.3的30项通过日志由用户提供；对其版本有效，不移植为本版通过结果。

## 已执行与待执行
```
python -m compileall -q .
python -m unittest discover -s checks -v
node --check static/experience.js
node --check static/assistant.js
PYTHONPATH=. python scripts/check_management_browser.py
PYTHONPATH=. python scripts/check_browser_static.py
```
上面的PYTHONPATH写法用于本轮Linux生成环境。Windows用户直接使用Docker验收门，无须照抄这一环境变量写法。

待在用户CMD的原工程目录执行：
```
docker compose run --rm web python scripts/integration_gate.py
```
门槛顺序：147项纯/静态/契约 → Django check → makemigrations检查 → migrate → 143项真实数据库测试。第一处失败即停止，脚本不把尚未执行步骤写成通过。

## 新增回归重点
金融：缺失/草稿/确认零成本、零收入牙医、遗漏开单人员、两粒度聚合、权限与过期表单、只读快照、CSV无患者身份。
更正：原版不改、仅一张Invoice、只计当前版本、双角色、撤权重查、审计失败回滚、历史可查、草稿不可见、数据库禁止回退指针。
运营：未来与改期替代排除、未知不当爽约、诊所取消分开、无治疗算到诊、主管范围与N/A。
并发：两个财务员相同版本写入只允许一个；重复批准只发布一个版本。

静态页面截图均保留STATIC FIXTURE水印。表单为合成替身，不能当作真实Django字段渲染证据。正式提交课程报告前，应补齐本地端到端截图和实际验收日志。
