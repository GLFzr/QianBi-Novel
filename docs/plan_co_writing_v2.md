# 共写工作流 2.0 — 完整方案 v2【修订r2】

> 项目：千笔一文 Novel（QianBi-Novel）· PySide6 + QML Windows 桌面「人 AI 共写长篇小说创作台」
> 定位：本文件是**设计文档**，本轮不改任何程序代码。方案建立在 V0.9.9 六大体系 + Step Gates 决策门 + 题材预设系统 + Agent Console v3（有条件通过，待实施）之上，且与现有自动流水线「全自动模式」**共存**（保留一键全自动）。
> 硬约束逐条对齐：可实施 · 可回归（18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 不破）· Agent 接力制落到现有槽位/上下文组装机制上 · 主 Agent 职责边界清晰不抢审校槽。
>
> **修订说明（v1→r2）**：v1 版本评审「有条件通过」，本版针对评审漏洞清单逐条修订。已通过部分（预设六字段保留、阶段状态机骨架、世界书/正则文件落地、两级提交语义、Agent 接力表、上下文上限表、里程碑结构、风险表）**保持不动**；凡改动处均以**【修订r2】**标注，并给出「原方案 → 修订」对照。评审漏洞清单见文末附录。

---

## 0. 一句话总览

把现有「一条自动流水线一口气跑完 _A1-A4/B1/C1-C7_」的自动模式，与用户原话要求的「六阶段人机共写：每一阶段都先以对话讨论、再点『确定』把讨论结果沉淀为产物」的**逐阶段共写模式**并列，做成同一流水线引擎上的**两档运行档位**：

- **自动档（保留现状）**：全自动模式，现有 `orchestrator.run()` + `stages.*` + Step Gates 决策门不变，18/18 断言不破。
- **共写档（新增）**：六阶段状态机 + Agent 接力制 + 对话区撬动每个阶段；每阶段的「确定」= 把最后对话讨论结果自动总结成产物。

两个档位共享同一套 `pipeline_state.json` 状态机、同一套 `ModelRouter` 三槽位、同一套产物落盘路径和版本系统——**共写只是给每个产物多了「先讨论后落盘」的一层壳**，最终产物结构与现有流水线完全一致，因此旧项目迁移、自动档续跑、产物可读性全部兼容。

---

## 1. 阶段状态机（六阶段）

### 1.1 状态定义

在 `app/core/state.py` 现有 `STAGE_SETTING / STAGE_OUTLINE / STAGE_CH_OUTLINE / STAGE_PROSE / STAGE_DONE` 基础上，**拆分并新增**共写档专用阶段。为不破坏既有自动档的 `STAGE_*` 常量与 `STAGE_ORDER` 数组，新增 `STAGE_*_CW` 一组独立常量 + 一个独立跳转表，两者并存在 `state.py`，按档位分别读取。

共写档六阶段（状态机 `key` → `中文名` → `产物文件` → `确定按钮产物`）：

| # | key | 中文名 | 阶段产物（落盘） | 「确定」行为（== 把对话自动总结成产物） |
|---|-----|--------|------------------|----------------------------------------|
| 1 | `cw_project` | 创建项目 | `设定/选题信息.md`（既有）+ `pipeline_state.cw_preset` | 选预设 / 不选预设填主题；写选题信息 |
| 2 | `cw_core` | 核心设定 | `设定/题材定位.md` | 生成「设定初始稿」→ 对话迭代 → 确定=总结定稿 |
| 3 | `cw_outline` | 剧情总大纲 | `大纲/大纲.md` | 生成「大纲初稿」→ 对话迭代 → 确定=自动总结成大纲 |
| 4 | `cw_worldbook` | 世界书与正则 | `设定/世界书.md` + `设定/正则.md` + `大纲/单元总纲.md`(重构) | 与用户一起确定世界书/正则内容 |
| 5 | `cw_unit` | 单元细纲 | `大纲/单元总纲.md` + `大纲/细纲_第N章.md` | 单元讨论确定 → 章细纲滚动生成 |
| 6 | `cw_prose` | 正文写作 | `正文/第N章.md`（+`.versions/`） | 临时草稿 → 章节确定终稿锁定 |

> 说明：阶段 3「程序大纲」与阶段 4「世界书/正则」是**两条并行可独立推进**的产物轨道。用户在《用户原话》里把「设定→大纲→世界书与正则→细纲」描述为串行，但世界书与正则本质上是设定/大纲的逻辑封闭约束，二者生成后要回喂给大纲与正文。**方案采用「大纲与高级设定→世界书/正则→细纲」三段串行的默认顺序，但世界书/正则允许在后续任何阶段回看/修订**（后文 §4.5 打回矩阵说明）。

### 1.2 阶段间流转（含打回）

```
cw_project ──确定──▶ cw_core ──确定──▶ cw_outline ──确定──▶ cw_worldbook
                                                        │◀──打回(worldbook→outline)──
                                                        ▼
cw_worldbook ──确定──▶ cw_unit ──确定──▶ cw_prose
                        │◀──打回(unit→worldbook)──
```

**「确定」按钮语义（全局统一）**：
- 每个共写阶段底部一个「✓ 确定 X」主按钮（X=设定/大纲/世界书/单元/细纲/章节）。
- 点击 = 把该阶段对话区**最后一条 Agent 总结 + 用户最终确认**自动总结为结构化产物，写入对应的阶段产物文件 = **锁定该产物**，状态机推进到下一阶段。
- 「确定」不是新开一次 LLM 调用，而是对**已收敛的对话**做一次「总结定稿」调用（见 §3.3）。

**【修订r2 · 漏洞4：共写执行模型与「确定/打回」是否走 Gate 的澄清】**

v1 §1.2 强行把「确定/打回」都挂到 Step Gates 的 `P2-P6 gate_hard`、走 `resolve_gate`（worker 线程阻塞），但评审指出这违背语义：『确定』在本质上不是「门」（是**总结调用**，由主线程启动一次性总结 worker），二者消息流不同。本版澄清执行模型：

1. **共写档不进入 `orchestrator.run()` 的线性 push 主循环**。共写档由独立的 `co_writing.run_stage(agent)` 交互状态机编排（详见 §3.0），主线程持有阶段状态，只在用户点「确定」或「打回」时驱动一次状态迁移——**讨论过程与现有 `orchestrator.run()` 完全解耦**，`run()` 仅在自动档使用（保留现状）。
2. **「确定」不是 Gate，不占门位**：「确定」恒由**主线程**启动一个一次性 `SummarizeWorker(QThread)`（仿 `_BlurbWorker`），读取该阶段对话转写 → 调总结 prompt → 落盘产物 → 状态机推进。它不经过 `gate()` / `resolve_gate()`。
3. **「打回」复用 Gate 语义但走独立入口**：「打回」本质是 `_apply_rollback`（归档+删除产物→状态机回退），与现有 `resolve_gate('return')` 的副作用同构。为不侵入 `orchestrator.run()` 主循环，共写档**不复用 `orchestrator.gate()`**，而是在 `co_writing` 内实现一个极薄的回退执行器（直接调用 `orchestrator._apply_rollback` 的等价逻辑，或抽公共函数 `rollback_stage(stage_key)`），由主线程同步执行；**没有 worker 线程 parked 在某个 P-gate 等待**。
4. 打回矩阵生效时机：`cw_outline` 确定后打回 `cw_core`、`cw_worldbook` 确定后打回 `cw_outline`、`cw_unit` 确定后打回 `cw_worldbook`、单元内打回单元讨论、`cw_prose` 章节确定前打回本章。所有打回都在「确认产物已落盘」之后触发（确定先落盘，打回再清理），保证不丢已确认产物（走版本安全网）。
5. 因此 **v1 §1.2 结尾的『分配到 P2-P6 gate_hard』整段删除**，改为 §3.0 的交互状态机描述。自动档的 `G2/G5L/G9` 之门与 Gate 基础设施保持原样，18/18 与门 4/4 探针不破。

