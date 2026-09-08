# DSH 压缩机制研究（deepseek-harness compaction）

> 状态：✅ 完成（2026-09-06）。方法：直接读 master 源码与官方文档（仓库 2026-08-13 建，最后 push 2026-09-04），非二手转述。
> 用途：回填《长程压缩与cheap区间_v1.md》§3，并评估其 §4.3「接力压缩」设计。
> 核心源文件：`packages/compaction/compaction-basic/src/{summarizer,config,region,index}.ts`、`docs/subsystems/compaction.md`。

---

## 1. /compact 的确切流程：摘要请求怎么构造、产物怎么接回

**摘要请求构造**（summarizer.ts `summarizeWithLlm`）：把上一轮对话**逐字节重放**（同一个 system prompt、同一份 tools、同样的消息序列，"reproducing ... verbatim lets the auxiliary call reuse the provider's warm prefix cache"），然后**追加一条独立的 user message**，内容即压缩指令（`COMPACTION_INSTRUCTION`）。注意纠正前期线索：指令**不是**拼进最后一条 user message 的尾部，而是新建一条 user message——前缀扩展的性质不变，只是追加的是新消息而非续写旧消息。请求带 `purpose: 'compaction'`，模型默认沿用会话当前路由的 provider/model（可配置 `summarizationProvider/Model` 覆盖，但**换模型就放弃缓存复用**）。`system`/`tools` 在 `SummarizationInput` 里注释明写 "reused for prefix-cache alignment"。

**产物接回**：摘要成功后，旧历史**被替换而非追加**——产物是一条新的 user message（内容 = 固定 preamble + `<compacted-summary>` 摘要 + 闭合标签），以 `surfaceOp: { op: 'replace', start, end }` 落盘，**顶替被压缩区间；其后紧跟逐字保留的近期尾巴（retain tail）**。会话在同一 session 内继续，不开新会话。替换后下一条请求的新前缀 = system + tools + checkpoint user message + 保留尾巴。日志侧 `compaction/start → compaction/summary → compaction/end` 三个事件只进日志不进模型上下文，start 即持久化锁（崩溃留下可检测的 orphan）。手动的 `/compact` 命令 idle-only、无参数、"does not consume a model turn"，压缩期间用户消息照常入队 FIFO。

来源：[summarizer.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/summarizer.ts)｜[compaction-basic README（KV Cache effect 两节）](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.md)｜[子系统文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/compaction.md)｜[command-compact README](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/command-compact/README.md)

**启示（小说流水线）**：DSH 证明了"压缩调用零破坏缓存"的正确姿势 = 逐字节重放 + 尾部追加独立指令消息；产物进入上下文的方式是**替换生成新前缀**，与活文档 §4.3 的"产物开新前缀"在缓存数学上等价（见 §7）。

## 2. 摘要触发条件

- **压力触发**：`auto: true`（默认）时，在 `agent/pre-step`（每步发起请求**之前**）用 `ctx.tokenMeter` 计价当前会话，`totalTokens ≥ floor(contextWindow × thresholdRatio)` 即触发；默认 `thresholdRatio: 0.8`。
- **保留尾巴**：`retainRatio: 0.16`（默认，上下文窗口的 16% 逐字保留）或绝对值 `retainTokens`，二者互斥且必须小于阈值。
- **溢出兜底**：收到 provider 确认的 `CONTEXT_WINDOW_EXCEEDED` 后走 `agent/request-error` 路径——**绕过阈值与保留策略（retain=0）**做最大幅度的头部压缩，`maxOverflowRetries: 1` 次后原错误照抛。
- **手动**：`/compact` 随时可压（低于阈值也可）；另有 `compactRegion()` 程序化指定区间。
- **前置剪枝**：挂载 `compaction-tool-result-pruner` 时先做无模型调用的超长工具输出剪裁，剪完低于阈值就**跳过摘要**。

来源：[config.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/config.ts)｜[index.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/index.ts)｜[compaction-basic README 配置表](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.md)

**启示**：DSH 是"请求前连续监测 + 硬限兜底"双触发；小说流水线的卷界触发（§4.3 触发器 1）相当于手动/计划触发，可照抄其"每章清算时检查读税 + 硬限前强压"的两级结构。

## 3. 摘要的提示词设计（官方全文可引用）

