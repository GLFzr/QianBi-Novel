# Agent Harness「长上下文质量劣化」外部解法研究

- 撰写日期：2026-09-29（为千笔质量提升计划准备的外部解法研究）
- 研究范围：其他 agent harness（Claude Code / Cursor / Anthropic 官方工程实践）、记忆框架（Letta/MemGPT、mem0）、长篇生成学术系统（RE3 / DOC / Agents' Room / RecurrentGPT / StoryWriter / NstAgent）、商业写作产品（Sudowrite / NovelCrafter / AI Dungeon）、改写闸与风格正则化解码。
- 对齐的故障编号（来自 2026-10-02 质量深测）：
  - **F1 质量随会话变长单调劣化**：7 章盲评从 5.5 跌到 3.8；后期章单发输入 179k token / 192k 窗口。
  - **F2 同题对照净损伤**：one-shot 新上下文 7.9 分 vs 流水线同章 5.4 分（同细纲同模型）。
  - **F3 改写环毁稿**：扩写堆料（3-gram 跨章复现 0.44 vs 真人 0.048）；压缩环 2572→45 字；去味环 2239→35 字（后两者仅"拒绝采纳"式长度守卫）。
  - **F4 AI 味定量超基线**：陈词 2.8x、「不是…而是…」2.08x、句长方差为真人 22%、段间衔接词 0.2x、对话占比 0.48x。
  - **F5 钩子工程失效**：5/7 章收在同一钩子型；上一章钩子被下一章应答率低。

**证据分级标记**（全文沿用）：
- **[实证]**：有对照实验/同行评审论文支持；
- **[官方文档]**：厂商官方文档或工程博客，属工程实践共识但非对照实验；
- **[访谈/社区]**：访谈、社区实测、二手报道，方向可信但数字未经验证；
- **[坊间]**：广泛流传但缺乏系统证据。

---

## 0. 总览：外部世界的三条主线

Anthropic 官方工程博客《Effective context engineering for AI agents》（2025-09-29，
https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents）把长程 agent 的上下文对策归为三族，
与本报告的六个机制一一对应，可当作总纲：

1. **Compaction（压缩）**——历史太长时摘要化旧内容，保住最近若干轮原文；
2. **Structured note-taking / agentic memory（结构化记忆）**——把"从上下文里学到的状态"写成外部笔记/记忆块，代替逐字历史；
3. **Sub-agent architectures（子代理隔离）**——派生干净上下文的子代理去做重活，只回传结论。

同一博客还明确承认：「随着会话增长，响应质量会下降」（response quality degrades as a conversation grows）——
这是 F1/F2 的官方级定性确认：**上下文越长本身就是一个质量风险，而不是只有"超窗"才是问题**。

学术侧最直接的对口证据是微软研究院的 **「LLMs Get Lost in Multi-Turn Conversation」**（Laban et al., arXiv:2505.06120，
ICLR 2026 Outstanding Paper）：把同一个单轮任务拆成多轮对话（信息完全等价、末轮包含全部所需信息），
模型平均劣化最高 **39%**；劣化主要来自"不可靠性上升"而非"能力下降"。
这为我们的 F2（one-shot 7.9 vs 流水线 5.4）提供了机制解释：**多轮累积的中间产物（改写稿、审校意见、全文引用）在干扰模型对当前任务指令的遵循**。

另一块地基是 **RULER**（NVIDIA, arXiv:2404.06654）与 **Lost in the Middle**（Liu et al., arXiv:2307.03172）：
前者证明 17 个长上下文模型的"有效上下文"显著短于标称窗口（大海捞针近乎满分，复杂任务照样崩）；
后者证明关键信息位于上下文中段时性能呈 U 形下跌。**推论：179k/192k 的填充率下，细纲与文风约束（往往位于 prompt 中段）正是最容易被"淹没"的东西。**

---

## 1. 机制一：上下文压缩 / 摘要（compaction）

### 1.1 原理：做什么

- **Claude Code auto-compact** [官方文档]（https://code.claude.com/docs/en/context-window）：
  会话逼近窗口上限时自动触发，动作是「摘要旧会话 + 重读关键文件恢复工作集 + 恢复任务清单（todo）」，
  然后以「压缩摘要 + 最近一小段原文尾巴」继续会话。API 侧（2025 年底起）提供两种压缩
  （https://platform.claude.com/docs/en/build-with-claude/compaction）：
  - **on-demand compaction**：一次请求里带 `context-management` 参数，让 API 把旧消息摘要化；
  - **compaction at a token threshold**：设定 token 阈值，超过即自动压缩。
  - 保留策略明确为「**最近 N 条消息逐字保留，摘要只覆盖更早的消息**」；官方 Cookbook 示范了「压缩时保住最近 3 条消息原文 + system prompt + 工具定义」的模式（https://platform.claude.com/cookbook/tool-use-automatic-context-compaction）。
