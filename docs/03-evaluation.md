# 实际评估

初始评估日期：2026-10-28；硬上限调整复验：2026-10-29（北京时间）。环境：Windows、CPython 3.10.5。执行 `python scripts/generate_examples.py`，最新测试实际结果 **50 passed**，退出码 0，原始结果见 [test-results.txt](../examples/test-results.txt)。examples/runs 中初始五组路径均为 **Mock**；真实适配器 HTTP 单元测试使用 httpx.MockTransport，不是服务调用或模型效果证据。

**当前标准已改为目标的90%～100%，不能超过目标时长。** 下文 refined、timeout 等历史记录按旧双向容差生成，保留原始输出不重写。real-short-refined 的16.15秒不再作为当前15秒验收通过证据。新记录见文末。

| 场景 | 输入、输出和 Trace 目录 | 实际结果 |
| --- | --- | --- |
| 正常并超时修正 | [normal](../examples/runs/normal/) | completed；38.4 秒不通过，修订 30 秒；P01 引用，规则通过 |
| 缺受众 | [missing_info](../examples/runs/missing_info/) | needs_input；requested_fields 含 audience；无脚本 |
| 无产品素材 | [no_materials](../examples/runs/no_materials/) | search 返回 0，下一动作 request_input；无编造素材 |
| 工具异常 | [tool_failure](../examples/runs/tool_failure/) | 搜索实际抛 RuntimeError；模型收到错误后 finish failed |
| 执行上限 | [budget_limit](../examples/runs/budget_limit/) | 第 3 步后 incomplete，保留 38.4 秒失败检查和待完成项 |

每个目录均包含实际 input.json、output.json、trace.json、run_config.json。汇总见 [summary.json](../examples/summary.json)。Trace 直接记录工具结果，不是预写决策日志；但选择动作的是确定性 Mock，因而只证明流程与不变量。

正常路径详细顺序：search_materials → save_script → estimate_duration（38.4，不通过）→ save_script → estimate_duration（30，通过）→ check_script（通过）→ finish completed。最终镜头时长 11.65、8.05、10.30 秒；求和 30。产品事实只有「支持字幕」，claims、来源 P01 和旁白对应。

自动测试还覆盖：五个字段分别缺失；模型读取空结果后主动改写查询；三类工具各自失败；两个独立预算；额度刚好够最后检查仍可完成；修订使旧检查失效；品牌违规后修订复检；模型异常脱敏；未知动作拒绝；模型不能突变运行状态；27/30秒边界及边界外0.01秒，33秒拒绝；规则已通过但超时长时禁止finish completed；标题、画面、旁白、claim、来源、声明、重复 ID、未出现在旁白的 claim 等攻击；CLI 退出码及产物一致性；真实 HTTP 适配器请求/响应协议与无配置不回退。

首次测试有 **5 failed / 31 passed**：4 个时长边界夹具错误地设置了超过 10 秒的镜头固定耗时，1 个预算夹具同时触发两种上限却断言图上限。已修改夹具为合法耗时并分别设置预算，重新执行通过。未隐藏或将失败计为通过。

模型配置阶段新增 `.env` 加载测试，先因缺少实现失败，添加加载逻辑后通过。其后全量验证发现 **3 failed / 39 passed**：editable 安装生成的中文路径 .pth 使用 Windows 本地编码，子进程强制 PYTHONUTF8 导致 Python 在加载 site 时失败。测试与示例生成器改用 PYTHONIOENCODING 仅控制标准输入输出编码，避免改变路径解码，全量重新执行 **42 passed**。未修改用户全局 Python 的 .pth 文件。

真实接口配置验证（qwen3.8-max）：

- [real-no-materials](../examples/runs/real-no-materials/)：模型实际选择 search_materials，收到空结果后改写 query 再检索，仍为空后 request_input，最终 needs_input。该记录可证明模型消费真实工具结果调整动作。
- [real-normal-timeout](../examples/runs/real-normal-timeout/)：首次检索成功，得到 P01；第 2 次模型调用超过 60 秒读取超时，最终 failed，Trace 保留 model_error : ReadTimeout。不是 Mock，也不构成正常生成通过的证据。
- [real-normal-timeout-retry](../examples/runs/real-normal-timeout-retry/)：人工发起一次独立重跑，同样在检索成功后的第 2 次请求读取超时。没有自动重试或伪装通过；现有 60 秒阈值尚未支撑该服务的完整脚本生成，需要后续结合服务响应延迟调试。
- [real-normal-timeout-fix](../examples/runs/real-normal-timeout-fix/)：读取上限改为 180 秒、关闭思考、精简历史重复稿件后，12 次请求均返回，单步耗时约 1.5～6.7 秒，未发生 ReadTimeout。时长实际为 41.4 → 17.9 → 27.15 → 25.65 → 28.4 秒；模型根据时长和规则结果修稿，但曾错误删除旁白中的产品事实，最终达到 12 步上限，规则复检未完成，状态 incomplete。不能将这条记录算作正常生成通过。