指令要求"Condense the conversation ABOVE into a structured checkpoint that lets another model resume the work with no loss of essential context"，强制输出固定 8 节 Markdown（空节写 "(none)" 不许删）：**Primary Request and Intent / Key Technical Concepts / Files and Code / Errors and Fixes / Pending Jobs / Current Work / Next Step（单个动作）/ Critical Context（决策+理由、约束、用户偏好、待解问题）**。Rules：保留精确的文件路径、命令、错误串、标识符、数值、函数签名；忠实记录用户纠正；"Do NOT mention this summarization or that the context was compacted"；只输出文本不调用工具；若历史中已有 `<compacted-summary>` 块，视为**先前的 checkpoint**——合并非逐字照抄。产物另包一层固定 preamble（"Treat the captured context as established background ... Continue the task directly"）。全文见 [compaction-basic README "Compaction instruction" 节](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.md)（与源码逐字一致，源码在 [summarizer.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/summarizer.ts)）。

**启示**：结构 = 任务型 resume（意图/状态/下一步），与小说"续写型 handover"（场景梗概/人物声口/衔接点/文风）不同——小说不必照抄 DSH 小节，但应抄它的**固定模板 + 空节显式标注 + 精确字串保留 + 旧 checkpoint 合并规则**四条纪律。

## 4. 压缩后的缓存账

