# 小影短视频脚本 Agent

题号：**4**；题目：**短视频脚本 Agent**。独立 Python CLI，使用 LangGraph 承载有预算的「模型选择动作 → 执行 → 观察 → 再决策」循环，交付可编辑 JSON 分镜、事实引用、逐镜头时长、规则检查和任务状态。

已使用 **qwen3.8-max** 跑通真实模型链路。当前时长标准为“可以略短，不能超过目标”，15 秒请求真实输出 **14.4 秒**，检查通过并完成；30秒请求经历34.95 → 26.7 → 27.2秒修订后完成。旧标准下的修订记录22.15 → 16.15秒继续保留，但最终超过15秒，**不作为当前标准的成功证据**。无素材路径展示了模型改写查询后请求补充。详见[实际评估](docs/03-evaluation.md)。这些是少量实际用例，不代表稳定成功率。Mock只证明流程。

## 快速运行

从仓库根目录执行，验证环境为 Windows / Python 3.10.5。没有服务需要启动。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
.venv\Scripts\python -m pip install -e ".[test]" --no-build-isolation
.venv\Scripts\python -m script_agent.cli --mode mock --input examples/inputs/normal.json --output-dir runs/normal
.venv\Scripts\python -m pytest -q
```

已配置 Python 环境也可直接 `python -m pip install -e ".[test]"`；主依赖已在 pyproject.toml 固定版本，完整验证环境快照为 requirements.lock.txt。快照针对 Windows / Python 3.10，其他平台需重新解析依赖并验证。

输出为指定目录的 `output.json` 和 `trace.json`。正常示例首稿 **38.4 秒**，Mock 读取超时 observation 后修订到 **30 秒**，最终三镜头为 **11.65 + 8.05 + 10.30 秒**。这些是公式估算，不是真实音频测量。

CLI 必须显式选择 `--mode mock` 或 `--mode real`。退出码：0 完成、2 输入/配置/写文件错误、3 需补充、4 失败、5 未完成。负向用例非零退出是预期行为。

## 真实模型

真实模式会自动读取当前工作目录的 `.env`，进程环境变量优先，不执行变量插值；Mock 模式不读取密钥。复制 `.env.example` 后在本机填写三个变量，或通过秘密管理方式注入当前进程；不要提交 `.env`。

```powershell
$env:SCRIPT_AGENT_BASE_URL = "https://your-provider.example/v1"
$env:SCRIPT_AGENT_MODEL = "your-model-name"
# SCRIPT_AGENT_API_KEY must already be injected into this process environment.
python -m script_agent.cli --mode real --input examples/inputs/normal.json --output-dir runs/real-normal
python -m script_agent.cli --mode real --input examples/inputs/short_duration.json --output-dir runs/real-short
python -m script_agent.cli --mode real --input examples/inputs/no_materials.json --output-dir runs/real-no-materials
```

接口为 `/chat/completions`，需支持 `messages`、`response_format: {type: json_object}`、`max_tokens`。不使用 SDK，使用 httpx 0.28.1 直接请求，无隐式重试、无静默回退 Mock。协议不兼容、无配置、响应不合法都明确失败。HTTP 环境代理禁用以避免意外泄露认证头；需要代理时应有意识地修改适配器并验证。

模型请求可在 `.env` 配置：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| SCRIPT_AGENT_READ_TIMEOUT_SECONDS | 180 | 每次网络读取的等待上限，允许 1～600 秒；不是端到端总时限 |
| SCRIPT_AGENT_MAX_TOKENS | 4096 | 输出预算，允许 256～16384；不建议为提速而压到不足以输出完整脚本 |
| SCRIPT_AGENT_ENABLE_THINKING | 空 | 空时不发送扩展参数；true/false 显式开关，仅适用于支持该参数的服务 |

连接超时固定 10 秒、写入超时 30 秒。当前本机 Qwen 配置为读取 180 秒、4096 tokens、关闭思考。模型请求省略历史动作内的旧稿正文和重复工具参数，但保留当前完整稿件、工具 observations 与历史动作；磁盘 Trace 保持完整。历史中性句、来源 ID、检查结果均不删减。

真实记录先写入默认忽略的 `runs/`。检查是否包含私密输入后，再将实际运行的 input、output、trace 整理到 `examples/runs/real-*` 并更新评估文档。归档当前合成资料的运行可使用下面命令，它会用本地工具复算 completed 稿件并检查与输出一致，不会调用模型。归档命令须在运行后立即执行，request_config 与提示词快照来自归档时的配置及代码；不要用新配置覆盖历史记录。非完成记录不会执行最终合格检查。

```powershell
python scripts/archive_real_run.py --run-dir runs/real-normal --input examples/inputs/normal.json --destination examples/runs/real-normal-new
```

当前真实记录覆盖正常完成、超时长修订复检完成、无素材改写查询并请求补充。30秒真实用例经历34.95 → 26.7 → 27.2秒，最终满足硬上限；15秒用例为首稿14.4秒通过。旧标准的15秒记录最终16.15秒，仅作历史记录，不能当作当前成功证据。

## 评审入口

- [需求与验收](docs/01-requirements.md)、[方案与取舍](docs/02-solution.md)、[实际评估](docs/03-evaluation.md)。
- [正常路径输出](examples/runs/normal/output.json)、[对应 Trace](examples/runs/normal/trace.json)。
- [当前真实正常与修订输出](examples/runs/real-normal-hard-cap/output.json)、[当前真实15秒输出](examples/runs/real-short-hard-cap/output.json)、[真实无素材Trace](examples/runs/real-no-materials/trace.json)。历史refined记录使用旧标准，详见评估文档。
- [当前硬上限的真实 30 秒修订 Trace](examples/runs/real-normal-hard-cap/trace.json)：34.95 → 26.7 → 27.2 秒，复检后完成。
- [缺信息](examples/runs/missing_info/trace.json)、[无素材](examples/runs/no_materials/trace.json)、[工具失败](examples/runs/tool_failure/trace.json)、[执行上限](examples/runs/budget_limit/trace.json)。
- [测试结果](examples/test-results.txt)、[汇总](examples/summary.json)、[AI 使用记录](docs/04-ai-usage.md)、[复盘](docs/05-retrospective.md)。

重现五组离线材料及测试结果：`python scripts/generate_examples.py`。该命令只覆盖上述 Mock 示例，不处理真实模型资料。

单独复现负向场景：

```powershell
python -m script_agent.cli --mode mock --input examples/inputs/missing_info.json --output-dir runs/missing
python -m script_agent.cli --mode mock --input examples/inputs/no_materials.json --output-dir runs/empty
python -m script_agent.cli --mode mock --input examples/inputs/normal.json --fail-tool search_materials --output-dir runs/failure
python -m script_agent.cli --mode mock --input examples/inputs/normal.json --max-steps 3 --output-dir runs/limit
```

## 数据、范围与限制

data/ 全是合成资料，P01 **只有「支持字幕」这一项产品事实**。检查器要求产品事实逐字匹配已检索素材；标题、画面和中性旁白来自品牌规则中的可编辑表达库。字幕文字与旁白统一在 voiceover 字段中计时。此策略保守且可复核，但限制自由改写，尚不支持任意主题的开放域创作、语义蕴含验证或自然语言品牌规则推理。修改表达库后需要重新验证。

工具只读本地 JSON：关键词检索、估算时长、事实和品牌规则检查。时长通过范围为目标的 **90%～100%**，上限始终为目标秒数；duration_tolerance 只控制允许短于目标的比例。默认每秒 4 个汉字/英文词，每镜头固定 0.8 秒，另含 0～5 秒显式停顿。每镜头四舍五入到百分之一秒后相加。自定义输入字段见 examples/inputs/normal.json，CLI 支持 `--materials`、`--rules`、`--max-steps`（默认 12）、`--max-tool-calls`（默认 8）。这是估算上限，真实音频仍需实测。

工具异常只保留安全的错误类型，详细内部错误不会写进 Trace。Trace 存储 brief、素材和动作内容，因此真实业务数据应留在本机。每次修订清空旧检查，只有当前检查均通过才能 completed；预算耗尽统一 incomplete 并保留 pending_items。

## 提交状态

题号：**4**；题目：**短视频脚本 Agent**。

公开仓库：[fabulous283/xiaoying-script-agent](https://github.com/fabulous283/xiaoying-script-agent)，评审无需私有仓库授权。候选人确认个人有效投入1小时，负责整体框架与思路并人工审核AI代码；具体编码由AI辅助完成，详见AI使用说明。

最终commit SHA随交卷信息单独提供；在交卷对应检出版本执行 `git rev-parse HEAD` 可获得完整SHA。文档不嵌入自身提交的SHA，以避免更新文档再次改变SHA。后续修改应重新运行验证，并以最终提交版本为准。