**打回矩阵（回答《方案必须覆盖》第 1 点的打回问题；触发与 §3.0 交互状态机一致）**：

| 当前阶段 | 可打回目标 | 触发 | 打回动作（复用/扩展 `orchestrator._apply_rollback` 模式） |
|----------|------------|------|--------|
| cw_outline 确定后 | 打回 cw_core | 对话区「打回上一步」 | 归档 `设定/题材定位.md` 到 `pipeline_debug/rollback/`，清空再重设（不删选题信息） |
| cw_worldbook 确定后 | 打回 cw_outline | 对话区「打回」 | 归档 `大纲/大纲.md` + `大纲/单元总纲.md`，重设 |
| cw_unit 确定后 | 打回 cw_worldbook | 对话区「打回」 | 归档世界书/正则 + 细纲，重设（保留核心设定） |
| cw_unit 内·单元讨论确定后 | 打回单元讨论 | 「打回单元讨论」 | 只清空当前单元讨论会话，章细纲不删（可重来单元范围/主题） |
| cw_prose 章节确定前 | 打回本章 | 「打回重写」（沿 G9） | 归档本章正文走版本安全网，重写 |
| cw_prose 章节确定后 | —— | —— | **锁定，不可打回**（§6.3） |

---

## 2. 预设体系升级

### 2.1 需求映射（用户原话逐条）

用户要求预设包含四类内容，全部「参考不锁定」：
1. **核心设定参考范例** —— 同类型优秀小说在这个部分是怎么设计的（金手指等）。
2. **剧情总纲的整体内容** —— 同类型大纲设计的范式。
3. **主题世界书编写参考** —— 同类型世界书怎么写。
4. **小单元主题的细纲逻辑** —— 例如爱情线它的逻辑是什么。

### 2.2 新预设 JSON 结构（向后兼容现有六字段）

现有六字段 `style_hint / world_rules / plot_conventions / taboos / deslop_extra / review_extra` **保留不动**（`presets.genre_block()` 继续用它们注入正文/细纲 prompt，回归不破）。**新增四个「共写参考字段」**（`grow_*` 前缀），供共写档各阶段 Agent 作为「示例参考」注入，且全部带「仅供参考、不得锁定死」的措辞护栏：

```jsonc
{
  "id": "cultivation",
  "name": "修仙·凡人流",
  "description": "...",
  "version": 2,                       // 语义升级，向后兼容：缺新字段=旧预设正常用
  // == 既有六字段（不动） ==
  "style_hint": "...",
  "world_rules": "...",
  "plot_conventions": "...",
  "taboos": "...",
  "deslop_extra": "...",
  "review_extra": "...",
  // == 新增：共写参考字段（全部"参考不锁定"） ==
  "grow_core_template": "… 同类型核心设定的优秀设计参考（主角金手指、成长线、读者契约、核心期待债怎么设计的…）…",
  "grow_outline_template": "… 同类型大纲的体量划分 / 卷级 / 终局储备 范式…",
  "grow_worldbook_direction": "… 同类型世界书应覆盖哪些板块（境界/势力/资源规则/限定与代价）…",
  "grow_unit_logic": "… 同类型小单元细纲逻辑：爱情线/案件单元/副本单元各自的开-承-转-合 逻辑模板…",
  "grow_regex_direction": "… 同类型适合固化成'正则/必须成立约束'的规则清单方向…"
}
```

### 2.3 兼容与迁移

- `presets/__init__.py` 的 `PRESET_FIELDS` 只遍历既有六字段做 `genre_block()` 注入——新字段**不进 genre_block**，由共写档阶段 Agent 单独读取（新增 `presets.grow_block(preset_id, field)` 读取器）。因此旧预设 / 旧项目一律兼容，`genre_block` 回归不破。
- 内置两套 JSON 各补四个字段（`cultivation.json` / `urban_destiny.json`）；用户导入的旧 JSON 缺字段时 `load_preset` 返回空串，共写档用「（该预设未提供此参考）」占位。
- **自定义主题 = 空预设流程**：用户创建项目时不选预设、直接填主题 → `cw_preset = ""`，共写档跳过所有 `grow_*` 参考块，阶段 Agent 用通用主干 prompt（同 `genre_block` 的空预设占位），其余流程完全一致。

---

## 3. 共写对话机制

**【修订r2 · 漏洞1：对话循环机制（阻断 M1 的核心缺口），组件级落地】**

v1 §3 只说了「复用 Agent Console v3 对话区」与「点确定→总结」，但**没有定义对话循环的任何组件**：转写存哪、每轮 Agent 回复由谁调用、每阶段 system prompt 是什么、多轮上下文如何累积、'确定'用哪条总结 prompt 用什么输入。评审判定这条链路缺失会让 M1 的「对话区」是空的。本版把整条链路写到组件级。

### 3.0 共写执行模型总览（替代 v1 §1.2 的「P2-P6 gate」表述）

共写档 = **主线程驱动的交互状态机** `co_writing.CoWriting`：

- 持有一个 `CWStage` 当前阶段指针；主线程持有 `if not running: await user_action`。
- 阶段内讨论 = 用户敲字 → 主线程启动**一个一次性 `DialogueWorker`** → worker 组装该阶段 system prompt + 上下文（上环节交接收尾 + 转写摘要）为 user 消息 → 调 `router.client(slot).chat_stream` 流式回进 Console → 完成即退出（QThread 一次性，不常驻不阻塞 UI）。
- 阶段推进 `run_stage(agent)` 只做「读上环节产物 → 组装该阶段首条 user 消息 → 触发首轮 DialogueWorker 给出范例/初稿」；后续每一轮用户输入各自独立启动一个新 DialogueWorker。
- 「确定」= 主线程启动 `SummarizeWorker`（见 §3.3）；「打回」= 主线程同步执行 `rollback_stage`（见 §1.2）。

**与现有代码的接线（全部可对照现有 worker 模式）**：`_IdeaWorker` / `_BlurbWorker` / `SelectionRewriteWorker`（bridge.py L25/L258/L278）是一把一次性 QThread，内部 `router.client(slot).chat/prompt`；`DialogueWorker` 完全照此写，只把 `chat` 换成 `chat_stream(on_chunk=sig_chunk.emit)` 以流式回 Console，并把单轮 system+user 扩展为「system = 阶段 prompt，user = 上环节交接 + 转写（截断）」。**不需要修改 `LLMClient.chat/chat_stream`**（它们保持单轮 system+user 不改动，回归不破）——多轮性由「每次把已存转写作为 user 消息的一部分重发给模型」实现（见 3.2 累积机制）。

### 3.1 对话区载体 = Agent Console v3 的对话区

**直接结论：Agent Console v3（`docs/plan_agent_console_v3.md`，有条件通过）的「对话区」就是共写各阶段的对话区载体，不另造窗口。**