- **Cursor** [访谈]：Sequoia 对 Cursor 团队的访谈确认其长会话策略就是 compaction——
  「模型上下文窗口有限，最终总会达到上限，我们在 Cursor 的解法是放入 compaction：把会话内容摘要后用摘要重新初始化对话」
  （https://sequoiacap.com/podcast/how-cursor-trained-composer-on-fireworks-distributed-infrastructure-for-high-performance-rl）。
- **通用 conversation summarization 的"保/丢"清单**（综合 MemGPT 论文 arXiv:2310.08560 与上述官方实践）：
  - **保**：任务目标与硬约束（字数、文风规则、禁用项）、关键事实（人物/设定/伏笔账本）、决策及理由、最近 N 轮原文；
  - **丢**：逐字的工具中间输出、被改写前的旧稿全文、已被推翻的方案、冗长引文。
- **MemGPT 的递归摘要** [实证/系统]：消息历史超限时对最旧消息做摘要折叠，全文仍存入可检索的 recall memory——「上下文里放摘要、原文进外存」。

### 1.2 触发时机

- Claude Code：接近窗口上限自动触发（社区实测约在 92–95% 填充率 [社区]，官方未公布精确值；
  GitHub issue #34925 还在要求把阈值做成可配置，说明当前不可调 [社区]）。
- Claude API：用户自设 token 阈值；官方建议"在质量开始下降前"主动压缩而不是等逼近上限。
- MemGPT：每步生成前检查上下文占用，超阈值即触发摘要换页。

### 1.3 有效性证据

- [实证] LLMs Get Lost in Multi-Turn Conversation（arXiv:2505.06120）：多轮化平均最高 -39%；
  且"末轮信息完整"也救不回来——说明**压缩掉中间轮次的信息损失，通常小于留着中间轮次的干扰损失**（这是 compaction 的因果有效性来源）。
- [实证] Lost in the Middle（arXiv:2307.03172）/ RULER（arXiv:2404.06654）：长而不精的上下文主动伤害任务表现，
  因此"把 179k 压成 20k 的目标+账本+最近原文"不只是省 token，是直接提高关键指令的相对显著性。
- [官方文档] Anthropic 把 compaction 列为长程 agent 三大对策之一，且在 API 层产品化——工程界已把它当默认解。
- **局限**：摘要有损。压缩后 Claude Code 常见"忘记早前决定"的抱怨 [社区]；对**强一致性依赖**的任务（伏笔、时间线），
  纯摘要不保险，需要与机制三（结构化记忆）配合。

### 1.4 对我们五类故障的映射

- **F1（单调劣化）**：直接对症。因果链：劣化曲线与 prompt 体积强相关 → LLMs Get Lost 证明多轮累积干扰指令遵循 →
  压缩把"逐字历史"换成"目标+账本+最近原文"，输入体积不随章数增长。**预期幅度：把后期章输入从 179k 压到 <40k，
  按我们的同题对照（7.9 vs 5.4，差 2.5 分）可视为该机制的理论上限收益。**
- **F2（同题对照）**：部分对症——但注意 one-shot 赢的不只是上下文短，还有"没有多轮改写链"（见机制五）。
- **F3/F4/F5**：不对症或仅间接（压缩不能阻止改写环毁稿，也不能改变解码侧的句式聚集）。

### 1.5 移植方式与代价

- 方式：把「卷会话」的跨章累积从"逐字拼接"改为"每章落账时产出结构化卷摘要（情节事实/人物状态/伏笔/文风偏差记录）+ 最近 1–2 章原文"。
- 代价：低-中。每次压缩多一次 LLM 调用；需要手工设计"保什么"的 schema（可参考 Sudowrite Story Bible 的分节，见机制四）。
- 风险：摘要器失真 → 关键事实必须进结构化账本（机制三）而不是散文摘要。

---

## 2. 机制二：子代理隔离（fresh-context subagent）

### 2.1 原理：做什么

- **Claude Code subagents** [官方文档]（https://code.claude.com/docs/en/sub-agents）：
  主代理把子任务派给带独立上下文窗口的子代理，子代理只回传结论摘要；官方文档明确其目的之一是"context savings"
  （子代理在自己的窗口里干脏活，主窗口不被中间产物污染）。Claude Code Academy 课程同样表述为
  「子代理与主代理并行、拥有完全独立的上下文窗口、只返回摘要」（https://academy.claude.com/courses/claude-code-101/context-management）。
- **Anthropic 工程博客** [官方文档]：sub-agent 架构被列为长程三对策之三；要点是"每个子代理从干净状态出发，
  只拿到完成该子任务所需的最小输入，返回压缩后的结论"。
