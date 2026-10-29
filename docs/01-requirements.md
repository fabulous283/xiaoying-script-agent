# 需求与成功标准

用户：需要可编辑、能追溯产品事实的短视频创作者。目标：基于主题、受众、平台、目标时长、风格和合成产品资料输出标题、分镜、旁白、逐镜头来源、时长及风险。

范围：Python CLI、本地检索、确定性时长/规则工具、单 Agent、LangGraph 循环、兼容 Chat Completions 的模型接口、离线 Mock。不包含前端、数据库、视频制作和在线部署。

验收对照：

| 试卷要求 | 实现与证据 |
| --- | --- |
| 正常生成 | real-normal-hard-cap/、real-short-hard-cap/ 的真实 input、output、trace；normal/ 为 Mock |
| 缺关键信息 | missing_info/，五个必填字段逐项参数化测试 |
| 无素材 | real-no-materials/；真实模型读空结果后改写查询，再请求补充；no_materials/ 为 Mock |
| 工具失败 | tool_failure/；三类工具分别注入异常并验证 observation |
| 超时长修正或明确失败 | real-normal-hard-cap/ 的真实34.95 → 26.7 → 27.2秒；normal/ 的Mock 38.4 → 30秒；budget_limit/ 未完成。旧real-short-refined/ 最终16.15秒不满足当前15秒硬上限 |
| 动态决策 | 真实模型根据时长失败结果修稿、根据空检索结果改写查询；Mock 不代替真实证据 |
| 事实与品牌合规 | 所引 ID 必须实际检索；事实逐字匹配；覆盖标题/画面/旁白 |
| 执行上限 | 12 图步数、8 次工具调用；可配置；触顶 incomplete |
| 统一交付 | README、src、tests、examples、data、五篇文档、依赖、环境示例 |
| GitHub URL 与最终 SHA | 待创建仓库和提交 |

成功必须满足：输入完整、存在实际检索素材、当前稿件估算时长在目标的90%～100%内、当前稿件规则检查通过。目标是不可超过的上限，duration_tolerance只允许略短。最终时长等于逐镜头估算之和，引用与规则报告一一对应。未通过检查不能以 completed 出口结束。

无效类型、负时长等输入属于 CLI 配置/格式错误（退出码 2）；缺字段或空白字段是可补充信息（needs_input）。工作流终态包括 completed、needs_input、failed、incomplete。真实模型可能选择不符合要求的动作，但运行时不允许虚假成功。