- Console v3 的 `ConsoleDock`（折叠 24px / 展开 280px 常驻中间列）天然是跨面板的「共写指挥台」：**阶段切换时，Console 对话区切到对应阶段子 Agent**——这正是用户原话「对话区与 Agent Console 的融合」。
- Console v3 三块内容（门 Banner + 对话区 + 思考链区）本方案复用到全过程：
  - **门 Banner** = 每阶段的「确定/打回」按钮 + 产物摘要（`gateBar` objectName 契约保留）。
  - **对话区** = 当前阶段子 Agent 的对话（人提问 + Agent 回应）。
  - **思考链区** = 阶段 Agent 生成产物时的推理（按 slot×stage×章留存的既有管线）。
- 阶段切换 = `ConsoleDock.currentAgent`（`setting/outline/worldbook/unit/prose/supervisor`）只切换**注入当前对话区上下文的 prompt 模板与槽位**，不重建窗口。

**【修订r2 · 漏洞1续】对话区载体补充**：v1 只说「Console 对话区是载体」，但 Console v3 §3.2 的对话区本身只是「显示缓冲 + 想法队列」、无 Agent 回包语义。本版明确：**共写档给 Console 对话区补一条「Agent 回包」显示通道**——`DialogueWorker` 的 `sig_chunk/sig_done` 直连到 Console 对话区的追加方法（新增 `ConsoleDock.appendAgentReply(agent, text)` 槽，纯新增不改既有 idea 队列路径）；且 Console 的输入框「发送」按钮在共写档绑定到 `Bridge.submitCwMessage`（见 3.4），而非既有的 idea 队列。自动档仍走 idea 队列，两者互不干扰。

### 3.2 对话转写存储（transcript）

- 新文件 `app/core/co_dialogue.py`：定义 `CwTranscript`（每阶段一份）与 `DialogueWorker`。
- 落盘位置：`pipeline_debug/console/<stage>/transcript.json`（`stage` = `project/core/outline/worldbook/unit/unit_<id>/prose/ch<num>`）。`pipeline_state.json` 只存「当前阶段 + 每阶段最新轮次号 + transcript 文件路径」，body 不入 state（避免 state 膨胀与格式耦合）。
- transcript 条目结构：`[{"role": "user"|"agent"|"summarize", "text": "...", "round": n, "ts": 浮点}]`；`summarize` 条目 = 该阶段「确定」时沉淀的总结稿，作为产物来源。
- 按阶段留存：`cw_unit` 的单元讨论按 `unit_<id>` 分文件，`cw_prose` 每章按 `prose/ch<num>` 分文件——保证「读改揣摩」与「章节确定」各有独立转写上下文。

**多轮上下文累积机制（针对漏洞1「多轮上下文如何累积」）**：每次触发 `DialogueWorker` 时，`co_dialogue.build_turn_message(stage)` 组装 user 消息 = `上环节交接收尾（结构化，≤800字）` + `该阶段转写（截断到最近 N=8 轮，或按字符上限 4k）` + `用户本轮输入`。模型只看到「交接 + 最近几轮」，不重放全部历史——这既满足用户原话「每个 Agent 不用吃掉所有上下文、只用知道自己上次做的事」，也天然控制 token。`N` 与截断长度为可配常量（默认 `CW_TRANSCRIPT_TURNS=8`、`CW_TRANSCRIPT_CHARS=4000`）。

### 3.3 「确定 = 自动总结」的实现

**【修订r2 · 漏洞2：新增总结器 prompt，废除『沿用 VOLUME_OUTLINE 生成模板既当生成又当总结』】**

v1 §3.3 把大纲总结写成『调用总结 Agent，输入=对话最后 N 条，输出沿用 `VOLUME_OUTLINE_PROMPT` 的输出结构』——但 `VOLUME_OUTLINE_PROMPT`（planning.py L73）是「由核心设定生成大纲」的生成模板，**不是「由对话转写归纳成大纲」的总结模板**，代码中也不存在任何转写→总结的 prompt。本版补成组件级：

- 新增总结器 prompt：`app/prompts/co_dialogue.py` 内定义 `CO_SUMMARIZE_OUTLINE_PROMPT`（"你是一名方案总结员。以下是用户与大纲设计 Agent 的对话转写（最近若干轮）。请把双方已收敛的结论归纳成一份可直接落盘的《全书大纲》…"），并要求**输出沿 `VOLUME_OUTLINE_PROMPT` 的输出结构**（`# 全书大纲` / `## 全书体量与阶段总览` / `## 卷级大纲` / 各卷 `### 第N卷`），使「确定大纲」落盘出的 `大纲/大纲.md` 与自动档产物结构一致、后续章节流水线可无差别消费。除大纲外，`CO_SUMMARIZE_SETTING_PROMPT` / `CO_SUMMARIZE_WORLDBOOK_PROMPT` / `CO_SUMMARIZE_UNIT_PROMPT` 同理各写一条（各自输出结构对应 `题材定位.md` / `世界书.md+正则.md` / `单元总纲.md` 条目）。**新增 `app/prompts/co_dialogue.py` 专门放这批总结器 + 各阶段对话 system prompt**，`planning.py` 保持现有生成模板不动（回归不破）。
- 总结器**输入** = 该阶段 `transcript.json` 的**最后 N 条**（`CW_SUMMARIZE_TURNS=6`，含用户最终诉求 + 收敛稿）+ 该阶段产物结构约束。明确「确定」= 主线程启动一次性 `SummarizeWorker(QThread)`（仿 `_BlurbWorker`），worker 内 `co_dialogue.summarize_stage(stage)` → 读 transcript → 调 `router.client(对应槽).chat(CO_SUMMARIZE_*_PROMPT)` → 写产物文件 → `emit done` → 主线程落 `summarize` 转写条目并推进状态机。**与 parked P-gate 无任何耦合（见 §1.2 修订）**。
- 用户对总结稿可**小幅修改**（编辑器直接改，改完点「保存」续用版本系统），或 **打回重议**（`rollback_stage` 回退到本阶段对话区，重开讨论后重新确定）。

> 注：v1 §3.3 的小幅修改/打回 UI 保留——「✓ 确认此修改」采用小幅修改；「↩ 打回重议」回退上一阶段或本阶段继续讨论。此部分不回退、不动。

### 3.4 Bridge 与 QML 接口（对话循环的 UI 接线）

- 新增 `Bridge` 槽：
  - `@Slot(str, str) submitCwMessage(agent, text)` → 校验 `run_mode=='cw'` 且未在总结/锁定中 → 追加 user 转写 → 启动 `DialogueWorker(agent, text)`（复用 `co_dialogue`），`sig_chunk` 追加到 Console、`sig_done` 追加 agent 转写条目。
  - `@Slot() startCoWriting()` → 校验 api-key（沿用 `startPipeline` L586-594 的遍历，共写档只遍历 `SLOT_ORDER` + `supervisor`（若为独立槽））→ 创建 `co_writing.CoWriting`（**不复用 `Orchestrator`**，见 §1.2/§9）→ 进入首个未完成 `CWStage`。
  - `@Slot(str) resolveCwStage(action, idea)` → `action='confirm'` = 启动 `SummarizeWorker`；`action='rollback'` = 启动线程执行 `rollback_stage`（打回动作落盘 + 状态回退）。
