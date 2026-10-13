# ADC v0.4：患者服务、接诊开单与双端 AI 助手

**逻辑链：保留已跑通的 v0.3 → 扩展患者与员工双端 → 明确人工确认 → 接入可替换 AI → 真实数据库回归验收。**

本包是待 Docker 集成验收的增量源码，不是已经替你安装的程序，不是公网或真实医疗系统。演示只用虚构数据。

## 1. 这一版新增什么

| 部分 | 已写入源码的功能 |
|---|---|
| 患者端 | 独立登录入口；绑定本人档案；首页、预约列表、可用时段、二次确认、本人预约取消、本人账单、操作帮助 |
| 员工端 | 保留旧预约工作台；牙医复核过敏、确认实际治疗、撤回误录草稿行、完成并开单、无治疗关闭、账单打印 |
| 双端助手 | 患者助手与员工助手，按各自权限响应；自然语言意图识别，规则与数据库生成事实卡片 |
| 包容性界面 | 手动标准／大字简明模式、手机布局、键盘焦点、跳过导航、错误提示、可选本地中文朗读 |
| AI 运行支持 | 无钥演示、外部兼容接口、授权及配额、同意后外发、错误降级、不含正文的调用元数据 |
| 升级支持 | 新增两份迁移、保留旧迁移、备份检查脚本、原目录升级说明、新的测试与报告草稿 |

本次没有开放历史账单更正、预约终态更正、完整季度财务页面、真实支付、短信身份验证、家属代办和公网生产部署。这些原有待办没有被 AI 功能取代；仍需后续增量。

## 2. 先看验证边界

实际已运行：101 个纯规则／静态／接口契约 test 方法；87 个 Chromium 静态页面与 JavaScript 断言；Python 语法编译和两个 JavaScript 语法检查。浏览器使用模板转换的固定数据页面，fetch 与 storage 是明确的测试替身。

真实 Django/PostgreSQL：原 v0.3 的30项由用户在本地成功执行；**新 v0.4 未在本生成环境执行**。现在测试目录共86项（原30＋新增54集成＋新增2并发），需在你的 Docker 环境整体重跑。具体见 `docs/TEST_REPORT.md`。

真实模型 API 未调用，无用户密钥，无实际分类准确率、费用或延迟测量结果。

## 3. 现有 Windows CMD 用户：在原目录升级

你当前已工作的目录为：

```cmd
D:\Users\Zhang\Desktop\ADC_engineering_v0.3
```

**保留该文件夹名称和 Compose 项目，不改成一个新的 v0.4 目录运行。**文件夹名称不是程序版本，页面将显示0.4。项目名变化可能指向另一套 Compose 资源，不能把“空数据库”误认成原数据被删除。

先在原目录关闭 Web，停止演示写入：

```cmd
cd /d D:\Users\Zhang\Desktop\ADC_engineering_v0.3
docker compose stop web
```

用资源管理器复制一份原源码作备份（例如旁边的 `ADC_code_before_v04`）。这不是数据库备份，不要从这个副本运行 Docker；如果副本包含 `.env`，也必须保密且不能上传。

把 **`ADC_v0.3_to_v0.4_update.zip` 内部的文件和文件夹**复制到原目录，允许覆盖同名源码。不要再套一层目录。更新包不含 `.env`，不会覆盖密钥；不要删除原 `.env`、数据卷或自己的文件。

确认 `manage.py` 和 `UPGRADE_WINDOWS.cmd` 处于同一层后执行：

```cmd
UPGRADE_WINDOWS.cmd
```

脚本依次：确认旧 `.env` → 停 Web → `pg_dump` 保存 `backups\pre_v04.dump` → `pg_restore --list` 检查备份格式可读 → 构建 Web → 运行整体验收 → 新增患者演示账号 → 启动 Web。

备份可读检查不等于完成恢复演练。脚本没有执行恢复，也没有对原数据库做重置。若同名备份已存在，脚本会停止；确认保存后可将旧备份另起名称，再重新执行。

**任何一步失败都停在该处。不要删 migration、改用 SQLite、运行 `docker compose down -v` 或跳过测试。**贴最后的报错即可，不要贴 `.env` 或初始化输出的密码。

脚本是本地候选操作流程，尚未在 Windows 上实际执行；数据库支持与新业务测试的结果以你这次运行输出为准。

## 4. 升级后入口与账号

