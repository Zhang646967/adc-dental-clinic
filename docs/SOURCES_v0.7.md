# v0.7 依据索引

- 用户明确决定：登录总是选角色；主管入台再选店；工作台独立；AI引导真实页面与手动操作；候补和优化纳入本版。
- 教师截图：愿景，业务用例，现状/改进业务序列，系统用例及规约，汇总Word或PDF。未规定页数和图数。
- ADC案例W44694，2024-10-08版第1—2页：多诊所业务、个人信息、多过敏/多资格、治疗单位/价格、季度和单据。没有附原案例或照片。
- note__3第1、4—5、11页：需求设计区别、可测试、前后条件和不变量。
- note__4第7、10—11页及note__5第4—10页：并行细化、ADT、模块接口、关注点分离和信息隐藏。
- OWASP Authorization Cheat Sheet（研究依据，不是本项目安全认证）：https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- Django5.2 sessions：https://docs.djangoproject.com/en/5.2/topics/http/sessions/
- PostgreSQL17 Explicit Locking：https://www.postgresql.org/docs/17/explicit-locking.html
- W3C clear step-by-step instructions：https://www.w3.org/WAI/WCAG2/supplemental/patterns/o4p07-step-instructions/
- OMG UML2.5.1：https://www.omg.org/spec/UML/2.5.1

本版算法为有限二部图增广路最大匹配，没有实现之前规划中的多资源CP-SAT。算法实际检查还包括全512个3×3图与独立穷举结果对比。公开资料用于解释机制，不能替代本项目运行和迁移测试。