- QML：Console 输入框「发送」在 `run_mode=='cw'` 时绑定 `submitCwMessage`；阶段确定/打回按钮绑定 `resolveCwStage`。自动档这些绑定保持原样。
- 回归：以上全部为**新槽 + 新条件分支**，不触碰既有 `startPipeline/SelectionRewrite/saveChapterText` 路径与 `gateBar` 契约。

### 3.5 对话区 <-> 确定按钮 的交互语义（用户原话逐条落地）

| 阶段 | 对话流程 | 「确定」按钮 |
|------|----------|--------------|
| cw_core 核心设定 | Console 先用预设给一个「设定范例」→ 用户提修改思路 → 与设定子 Agent 讨论 → 直至收敛 | 点「确定设定」→ 启动设定总结 → 定稿 `设定/题材定位.md` |
| cw_outline 大纲 | Console 按预设给一个「简单大纲 + 全书想表达的主题」→ 与大纲子 Agent 讨论多次 | 点「确定大纲」→ **启动大纲总结（§3.3）** → 可小幅修改 或 打回上一步继续讨论重新做 |
| cw_worldbook | 设定/大纲已定 → 生成世界书与正则草案 → 与用户一起确定 | 点「确定世界书/正则」→ 世界书总结定稿 |
| cw_unit | 先给「紧接着上文内容的几章细纲」给灵感 → 用户定单元范围+主题（±10章）→ 深讨单元故事 | 点「确定单元」→ 单元总结定章数 + 剧情 → 写单元总纲 |
| cw_prose | 据细纲生成章正文 → 用户键盘改 → 保存(临时)/确定(终稿) | 点「章节内容确定」→ 终稿锁定（§6） |

---

## 4. 世界书与正则

### 4.1 文件落地

- **世界书**：`设定/世界书.md`（新增文件）。结构：板块（境界/势力/资源规则/能力边界/限定与代价）+ 每个板块的「必须成立约束」清单。
- **正则**：`设定/正则.md`（新增文件）。正则不是「文本匹配正则」，而是**故事逻辑硬约束**（逻辑封闭边界）：每条 = 一条「若 A 则 B 且必须 C」的不可违反逻辑式，供审校槽与主 Agent 逐条比对。命名沿用用户词「正则」，实为「逻辑约束规则集」。
- **单元总纲**：`大纲/单元总纲.md`（新增）——世界书/正则与大纲的结构化桥梁（§5.2）。

### 4.2 现有 `world_rules` 字段的关系

- `presets.grow_worldbook_direction` 与世界书**模板方向**相关（参考）；
- 既有 `world_rules`（既有六字段之一）是**注入正文 prompt 的题材世界规则**，保留；
- 世界书 `设定/世界书.md` 是**项目级最终确认版**（比 `world_rules` 更细、更锁定），生成时以预设的 `grow_worldbook_direction` + `world_rules` 为参考，最终以用户确认的 `世界书.md` 为准。
- `genre_block()` 注入的可选：`stages._genre_block()` 可升级为「世界书 + 正则」优先，若 `设定/世界书.md` 存在则以它为主、`world_rules` 为辅；否则回退用纯 `genre_block()`（旧项目/自动档不破）。

### 4.3 生成流程（与用户一起确定）

1. **草案生成**：世界书子 Agent 基于「核心设定 + 大纲 + 预设 grow_worldbook_direction」生成 `世界书.md` 草案 + `正则.md` 草案。
2. **对话敲定**：Console 对话区与用户逐条过世界书板块与正则条目，用户增删改。
3. **确定**：点「确定世界书/正则」→ 定稿。
4. **注入下游**：写入后的 `世界书.md` + `正则.md` 注入写作 prompt、审校 prompt、主 Agent 上下文（§4.4）。

### 4.4 注入路径

| 下游 | 注入方式 | 注入点 |
|------|----------|--------|
| 正文写作（writing 槽） | `stages.chapter_microcycle` 组装 PROSE_WRITING_PROMPT 时，把「本书世界书（节选）+ 正则清单」并入 `genre_block` 或新增 `worldbook_block` 字段 | `app/core/stages.py` |
| 审校（review 槽） | `_chapter_review` 的 REVIEW_PROMPT 增 `ruling_check` 字段 = 正则清单 | `app/core/stages.py` |
| 主 Agent（supervisor，§7） | 主 Agent 校验上下文接世界书+正则，做「逻辑一致性」比对 | `app/core/agents.py`(新) |
| 细纲（helper 槽） | `CHAPTER_OUTLINE_PROMPT` / `CO_CHAPTER_OUTLINE_PROMPT` 增世界书约束块 | `app/prompts/planning.py` / `app/prompts/co_dialogue.py` |

**【修订r2 · 漏洞8：新增 prompt 的 .format 占位符必须全调用点同步补参】**

v1 §4.4 说明了注入点，但未注明 `.format` 占位符的副作用。新增 `worldbook_block`（写作）与 `ruling_check`（审校）两个 `.format` 占位符会进入 `PROSE_WRITING_PROMPT` / `REVIEW_PROMPT` 模板；若只在共写档传入而在自动档既有调用点漏传，`str.format` 会抛 `KeyError`，直接打破 18/18 断言。**硬性要求**：

- `stages.chapter_microcycle`（现 `PROSE_WRITING_PROMPT.format` L377-394）与 `_chapter_review`（现 `REVIEW_PROMPT.format` L555-565）**两个自动档调用点必须同步补参**：`世界书.md` 不存在的旧项目/自动档一律传空串 `worldbook_block=""`、`ruling_check=""`（模板内用「（本书未启用世界书/正则）」占位承接）。
- 新增一个探针 `probe_worldbook_format.py`：断言「无世界书项目跑 `chapter_microcycle` 组装与 `_chapter_review` 组装不抛 `KeyError`，且空串注入正常」——纳入 M2 回归。

---

## 5. 细纲二级结构（单元 → 章）

### 5.1 单元（Unit）

- **单元总纲** `大纲/单元总纲.md`：单元列表，每个单元 = `单元ID / 章节范围[start..end]（可±10章）/ 主题 / 主线推进行为 / 起止状态`。用户点击「确定单元」时由单元对话定：单元要呈现的主题 + 所用章节范围（**不写死，±10 章**，可整体完结于范围前/后）。
- **「单元剧情」存哪**：存于 `大纲/单元总纲.md` 对应单元条目下的「单元剧情（讨论后确认版）」小节——它是细纲与正文的契约源，不另起新文件，避免碎片化。

### 5.2 章细纲（滚动 5 章）

- **章细纲文件不变**：沿用 `大纲/细纲_第N章.md`（与现有流水线的 `project.get_outline_path` 完全一致 → 自动档可在此续跑，互不破坏）。
- **滚动生成**：用户上回写到第 5 章、确定单元为第 6–50 章后，细纲子 Agent **只生成第 6–10 章**（`OUTLINE_BATCH=5` 档位，共写档用 5，自动档维持 2），每章 ~200 字、简述该章需发生的事件与故事内容；写完这 5 章再进行下一批。
- **细纲可直接编辑**：像改小说一样改 `细纲_第N章.md`，改完点「确定细纲」→ Agent **读一遍用户修改后的细纲**并校验（重读→与单元剧情/世界书对账→给出「已确认 / 提出衔接修正」），也可在对话区提改进思路由 Agent 改，直到用户点「确定细纲」。

### 5.3 与现有细纲 prompt 的关系

