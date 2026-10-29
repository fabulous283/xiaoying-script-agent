# 设计与技术取舍

使用 LangGraph **1.1.6** 的 StateGraph、START/END、条件边、compile/invoke。StateGraph 保存 context；每个图节点完成一轮「模型决策 + 一次动作执行」，条件边只依据任务是否结束路由。框架不生成脚本、不改写查询、不自动修复时长、不替模型决定业务动作。工具函数直接调用，未使用 LangGraph prebuilt Agent、持久化、工具网络服务或多 Agent。

```text
brief + rules + action schema + actual history
                    ↓
              model.decide(context)
                    ↓
           Pydantic whitelist validation
                    ↓
     search / save / duration / rules / request / finish
                    ↓
       append actual observation → next model turn
```

动作使用带 discriminator 的 Pydantic 联合结构，拒绝未声明字段、未知工具、空理由和无效脚本。save_script 保存模型给出的完整稿件；真实模式没有确定性生成器替模型写稿。工具只接收运行时当前稿件，不信任模型自报通过。模型只能请求检查，不允许直接写检查状态。

查询空结果、检查失败、工具错误都作为 observation 交回模型；编排代码不自动选择下一业务动作。request_input 和 finish 是终止动作，成功出口附加确定性核验，拒绝遗漏或过期检查。save_script 清空旧检查，包括内容相同的再次保存，以避免修稿后沿用旧状态。

工具：search_materials 在合成关键词上做子串匹配，返回稳定 ID 和原始 facts；estimate_duration 按汉字/英文单词估算、按镜头舍入并累加；check_script 对标题/画面/句子白名单、逐条 claim、已检索来源、禁用表达、声明和重复镜头 ID 检查。检查覆盖旁白未登记的事实，不能仅添加一个合法 claim 来隐藏其他编造句子。

2026-10-29起，时长范围固定为 `[target * (1 - duration_tolerance), target]`，上限不再增加容差。提示词同步说明硬上限并建议围绕允许区间中点选句；最终始终以实际估算结果验收。旧Trace在复核脚本中明确标记legacy_symmetric_tolerance，只按历史标准验证记录是否真实一致，另列当前上限是否满足；运行时没有旧标准回退。

事实策略刻意保守：开放域语义蕴含不是此首版的能力。自由文案仅允许品牌数据中的中性句子，产品句子必须精确等于所引 fact 加句号。避免把匹配到产品名、引用合法 ID 或让同一模型自评当作事实证明；代价是风格/受众定制有限。品牌数据自身需要可信审核。

预算：图节点即一个应用层 step，默认 12；真实 HTTP 请求最多每步一次。读取超时通过 SCRIPT_AGENT_READ_TIMEOUT_SECONDS 配置，默认 180 秒，连接/写入/连接池超时分别 10/30/10 秒；网络读取上限不是端到端总时限。工具尝试包含失败，默认最多 8 次。达到工具额度后仍允许模型执行非工具终止动作；继续请求工具时返回 incomplete，不执行第 9 次调用。达到最后一步若动作已经合法完成，保留完成状态；否则 incomplete。LangGraph recursion_limit 为 max_graph_steps + 2，应用层预算先处理，避免框架异常吞掉部分结果。

Trace 包含运行 ID、模式、模型名、UTC 时间（ISO 8601）、配置、步骤、简短行动依据、有效工具参数、实际返回、耗时、observed_step、next_action、状态和完整最终结果。不要求或保存模型私有思维链。每次传模型的是实际历史副本，测试证明不能直接改写运行状态。工具错误保留类型，不保存可能含认证头或敏感数据的异常原文。

使用 httpx 直接接兼容接口，减少 SDK 耦合。参考 [LangGraph StateGraph 官方文档](https://reference.langchain.com/python/langgraph/graph/state/StateGraph) 的节点、条件边和编译机制；版本以已安装并执行测试的 1.1.6 为准。Pydantic 2.12.5 负责动作/输入校验，httpx 0.28.1 负责 HTTP，pytest 9.0.3 负责离线验证。requirements.lock.txt 锁定本机实际使用的递归依赖。

超时排查调整：发送给真实模型前仅移除 history 中 decision.script 和 tool_arguments，避免历史稿件和有效工具参数反复复制；保留完整工具 observations、reason、动作、当前稿件与检查。该视图使用深拷贝，不影响磁盘 Trace。以离线正常路径前 5 步和当前稿件构造的对比上下文，从 8683 字节减至 4359 字节（同一 JSON 序列化口径，仅为示例对比，不是线上 token 计费）。

可选 SCRIPT_AGENT_ENABLE_THINKING 通过 HTTP 顶层 enable_thinking 发送；空值不发送以保持服务可选性。参见[阿里云官方思考模式说明](https://www.alibabacloud.com/help/en/model-studio/deep-thinking)。本机配置 false，避免为结构化动作生成额外思考；是否支持以真实服务响应为准。SCRIPT_AGENT_MAX_TOKENS 明确限制输出预算，未改用流式传输，未通过删减实际检查或强制动作来提速。
