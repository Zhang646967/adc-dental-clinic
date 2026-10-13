# 生产配置候选与独立验证

本目录是配置候选，不是已部署、已恢复或安全认证结果。本地 `compose.yaml` 与现有 `.env` 均不改；没有把开发端口开放到公网。当前仍有真实PostgreSQL、TLS/代理、镜像、依赖、恢复和容量门禁待执行。

## 独立数据库回归

在未改本地v0.7的独立代码副本中，使用单独项目名，不叠加本地Compose：

```cmd
docker compose -p adc-v09-verify -f compose.verify.yaml run --rm verify
```

这个文件没有宿主机数据库端口，临时数据库使用tmpfs且仅为合成测试。`config.settings.test`覆盖为本地规则模式，密钥为空，不产生外部AI调用。测试所用常量密码只在无公开端口的临时环境使用，不能复制到部署配置。完成后只清理这个明确命名的验证项目；不得对原项目运行删除卷命令。

## 生产准备流程（未执行）

1. 固定测试通过的源码指纹和镜像摘要；锁定实际安装依赖。`requirements-production.txt`是候选选择，不是已安装锁文件。
2. 由部署维护者独立创建迁移owner及受限runtime角色。runtime须具有所需业务表DML/序列权限，但不能拥有库、表或建表/建角色权限。密码不进入报告或版本库。
3. 迁移使用独立维护容器及owner，不把owner密码送入Web。完成后用runtime运行 `manage.py check_runtime_role`；检查命令不会自动授予权限。
4. `config.settings.production`要求显式设置 `ADC_DEPLOYMENT_STAGE`、单一DNS主机 `ADC_PUBLIC_HOST`、生产专用`DJANGO_SECRET_KEY`、DB参数、`ADC_DATABASE_OWNER`、`ADC_TRUST_PROXY_HEADERS=1`。默认启用业务只读。DB默认要求TLS；私有隔离网络关闭TLS必须另设`ADC_PRIVATE_DB_NETWORK_ACK=1`。这些标志不等于验证通过。
5. 使用 `Dockerfile.production` 构建。用同镜像执行 `collectstatic --noinput` 到共享静态目录。Nginx模板需替换域名并配置真实证书，执行`nginx -t`；应用监听仅在私有网络可达，代理清除并重写转发头。
6. 执行 `manage.py check --deploy --settings=config.settings.production`、权限检查、HTTPS/cookie/CSRF/静态资源/限速及目标环境端到端验收。HSTS先短期验证，未开启子域继承或preload。
7. 备份恢复到独立空库，核对编号、关系、金额与重新登录；达到门禁后再切流量。新数据已经产生时不能盲目回滚丢弃写入。

生产配置由未启动保护桩升级为带输入校验的候选。尚未提供全自动生产编排或DB角色创建脚本，避免把未经验证的权限配置当成即用部署。真实系统禁止使用真实患者数据，本课程只使用合成资料。

## 技术参考（2026-09-27核对）
Django 5.2 Deployment checklist / Middleware；Gunicorn settings；Nginx ngx_http_proxy_module；OWASP Session Management。对应URL见报告参考文献。外部文档不证明ADC自身部署已通过。
