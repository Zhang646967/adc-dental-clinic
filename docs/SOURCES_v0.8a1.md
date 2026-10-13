# 本轮设计来源（2026-09-27核查）

- 用户v0.7实际页面反馈：唯一角色自动激活、候补起止限制、规则解释和下一步入口。属于本项目需求变更。
- note__2.pdf 第4页：Incremental Model、可交付子集与扩展接口。
- note__3.pdf 第1、4、11页：需求与设计追踪、可测试行为、不变量及操作前后条件。
- note__5.pdf 第4—8页：关注点分离、简单性与信息隐藏。具体字段、账户生命周期和控件不是讲义指定。
- MDN datetime-local：https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/datetime-local 。原生控件跨浏览器不同，不能把min/max误写成任何平台都不可选择错误时间；它本身没有时区。
- Django 5.2 authentication：https://docs.djangoproject.com/en/5.2/topics/auth/default/ 。密码API、验证器与会话行为；不等于本项目已验收。
- Django 5.2 transactions：https://docs.djangoproject.com/en/5.2/topics/db/transactions/ 。原子事务机制；并发和角色规则另行测试。
- PostgreSQL 17 explicit locking：https://www.postgresql.org/docs/17/explicit-locking.html 。行锁与advisory锁；应用协议不是对数据库所有者的绝对限制。

没有真实模型调用，没有新增提供商或实际患者资料。全部前端截图来自明确标注的固定数据，不是用户部署的新版本画面。