- **长篇生成学术版的同构做法**：
  - **Agents' Room**（Huot et al., Google DeepMind, arXiv:2410.02603, ICLR 2025）：orchestrator（**代码而非 LLM**）持有一个共享 scratchpad，
    每次只把"该 agent 需要的视图"格式化进它的独立 prompt；planning agents（[conflict]/[character]/[setting]/[plot]）与
    writing agents（[exposition]/[rising action]/[climax]/[falling action]/[resolution]）都是**独立的单次 LLM 调用**，
    各自上下文 1k–8k token，从不累积对话。
  - **StoryWriter**（清华 THU-KEG, arXiv:2506.16445, CIKM 2025）：outline agent → planning agent → writing agent 三段式，
    writing agent「基于当前事件**动态压缩**故事历史」再生成新情节——同样是"每章/每事件一次受控生成"，而非滚雪球会话。

### 2.2 触发时机

- 按**任务边界**触发，不按 token 阈值触发：每当一个可完整定义的子任务（"写第 N 章草稿""审校这段""起 3 个候选钩子"）出现，
  就派子代理。边界划法（Claude Code 官方建议 + Agents' Room 实践）：
  1) 子任务的输入能被一次性完整描述（细纲+账本+最近原文）；2) 输出能以"结论"形式回传；3) 不需要主链路的中间废稿。

### 2.3 有效性证据

- [实证] Agents' Room 人工评估：故事比端到端（E2E）基线**长 2 倍**且在所有维度被人类评委更多偏好；
  零样本 Plan/Write/Plan+Write 对 E2E 的胜率为 42%/43%/45%，微调后 55%/48%/52%（对人类写作仍落后：Plan+Write 41% vs 人类 59%）。
  **注意反证**：AR 长文的 trigram 段内复现率（Intra 44–47）显著高于 E2E（28）——分块生成天然引入重复，**必须配重复检测闸**（映射到 F3 的 0.44 复现率，见机制五）。
- [实证] StoryWriter：人工+自动评估均"显著优于现有长篇基线"，均长 8000 词、产出 6000 篇长故事数据集。
- [实证] 我们自己的 F2 数据就是本机制最干净的 A/B：同题同模型，新起上下文 7.9 vs 流水线 5.4——
  「fresh context + 一次性受控输入」与「长会话多轮链」的 2.5 分差距。
- [官方文档] Claude Code 把 subagent 当作 context 管理一等公民（官方文档含上下文节省的可视化案例）。

### 2.4 对我们五类故障的映射

- **F1（单调劣化）**：最强对症。因果：劣化来自历史累积 → 子代理输入只含"当章所需" → 输入体积与章号解耦，劣化曲线被"斩平根"。
  **预期幅度：上限即 F2 差距（+2.5 分）；Agents' Room/StoryWriter 证明分块生成还能同时变长变好。**
- **F2（同题对照）**：直接对症——把流水线每一步重构成"one-shot 式受控生成"，就是让流水线章逼近 7.9 分那条路。
- **F3（毁稿）**：间接对症——改写环在干净上下文+显式指令下更可控，但毁稿主因是"无客观采纳标准"（机制五）。
- **F4/F5**：间接（子代理可以让"钩子设计""风格检查"各自成为专职 agent，但需配合四/六）。

### 2.5 移植方式与代价

- 方式：**废除"卷会话逐字累积"作为写作上下文的来源**。每章生成 = 新开上下文，组装固定配方：
  全书/卷级 bible（结构化）+ 本章细纲 + 前情账本 + 上一章结尾原文（保钩子衔接）+ 文风规则。orchestrator 用代码（Python）而非 LLM 担任（Agents' Room 的做法）。
- 代价：中。需要定义"章间传递的状态 schema"（这正是机制三的工作）；子代理间不能共享隐性上下文，漏项需显式化。
- 风险：分块生成的重复问题（Agents' Room 的 44–47 trigram 教训）→ 必须与机制五的重复闸同装。

---

## 3. 机制三：记忆分层（external memory / structured state）

### 3.1 原理：做什么

- **MemGPT / Letta** [实证/官方文档]（Packer et al., arXiv:2310.08560；https://www.letta.com/blog/memory-blocks）：
  把上下文当 RAM、外部存储当磁盘分级管理：
  - **core memory（常驻上下文、可编辑）**：persona/human/自定义 memory blocks，agent 用 `core_memory_append/replace` 工具**原地改写**；
  - **archival memory（上下文外、无限量）**：向量库，按需 `archival_memory_search` 检索；
  - **recall memory**：全文对话外存可检索；超限时递归摘要。
  - 2025 年新增 **sleep-time agents**（https://www.letta.com/blog/sleep-time-compute）：
    后台代理在"空闲期"重读历史、重写记忆块，把主代理上下文维持在"高信噪比"状态。