超时专项验证见 [timeout-diagnostics.json](../examples/timeout-diagnostics.json)。三个调整合并验证，不能独立证明某一项是唯一根因；由于所有请求均在旧阈值 60 秒内返回，单纯延长阈值不足以解释本次改善，关闭思考和精简请求是合理影响因素。此结论为推断，未做单因素 A/B。最新测试增加配置生效、连接/读取超时分离、保留 observations、历史精简不修改原状态及非法参数拒绝验证。新增请求配置测试先因旧 60 秒固定值失败，修复后通过。

提示与计数参考优化后的实际结果：

| 真实场景 | 记录 | 实际动作与结果 |
| --- | --- | --- |
| 30 秒正常生成 | [real-normal-refined](../examples/runs/real-normal-refined/) | search → save → estimate（27.15 秒通过）→ check（通过）→ finish completed；5 步 / 3 次工具 |
| 15 秒约束与超时修正 | [real-short-refined](../examples/runs/real-short-refined/) | search → save → estimate（22.15 秒，不通过）→ save 修订 → estimate（16.15 秒，通过）→ check（通过）→ finish completed；7 步 / 4 次工具 |

两次运行均使用默认 12 步 / 8 次工具额度，未放宽规则或时长容差。30 秒稿三镜头为 10.80 + 7.80 + 8.55 = 27.15 秒，属于首稿直接通过；15 秒稿落在 13.5～16.5 秒允许范围内，可证明模型根据实际超时长结果选择修稿并复检。对照用例改变的是目标时长，所有原始输入、完整动作和工具返回均可复核。最终引用 P01，产品事实为“支持字幕”，无量化效果结论。

改动：真实模型请求增加 writing_reference，列出合法中性句和已检索事实原句的 speech_units，使用与时长工具相同的确定性计数。它不生成脚本、不选择句子，不替代估算工具。提示明确使用素材事实原句、claim 与旁白同时保留、根据实测时差少量增删、修稿后两个检查都重做。新增计数参考测试先因缺少 writing_reference 失败，补实现后全量 48 项通过。

归档时使用 `scripts/archive_real_run.py` 对两条 completed 记录的最终稿重新执行时长和规则检查，复算结果与 output.check_details 及逐镜头输出一致，并校验 trace.final_output 与 output 相同。归档保存提示词与当前请求配置，当前配置来源明确标为归档进程，不声称旧 Trace 已记录这些参数。密钥检查通过，归档未写入密钥或服务私有地址。

仍有边界：只有少量真实用例，未测端到端稳定成功率，也未进行真实视频口播测量。旧的预算耗尽记录揭示模型存在计数与规则理解错误，不能因为两条成功记录而隐藏。尚未创建 GitHub URL 和最终 SHA，不能宣称交卷完成。

限制：Mock 只以主题关键词选择素材，其他输入对离线文案影响有限；真实模型也受保守表达库限制。时长为公式估算；关键词检索不等于语义相关性。错误只保留类型便于脱敏，定位真实接口问题时需本地安全排查。多次运行覆盖同名示例目录，真实记录应使用独立目录并审核后归档。

## 2026-10-29 硬上限复验

用户明确要求“可以略短，但不能超过目标”。时长工具上限改为target，默认下限仍为90%；数据字段保持不变，duration_tolerance仅表示允许短缺的比例。先修改边界测试，实际得到2 failed / 3 passed，确认30.01秒和33秒在旧逻辑中被错误放行，再修复工具并同步提示。新增规则检查通过但超目标时无法finish completed的集成测试；当前50项全部通过。

| 当前真实记录 | 时长检查实际返回 | 终态 |
| --- | --- | --- |
| [real-short-hard-cap](../examples/runs/real-short-hard-cap/) | 目标15秒，通过范围13.5～15秒，首稿14.4秒通过 | completed；5步、3次工具；规则通过 |
| [real-normal-hard-cap](../examples/runs/real-normal-hard-cap/) | 目标30秒，通过范围27～30秒；34.95秒过长 → 26.7秒过短 → 27.2秒通过 | completed；9步、5次工具；规则通过 |

两条均使用默认预算，归档时按当前工具重新计算最终时长和事实规则，与保存输出一致，P01引用保留。30秒记录提供了当前标准下真实模型根据实际时长结果修稿并复检的证据，替代旧16.15秒案例作为验收入口。

复核脚本显式区分六组旧真实记录与当前标准：历史Trace仍按其原始双向容差复算以检查完整性，同时标出最终稿是否满足当前上限；不会把旧记录改成新结果，也不会让运行时代码回退旧规则。原Mock示例已用新标准实际重跑。