```text
员工工作台：http://127.0.0.1:8000/
患者入口：http://127.0.0.1:8000/portal/login/
员工助手：http://127.0.0.1:8000/assistant/
患者助手：http://127.0.0.1:8000/portal/assistant/
```

原 `front_a`、`doctor_a`、`manager_a` 等账号密码不变。新增：`patient_demo_a`、`patient_demo_b`、`doctor_b`，密码由 `seed_portal_demo` 在成功提交后随机显示，请自行保存。

重复运行初始化不会重置已有密码。遗失上述三个新账号密码时，才显式执行：

```cmd
docker compose run --rm web python manage.py seed_portal_demo --reset-passwords
```

这不重置旧员工账号。保留的演示患者档案与账号通过 PatientAccess 绑定；不要将“知道患者编号”当成账号认证。

用不同浏览器或独立浏览器配置分别登录患者和员工，避免同一浏览器 cookie 会话被另一个账号替换。

## 5. 先不用 Key：演示模式完整验收

默认 `AI_MODE=demo`。所有普通业务页面均能独立使用；助手明确显示“本地规则演示（未调用AI）”。不要把这种演示写成已验证外部模型能力。

推荐端到端路径：patient_demo_a 选择甲店／牙医1的未来时段 → 确認提交 → front_a 登记到诊 → doctor_a 复核过敏、添加一个真实含义的**虚构治疗记录** → 核对并完成 → patient_demo_a 查看自己的结算单。另用无治疗分支验证零金额单。详情见 `docs/ACCEPTANCE_v0.4.md`。

## 6. 配置你自己的 AI：不要发密钥到聊天

原目录 CMD 运行以下临时容器命令，不依赖损坏的 Windows Python：

```cmd
docker run --rm -it -v "%cd%:/app" -w /app python:3.13-slim python scripts/configure_ai.py
```

根据提示输入 `remote`、服务商文档中的 HTTPS Base URL、可用模型 ID、支持的 token 字段，并在隐藏输入处粘贴 Key。Base URL 不应带 `/chat/completions` 尾缀。脚本只更改 AI_* 行，保留原数据库连接和 Django 密钥，不发送网络请求。

适配器要求 `POST /chat/completions`、`messages`、JSON object 输出和相应 token 参数。它不是所有服务商原生 API 的通用适配器；兼容性须通过服务商文档与实际测试确认。本版不实现仅 Responses、Gemini 或 Anthropic 原生协议的转换。

然后执行：

```cmd
docker compose up -d --force-recreate web
docker compose run --rm web python manage.py check_ai
```

第二条只显示模式、是否配置Key和模型，不回显任何密钥，**不发网络请求**。

明确接受一次服务商可能计费的合成测试后，才执行：

```cmd
docker compose run --rm web python manage.py check_ai --live
```

该测试只发送“我想预约”和固定分类提示，不发送数据库记录。真实聊天还需要在页面勾选问题文本外发同意。Key 错误、模型不兼容或网络故障会清楚标记为本地降级，不悄悄伪装成功。

切回本地演示可再运行配置脚本并输入 `demo`，重建运行中的 Web 容器即可。禁用模式不会自动删除环境中的旧密钥；如需撤销密钥应在服务商侧执行。

## 7. 文件索引

`docs/AI_INTERFACE.md`：接口、信任边界、外发数据和配额。  
`docs/CHANGELOG_v0.4.md`：明确的范围变更、新表、行为限制。  
`docs/ACCEPTANCE_v0.4.md`：手工回归与失败处理。  
`docs/TEST_REPORT.md`：实际证据与未运行项目。  
`docs/REPORT_SECTION.md`：可以纳入课程报告的本轮章节草稿。  
`docs/browser/`：标注为静态夹具的截图和浏览器检查，不是生产系统截图。  
`docs/archive_v0.3/`：原版文档与原时点证据，不拿旧证据冒充新验收。

## 本模块思维导图

```text
ADC v0.4
├─ 患者：账户绑定 → 时段 → 二次确认 → 本人记录/账单
├─ 员工：到诊 → 过敏复核 → 实际治疗 → 唯一账单
├─ AI：同意 → 文本分类 → 重新授权 → 系统事实 → 明示来源
├─ 体验：标准/大字、键盘、移动端、本地朗读与替代文本
└─ 升级：原目录/原卷 → 备份 → 回归 → 再启用外部 API
```