- **mem0** [实证，有争议]（arXiv:2504.19413）：抽取-固化-检索式记忆层。宣称 LOCOMO 上 LLM-as-Judge 比 OpenAI 记忆高 26%（相对），
  且准确率约为全量上下文基线的 2 倍、token 成本只有其零头（官方页 https://mem0.ai/research 称 92.5 分 / 3–4 倍 token 节省）。
  **争议标注**：Zep 等竞争者公开质疑其基准口径 [社区]；另一项分布式多智能体研究（arXiv:2601.07978）发现 Mem0/RAG/全上下文在 77–81% 区间聚类、差距缩小。**结论：方向成立（少量精确记忆 ≥ 全量历史），幅度有水分。**
- **Generative Agents** [实证]（Park et al., 2023, arXiv:2304.03442）：记忆流 + 近因/重要度/相关度三因子检索 + 周期性 reflection——
  「结构化状态+检索」路线的开山证据（25 agent 小镇涌现行为依赖此设计，全文历史从不进上下文）。
- **长篇专用状态跟踪**：
  - **RecurrentGPT** [实证]（arXiv:2305.13304）：每步维护「short-term memory（最近文本+更早摘要）+ long-term memory（盘上可检索摘要）+ intrinsic plan（后续段落计划）」，模拟 LSTM 的文本化状态传递，生成任意长文。
  - **NstAgent** [实证但很新]（arXiv:2609.35759，2026-09）：LLM 显式维护"结构化叙事状态（人物/已发生事件/未来要求）"，
    声称 1 万–10 万词范围内一致性与写作质量**均无明显随长度退化**——这是对 F1 最正面的学术结果，但发表极新、尚待同行检验。
  - **StoryWriter / Sudowrite / NovelCrafter / AI Dungeon 的产品化形态**（详见机制四）。

### 3.2 触发时机

- 写入：章落账时（新事实出现即增量更新账本）；Letta 式 sleep-time 则可在批次空闲时后台整理。
- 读取：**每次组装生成上下文时**（不是"忘了才去查"）；AI Dungeon/NovelCrafter 用**关键词触发**决定哪条记忆进上下文（见 4.3/4.4）。

### 3.3 有效性证据

- [实证] mem0（LOCOMO 26% 相对提升；幅度有争议，见上）；
- [实证] Generative Agents（检索式记忆流支撑长程一致行为）；
- [实证] RecurrentGPT（人类评估长文优于直接长生成基线）；
- [实证·新] NstAgent（10 万词无显著退化）；
- [实证] RULER 的反面证据：全上下文在长历史下检索/聚合任务崩溃，等价支持"不要塞全量历史"；
- [官方文档] Letta 商业化多年、Claude Code 的 CLAUDE.md（项目级常驻指令）是 core memory 的极简形态。

### 3.4 对我们五类故障的映射

- **F1**：对症（与机制一/二同向）。因果：状态账本把"跨章需要记住的东西"变成常驻小体量结构化块，取代逐字全文。
- **F5（钩子/伏笔）**：**这是本机制独占对症的故障**。钩子应答率低的本质是"上一章埋的钩子没有进入下一章的生成上下文或大纲约束"——
  一个显式「钩子/伏笔账本」（类型、埋设章、应答期限、应答状态）+ 章级 planning 时强制检查账本，是因果直接的修法
  （NovelCrafter 的 beat 摘要 + AI Dungeon Story Cards 同思路；学术侧 = NstAgent 的 future requirements 字段）。
- **F4（AI 味）**：间接——账本里可以放"本章已用钩子类型/已高频句式黑名单"，但需要配合机制六的检测器。
- **F3**：不对症。

### 3.5 移植方式与代价

- 方式：三类块——(a) 设定块（人物/世界观，Sudowrite Story Bible 式）；(b) 进度块（每章落账的结构化摘要：事件、状态变化、钩子账本）；
  (c) 风格块（文风规则+禁用句式清单，常驻）。检索用"关键词触发"（AI Dungeon/NovelCrafter 式）即可起步，向量检索是二期。
- 代价：中。主要是 schema 设计 + 落账摘要的稳定性；不需要外部数据库（本地 JSON/SQLite 即可，契合 PySide6 本地架构）。

---

## 4. 机制四：长篇 / 多章生成系统的上下文设计

### 4.1 RE3：plan → draft → reprompt → revise [实证]

（Yang et al., EMNLP 2022, arXiv:2210.06774；代码 https://github.com/yangkevin2/emnlp22-re3-story-generation）
- 做什么：先出大纲再逐段写；**每次续写都用 reprompting 重组"小而准"的上下文**（大纲+人物+最近情节），而不是滚雪球；
  revise 环节只做**过滤式修订**：矛盾检测、冗余检测、重复检测（符号/规则检测器触发才改）。
- 对我们的映射：reprompting = 机制二的输入配方；过滤式修订 = 机制五的闸门原型（F3）。