- **摘要调用本身**：官方明确"the provider's warm prefix cache is reused up to the trailing instruction; **only that instruction, and the summary output, is uncached**"——即输入端只有指令那一条新消息是 miss（~几百 tok），其余 ~100% hit；输出端 = 摘要正文（`maxTokens` 默认 8192 封顶，截断即整次失败丢弃）。
- **压缩后的新前缀**：官方口径"**Replacing rather than append-only. Each checkpoint invalidates reuse from the first replaced history token; the unchanged request prefix before that range remains reusable**"——被替换区间从第一个被顶替的历史 token 起全部 miss（通常即全部对话历史），system+tools 前缀段仍热；新前缀（checkpoint+尾巴）远小于原历史，故一次性 miss 很小，此后恢复高命中。`/compact` README 原话："The accepted surface replacement invalidates reuse from the first shadowed history token."
- **社区实测**：[#2064](https://github.com/deepseek-ai/deepseek-harness/discussions/2064)：650 请求/16 会话/155.9M tok 实测 **hit 98.09%**（v4-pro，"normal for agent workloads — the same context gets resent constantly"），并指出**会话首笔请求约占整账单 52%**（固定 8,246 miss tok，大头是 tool schemas）。[#3304](https://github.com/deepseek-ai/deepseek-harness/discussions/3304)：反例——前缀不稳（每次全量 30 个 tool schema、模式切换）时 **cached_tokens 恒为 0**。直接针对"压缩调用命中率/压缩后首笔 miss"的公开实测数字**未获取到**，以上为间接口径。

**启示**：活文档 §4.1 的缓存数学（旧会话末笔 ~100% hit、新前缀一次性 miss）与 DSH 官方陈述完全一致，且有 98% 实测佐证；额外注意 #3304 的反例——**tools/schema 顺序必须跨会话冻结**，这正是 project_header 逐字沿用策略的价值。

## 5. Claude Code /compact 对照

官方文档（[code.claude.com/docs/en/costs](https://code.claude.com/docs/en/costs)）：auto-compact 在"approaching context limits"时摘要旧历史（社区口径 ~95% 容量，[经 badlogic gist 转引](https://gist.github.com/badlogic/cd2ef65b0697c4dbe2d13fbecb0a0a5f)）；`/compact [instructions]` 支持自定义保留方向（如 "Focus on code samples"），也可写进 CLAUDE.md 常设；compaction 在账务里记为 "expected rebuild" 而非 cache miss；Pro/Max 有 "resume from a summary"（大 会话恢复不携全史）。保留内容（社区提取的 prompt）：what was accomplished / current work in progress / files involved / next steps / key user requests or constraints——**决策、未完成事项、文件状态**；丢弃近程原文（无 DSH 式 verbatim tail 的公开证据，⌜保留最近 N 条消息⌟一说未在官方源获证）。社区报告痛点：auto-compact 在任务中途触发会 "go off the rails"，多次压缩累积失真。

**与 DSH 的差异**：① Claude Code 面向"开新会话接续"，DSH 是同会话 in-place replace；② Claude Code 允许用户定制保留方向，DSH 模板固定、不接受参数（`/compact (no arguments)`）；③ DSH 强制 verbatim 尾巴 + 字节级前缀对齐，Claude Code 无对应公开机制。④ 两者摘要小节高度同源（DSH 的 8 节明显承自 Claude Code 系 8-9 节模板，去掉 "Problem Solving/All user messages"、加 "Critical Context"）。

## 6. 各家 harness 压缩对照表

| Harness | 触发 | 保留 | 丢弃 | 摘要请求构造 | 产物接回 |
|---|---|---|---|---|---|
| **DSH**（compaction-basic） | 80% 窗口（请求前检查）+ overflow 兜底 + 手动 | 16% 窗口 verbatim 尾巴；摘要 8 节 | 被替换的旧历史 | **逐字节重放 + 尾部追加指令**（同模型保缓存） | 同会话 replace 成 user checkpoint，新前缀继续 |
| Claude Code | ~95% 容量（社区口径）+ 手动 | 决策/未完成/文件/下一步/约束 | 近程原文（无公开 tail 机制） | 全史+指令；支持自定义方向 | 摘要作新会话初始上下文 |
| Codex CLI | `model_auto_compact_token_limit`（95% 有效窗口，180k/244k 档） | 摘要 + 最近 ~20k tok 用户消息 | 更早历史 | 全史+handoff prompt | 新史 = 初始上下文 + 近期消息 + summary，带 summary_prefix |
| OpenCode | `context_limit − output_limit` 溢出 | 摘要；prune 另行保近 40k tok 工具输出 | 40k 外旧工具输出 | 全史+compaction.txt | 标记 "summary" 的 assistant 消息 |
| OpenHands（LLMSummarizingCondenser） | 事件数 >240 / token 超限 / 显式请求 | `keep_first: 2`（开头 2 事件永不压）；摘要含 USER_CONTEXT/TASK_TRACKING/TASK IDs/COMPLETED/PENDING/CODE_STATE | forgotten events | 独立 LLM（非主会话前缀重放，无缓存对齐） | Condensation 事件替换 forgotten 区间 |
| Gemini CLI | 50% token 限额 | 最近 30% 历史；近期工具输出 50k tok 预算内全保，超出的截尾 30 行存临时文件 | 更旧历史+超预算工具输出 | 全史+`<state_snapshot>` 指令（flash-lite 别名模型）+**二次"Probe"自校验** | `[user: snapshot, model: "Got it...", 保留尾巴]`，膨胀即放弃 |
| Amp | **无自动压缩**（已移除） | `/handoff <goal>`：按目标抽取相关信息 + 相关文件清单 | 其余全部 | 副模型按 goal 分析全 thread | 生成可编辑 prompt 草稿开**全新 thread** |

来源：[OpenHands llm_summarizing_condenser.py](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py) 及 [summarizing_prompt.j2](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/context/condenser/prompts/summarizing_prompt.j2)｜[Gemini chatCompressionService.ts](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/context/chatCompressionService.ts)｜[Amp handoff 公告](https://ampcode.com/news/handoff)｜Codex/OpenCode/Claude Code 细节转引自 [badlogic gist](https://gist.github.com/badlogic/cd2ef65b0697c4dbe2d13fbecb0a0a5f)（其标注了各仓库内文件路径）。

**启示**：业谱系两极——DSH/Codex/Gemini CLI 都演化为"摘要 + **保留 verbatim 近程尾巴**"，Amp 干脆放弃压缩改为"目标驱动抽走到新 thread"；小说的"近全远压 + 卷界开新会话"正是两者中间态，方向与主流一致。

## 7. 对活文档 §4.3「接力压缩」设计的评估

**与 DSH 的同**：① 摘要调用 = 旧会话前缀扩展（~100% hit）——与 DSH 逐字节重放一致；② "从不修改已发送的 token"——DSH 靠 append-only 日志 + surface 投影实现，你的方案靠"压缩只在会话边界"实现，约束等价；③ 产物成新前缀、一次性 miss 后恢复高命中。

**与 DSH 的异（及风险）**：
1. **DSH 同会话 replace，你开新会话**。缓存上你并不吃亏：DeepSeek 缓存按内容前缀匹配、跨请求共享，新会话只要 system 段逐字相同照样命中（呼应 §4/#3304）；且你把产物从"agent 任务 checkpoint"脱钩为"写作交接书"，语境更贴。**但**新会话没有 DSH 的 16% verbatim tail 保护之外的机制——你保留了 49/50 章原文（等价 tail），成立。
2. **输出截断 fail-closed**：DSH 摘要超 `maxTokens` 即整次作废（"incomplete checkpoint" 不落地）。交接书应留 headroom + 生成后校验完整性（如"⑥未决钩子清单"非空即合格）。
3. **shrink 校验缺失**：DSH 拒绝"摘要不小于被替换内容"（"summary is not smaller than the shadowed content"）。你的方案应加同款保险丝：交接书+状态块 > 卷历史一定比例即报警，防"越压越肥"。
4. **重复注入**：DSH issue [#5766](https://github.com/deepseek-ai/deepseek-harness/issues/5766) 指出摘要会复述本就逐字重注入的 AGENTS.md/技能目录。你的交接书模板**不要包含** project_header/写作指令库已覆盖的内容（世界观、文风总纲），只写"本卷增量"。
5. **CJK 计量**：DSH 自认 token meter 的 4 字符/token 启发式"underprices CJK text"——中文小说的触发器（读税监测、1M 硬限）必须用 API 返回的真实 usage 记账，不能用字符估算（[#5632](https://github.com/deepseek-ai/deepseek-harness/issues/5632) 即非拉丁文本计量漂移 bug）。
6. **多次摘要退化**：Claude Code/Amp 社区均报 summary-on-summary 累积失真；你的一卷一压 + 台账零丢失锚点是正确对冲——**交接书只做叙事记忆，精确事实永远以台账为准**（§4.3 第 3 条），这条是设计中优于所有被研 harness 的点，保留。

## 8. 可直接抄进小说程序的 3 条实现要点

1. **摘要调用 = 逐字节重放 + 追加独立指令消息**：复用旧会话完整 messages（含 system/tools 路由参数）原样重发，压缩指令作为**最后一条新 user message**（不拼进旧消息）；必须同 provider/model 路由，并记录该笔的 usage（prompt_cache_hit_tokens 应 ≈ 全部输入 − 指令长度）作为验证断言。
2. **产物落地三校验 + fail-open**：交接书生成后校验 ①比源内容小（shrink）②关键小节非空（防截断）③不含常驻注入内容（防重复）；任一失败→旧会话继续写下一卷（不压缩），与 DSH "summarization failure preserves the latest durable surface" 同款兜底。
3. **双层触发 + verbatim 尾巴冻结**：主触发在每章清算时用真实 usage 检查（读税/1M 硬限前 100k），兜底触发 = 硬限已破时保留 0 强压一次 + 限重试 1 次；新会话前缀中 49-50 章原文、project_header、写作指令库**逐字节冻结**（跨卷也不改措辞），这是 #3304（前缀不稳→0 命中）的直接防御。

---

## 引用列表

**DSH 官方（源码/文档，master 分支）**
- 仓库：https://github.com/deepseek-ai/deepseek-harness
- summarizer.ts（指令全文/前缀缓存注释）：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/summarizer.ts
- config.ts（阈值/保留/重试默认值）：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/config.ts
- region.ts（replace 事务/工具对完整性/shrink 校验）：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/region.ts
- index.ts（自动触发/溢出恢复流程）：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/index.ts
- compaction-basic README（KV Cache effect / 指令全文 / 限制）：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.md
- 子系统参考（compaction/* 事件/锁/剪枝）：https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/compaction.md
- command-compact README（/compact 行为）：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/command-compact/README.md
- 讨论 #2064（98.09% hit 实测）：https://github.com/deepseek-ai/deepseek-harness/discussions/2064
- 讨论 #3304（前缀不稳→0 命中）：https://github.com/deepseek-ai/deepseek-harness/discussions/3304
- issues：#5766（摘要复述常驻注入）、#5733（输出预算无 headroom）、#5650（英文 checkpoint/无用户控制）、#5632（非拉丁计量漂移）
- 未获取到：压缩调用命中率/压缩后首笔 miss 的直接社区实测数字。

**对照 harness**
- Claude Code 官方（costs/cache）：https://code.claude.com/docs/en/costs
- 跨 harness 压缩研究（badlogic gist，含 Claude Code/Codex/OpenCode prompt 与文件路径）：https://gist.github.com/badlogic/cd2ef65b0697c4dbe2d13fbecb0a0a5f
- OpenHands LLMSummarizingCondenser：https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py
- OpenHands 摘要 prompt：https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/context/condenser/prompts/summarizing_prompt.j2
- Gemini CLI 压缩服务：https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/context/chatCompressionService.ts
- Amp handoff 公告：https://ampcode.com/news/handoff ；Amp 上下文管理指南：https://ampcode.com/guides/context-management