**【修订r2 · 漏洞3：二选一，采纳 A —— 新增轻量 200 字细纲 prompt，保留「每章约 200 字」承诺】**

v1 §5.3 矛盾：既承诺「每章约 200 字」，又说「复用 `CHAPTER_OUTLINE_PROMPT`」。而 `CHAPTER_OUTLINE_PROMPT`（planning.py L118-225）是重型模板（章节定位/目标情绪/结构公式/五段式/情节点带字数预算/结尾钩子等），单章远超 200 字，两头不可能都占。本版**采纳评审推荐 A**：

- 新增轻量细纲 prompt：`app/prompts/co_dialogue.py` 内 `CO_CHAPTER_OUTLINE_PROMPT`（"为第 N 章到第 M 章各写一条约 200 字的细纲，简述本章需发生的事件与故事内容"），字段精简为「核心事件 / 承接上文 / 需推进的单元契约项 / 世界书约束提醒 / 章尾钩子」五栏，线密度对齐「每章 ≈200 字」承诺。
- **维持 `===第N章===` 分隔符**：`parse_outlines`（stages.py L301）靠该分隔符解析细纲，`CO_CHAPTER_OUTLINE_PROMPT` 必须以 `===第N章===` 开头输出每个小节，保证落盘后能被 `parse_outlines` 正常解析、后续 `chapter_microcycle` 无差别消费。
- **`CHAPTER_OUTLINE_PROMPT`（重型）保留给自动档不变**，回归不破；共写档 `cw_unit` 章细纲滚动生成专用轻量版。
- 新增探针 `probe_co_outline_parse.py`：断言「轻量 prompt 输出结构含 `===第N章===`、可被 `parse_outlines` 切出 5 条、每条 ≤ 约 200 字」——纳入 M3 回归。

---

## 6. 正文写作语义升级

### 6.1 状态机：临时草稿 → 终稿锁定

核心升级是把「保存 = 唯一产生版本」扩展为**两级提交语义**（不改既有保存驱动，只在其上叠一层锁定状态）：

| 动作 | 语义 | 是否产生版本 | 是否可再改 |
|------|------|--------------|------------|
| 键盘改动 / 局部改写 | 工作副本（沿用现有 `markEditorDirty` + 5s 防抖草稿） | 否 | 是 |
| 「保存」（临时保存） | 工作副本落正文 + 归档版本（**沿用 `saveChapterText` 现状**） | 是 | **是**（仍是临时稿，可再改） |
| 「章节内容确定」**（新增）** | 终稿锁定：正文不可再改 | 是（若内容较上次有变则产生版本） | **否**（锁定） |

**章节确定语义**：
- 新增 chapter 状态字段 `locked`（`pipeline_state.json` 或 `正文/.annotations/第N章.json`）。
- 点「章节内容确定」→ 写锁定标记 + 终稿版本 + 更新正文，编辑器对该章只读。
- **「保存后内容是有可能进行改动的」明确落在临时稿**：保存 = 临时草稿可再改；「确定」才是真正不可改的终稿锁定。

### 6.2 用户改稿 → Agent 读改揣摩意图（共写闭环）

- 用户在正文编辑器改稿后**点「保存」**：若检测到改动（diff `saveChapterText` 的 old vs text），trigger **「读改揣摩」子 Agent**（`review` 槽），在 Console 对话区输出：「你这次改动想表达什么意图？」（总结改动方向 + 推断意图 + 是否影响后续章衔接）。沿 `versions.diff_texts` 计算 diff。改稿触发读改揣摩复用 `DialogueWorker`（`agent='readback'`，system prompt = `CO_READBACK_PROMPT`：输入=本章 old/new diff + 上章结尾 + 本细纲）。
- 用户在**对话区提出本章修改**：写作子 Agent 自动改「本章正文 + 本章细纲」两处（对齐用户意图），改完流式预览 → 用户「保存/放弃」。此路径同样复用 `DialogueWorker`（`agent='prose'`，system prompt 含本细纲 + 世界书正则 + 上章结尾）。

### 6.3 与现有版本/草稿系统兼容

- `.versions/` 30 版滚动、`.drafts/` 5s 防抖、崩溃恢复全部保留；
- 终稿锁定新增的 `locked` 字段是**增量**：旧章节无此字段 = 视为未锁定；`list_chapters`/`next_chapter_num` 等既有函数不受影响（只新增读取辅助），回归不破；
- 「保存还是临时稿」由 UI 文案区分（「保存（临时）」vs「确定章节（锁定）」），现行 `saveChapterText` 语义不变，只是按钮文案与新增确认按钮并存。

---

## 7. Agent 接力架构（重点）

### 7.1 角色清单 + 槽位映射

**【修订r2 · 轻微1+漏洞6：修正『独立槽位』措辞，并明确 supervisor 槽位绑定策略】**

v1 §7.1 表头写「独立槽位」，但表格里设定/大纲/写作都映射到 writing 槽、世界书/细纲映射到 helper 槽，并非字面「独立槽位」。**真正防『超长提示词』的是『独立提示词 + 只注入上环节产物』，不是槽位独立**。本版把文字统一改为「独立提示词 + 独立上下文窗口，槽位可共享」（措辞修订，机制不变——独立 prompt + 交接），并给出 supervisor 绑定决策。

用户明确要求「不要让一个 Agent 吃全部上下文，每个 Agent 只知道自己上一次做的事；主 Agent 保证不越界、审文、去AI味、衔接比对、逻辑一致性」。落到现有三槽位 +（可选）逻辑槽：

| 角色 | 槽位 | 职责边界（提示词职责） | 只注入的上下文（唯一来源） |
|------|------|------------------------|----------------------------|
| **设定 Agent** | writing | 生成核心设定参考稿 + 与用户讨论收敛 | 选题信息 + `grow_core_template` + 用户对话 |
| **大纲 Agent** | writing | 生成大纲稿 + 讨论 + 自动总结 | 核心设定产物 + `grow_outline_template` + 用户对话 |
| **世界书 Agent** | helper | 生成世界书/正则草案 + 对账 | 核心设定 + 大纲 + `grow_worldbook_direction`/`grow_regex_direction` |
| **细纲 Agent** | helper | 单元讨论 + 章细纲滚动生成 + 细纲重读校验 | 单元剧情 + 世界书/正则 + 上文结尾 + `grow_unit_logic` |
| **写作 Agent** | writing | 章正文生成 / 改稿 / 对话区修改 | 本细纲 + 世界书/正则 + 上文结尾 + 摘要链 + 用户改动意图 |
| **审校 Agent** | review | 一致性（沿用现有 `_chapter_review`，加正则比对）| 本章正文 + 世界书/正则 + 全局摘要 + 角色状态 + 伏笔 + 时间线 |
| **主 Agent（Supervisor）** | **复用 review 槽**（推荐，见下）| 范围控制 / 审文 / 去AI味 / 衔接比对 / 逻辑一致性 | **全量摘要 + 上一章结尾 + 下一章细纲 + 世界书/正则**（不做整章正文） |

**【修订r2 · 漏洞6：SLOT_SUPERVISOR 绑定决策】**