### 4.2 DOC：详细大纲 + 大纲动态修订 [实证]

（Yang et al., ACL 2023, arXiv:2212.10077）
- 做什么：detailed outliner 生成层级细纲（把创作负担前移到规划），controller 保证段落与细纲对齐；
  **写作中发现大纲可动态修订**——大纲是活文档而非一次性产物。
- 证据：人工评估中 plot coherence 比 RE3 基线 **+22.5% 绝对值**，outline relevance +28.2%、interestingness +20.7%（论文宣称口径）。
- 对我们的映射：F5（钩子在大纲层规划与检查）+ F1（正文生成只需要"细纲+局部上下文"，全文不进 prompt）。
- 注意：DOC/RE3 的语料是英短篇（数千词级），向中文长篇网文外推需自行验证。

### 4.3 Agents' Room：角色分工 + orchestrator 管上下文 [实证]

（见 2.1/2.3。补充）其 scratchpad 设计（"每个 agent 只看到自己需要的视图"）是我们把"上下文组装"从 LLM 手里收回到 Python 代码手里的直接范本。

### 4.4 StoryWriter / NstAgent / RecurrentGPT：状态化长篇 [实证]

- StoryWriter（arXiv:2506.16445）：事件级大纲（含事件-事件关系）→ 每章 planning → writing agent 按当前事件动态压缩历史。均长 8000 词、质量显著超基线。
- NstAgent（arXiv:2601.07978 同团队线；见 3.1）：10 万词无显著退化（新，待检验）。
- RecurrentGPT（arXiv:2305.13304）：文本化 LSTM 状态（short-term/long-term/plan 三件套），任意长生成。

### 4.5 商业产品：有界上下文 + 关键词触发的 codex [官方文档]

- **Sudowrite Story Bible**（https://docs.sudowrite.com/.../what-is-story-bible；模板博客 https://sudowrite.com/blog/story-bible-template）：
  链式生成 braindump→synopsis→genre/style→characters→world→outline→scenes（**每层以上一层为上下文**，创作负担逐层前移）；
  写作时每次生成都注入"完整 Story Bible + 最多 **20,000 词**前文 + 最多 **25 个链接章节**"——
  **前文硬上限 2 万词就是他们的 compaction 边界**（官方未公布溢出策略 [官方文档]）。
- **NovelCrafter Codex**（https://www.novelcrafter.com/help/faq/ai-and-prompting/codex-context-in-prompting）：
  codex 条目带关键词/别名（Tracking 页），**beat/聊天/前文中出现 mention 的条目才注入**；场景可手动 +Codex；章/幕/书摘要分层存放。
- **AI Dungeon**（https://help.aidungeon.com/understanding-settings）：
  Memory（常驻，置于最远端）+ Author's Note（常驻，插在距末尾约 3 个动作处，用于近期文风/节奏引导）+
  Story Cards/World Info（**关键词触发条件注入**）。社区明确警告：pinned/触发信息塞太多会挤占正文空间、污染上下文 [社区]。
- 共同模式（三家独立趋同，属强工程共识）：**常驻块（小）+ 条件触发块（关键词）+ 最近原文（硬上限）**，从不把"全书全文"当上下文。

### 4.6 长度控制：LongWriter / AgentWrite [实证]

（arXiv:2408.16370）先让模型给每段规划**目标字数**，再逐段按预算写——把"输出长度"变成计划约束。
映射：F3 中"压缩环 2572→45 字"这类事故的根治法不是事后守卫，而是**生成前显式字数预算**。

### 4.7 对我们五类故障的映射与移植代价

- F1/F5 主要受益（细纲前移 + 钩子在大纲层规划）；F3 受益于 AgentWrite 式字数预算。
- 代价：中。需要一次"上下文组装器"重构：从"会话历史即上下文"改为"bible+账本+细纲+有限原文"的显式配方（Sudowrite 式）。

---

## 5. 机制五：改写/修订环的质量闸（draft–critique–revise 的采纳条件）

### 5.1 原理：外部信号 + 有条件采纳

- **Self-Refine** [实证]（Madaan et al., NeurIPS 2023, arXiv:2303.17651）：同一 LLM 自反馈再改，多数任务 +5–20%（对话质量 +20% 绝对），
  **但前提是反馈"信息量足"**；论文与 OpenReview 讨论都承认反馈差时循环会漂移甚至变差。
- **Cannot Self-Correct Reasoning Yet** [实证]（Huang et al., ICLR 2024, arXiv:2310.01798）：**没有外部反馈的内在自我修正会降低表现**
  （模型会把自己的错误答案"改得更自信"）。**这是 F3 的因果诊断**：我们的扩写/压缩/去味环是"无外部信号的自我改写"，
  模型在干净上下文里面对"请改得更好"这种无锚指令时，塌缩到字数剧变（45 字/35 字）或堆料复写（0.44）都是该论文预测内的失败形态。
