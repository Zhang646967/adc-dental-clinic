# 来源与边界

私有材料：ADC案例（本会话上传，CASE第1–2页）；note__3第1/4/11页；note__4第7/11页。原件不包含在公开代码包中。原始工程包ADC_engineering_v0.3已直接解压核对，旧迁移哈希见original_migration_hashes.json。用户提供的旧版30项测试输出是用户本地证据，不是本生成环境运行记录。

以下为外部公开技术依据，查阅日期2026-09-22；新增实现不等于来源对本系统背书：

- OpenAI API Key Safety：密钥只在后端、环境变量、不要放客户端或仓库。https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety
- OpenAI Chat API：Chat Completions接口格式；本适配器使用其兼容请求结构，不承诺任意服务商兼容。https://developers.openai.com/api/reference/resources/chat
- W3C Older Users：可访问性与老年使用者需求的重叠；不把年龄视为能力的确定性替代。https://www.w3.org/WAI/older-users/
- WCAG2.2：文字、对比、可操作性、重新排版等评价依据；本项目没有完整合规认证。https://www.w3.org/TR/WCAG22/
- OWASP Prompt Injection：输出验证、最小权限、人工批准等风险缓解。https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- OWASP Excessive Agency：限制功能、权限与自主性。https://genai.owasp.org/llmrisk/llm062025-excessive-agency/
- Docker Compose Project Name：项目标识与资源隔离，解释原目录升级的必要性。https://docs.docker.com/compose/how-tos/project-name/

没有使用原案例照片、公开真实患者资料或复制授权PDF；没有调用外部模型处理这些私有资料。界面截图为本地静态测试夹具，固定虚构数据并有显著标记。