v1 §7.1 写「新增 `SLOT_SUPERVISOR`/`SLOT_PLAN` 进 `config.SLOT_ORDER`，缺省回落现有 helper/review」。评审指出这不成立：`config.slot_connection`（config.py L154-161）的真实回退链是「该槽未绑定 → 写作槽 → 第一条连接」，且一旦把新槽加进 `SLOT_ORDER`，`Bridge.startPipeline` 的 api-key 检查（L586-594）、`_get_slot_text`（L444-448）、`ConnectionListModel`（L222-224）都会随之迭代新槽位，用户可能不知 supervisor 正静默用写作槽的 key。本版**采纳推荐方案：supervisor 不新增进 `SLOT_ORDER`，直接复用 review 槽**（`SLOT_SUPERVISOR` 只在 `co_dialogue.py` 内部作为一个「逻辑 Agent 名」，其槽位解析恒为 `SLOT_REVIEW`）。理由：

1. **零波及现有槽位消费者**：不改 `config.SLOT_ORDER/SLOT_LABELS`，则 `startPipeline`、`_get_slot_text`、`ConnectionListModel`、`slot_connection` 全部不动，无静默回退隐患，回归最稳。
2. **语义自洽**：主 Agent 的「审文/去AI味/逻辑一致性」与审校槽本就同属「一致性审查」职责簇，二者复用同一连接/key 是合理默认；二者差异只在**提示词**（主 Agent 是跨章范围审查，审校槽是单章内审查），而不是槽位。
3. **如需独立**：作为可选项（M5 后置），若用户想在设置面板给 supervisor 单独选连接，再新增 `SLOT_SUPERVISOR` 进 `SLOT_ORDER`，此时必须同时：①在 `settingsPanel` 露一条 supervisor 槽位下拉（绑定继承 review 的默认值）；②`_get_slot_text`/`ConnectionListModel` 自然跟随 `SLOT_ORDER` 迭代（已覆盖）。此选项默认关闭。
4. 「缺省回落」表述一律改为「supervisor 恒绑定 review 槽，无独立槽位」——不再有『缺省回落 helper/review』的错误说法。

**槽位机制落地（硬约束「落到现有槽位/上下文组装机制」）**：
- 每个共写阶段 = **一个独立 system prompt + 一个（逻辑）Agent + 只注入上环节产物**；槽位映射如上表（writing/helper/review 三槽复用，不新增实槽）。通过新增 `app/core/agents.py`（或并入 `app/core/co_dialogue.py`）实现「Agent 接力表」：`agents/agent_registry` 定义每个逻辑 Agent 的 `(上一环节产物读取器, 阶段 system prompt 模板, 槽位, 产物路径)`，`co_writing.run_stage(agent)` 负责组装该 Agent 上下文（只读上环节产物文件 / 交接收尾）+ 调对应槽 + 写回产物。
- **上下文交接协议**：上环节产物如何进入下环节——**结构化字段交接**（不是逐字全文）。每个产物文件末尾带一段 `## 交接收尾（给下一 Agent）` 结构化摘要（3-6 条关键事实 + 开放问题），下一 Agent 只读这段。这样「不吃全量上下文」从机制上落实。

### 7.2 每个 Agent 的提示词职责边界（摘要）

- **设定 Agent**：只谈核心设定（金手指/成长线/读者契约/主角代理权），不碰大纲与章节。
- **大纲 Agent**：只谈卷级与阶段，以设定 Agent 的收尾摘要为输入，不重读设定全文。
- **世界书 Agent**：只谈世界规则与逻辑约束，输入设定+大纲的结构化收尾。
- **细纲 Agent**：只谈单元与章，输入单元剧情+世界书正则+上文结尾。
- **写作 Agent**：只谈本章正文，输入本细纲+世界书正则+上文结尾+摘要。
- **审校 Agent**：沿用现状，加正则比对。
- **主 Agent（Supervisor）**：**边界 = 不重复写内容、不重复审校槽已有职责**。职责收敛为：① 范围控制（确保各子 Agent 产物不越界）；② 审文/去AI味（对定稿做一次「AI味复审」，与 deslop 互补，不重叠）；③ 衔接比对（上一章实际结尾 vs 下一章细纲 vs 本章开头，找断裂）；④ 逻辑一致性（对照世界书/正则清单逐条检查，发现违规回退给对应子 Agent 重做）。**主 Agent 不产生正文本身**——写正文仍是写作 Agent/用户。

### 7.3 上下文量控制（量化建议）

| 上下文块 | 来源 | 所有权 | 上限 |
|----------|------|--------|------|
| 核心设定全文 | `设定/题材定位.md` | 设定 Agent | 全量 ≤4k 字 |
| 大纲全文 | `大纲/大纲.md` | 大纲 Agent | 全量 ≤4k 字 |
| 世界书/正则 | `设定/世界书.md`+`设定/正则.md` | 世界书 Agent | 全量 ≤4k 字 |
| 单元剧情重点 | `大纲/单元总纲.md` 当前单元条目 | 细纲 Agent | ≤1.5k 字 |
| 上一章结尾/文风样本 | 上一章正文尾部 | 写作 Agent | ≤800 字 |
| 章摘要链/全局摘要 | `追踪/章节摘要.md` / `全局摘要.md` | 写作/主 Agent | ≤2k 字 |
| 主 Agent 全量摘要 | 全球摘要+角色状态+伏笔+时间线+上章结尾+下章细纲 | 主 Agent | ≤6k 字 |

> 设计意图：没有任何子 Agent 的 prompt 包含「全书正文」全量——这是「不吃全量上下文」的量化落点。若正文随书变长，仅摘要链 + 结构化交接收尾随书增长（受控），不做全文拼接。
>
> **修订r2 增补**：对话循环自身的多轮累积也纳入本表——每次 `DialogueWorker` 的 user 消息只含「交接 ≤800 字 + 转写最近 ≤4k 字 + 本轮输入」，不重放全史（§3.2）。这使「共写讨论」与「自动流水线」共享同一套上下文预算纪律。

### 7.4 主 Agent 与审校槽去重

- **审校槽** = 每章当下的一致性检查（章节内矛盾、设定冲突、伏笔、规则违反），产出 BLOCKING/ADVISORY，进 `_review_findings`。
- **主 Agent** = 跨章/跨阶段的范围与衔接监督（上一章↔本章↔下一章细纲的断裂、AI味复检、逻辑封闭性），不等同于逐章审校，不重复产同一份 BLOCKING/ADVISORY。
- 分工锚：审校槽做「单章内一致性」，主 Agent 做「章间衔接 + 全文范围 + 逻辑封闭」，两套 Findings 分开展示（审校槽进 StepGate G9；主 Agent 进 Console 对话区报告）。

---

## 8. UI 更改设计

### 8.1 阶段导航

**【修订r2 · 漏洞7：明确 PipelinePanel 阶段卡片由 run_mode 切换，旧 4 卡自动档保留】**

v1 §8.1 只说新增 `StageStepperCW`，但没说 `PipelinePanel` 现有 `stageCards()`（bridge.py L1508-1545，只渲染 setting/outline/ch_outline/prose 4 卡）是否/如何替换。本版明确：

- 共写档用新增 `StageStepperCW`（或 `StageStepper` 加 `mode:"cw"` 属性，**保留原组件 objectName 与自动档行为**）渲染六段 `创建/设定/大纲/世界书/单元/正文`。
- `PipelinePanel` 的阶段卡片渲染**按 run_mode 切换**：
  - `run_mode=='auto'`（及 `step/border`）→ 维持既有 `stageCards()` 4 卡（设定/大纲/细纲/正文），**现有 UI 与探针全不动**。
  - `run_mode=='cw'` → 改用 `StageStepperCW` 六卡。实现方式：新增 `bridge.stageCardsCW()`（返回六阶段状态），`PipelinePanel.qml` 顶部加 `if runMode=='cw'` 分支切换到 `StageStepperCW`；自动档分支保持 `stageCards`。