- **RE3 的过滤式修订** [实证]：修订只由**检测器触发**（矛盾/冗余/重复检测命中才动原文），否则保留原稿——"默认不改"。
- **DOC 的 controller** [实证]：以"段落-细纲对齐"为外部锚，保证改写不跑偏大纲。
- **LLM-as-Judge** [实证]（arXiv:2306.05685）：LLM 评委与人类一致性可超 80%，但有位置偏差/长度偏好——
  用于"采纳闸"时要用成对比较（A/B 原稿 vs 改稿）而非打分，且要显式惩罚长度突变。

### 5.2 触发时机与闸门设计（外部实践汇总）

1. **改写前**：给改写环**外部锚**——细纲段落、目标字数预算（AgentWrite 式）、改动白名单（"只做 X 类修改"）。
2. **采纳时**：成对评审（原稿 vs 改稿，同上下文盲评）+ 机器指标闸（长度偏差、3-gram 复现率、句长方差、对话占比——我们已有这批指标！）
   ——**先验上：机器指标闸零成本且确定性强，应做第一道闸；LLM 盲评做第二道。**
3. **不通过时**：回退原稿（rollback）而非"再改一轮"——Self-Refine 证据表明无信号再改更糟；
   RE3 的"默认不改"是同一哲学。
4. **粒度**：段落级采纳优于全稿采纳（ Agents' Room 44–47 trigram 的教训：块级合并必须配重复检测）。

### 5.3 对我们五类故障的映射

- **F3（毁稿）**：最强对症、且是唯一能解释 2572→45 字这种灾变的机制级解释（无外部信号的自我修正）。
  **预期幅度：长度/复现率类指标可用机器闸压到阈值以下（工程上接近 100% 拦截）；文字质量提升幅度取决于评审 prompt，无公开数字可引（不确定）。**
- **F2（净损伤）**：重要组成——2.5 分差距里"多轮改写链"的份额由本机制回收。
- **F4**：第二道闸可直接复用 AI 味指标（陈词计数/句式计数）作为采纳条件。
- F1/F5：不对症（但闸门防止"上下文修好后改写环再毁稿"）。

### 5.4 移植代价

- 低-中：我们不缺指标（深测已产出全套量化指标），缺的是把指标从"评测报告"变成"采纳条件"的接线；
  LLM 成对盲评为每次改写多 1 次调用。现有"长度守卫（拒绝采纳）"升级路径清晰：
  **拒绝 → 回退 + 段落级局部重试（带外部锚） → 机器指标 + 成对盲评双闸**。

---

## 6. 机制六：风格正则化（防句式单一 / 陈词堆积）

### 6.1 做什么（按证据强度排序）

1. **解码参数** [实证]：重复惩罚/频率惩罚/_presence 惩罚的权衡已被系统研究——
   Penalty Decoding（EMNLP 2023, https://aclanthology.org/2023.emnlp-main.78.pdf）指出 beam search 的自我强化效应（self-reinforcement）导致重复，
   带遗忘机制的惩罚解码可在不伤连贯下抑制；「Repeat Curse」综述（arXiv:2504.14218）讨论对比搜索（contrastive search）兼顾多样与连贯。
   **注意双刃**：高重复惩罚会把概率质量推向"安全但更陈词"的表达 [社区/初步]；Wikipedia "Signs of AI writing" 也记录了"过度回避重复本身可被检测"（https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing）[坊间但广泛]。
2. **多样性保持的偏好对齐** [实证]：Weaver（arXiv:2401.17268）指出**标准 DPO 会压低输出多样性**，
   提出每条指令配多个高质量样本的 Revised-DPO（RPO），其创作模型在写作基准上超 GPT-4 类通用模型。
   移植意义：若我们微调，选多样性保持的目标；若只调 API，则靠解码端+闸门。
3. **持续多样化解码** [实证但很新]：Recoding-Decoding（arXiv:2603.19519）宣称可产出持续不重复的创意输出（2026 年新工作，待检验）。
4. **风格指令固化 + 风格块常驻** [官方文档]：Sudowrite 把 genre/style 做成 Story Bible 的固化层、每次生成都注入；
   AI Dungeon 的 Author's Note 插在**贴近生成点**（距末尾约 3 个动作）——位置本身就是效果参数（Lost in the Middle 的直接应用：文风指令放中段=淹没）。
5. **陈词/句式黑名单** [初步]：「13,000 个 AI 高频短语」研究（新闻报道级 https://www.newsbytesapp.com/...，原始论文待核）
   给出英文"AI tells"；中文侧（「不是…而是…」等）目前主要是社区清单 [坊间]，
   但**我们自己的定量基线（2.8x/2.08x）就是最可靠的中文清单来源**——可直接转为生成时黑名单+闸门特征。

