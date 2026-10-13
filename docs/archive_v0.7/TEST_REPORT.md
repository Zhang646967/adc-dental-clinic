# 实际检查记录 v0.7

**证据不能跨版本或跨层互相替代。** 当前日期2026-09-27。代码以v0.5候选源码为基线；用户已提供v0.3的30项PG通过日志，不代表新版本。

| 检查 | 实际结果 | 边界 |
|---|---|---|
| 纯规则/静态/模拟HTTP契约 | 181个test方法通过 | 原147+新增34；无真实模型调用 |
| 匹配算法有限穷举 | 包含在上述方法内 | 512个3×3图逐一与独立穷举最优匹配对比；不计成512个test方法 |
| v0.7静态Chromium | 157/157断言通过 | 7模板、3宽度、2模式，加JS焦点/dirty表单引导；set_content固定数据 |
| 原双端助手前端回归 | 87/87断言通过 | 原转换模板和fetch/storage替身；非真实API |
| 原管理界面回归 | 84/84断言通过 | 固定合成数据与源CSS/JS |
| Python语法 | compileall通过 | 不验证Django模型/模板引擎 |
| JavaScript | 3脚本node --check通过 | 不等于全部浏览器支持已验证 |
| 旧迁移原文 | 11份哈希不变，新增2份 | 没有执行迁移探测器或PG |
| 新版Django/PostgreSQL | 197项已编写，未执行 | 原143+新增52集成+2并发；详见evidence文件 |
| DOCX/PDF | 26页、9模型图、20规约 | 已按渲染页检查；不是系统运行证据 |
| 外部AI/公网/压测/恢复/全面安全审计 | 未执行 | 未取得key、无付费请求、无生产服务 |

## 已执行命令
```text
python -m unittest discover -s checks -v
python -m compileall -q .
node --check static/experience.js
node --check static/assistant.js
node --check static/guidance.js
python scripts/check_browser_static.py
python scripts/check_management_browser.py
python scripts/check_v07_browser.py
```
源日志：`docs/evidence_v07/`。所有界面截图明确为STATIC FIXTURE或等价标记。新的浏览器检查实测发现手机大字下头部和算法标签溢出；已通过flex换行、最小宽度和可读标签修复后重新运行。

## 未执行原因与下一门槛
生成环境没有Django、psycopg、PostgreSQL或Docker；依赖下载遇到DNS失败。没有改用SQLite伪造结果。用户在独立合成数据Docker环境执行`python scripts/integration_gate.py`，顺序是181项基础检查、Django系统检查、makemigrations一致性、真实迁移和197项PG测试。任意一步失败立即停止。

升级前要保留源码及数据备份。升级脚本只检查pg_dump格式可读，并未执行独立空库恢复。新会话策略、跨表资源锁、197个真实数据库测试以及Windows脚本都必须实机核验。

## 测试修改说明
原URL静态检查改为读取所有included URLconf，仍验证模板route存在；旧HTTP测试通过真实角色/范围选择激活上下文；部分跨工作台直接访问预期由404变为网关403。没有关闭CSRF、workspace中间件、权限、账单/费用规则或并发测试。