- 左侧不新增 rail 图标（避免挤占）；六阶段以顶部 stepper + PipelinePanel 内「阶段卡片」呈现，跟现在一致。

### 8.2 每阶段视图（复用 Editor + Console）

| 区域 | 共写档用法 |
|------|------------|
| Console 对话区 | 当前阶段子 Agent 对话 + 门 Banner（确定/打回/产物摘要） |
| 主编辑区 | 当前阶段**产物编辑**（设定.md / 大纲.md / 世界书.md / 细纲.md / 正文.md），常驻可编辑 |
| Console 思考链区 | 阶段 Agent 生成产物时的推理链（按槽位×阶段×章留存） |
| 状态栏 | 显示当前阶段 agent + 槽位 + 上下文量 |

- **阶段切换** = `ConsoleDock.currentAgent` 切换 + 主编辑器载入对应产物文件。每个阶段顶部一个「✓ 确定」+「↩ 打回」按钮（进门 Banner 或阶段工具栏）。

### 8.3 细纲编辑器

- 章细纲以列表/分章标签呈现（可编辑每章 200 字细纲），选某一章 → 主编辑区载入 `细纲_第N章.md`。
- 每章一个「确定细纲」校验按钮 + 支持对话区提思路由 Agent 改。

### 8.4 章节确定按钮位置

- 主编辑器顶栏 + Console 门 Banner 均放「保存（临时）」与「确定章节（锁定）」两键；`gateBar` objectName 契约保留。
- 已锁定章节编辑器 `readOnly`，顶栏显示「✓ 已确定（终稿锁定）」徽章。

### 8.5 与 Agent Console / 阅读器 dock 布局整合

假定 Agent Console v3 已实施（M1-M3）。共写工作流叠加其上：

```
1600 宽：
┌──┬─────┬──────────┬─────────────┬──────────┐
│48│ 300 │ Console  │ 主编辑列(阶段 │ 阅读 dock │
│  │ 面板 │24/280    │ 产物/正文)   │ ~460     │
│  │     │(折叠/展开)│              │          │
│  │     │ 对话+门+  │ 顶部: 阶段导航/确定/打回 │
│  │     │ 思考链    │              │          │
└──┴─────┴──────────┴─────────────┴──────────┘
```

### 8.6 QML 组件树与 Main.qml 演进（伪代码级）

```qml
ApplicationWindow (width 1400→1600) {
    RowLayout {
        NavRail {}                                    // 保留 5 图标
        PanelStack { BookshelfPanel/PipelinePanel/ChapterPanel/NotesPanel/SettingsPanel }
        ConsoleDock {                                  // Agent Console v3 已交付
            property string currentAgent      // setting/outline/worldbook/unit/prose/supervisor/readback
            GateBanner { /* 沿用 gateBar objectName */ }
            DialogArea { /* 阶段对话：run_mode=='cw' 时 发送→submitCwMessage；有 appendAgentReply 通道 */ }
            ThinkingArea { /* 按 slot×stage×章 */ }
        }
        ColumnLayout {                                // 主编辑列
            StageToolbar { StageStepperCW {} // run_mode=='cw' 六卡（自动档仍 4 卡）；确定/打回按钮；章节锁定徽章 }
            EditorView { /* 阶段产物 / 正文；锁定章 readOnly */ }
            StatusBar {}
        }
        ReaderDockHost { ReaderView {} }              // v3 已交付
    }
}
```

**回归不破要点**：所有新增 UI（StageStepperCW、ConsoleDock、章节锁定、`stageCardsCW`）都是**新增属性/组件/条件分支**，不改动现有 `gateBar`/`panelStack`/`readerView` 的 objectName 与既有数据契约；`stageCards` 4 卡在自动档原样保留；18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 的既有项不动，仅新增探针。

---

## 9. 实施里程碑（M1-M5）

**【修订r2 · 漏洞5+1：M1 明确 cw 运行档接线 + 对话循环组件】**

v1 未说明 `run_mode='cw'` 是否进入 `Bridge.setRunMode` 白名单（bridge.py L661 只允许 auto/step/border），也未说明 `startPipeline` 与 cw 入口的互斥。本版在 M1 明确接线：

**M1 — 对话区 + 阶段状态机骨架 + cw 运行档接线**
- 新增 `app/core/co_dialogue.py`：`CwTranscript`（每阶段转写存取）+ `DialogueWorker(QThread)`（仿 `SelectionRewriteWorker`，组装阶段 system prompt + 交接 + 转写摘要为 user，`chat_stream` 流式回 Console）+ `build_turn_message`（转写截断累积，§3.2）。
- 新增 `app/core/co_writing.py`：状态机编排 `CoWriting.run_stage(agent)` + `summarize_stage(agent)`（启动 `SummarizeWorker`）+ `rollback_stage(stage_key)`（调 `_apply_rollback` 等价逻辑，§1.2）。
- 改 `app/core/state.py`（六阶段 CW 常量+跳转表）、`app/prompts/co_dialogue.py`（各阶段对话 system prompt + `CO_SUMMARIZE_*_PROMPT`，§3.3）。
- 改 `app/ui/bridge.py`：
  - `setRunMode` 白名单扩为 `("auto","step","border","cw")`（L661 加 `"cw"`）。
  - 新增 `startCoWriting()`（校验 api-key 沿用 L586-594 遍历 → 进 `CoWriting` 首个未完成 stage，**与 `startPipeline` 互斥**：`_running` 重置前不允许切换；`run_mode=='cw'` 时 PipelinePanel「开始」按钮改触发 `startCoWriting`，自动档仍触发 `startPipeline`）。
  - 新增 `submitCwMessage(agent, text)` / `resolveCwStage(action)`（§3.4）。
  - `orchestrator.gate_enabled`（L90-98）对 `cw`：`gate_enabled` 只在自动档被 `orchestrator.run()` 调用，共写档不进 `run()`（§1.2），故不改 `gate_enabled`；如需防御，可在其开头 `if mode=='cw': return False`（共写档不被 Gate 打断）。
- 改 `Main.qml` / `PipelinePanel.qml`（`StageStepperCW` 占位 + `run_mode` 分支 + 阶段确定/打回按钮初版，§8.1/8.6）、`tests/`（新增 `probe_cw_state.py` + `probe_cw_dialogue.py`）。
- 回归：`assert_v099.py`（18/18 不破）+ `smoke_func` + `probe_gate_*`（门 4/4 不破）+ 新增 CW 状态机探针（六阶段推进、打回矩阵）+ 新增对话循环探针（`submitCwMessage`→`DialogueWorker`→transcript 落盘→`resolveCwStage('confirm')`→总结落产物，关联 `probe_cw_dialogue_flow.py`）。

**M2 — 预设升级 + 世界书/正则**
- 改：`app/presets/*.json`（+4 grow 字段）、`app/presets/__init__.py`（`grow_block` 读取器）、`app/core/co_writing.py`（世界书 Agent）、`app/prompts/planning.py`、`app/core/stages.py`（worldbook 注入写作/审校，**含 §4.4 修订的 `.format` 双调用点补参与空串占位**）、`app/project.py`（世界书/正则/单元总纲路径辅助）。
- 回归：既有预设 18/18 + 新增 `probe_worldbook.py`（文件落地 + 注入 writing/review prompt 断言）+ `probe_worldbook_format.py`（§4.4：无世界书项目组装不抛 `KeyError`）。

**M3 — 细纲二级结构**
- 改：`app/core/co_writing.py`（单元讨论 + 章滚动 5 章）、`app/prompts/co_dialogue.py`（新增 `CO_CHAPTER_OUTLINE_PROMPT`，§5.3 修订）、`app/prompts/planning.py`、`app/ui/qml/components/StepGateBar.qml`（确定细纲/打回单元）、PipelinePanel。
- 回归：`tests/probe_outline_batch` 变体（5 章滚动）+ LOL 兼容（`OUTLINE_BATCH` 自动档仍 2）+ 新增 `probe_co_outline_parse.py`（轻量版 `===第N章===` 可被 `parse_outlines` 解析、≤200字，§5.3 修订）。

**M4 — 章节确定语义**
- 改：`app/core/versions.py`（`locked` 标记辅助）、`app/ui/bridge.py`（`saveDraft`=临时保存现状 / `confirmChapterLocked` 新增 + `readChapterLocked`）、`app/prompts/co_dialogue.py`（`CO_READBACK_PROMPT`，§6.2）、`Main.qml`（保存/确定双键 + 锁定徽章 + 锁定读编辑）、`tests/probe_chapter_lock.py`（锁后只读 + 版本行为）。
- 回归：版本系统既有断言（M1 versions 不破）+ 新增锁探针。

**M5 — Agent 接力 + 主 Agent**
- 改：`app/core/agents.py`(新，接力表+上下文交接协议)、`app/core/co_writing.py`（编排到接力）、`app/core/orchestrator.py`（supervisor 审文/衔接/逻辑校验挂点，**supervisor 复用 review 槽，不新增 `SLOT_ORDER`，默认无独立槽位与 UI**，§7.1 修订）、`app/prompts/co_dialogue.py`（各逻辑 Agent prompt 模板 + 结构化交接收尾）、`Main.qml`/Console（supervisor 报告区）。
- 回归：M1-M4 全套 + `probe_agent_relay.py`（每个逻辑 Agent 只注入上环节产物/交接收尾、主 Agent 不产生正文、上下文上限断言）+ 全自动档 `probe_gate_flow` 不破。

---

## 10. 风险与规避

| 风险 | 影响 | 规避 |
|------|------|------|
| 上下文量失控（全书变长） | 成本/质量 | 结构化交接 + 摘要链 + 上下文上限表（§7.3）+ 对话循环转写截断（§3.2）；主 Agent 不拼全文正文 |
| API 成本（每章调用次数变化） | 成本 | 共写档默认只在确定/锁定/读改揣摩时加调用；自动档维持原次数；可配置调用频率 |
| 旧项目数据迁移（无世界书/无单元） | 兼容 | `load_preset` 缺字段容错；旧项目无世界书/单元时，共写档自动补生成或用占位；`locked` 字段缺省=未锁；`.format` 空串占位承接（§4.4 修订） |
| 旧流水线兼容（自动档保留） | 回归 | 两档并行：`stage` 常量并存、`OUTLINE_BATCH` 自动档仍 2、`genre_block` 不动、gateBar/panelStack/readerView objectName 不动、`chapter_microcycle`/`_chapter_review` 自动档调用点补参且空串兼容（§4.4） |
| Agent 接力丢上下文（交接遗漏） | 剧情断裂 | 「交接收尾」结构化块 + 主 Agent 衔接比对（上章结尾↔下章细纲↔本章开头）作为兜底 |
| 正则/世界书过度锁定 | 阉割创作 | 全部 grow_ 字段「参考不锁定」措辞护栏 + 世界书按阶段可回看修订 |
| 确定按钮误触发 | 误操作 | 确定=总结定稿后仅小幅修改可改；需要改结构走打回；锁定章只读 |
| supervisor 槽位静默回退 | 用户困惑 | supervisor 复用 review 槽、无独立槽位（§7.1 修订），不引入静默回退链 |

---

## 附：评审漏洞清单 → 修订对照

| # | 严重度 | 评审点 | 本版修订位置 |
|---|--------|--------|--------------|
| 1 | 阻断 M1 | 多轮「对话讨论」机制缺失，未落到组件级 | §3.0/§3.1/§3.2/§3.4：`co_dialogue.py` + `DialogueWorker` + transcript 落盘 + `submitCwMessage` + 转写截断累积 |
| 2 | 高危 | 「确定大纲=自动总结」无总结器 | §3.3：新增 `CO_SUMMARIZE_*_PROMPT` 系列 + `SummarizeWorker` + 明确输入=最后 N 条转写 |
| 3 | 中危 | 细纲「~200 字」与「复用重型 prompt」矛盾 | §5.3：采纳 A，新增轻量 `CO_CHAPTER_OUTLINE_PROMPT`，保留 `===第N章===`，加 parse 兼容探针 |
| 4 | 中危 | 共写执行模型未与 orchestrator 线性线程对齐 | §1.2：共写不走 `run()`，交互状态机 + 一次性 worker；确定非 Gate、打回独立 `rollback_stage`；删除 P2-P6 gate 表述 |
| 5 | 中危 | `run_mode='cw'` 无接线 | §9 M1 + §3.4：白名单加 `"cw"`、`startCoWriting` 与 `startPipeline` 互斥、gate_enabled 防御 `return False` |
| 6 | 中危 | `SLOT_SUPERVISOR` 依赖新增进 SLOT_ORDER 波及消费者 | §7.1：supervisor 复用 review 槽、不新增 `SLOT_ORDER`；可选项（M5 后置）才独立化且必配 UI 绑定；修正回落措辞 |
| 7 | 轻微 | stageCards 仍是旧 4 阶段 | §8.1 + §9 M1：`stageCardsCW()` 六卡按 run_mode 切换，自动档 4 卡保留 |
| 8 | 建议 | 新增 prompt 的 `.format` 占位符未同步补参 | §4.4 + §9 M2：`worldbook_block`/`ruling_check` 在两处自动档调用点补参、无世界书传空串、加 `probe_worldbook_format.py` |
| — | 轻微(措辞) | 「独立槽位」与自身角色表矛盾 | §7.1：改「独立提示词+独立上下文窗口，槽位可共享」 |

---

## 附：硬约束逐条自检

- **只出方案不改码**：本文件为纯设计，无 diff。✔
- **可实施可回归**：所有新增为增量（新状态/新组件/新字段/新条件分支），既有 18/18+冒烟+门4/4+UI探针8/8 契约不动，`chapter_microcycle`/`_chapter_review` 调用点仅补空串参数（不含 KeyError），每里程碑附回归清单。✔
- **与自动流水线共存**：两档位共享状态机与槽位，自动档保留，`run_mode` 分支隔离。✔
- **Agent 接力落到槽位机制**：每个逻辑 Agent = 独立提示词 + 只注入上环节产物（含交接收尾 + 转写截断），槽位共享 writing/helper/review（§7.1/§3.2）✔
- **主 Agent 职责边界**：不写内容、不抢审校槽，只做范围/衔接/逻辑，复用 review 槽（§7.4/§7.1）✔