### 6.2 触发时机

- 解码参数/风格块：每次生成（常驻）；黑名单与句式约束：进 system prompt + 进改写闸；
- 段落级 rerank：候选生成 N 版按"句长方差/对话占比/衔接词密度"打分选优——**无公开对照证据，标为合理推断而非实证**（唯一相关证据是 best-of-N 在通用基准的增益，不能直接外推到文风）。

### 6.3 对我们五类故障的映射

- **F4（AI 味）**：主对症。因果拆解：
  - 陈词 2.8x/句式 2.08x → 常驻风格块 + 黑名单 + 解码温度/惩罚调参（低-中成本）；
  - 句长方差 22% → 解码多样性（温度/top-p）+ 可选段落 rerank（无实证，试错项）；
  - 衔接词 0.2x / 对话占比 0.48x → 更像"指令显著性问题"：这两项是**结构指令**，应放进细纲（机制四：每段明确"对话/叙述配比""段间承接方式"），
  而不是靠改写环补救——**去味环本身就是一个高风险自我改写环（F3 已证明会毁稿），风格应在生成时注入，事后改写只做带闸的微调。**
- F1/F2 间接（风格指令从 179k 中段挪到小上下文头部，显著性上升——Lost in the Middle 的直接推论）。

### 6.4 移植代价

- 低（风格块、黑名单、解码参数）→ 中（段落 rerank 需 N 倍生成成本）。无结构性改动，可与所有机制叠加。

---

## 7. 按我们故障排序的解法优先级（含组合关系）

### P0（先做，互相独立、成本最低、直接止血）

| 优先级 | 机制 | 治什么 | 理由与预期幅度 |
|---|---|---|---|
| P0-1 | **机器指标采纳闸 + 回退 + 段落级重试**（机制五） | F3（止血）、F4 部分 | 指标已有；长度/3-gram 闸可接近 100% 拦截毁稿；防止后续任何改写环继续净损伤。根治"无信号自我修正"（arXiv:2310.01798）。 |
| P0-2 | **每章 fresh-context 受控生成**（机制二+四） | F1、F2 | 我们自己的 A/B（7.9 vs 5.4）就是证据；Agents' Room/StoryWriter 证明规模化可行。上限约 +2.5 分（盲评口径）。 |
| P0-3 | **AgentWrite 式字数预算**（机制四.6） | F3（长度事故） | 生成前预算优于事后守卫；LongWriter 实证 10k+ 词可控。 |

### P1（结构性改造，与 P0-2 配套设计、一次落地）

| 优先级 | 机制 | 治什么 | 理由与预期幅度 |
|---|---|---|---|
| P1-1 | **结构化账本（bible + 进度块 + 钩子/伏笔账本）**（机制三） | F5（独占对症）、F1 | NovelCrafter/AI Dungeon/NstAgent 三方趋同；钩子应答率可用"账本检查进章级 planning"因果修复；幅度无公开数字（不确定）。 |
| P1-2 | **卷会话 compaction：落账摘要替代逐字历史**（机制一） | F1（残余）、F2 | LLMs Get Lost 的 39% 劣化主要来自多轮干扰；把后期章输入 179k→<40k。与 P1-1 是同一份 schema 的两面，必须一起做。 |

### P2（增益项、试错项）

| 优先级 | 机制 | 治什么 | 说明 |
|---|---|---|---|
| P2-1 | 风格块常驻 + 陈词/句式黑名单 + 解码参数调优（机制六） | F4 | 低成本；中文黑名单以我们自己的定量基线为准（比任何公开英文清单可靠）。 |
| P2-2 | 结构指令进细纲（对话占比/承接方式/钩子类型配额）（机制四+六） | F4、F5 | 治"衔接词 0.2x/对话 0.48x/钩子 5/7 同型"的生成侧根因。 |
| P2-3 | 段落级 rerank / LLM 成对盲评第二道闸（机制五/六） | F4、F3 | rerank 无公开文风侧证据，标为实验项；成对盲评有 2306.05685 支持但要防长度偏好。 |
| P2-4 | 睡眠期记忆整理 / 向量检索 codex（机制三进阶） | F1、F5 | 二期；关键词触发先用起来（AI Dungeon 教训：触发条目塞太多反污染上下文）。 |

### 组合关系（哪些必须同装）

1. **机制二+三+一 = 一套**：fresh-context 写章（二）必须有章间状态传递（三），卷历史要压缩（一）——三者是同一个"上下文组装器"重构的三个面。只做（一）不做（二）：摘要失真且改写链仍在毁稿；只做（二）不做（三）：跨章一致性（F5）必然崩。
2. **机制五必须先装**：任何改写环（扩写/压缩/去味/审校）在无闸状态下都是负资产（我们 7 章盲评已证；arXiv:2310.01798 已解释）。装闸之后，机制二的干净上下文才能让改写环转正。
3. **机制六与一切正交可叠加**：风格块/黑名单/解码参数不依赖其他机制，随时可上；但注意"去味环"应降级为"带闸微调"，风格注入前移到生成时。
4. **反例警示组合**：Agents' Room 数据显示"分块生成+无重复闸"会把 trigram 复现推高到 44–47（vs 端到端 28）——
   我们扩写环的 0.44 复现率与之同构。**P0-1 的重复闸与 P0-2 的分块生成必须同装，否则 P0-2 可能让 F3 的堆料更糟。**

### 预期总收益（保守口径，均为推断而非承诺）

- F1/F2：P0-2+P1 组合的理论上限 = 我们同题对照的 2.5 分差；实际回收预计过半（推断，无公开对口服数据）。
- F3：机器闸接近完全拦截长度/复现灾变（工程确定性）；文字质量部分靠成对盲评闸（幅度不确定）。
- F4：黑名单+风格块对"陈词 2.8x/句式 2.08x"应能显著压缩（我们指标可回测验证；无公开中文数据）。
- F5：钩子账本+大纲层规划是因果修法，幅度无公开数据（不确定）。

### 不确定与待验证清单

1. Claude Code auto-compact 精确阈值（92–95% 为社区口径，官方未公布）；
2. mem0 的 26%/2x 宣称存在竞争者争议，方向可信、幅度存疑；
3. NstAgent（2609.35759）与 Recoding-Decoding（2603.19519）为 2026 年新工作，未经同行复现；
4. DOC 的 +22.5% 为英文短篇人工评估，向中文网文外推需自测；
5. 段落级 rerank 对文风的效果无对照证据；
6. 中文"AI 味"句式清单（「不是…而是…」等）目前只有我们自己的基线与社区清单，属"自有实证+坊间清单"混合；
7. Sudowrite 20k 词前文上限的溢出策略官方未说明（推测为截断/摘要，未证实）。

---

## 附：主要来源索引

- LLMs Get Lost in Multi-Turn Conversation — https://arxiv.org/abs/2505.06120（ICLR 2026 Outstanding Paper）
- Lost in the Middle — https://arxiv.org/abs/2307.03172；RULER — https://arxiv.org/abs/2404.06654
- Anthropic, Effective context engineering for AI agents — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Claude Code context window / subagents 文档 — https://code.claude.com/docs/en/context-window 、https://code.claude.com/docs/en/sub-agents
- Claude API compaction — https://platform.claude.com/docs/en/build-with-claude/compaction 、.../compaction-threshold；Cookbook — https://platform.claude.com/cookbook/tool-use-automatic-context-compaction
- Cursor compaction（Sequoia 访谈）— https://sequoiacap.com/podcast/how-cursor-trained-composer-on-fireworks-distributed-infrastructure-for-high-performance-rl
- MemGPT — https://arxiv.org/abs/2310.08560；Letta memory blocks / sleep-time — https://www.letta.com/blog/memory-blocks 、https://www.letta.com/blog/sleep-time-compute
- mem0 — https://arxiv.org/abs/2504.19413 、https://mem0.ai/research（争议：arXiv:2601.07978）
- Generative Agents — https://arxiv.org/abs/2304.03442
- RE3 — https://arxiv.org/abs/2210.06774；DOC — https://arxiv.org/abs/2212.10077
- Agents' Room — https://arxiv.org/abs/2410.02603（ICLR 2025）
- RecurrentGPT — https://arxiv.org/abs/2305.13304
- StoryWriter（THU-KEG）— https://arxiv.org/abs/2506.16445（CIKM 2025）；NstAgent — https://arxiv.org/abs/2609.35759
- LongWriter / AgentWrite — https://arxiv.org/abs/2408.16370
- Self-Refine — https://arxiv.org/abs/2303.17651；Cannot Self-Correct — https://arxiv.org/abs/2310.01798；LLM-as-Judge — https://arxiv.org/abs/2306.05685
- Weaver（RPO）— https://arxiv.org/abs/2401.17268
- Penalty Decoding — https://aclanthology.org/2023.emnlp-main.78.pdf；Repeat Curse — https://arxiv.org/html/2504.14218v1；Recoding-Decoding — https://arxiv.org/abs/2603.19519
- Sudowrite Story Bible — https://docs.sudowrite.com/.../what-is-story-bible 、https://sudowrite.com/blog/story-bible-template
- NovelCrafter Codex — https://www.novelcrafter.com/help/faq/ai-and-prompting/codex-context-in-prompting
- AI Dungeon 上下文机制 — https://help.aidungeon.com/understanding-settings
- Wikipedia: Signs of AI writing — https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing
