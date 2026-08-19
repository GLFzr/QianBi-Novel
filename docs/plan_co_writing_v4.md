# 共写工作流 2.0 — 完整方案 v4【修订r4】

> 项目：千笔一文 Novel（QianBi-Novel）· PySide6 + QML Windows 桌面「人 AI 共写长篇小说创作台」
> 定位：本文件是**设计文档**，本轮不改任何程序代码。方案建立在 V0.9.9 六大体系 + Step Gates 决策门 + 题材预设系统之上，且与现有自动流水线「全自动模式」**共存**（保留一键全自动）。本文在 v3（r3 通过）基础上，仅对 r4 评审漏洞 `SEV-1/SEV-2/MED-1/MED-2/LOW-1/LOW-2/LOW-3` 点名处修订；r2/r3 已通过项**保持不动**，凡本次改动处均以**【修订r4】**标注。
> 硬约束逐条对齐：可实施 · 可回归（18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 预期不破，待 M1 实施后实跑复核）· Agent 接力制落到现有槽位/上下文组装机制上 · 主 Agent 职责边界清晰不抢审校槽。
>
> **修订说明（v1→r2→r3→r4）**：v1「有条件通过」，v2 修 r2、v3 修 r3；本版（v4）仅对 r4 七条漏洞逐条修订：**裁决单元总纲唯一属主 = cw_unit（SEV-1）、世界书回看回边入状态机（SEV-1）、改写世界书格式探针为『router 打桩 + 组装期断言』（SEV-2）、locked 章跨档信息（MED-1）、读改揣摩成本显式化（MED-2）、正则语义待用户确认并把两种结构都写清（LOW-1）、自检表改标『预期不破』（LOW-2）、清理『程序大纲/（重构）』残留（LOW-3）**。已通过部分（预设六字段、阶段状态机骨架、世界书/正则文件落地、两级提交语义、Agent 接力表、上下文上限表、里程碑结构、风险表、r2/r3 已修订项）**保持不动**；原文 **【修订r2】/【修订r3】** 标注保留，表示 r2/r3 修订、本版未回退。

---

## 0. 一句话总览

把现有「一条自动流水线一口气跑完 _A1-A4/B1/C1-C7_」的自动模式，与用户原话要求的「六阶段人机共写：每一阶段都先以对话讨论、再点『确定』把讨论结果沉淀为产物」的**逐阶段共写模式**并列，做成同一流水线引擎上的**两档运行档位**：

- **自动档（保留现状）**：全自动模式，现有 `orchestrator.run()` + `stages.*` + Step Gates 决策门不变，18/18 断言不破。
- **共写档（新增）**：六阶段状态机 + Agent 接力制 + 对话区撬动每个阶段；每阶段的「确定」= 把最后对话讨论结果自动总结成产物。

两个档位共享同一套 `pipeline_state.json`、同一套 `ModelRouter` 三槽位、同一套产物落盘路径和版本系统——**共写只是给每个产物多了「先讨论后落盘」的一层壳**，最终产物结构与现有流水线完全一致，因此旧项目迁移、自动档续跑、产物可读性全部兼容。

**【修订r3 · M2：状态机键分离 + 项目模式粘性规则（防互相污染续跑判断）】**（r3 保留）

r3 §0 钉死：`state['cw']` 独立嵌套对象（`mode/stage/turn`），`STAGE_*_CW` 只写 `state['cw']['stage']`，绝不写自动档 `state['stage']`；项目打开时按 `state['cw']['mode']` 判定档位粘性；cw↔自动档为受控切换（`migrate_project_mode`）。**本版（r4）在此基础上叠加 MED-1 的『locked 章跨档处置』（见下）。**

**【修订r4 · MED-1：locked 章节的跨档行为（补 M2 切换与 M4 锁定语义咬合缺口）】**

r3 §0 M2 说 cw↔自动档「仅阶段空闲时切换、产物可兼容」，但未处理 **`locked` 章节**在自动档下的行为。已核对两份代码现实：

- `orchestrator._apply_rollback`（orchestrator.py L146-179）：`G9` 分支（L167-174）对目标章 `shutil.copy2` 归档后 **`os.remove(path)`** 直接删除正文文件——若该书带 locked 章切回自动档并触发 G9 重写，会把已锁定终稿在本体内删除（版本历史保留，但编辑器失去正文只读锚点）。
- `bridge.regenerateStage`（bridge.py L1548-1586）：`ch_outline` 分支（L1562-1573）按 `n >= next_chapter_num` 批量 `os.remove` 细纲；`setting/outline` 分支（L1555-1561）删设定/大纲产物并连带删细纲。若 locked 章存在，其细纲被重生成会与已锁定正文契约脱节。

本版钉死 **locked 章的跨档处置规则**（把 M2 模式切换与 M4 锁定语义咬合起来）：

1. **locked 章在自动档是「只读锚点」，不需要也不允许被自动档重写**：切回自动档后，
   - `orchestrator.run()` 的 G9 分支：编章时**跳过 locked 章**（不进入「回退重写候选」），`_apply_rollback('G9', n)` 对 locked 章直接拒绝（返回「该章已锁定，请先在共写档显式解锁」）。
   - `bridge.regenerateStage` 的 `ch_outline`：**不会删 loop 到 locked 章的细纲**（locked 章的细纲视为已定契约，`n >= next_chapter_num` 只对未锁定的后续章生效）。
   - 新增守卫辅助 `bridge.isChapterLocked(n)` / `bridge.attemptUnlock(n, reason)`：G9 与 regenerateStage 在被拒入口前调用它，与现有 `_running` 守卫同构（纯新增分支，不改既有自动档对未锁定章的行为）。
2. **显式解锁是唯一放行通道**：用户须先在共写档 `CwDialogueDock`/章节面板对 locked 章点「解锁」才能进入自动档重写；`attemptUnlock` 记录 `locked=False` 并走版本安全网（解锁前的终稿仍留 `versions/`），`readChapterLocked` 供 UI 只读态/徽章消费。
3. **`migrate_project_mode(to_cw)` 遇 locked 章保持锁定**：从自动档切回共写档时，已 locked 的正文维持 `locked=True`，不因档位切换降级为临时稿（切档不改锁定语义）。
4. **自动档本身不产生 locked 章**：自动档的 `saveChapterText` 仍只写临时稿（`locked` 缺省 False），锁定只由共写档「章节内容确定」产生；因此该规则只在「带 locked 章的 cw 书切回自动档」这一受控场景生效。
5. 新增探针 `probe_chapter_lock_cross_mode.py`：断言（a）locked 章章节切换回自动档后，`_apply_rollback('G9', locked_n)` 被拒且不删除正文；（b）`regenerateStage('ch_outline')` 不删 locked 章的细纲；（c）`attemptUnlock` 后 G9 可正常回退；（d）`migrate_project_mode(to_cw)` 保持 locked——纳入 M4/M2 回归。

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
| 4 | `cw_worldbook` | 世界书与正则 | `设定/世界书.md` + `设定/正则.md` | 与用户一起确定世界书/正则内容（**本阶段不产单元总纲**，见下） |
| 5 | `cw_unit` | 单元细纲 | `大纲/单元总纲.md` + `大纲/细纲_第N章.md` | 单元讨论确定 → 写单元总纲 → 章细纲滚动生成 |
| 6 | `cw_prose` | 正文写作 | `正文/第N章.md`（+`.versions/`） | 临时草稿 → 章节确定终稿锁定 |

**【修订r4 · SEV-1（a）：裁决 `大纲/单元总纲.md` 的唯一属主 = cw_unit】**

r3 阶段表 row4（cw_worldbook）把 `大纲/单元总纲.md(重构)` 也列为产物，row5（cw_unit）又声称同一文件——**一个文件挂到两个阶段名下**，且 row4 带 `(重构)` 残留标注。已核对 `设定/世界书.md`+`设定/正则.md` 是世界书阶段产物，`大纲/单元总纲.md` 本质是「单元列表 + 每单元的主题/章节范围/主线推进/起止状态」——它由「确定单元」的对话生成，**属于 cw_unit**。本版修订：

- **row4（cw_worldbook）产物只写 `设定/世界书.md` + `设定/正则.md` 两文件**，删掉 `+ 大纲/单元总纲.md(重构)`。
- **row5（cw_unit）产物 = `大纲/单元总纲.md` + `大纲/细纲_第N章.md`**（单元总纲唯一属主），与 §5.1/§5.2 一致。
- 清理链路：世界书/正则与单元总纲的依赖还在（世界书生成时参考大纲，单元总纲生成时参考世界书/正则），但**落盘属主清晰**——世界书阶段不创建单元总纲，单元总纲只在 cw_unit「确定单元」后落盘（见 §5.1）。全局 L0W-3：统一「单元总纲属主 = cw_unit」。

> 说明（SEV-1 裁决后半）：阶段 3「剧情总大纲」与阶段 4「世界书/正则」是**串行唯一路径**（outline→worldbook→unit），世界书/正则生成后要回喂给单元细纲与正文。**「世界书可后续回看/修订」通过状态机显式回边实现（见 §1.2 回边矩阵与 §4.5 reopen），不再是『并行轨道』的含糊说法。**（SEV-1(c) 裁决：**采纳『三段串行 + 可回看回边』**，删除『两条并行可独立推进』脚注，只留『串行 + 回看』。）

### 1.2 阶段间流转（含打回）

```
cw_project ──确定──▶ cw_core ──确定──▶ cw_outline ──确定──▶ cw_worldbook
                                                        │◀──打回(worldbook→outline)──
                                                        ▼
cw_worldbook ──确定──▶ cw_unit ──确定──▶ cw_prose
                        │◀──打回(unit→worldbook)──
                        │
                        ▸ 回看回边（SEV-1）：
                        cw_unit / cw_prose(非锁定章) ──回看世界书──▶ reopen cw_worldbook 修订后重确定
```

**「确定」按钮语义（全局统一）**：
- 每个共写阶段底部一个「✓ 确定 X」主按钮（X=设定/大纲/世界书/单元/细纲/章节）。
- 点击 = 把该阶段对话区**最后一条 Agent 总结 + 用户最终确认**自动总结为结构化产物，写入对应的阶段产物文件 = **锁定该产物**，状态机推进到下一阶段。
- 「确定」不是新开一次 LLM 调用，而是对**已收敛的对话**做一次「总结定稿」调用（见 §3.3）。

**【修订r4 · SEV-1（b）：新增『世界书回看回边』到状态机 + 打回/重开矩阵补行使】**

r3 脚注宣称世界书「允许后续任何阶段回看/修订」，但严格串行状态机没有任何回边——「并行/可回看」与「严格串行」自相矛盾，r4 裁决：**采纳『三段串行 + 可回看回边』**，把「回看世界书」落成**显式状态机回边**：

- **回看入口**：`cw_unit`（或 `cw_prose` 的非锁定章）提供「回看世界书/正则」入口 → 触发 `co_writing.reopen_stage('cw_worldbook')`（轻量 reopen：保留当前 unit/prose 上的对话转写与已锁定产物，仅把 `state['cw']['stage']` 软切回 `cw_worldbook` 供修订）。
- **修订后重确定**：reopen 后的 cw_worldbook 对话讨论世界书/正则修订 → 点「确定世界书/正则」→ 写回 `设定/世界书.md`+`设定/正则.md` → **自动继承到下游未锁定产物**：
  - 已锁定单元 `大纲/单元总纲.md` 的世界书约束字段**重对账刷新**（不删除单元结构，只更新依赖世界书的约束引用）；
  - 未锁定章细纲/正文**标记「世界书已变更，需重校验」**，由细纲/写作 Agent 在读改/生成时重读新世界书；
  - 已锁定章正文**不自动改**（终稿不可动），仅由 supervisor 在其下次衔接比对提示「世界书变更影响第 N 章，建议用户显式解锁后重核」（MED-1 解锁通道复用）。
- **与打回的区别**：reopen 是「保留下游、软切修订」；`rollback_stage` 是「级联失效下游产物强制回退」（§1.2 r3 M3/L1）。reopen 不级联删除，rollback 才级联。**打回矩阵补一行**：

| 当前阶段 | 动作 | 触发 | 副作用 |
|----------|------|------|--------|
| cw_unit / cw_prose(非锁定章) | **回看世界书/正则（reopen）** | 「回看世界书」入口 | 软切 `state['cw']['stage']=cw_worldbook`；保留下游转写与已锁定产物；修订重确定后刷新未锁定下游的世界书引用；已锁定章不动 |
| cw_unit 确定后 | 打回 cw_worldbook | 「打回」 | 级联失效全部 `细纲_第N章.md`（r3 已列），删除 `设定/世界书.md`+`设定/正则.md` |

**（r2 保留）漏洞4：共写执行模型与「确定/打回」澄清**（r2/r3 原文保留，摘要）
- 共写档不进 `orchestrator.run()`，由 `co_writing.run_stage(agent)` 交互状态机编排；「确定」= 主线程启动一次性 `SummarizeWorker`，「打回」= 主线程同步 `rollback_stage`；无 worker parked 在 P-gate。

**（r3 保留）漏洞 M3+L1：打回矩阵五个显式 `rollback_stage(stage_key)` + 级联失效列**（r3 原文保留）：core 打回连带失效 大纲/全部细纲/世界书/正则/单元总纲；worldbook 打回连带失效全部细纲；unit 打回连带失效全部细纲；单元内打回单元讨论；cw_prose 章节确定前打回本章。关键不变量：『归档目标文件集 ∪ 级联失效产物集』覆盖全部下游派生，归档入 `rollback/` 保留、清下游指针。**本版在其上补 reopen 回边（不级联、只刷新引用），并把 `编辑` 新增的 `reopen_stage` 与 `rollback_stage` 并举。**

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

**（r2 保留）漏洞1：对话循环组件级落地**（`co_dialogue.py` + `DialogueWorker` + transcript + `submitCwMessage` + 转写截断累积）。**（r3 保留）H1：对话区载体 = M1 自带 `CwDialogueDock`（主编辑列内部，不改三列骨架），Console v3 仅为后置可选替换宿主。**

### 3.0 共写执行模型总览（替代 v1 §1.2 的「P2-P6 gate」表述）

共写档 = **主线程驱动的交互状态机** `co_writing.CoWriting`：

- 持有一个 `CWStage` 当前阶段指针；主线程持有 `if not running: await user_action`。
- 阶段内讨论 = 用户敲字 → 主线程启动**一个一次性 `DialogueWorker`** → worker 组装该阶段 system prompt + 上下文（上环节交接收尾 + 转写摘要）为 user 消息 → 调 `router.client(slot).chat_stream` 流式回进 `CwDialogueDock`（§3.1，M1 自带）→ 完成即退出（QThread 一次性，不常驻不阻塞 UI）。
- 阶段推进 `run_stage(agent)` 只做「读上环节产物 → 组装该阶段首条 user 消息 → 触发首轮 DialogueWorker 给出范例/初稿」；后续每一轮用户输入各自独立启动一个新 DialogueWorker。
- 「确定」= 主线程启动 `SummarizeWorker`（见 §3.3）；「打回」= 主线程同步执行 `rollback_stage`（见 §1.2）；「回看世界书」= 主线程同步执行 `reopen_stage('cw_worldbook')`（§1.2 SEV-1）。

**（r3 保留）L2：主 Agent 触发点**（两固定触发点：「cw_unit 确定细纲后」对账、「cw_prose 章节内容确定后」跨章衔接+逻辑封闭，复用 review 槽，只产报告不产正文）。

### 3.1 对话区载体 = M1 自带最小化对话 dock（不依赖 Agent Console v3）

**（r3 保留）H1**：M1 自带最小 `CwDialogueDock`，四件事（appendAgentReply / 对话区 / 门 Banner / 发送绑定 submitCwMessage）；不依赖、不等待 Console v3；阶段切换 = `currentAgent` 切换，不重建窗口；升级路径显式写死（Console v3 合并后才替换）。

### 3.2 对话转写存储（transcript）

- 新文件 `app/core/co_dialogue.py`：定义 `CwTranscript`（每阶段一份）与 `DialogueWorker`。
- 落盘位置：`pipeline_debug/console/<stage>/transcript.json`（`stage` = `project/core/outline/worldbook/unit/unit_<id>/prose/ch<num>`）。`pipeline_state.json` 只存「当前阶段 + 每阶段最新轮次号 + transcript 文件路径」，body 不入 state。
- transcript 条目结构：`[{"role": "user"|"agent"|"summarize", "text": "...", "round": n, "ts": 浮点}]`；`summarize` 条目 = 该阶段「确定」时沉淀的总结稿，作为产物来源。
- 按阶段留存：cw_unit 单元讨论按 `unit_<id>` 分文件，cw_prose 每章按 `prose/ch<num>` 分文件。

**多轮上下文累积机制**：每次触发 `DialogueWorker`，`co_dialogue.build_turn_message(stage)` 组装 user 消息 = `上环节交接收尾（≤800字）` + `该阶段转写（截断到最近 N=8 轮，≤4k 字）` + `用户本轮输入`。`N` 与截断长度可配（`CW_TRANSCRIPT_TURNS=8`、`CW_TRANSCRIPT_CHARS=4000`）。

### 3.3 「确定 = 自动总结」的实现

**（r2 保留）漏洞2**：新增 `CO_SUMMARIZE_*_PROMPT` 系列 + `SummarizeWorker`；输入=该阶段 transcript 最后 N 条（`CW_SUMMARIZE_TURNS=6`）；输出沿对应产物结构（大纲沿 `VOLUME_OUTLINE_PROMPT` 结构）。用户可小幅修改或打回重议。

> 注：v1 §3.3 的小幅修改/打回 UI 保留——「✓ 确认此修改」采用小幅修改；「↩ 打回重议」回退上一阶段或本阶段继续讨论。

### 3.4 Bridge 与 QML 接口（对话循环的 UI 接线）

**（r3 保留）M1**：新增 `self._cw_active`（`_set_cw_active(v)`），`startCoWriting` 与 `startPipeline` 双头守卫 `_running or _cw_active`；`_cw_active` 在 confirm/rollback 期间置位、阶段空闲清位。**（r4 增补）`reopen_stage` 期间同样保持 `_cw_active`，空闲（reopen 修订确定/放弃）才清位**，防止回看世界书期间与自动档并发。

**（r3 保留）H1（宿主改指 CwDialogueDock）**：`submitCwMessage(agent,text)` / `startCoWriting()` / `resolveCwStage(action)`。回归：新槽+新分支+`_cw_active`守卫，不触碰既有路径。

### 3.5 对话区 <-> 确定按钮 的交互语义（用户原话逐条落地）

| 阶段 | 对话流程 | 「确定」按钮 |
|------|----------|--------------|
| cw_core 核心设定 | Console 先用预设给一个「设定范例」→ 用户提修改思路 → 与设定子 Agent 讨论 → 直至收敛 | 点「确定设定」→ 启动设定总结 → 定稿 `设定/题材定位.md` |
| cw_outline 大纲 | Console 按预设给一个「简单大纲 + 全书想表达的主题」→ 与大纲子 Agent 讨论多次 | 点「确定大纲」→ 启动大纲总结（§3.3）→ 可小幅修改 或 打回上一步继续讨论重新做 |
| cw_worldbook | 设定/大纲已定 → 生成世界书与正则草案 → 与用户一起确定 | 点「确定世界书/正则」→ 世界书总结定稿（只写 `设定/世界书.md`+`设定/正则.md`，不产单元总纲） |
| cw_unit | 先给「紧接着上文内容的几章细纲」给灵感 → 用户定单元范围+主题（±10章）→ 深讨单元故事 | 点「确定单元」→ 单元总结定章数 + 剧情 → **写单元总纲（唯一属主）** → 章细纲滚动生成 |
| cw_prose | 据细纲生成章正文 → 用户键盘改 → 保存(临时)/确定(终稿) | 点「章节内容确定」→ 终稿锁定（§6） |

---

## 4. 世界书与正则

### 4.1 文件落地

- **世界书**：`设定/世界书.md`（新增文件）。结构：板块（境界/势力/资源规则/能力边界/限定与代价）+ 每个板块的「必须成立约束」清单。
- **正则**：`设定/正则.md`（新增文件）。**默认解释为『故事逻辑硬约束规则集』**（逻辑封闭边界）：每条 = 一条「若 A 则 B 且必须 C」的不可违反逻辑式，供审校槽与主 Agent 逐条比对。命名沿用用户词「正则」，实为「逻辑约束规则集」。

**【修订r4 · LOW-1：正则语义确认 + 两种结构的可切换承载】**

r3 §4.1 已透明声明把「正则」解释为逻辑约束而非字面正则表达式（regEx）。评审建议与用户确认；本轮因会话上下文无法实时弹问（ask_user_question 不可用），**把该决策作为待确认项写进方案，并把两种结构的落盘都写清，保证任一本意都可执行**：

- **默认（推荐）——逻辑约束规则集**：`设定/正则.md` 存「正则/必须成立约束」清单，每条为不可违反逻辑式；审校槽 `ruling_check` 与主 Agent 逻辑比对逐条消费。`设定/世界书.md` 额外带一栏「可固化正则的规则方向」，供世界书 Agent 提炼规则条目。
- **备选——若用户实为『字面正则表达式』**：则 `设定/正则.md` 改为 `正则规则清单 + 文本匹配样本` 结构（每条 = `name / pattern / 匹配说明 / 惩罚句/替换建议`），审校槽用 `re` 对正文做文本级匹配校验；世界书阶段产该文件，worldbook_block 注入改注入匹配样本集。
- **实施开关**：M2 实施前在设置面板露一个单选「『正则』语义」，二选一；`co_dialogue.build_prose_context()` 与 `stages.ruling_check` 只依赖抽象接口 `regex_rules(proj) → list[dict]`，两种结构均映射到同一 dict 契约，切换不改审校/主 Agent 消费逻辑。**此决策不阻塞本方案其余部分**；默认按逻辑约束集推进，用户选择字面正则时仅换 `设定/正则.md` 结构与 regex_rules 解析实现。

- **单元总纲**：`大纲/单元总纲.md`（新增）——**唯一属主 = cw_unit**（§1.1 SEV-1）；世界书/正则与大纲的结构化桥梁（§5.2）。

### 4.2 现有 `world_rules` 字段的关系

- `presets.grow_worldbook_direction` 与世界书**模板方向**相关（参考）；
- 既有 `world_rules`（既有六字段之一）是**注入正文 prompt 的题材世界规则**，保留；
- 世界书 `设定/世界书.md` 是**项目级最终确认版**（比 `world_rules` 更细、更锁定），生成时以预设的 `grow_worldbook_direction` + `world_rules` 为参考，最终以用户确认的 `世界书.md` 为准。
- `genre_block()` 注入的可选：`stages._genre_block()` 可升级为「世界书 + 正则」优先，若 `设定/世界书.md` 存在则以它为主、`world_rules` 为辅；否则回退用纯 `genre_block()`（旧项目/自动档不破）。

### 4.3 生成流程（与用户一起确定）

1. **草案生成**：世界书子 Agent 基于「核心设定 + 大纲 + 预设 grow_worldbook_direction」生成 `世界书.md` 草案 + `正则.md` 草案。
2. **对话敲定**：CwDialogueDock 对话区与用户逐条过世界书板块与正则条目，用户增删改。
3. **确定**：点「确定世界书/正则」→ 定稿（只写 `设定/世界书.md`+`设定/正则.md`）。
4. **注入下游**：写入后的 `世界书.md` + `正则.md` 注入写作 prompt、审校 prompt、主 Agent 上下文（§4.4）。
5. **回看修订**（§1.2 SEV-1 reopen）：后续 cw_unit/cw_prose(非锁定章) 提供「回看世界书」入口 → reopen → 修订后重确定 → 刷新未锁定下游的世界书引用，锁定章经 supervisor 提示 + 显式解锁后重核。

### 4.4 注入路径

| 下游 | 注入方式 | 注入点 |
|------|----------|--------|
| 正文写作（writing 槽）· **自动档** | `stages.chapter_microcycle` 组装 PROSE_WRITING_PROMPT 时，把「本书世界书（节选）+ 正则清单」并入 `genre_block` 或新增 `worldbook_block` 字段 | `app/core/stages.py` |
| 审校（review 槽）· **自动档** | `_chapter_review` 的 REVIEW_PROMPT 增 `ruling_check` 字段 = 正则清单 | `app/core/stages.py` |
| **正文写作（writing 槽）· 共写档**【修订r3·H2】 | `DialogueWorker`（`agent='prose'` / `'readback'`）组装 `CO_PROSE_WRITE_PROMPT` / `CO_READBACK_PROMPT` 时，**同样并入 `worldbook_block` + 正则清单**（与 stages 两调用点共用同一空串回退）：`co_dialogue.build_prose_context()` 读 `设定/世界书.md`+`设定/正则.md`，nullable 项目/缺失时传 `""`，模板内用「（本书未启用世界书/正则）」占位。「对话区修改」路径同一函数注入，保证**共写正文也被世界书/正则约束** | `app/core/co_dialogue.py` |
| **审校（review 槽）· 共写档**【修订r3·H2】 | 共写档「读改揣摩」（`agent='readback'`，复用 review 槽连接）与「章节确定」前的跨章校验 prompt 组装时**并入 `ruling_check`**（`CO_READBACK_PROMPT` / `CO_REVIEW_CW_PROMPT` 共用 `ruling_check` 占位符，空串回退同 §r2） | `app/core/co_dialogue.py` |
| 主 Agent（supervisor，§7） | 主 Agent 校验上下文接世界书+正则，做「逻辑一致性」比对 | `app/core/agents.py`(新) |
| 细纲（helper 槽） | `CHAPTER_OUTLINE_PROMPT` / `CO_CHAPTER_OUTLINE_PROMPT` 增世界书约束块 | `app/prompts/planning.py` / `app/prompts/co_dialogue.py` |

**（H2 一致性声明）**：自动档走 `stages.chapter_microcycle`/`_chapter_review`，共写档走 `co_dialogue.build_prose_context()`/`CO_*_PROMPT`，两条路径都拿到 `worldbook_block` 与 `ruling_check`，共用同一空串回退。**（r4）`ruling_check` 内容经 `regex_rules(proj)` 抽象读取，兼容『逻辑约束集』与『字面正则样本』两结构（§4.1 LOW-1）。**

**（r2 保留）漏洞8：新增 prompt 的 .format 占位符必须全调用点同步补参**：`stages.chapter_microcycle`（L377-394）与 `_chapter_review`（L555-565）两个自动档调用点必须同步补 `worldbook_block=""`/`ruling_check=""`；`co_dialogue.build_prose_context()` 与共写审校路径同步补（`CO_PROSE_WRITE_PROMPT`/`CO_READBACK_PROMPT`/`CO_REVIEW_CW_PROMPT`），抽 `worldbook_context(proj)` 便携空串回退。

**【修订r4 · SEV-2：改写探针规格 —— 世界书格式探针不再『跑完整微循环』，改为『router 打桩 + 组装期断言』】**

r3 §4.4 与 §9 M2 承诺 `probe_worldbook_format.py`「无世界书项目跑 `chapter_microcycle`（stages.py L377）/ `_chapter_review`（L555）不抛 KeyError」——但已核对这两个函数内部（L396 `_stream(ctx, ...)`、L569 附近）都会走 `router.client(slot).chat_stream` **发起真实 LLM 调用**，单测探针无法跑它们而不撞网络；如此探针按原描述不可执行，正是「18/18 不破 + 不抛 KeyError」中最高风险改动点（动两处自动档热路径）的可落地验证缺失。本版**改写探针规格**，明确用打桩把『组装』与『网络调用』分离：

- **探针改名并重定义为『组装期（format）探针』**：`probe_worldbook_format.py` **绝不调用 `chapter_microcycle` / `_chapter_review` 本体**（那会发 LLM），而是：
  1. **stub 一个 ctx 对象**（fake 组装上下文）：`ProbeCtx` 提供 `chapter_microcycle`/`_chapter_review` 在 `prompt = prompts.PROSE_WRITING_PROMPT.format(...)` / `prompts.REVIEW_PROMPT.format(...)` **之前的组装段所需字段**（`chapter_num/core_setting/outline/next_chapter_brief/global_summary/recent_summaries/character_states/foreshadows/previous_excerpt/style_sample/user_guidance/user_ideas/word_target/tic_blacklist/used_setpieces/genre_block` 等，逐个按 `PROSE_WRITING_PROMPT`/`REVIEW_PROMPT` 的占位符补齐），并用 **fake router**（`client().chat_stream`/`chat` 返回固定串、只记录收到的 prompt）**替换 LLM 连接**——**不触发网络**。
  2. 用旧项目（无 `设定/世界书.md`、无 `设定/正则.md`）走**组装路径**：断言 `prompts.PROSE_WRITING_PROMPT.format(...)` 与 `prompts.REVIEW_PROMPT.format(...)` **不抛 `KeyError`**，且世界书缺失时注入的是**空串/占位符文本**（`（本书未启用世界书/正则）`）。
  3. **对照断言证明『空串回退』闭环**：新增 `worldbook_block`/`ruling_check` 占位符后，`stages.py` L377 与 L555 两调用点 **若不补参 → format 抛 `KeyError`**（断言捕获到）；**补空串 → 通过**（断言通过）。用「缺参抛错 / 补空串通过」一对对照证明 H2 空串回退必须落地。
  4. **共写档组装点同样只断言组装不撞网络**：`co_dialogue.build_prose_context()` 返回的 `(worldbook_block, ruling_check)` 在无世界书项目下为空串；`CO_PROSE_WRITE_PROMPT`/`CO_READBACK_PROMPT`/`CO_REVIEW_CW_PROMPT` 的 `.format` 用该返回值不抛 `KeyError`（`co_dialogue` 组装函数本身可测，不触发 `_stream` 网络段；真正调用 `chat_stream` 的全部交给集成/冒烟阶段，不进 18/18 快速回归）。
  - **断言目标措辞统一**：从『跑 `chapter_microcycle`/`_chapter_review` 不抛 KeyError』改为『**组装期 `.format` 不抛 KeyError、空串回退正常**』——这是可落地、不依赖网络、可纳入 18/18 式快速回归的断言边界。
  - **纳入回归**：`probe_worldbook_format.py`（自动档两调用点组装）+ `probe_worldbook_format_co.py`（共写档三 prompt 组装）均入 M2 快速回归；真实端到端（含 LLM）走 smoke/集成，不进无网络探针。

---

## 5. 细纲二级结构（单元 → 章）

### 5.1 单元（Unit）

- **单元总纲** `大纲/单元总纲.md`：单元列表，每个单元 = `单元ID / 章节范围[start..end]（可±10章）/ 主题 / 主线推进行为 / 起止状态`。用户点击「确定单元」时由单元对话定：单元要呈现的主题 + 所用章节范围（**不写死，±10 章**，可整体完结于范围前/后）。**【修订r4】`大纲/单元总纲.md` 唯一属主 = cw_unit，由「确定单元」落盘（§1.1 SEV-1），其他阶段不写该文件。**
- **「单元剧情」存哪**：存于 `大纲/单元总纲.md` 对应单元条目下的「单元剧情（讨论后确认版）」小节——它是细纲与正文的契约源，不另起新文件，避免碎片化。

### 5.2 章细纲（滚动 5 章）

- **章细纲文件不变**：沿用 `大纲/细纲_第N章.md`（与现有流水线的 `project.get_outline_path` 完全一致 → 自动档可在此续跑，互不破坏）。
- **滚动生成**：用户上回写到第 5 章、确定单元为第 6–50 章后，细纲子 Agent **只生成第 6–10 章**（`OUTLINE_BATCH=5` 档位，共写档用 5，自动档维持 2），每章 ~200 字、简述该章需发生的事件与故事内容；写完这 5 章再进行下一批。
- **细纲可直接编辑**：像改小说一样改 `细纲_第N章.md`，改完点「确定细纲」→ Agent **读一遍用户修改后的细纲**并校验（重读→与单元剧情/世界书对账→给出「已确认 / 提出衔接修正」），也可在对话区提改进思路由 Agent 改，直到用户点「确定细纲」。

### 5.3 与现有细纲 prompt 的关系

**（r2 保留）漏洞3**：采纳 A，新增轻量 `CO_CHAPTER_OUTLINE_PROMPT`（每章 ≈200 字五栏：核心事件/承接上文/需推进的单元契约项/世界书约束提醒/章尾钩子），维持 `===第N章===` 分隔符（`parse_outlines` 可解析），`CHAPTER_OUTLINE_PROMPT` 重型版保留给自动档。新增 `probe_co_outline_parse.py`。

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
- **（r4·MED-1 接线）**：`locked` 跨档由 `isChapterLocked`/`attemptUnlock` 守卫消费（§0 MED-1），自动档 G9/regenerateStage 跳过或拒绝 locked 章。

### 6.2 用户改稿 → Agent 读改揣摩意图（共写闭环）

**【修订r4 · MED-2：读改触发开销显式化 + 可配开关】**

r3 §6.2「用户改稿点保存→Agent 读改揣摩」未写明触发频率。已核对 `saveChapterText`（bridge.py L866）本身用 `versions.snapshot` 判定「内容有变」，故「有改动即读」基本等于「每次有内容变动的保存都触发一次 `DialogueWorker(agent='readback')`（一次 LLM 调用，复用 review 槽）」。需求上用户确实这么要求、可接受，但本版**把成本预期与节流开关写死**：

- **触发规则明确 = 每次『内容有变』的保存触发一次 readback `DialogueWorker`**（复用 review 槽连接，`CO_READBACK_PROMPT`）；无改动的保存不触发（沿用 `versions.snapshot` 判定）。
- **可配开关**（设置面板，默认开）：
  - `readback_on_save`（默认 true）：是否「保存即读」；
  - `readback_min_diff`（默认 0 字，可调）：仅当 diff 字符数 ≥ 该阈值才触发，规避纯空白/单字改动噪音；
  - 用户也可在 `CwDialogueDock` 手动点「读一遍」随时触发（不经保存）。
- **成本预期写入 §10 风险表**：共写档单章成本 = 生成 1 次 + 读改揣摩（每存一次 N 次，默认 ≤ 用户保存次数）+ 章节确定 1 次 + supervisor 1 次；与自动档（每章草稿+审校+门）相比是**用户驱动、可预期**，不隐藏。
- - 用户在**对话区提出本章修改**：写作子 Agent 自动改「本章正文 + 本章细纲」两处（对齐用户意图），改完流式预览 → 用户「保存/放弃」。此路径同样复用 `DialogueWorker`（`agent='prose'`，system prompt 含本细纲 + 世界书正则 + 上章结尾）。

### 6.3 与现有版本/草稿系统兼容

- `.versions/` 30 版滚动、`.drafts/` 5s 防抖、崩溃恢复全部保留；
- 终稿锁定新增的 `locked` 字段是**增量**：旧章节无此字段 = 视为未锁定；`list_chapters`/`next_chapter_num` 等既有函数不受影响（只新增读取辅助），回归不破；
- 「保存还是临时稿」由 UI 文案区分（「保存（临时）」vs「确定章节（锁定）」），现行 `saveChapterText` 语义不变，只是按钮文案与新增确认按钮并存。
- **（r4·MED-1）**：`locked` 缺省 False，自动档不产 locked 章，锁定只在共写档「章节内容确定」产生；跨档时 locked 保持锁定，详见 §0 MED-1。

---

## 7. Agent 接力架构（重点）

### 7.1 角色清单 + 槽位映射

**（r2 保留）**：修正『独立槽位』→『独立提示词 + 独立上下文窗口，槽位可共享』；supervisor 复用 review 槽、不新增 `SLOT_ORDER`。

| 角色 | 槽位 | 职责边界（提示词职责） | 只注入的上下文（唯一来源） |
|------|------|------------------------|----------------------------|
| **设定 Agent** | writing | 生成核心设定参考稿 + 与用户讨论收敛 | 选题信息 + `grow_core_template` + 用户对话 |
| **大纲 Agent** | writing | 生成大纲稿 + 讨论 + 自动总结 | 核心设定产物 + `grow_outline_template` + 用户对话 |
| **世界书 Agent** | helper | 生成世界书/正则草案 + 对账 | 核心设定 + 大纲 + `grow_worldbook_direction`/`grow_regex_direction` |
| **细纲 Agent** | helper | 单元讨论 + 章细纲滚动生成 + 细纲重读校验 | 单元剧情 + 世界书/正则 + 上文结尾 + `grow_unit_logic` |
| **写作 Agent** | writing | 章正文生成 / 改稿 / 对话区修改 | 本细纲 + 世界书/正则 + 上文结尾 + 摘要链 + 用户改动意图 |
| **审校 Agent** | review | 一致性（沿用现有 `_chapter_review`，加正则比对）| 本章正文 + 世界书/正则 + 全局摘要 + 角色状态 + 伏笔 + 时间线 |
| **主 Agent（Supervisor）** | **复用 review 槽** | 范围控制 / 审文 / 去AI味 / 衔接比对 / 逻辑一致性 | **全量摘要 + 上一章结尾 + 下一章细纲 + 世界书/正则**（不做整章正文） |

**槽位机制落地**：每个共写阶段 = 独立 system prompt + 一个逻辑 Agent + 只注入上环节产物；通过 `app/core/agents.py` 实现「Agent 接力表」（上一环节产物读取器, 阶段 prompt 模板, 槽位, 产物路径）；**上下文交接协议**=结构化字段交接（3-6 条关键事实 + 开放问题），下一 Agent 只读交接收尾。

### 7.2 每个 Agent 的提示词职责边界（摘要）

（r3 保留）设定 Agent 只谈核心设定；大纲 Agent 只谈卷级；世界书 Agent 只谈世界规则；细纲 Agent 只谈单元与章；写作 Agent 只谈本章正文；审校 Agent 沿用现状加正则比对；**主 Agent** 边界=不重复写内容、不重复审校槽职责，只做范围控制/审文去AI味/衔接比对/逻辑一致性，不产生正文本身。

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

> 设计意图：没有任何子 Agent 的 prompt 包含「全书正文」全量；对话循环多轮累积同样只含「交接 ≤800 字 + 转写最近 ≤4k 字 + 本轮输入」（§3.2）。

### 7.4 主 Agent 与审校槽去重

- **审校槽** = 每章当下的一致性检查（章节内矛盾、设定冲突、伏笔、规则违反），产出 BLOCKING/ADVISORY，进 `_review_findings`。
- **主 Agent** = 跨章/跨阶段的范围与衔接监督（上一章↔本章↔下一章细纲的断裂、AI味复检、逻辑封闭性），不等同于逐章审校，不重复产同一份 BLOCKING/ADVISORY。
- 分工锚：审校槽做「单章内一致性」，主 Agent 做「章间衔接 + 全文范围 + 逻辑封闭」，两套 Findings 分开展示（审校槽进 StepGate G9；主 Agent 进 `CwDialogueDock` 报告区，触发点见 §3.0）。

---

## 8. UI 更改设计

### 8.1 阶段导航

**（r2 保留）漏洞7**：`PipelinePanel` 阶段卡片按 run_mode 切换——自动档维持 `stageCards()` 4 卡，`run_mode=='cw'` 用 `StageStepperCW` 六卡（`stageCardsCW()`）；左侧不新增 rail 图标。

### 8.2 每阶段视图（复用 Editor + Console）

| 区域 | 共写档用法 |
|------|------------|
| CwDialogueDock 对话区 | 当前阶段子 Agent 对话 + 门 Banner（确定/打回/回看/产物摘要） |
| 主编辑区 | 当前阶段**产物编辑**（设定.md / 大纲.md / 世界书.md / 细纲.md / 正文.md），常驻可编辑 |
| 思考链区 | 阶段 Agent 生成产物时的推理链（按槽位×阶段×章留存） |
| 状态栏 | 显示当前阶段 agent + 槽位 + 上下文量 |

- **阶段切换** = `CwDialogueDock.currentAgent` 切换 + 主编辑器载入对应产物文件（宿主为 M1 自带 dock，非 Console v3）。每个阶段顶部一个「✓ 确定」+「↩ 打回」按钮；`cw_unit`/`cw_prose`(非锁定章) 另露「回看世界书」按钮（§1.2 SEV-1）。

### 8.3 细纲编辑器

- 章细纲以列表/分章标签呈现（可编辑每章 200 字细纲），选某一章 → 主编辑区载入 `细纲_第N章.md`。
- 每章一个「确定细纲」校验按钮 + 支持对话区提思路由 Agent 改。

### 8.4 章节确定按钮位置

- 主编辑器顶栏 + CwDialogueDock 门 Banner 均放「保存（临时）」与「确定章节（锁定）」两键；`gateBar` objectName 契约保留。
- 已锁定章节编辑器 `readOnly`，顶栏显示「✓ 已确定（终稿锁定）」徽章；`cw` 下另放「解锁」入口（§0 MED-1）。

### 8.5 与阅读器/主编辑列布局整合（M1 最小 dock，Console v3 为可选升级）

**（r3 保留）H1**：`CwDialogueDock` 叠在现有主编辑列内部（不改 `[48 nav | 300 panel | 主编辑列]` 三列骨架）；`cw_unit`/`cw_prose`（非锁定章）在 dock 顶部多一个「回看世界书」动作（§1.2）。若将来合并 Console v3 才替换为独立列，共写逻辑零改动。

### 8.6 QML 组件树与 Main.qml 演进（伪代码级，M1 默认）

```qml
ApplicationWindow (width 1400) {            // M1 保持 1400，不加宽
    RowLayout {
        NavRail {}                          // 保留 5 图标
        PanelStack { BookshelfPanel/PipelinePanel/ChapterPanel/NotesPanel/SettingsPanel }
        ColumnLayout {                      // 主编辑列（既有 L304 内叠加）
            RowLayout {                     // M1：CwDialogueDock 与主编辑器并排
                CwDialogueDock {            // M1 自带，非 Console v3
                    property string currentAgent  // setting/outline/worldbook/unit/prose/supervisor/readback
                    GateBanner { /* 确定/打回/回看；沿用 gateBar objectName */ }
                    DialogArea { /* 阶段对话：run_mode=='cw' 时 发送→submitCwMessage；appendAgentReply(agent,text) */ }
                }
                EditorView { /* 阶段产物 / 正文；锁定章 readOnly */ }
            }
            StageToolbar { StageStepperCW {} // run_mode=='cw' 六卡（自动档仍 4 卡）；确定/打回/回看按钮；章节锁定徽章 }
            StepGateBar {}                   // 既有 541
            StatusBar {}
        }
        ReaderDockHost { ReaderView {} }     // 既有 836 全屏沉浸层；dock 收窄属后置 Console v3 升级
    }
}
```

> 注：`CwDialogueDock` 放主编辑列内部是本版与 r2 的关键差异；Console v3 合并后再迁移独立列（§8.5）。

**回归不破要点**：所有新增 UI（StageStepperCW、`CwDialogueDock`、章节锁定/解锁、`stageCardsCW`、回看世界书）都是**新增属性/组件/条件分支**，不改动现有 `gateBar`/`panelStack`/`readerView`/`StepGateBar` 的 objectName 与既有数据契约；`stageCards` 4 卡在自动档原样保留；既有 18/18 + 冒烟 + 门 4/4 + UI 探针 8/8 **预期不破（待 M1 实施后实跑复核，§LOW-2）**，仅新增探针。

---

## 9. 实施里程碑（M1-M5）

**（r3 保留）H1/M1/M2/M3 修订**：M1 自包含化 + `_cw_active` 互斥 + `state['cw']` 键分离 + 显式 `rollback_stage`。**（r4 叠加）** 各里程碑补 SEV-1/SEV-2/MED-1 对应探针与实现。

**M1 — 最小对话 dock + 阶段状态机骨架 + cw 运行档接线**（不依赖 Agent Console v3，自包含）
- 新增 `CwDialogueDock`（§3.1/H1）、`app/core/co_dialogue.py`（`CwTranscript`/`DialogueWorker`/`build_turn_message`/`build_prose_context`）、`app/core/co_writing.py`（`CoWriting.run_stage` + `summarize_stage` + `rollback_stage`（五个显式实现）+ **`reopen_stage('cw_worldbook')`（§1.2 SEV-1）** + `load_cw_state/save_cw_state`）、`app/core/state.py`（`STAGE_*_CW` 常量+跳转表）、`app/prompts/co_dialogue.py`（阶段 prompt + `CO_SUMMARIZE_*_PROMPT`）。
- 改 `app/ui/bridge.py`：`setRunMode` 白名单加 `"cw"`、`_cw_active` 双头守卫、`submitCwMessage`/`resolveCwStage`；**（r4）reopen 期间保持 `_cw_active`**。
- 改 `Main.qml`/`PipelinePanel.qml`（`CwDialogueDock` + `StageStepperCW` + `run_mode` 分支 + 确定/打回按钮初版 + 「回看世界书」入口初版）。
- 回归：`assert_v099.py`（18/18 不破）+ `smoke_func` + `probe_gate_*` + CW 状态机探针（六阶段推进、打回矩阵 + `state['cw']` 键分离）+ 对话循环探针 + 互斥探针 + **（r4·SEV-1）`probe_reopen_worldbook.py`（reopen 软切 cw_worldbook、修订重确定后刷新未锁定下游世界书引用、锁定章不动）**。

**M2 — 预设升级 + 世界书/正则**
- 改：`app/presets/*.json`（+4 grow 字段）、`app/presets/__init__.py`（`grow_block`）、`app/core/co_writing.py`（世界书 Agent）、`app/prompts/planning.py`、`app/core/stages.py`（worldbook 注入写作/审校，含 §4.4 `.format` 双调用点补参）、`app/core/co_dialogue.py`（`build_prose_context`，共写三路径注入 + 空串回退）、`app/project.py`（世界书/正则/单元总纲路径辅助）。
- **（r4·SEV-2）改写探针**：`probe_worldbook_format.py` 规格改为 **router 打桩 + 组装期 `.format` 断言**（不跑完整微循环、不发 LLM，§4.4 SEV-2），并新增 `probe_worldbook_format_co.py`（共写三 prompt 组装断言）；`probe_worldbook.py`（文件落地 + 注入 writing/review prompt 结构断言）。
- **（r4·LOW-1）`regex_rules(proj)` 抽象接口 + 设置面板「『正则』语义」单选**（逻辑约束集/字面正则样本两结构可切换承载，§4.1）。

**M3 — 细纲二级结构**
- 改：`app/core/co_writing.py`（单元讨论 + 章滚动 5 章 + `rollback_stage` 三条含细纲/单元级联失效实现 + **`reopen_stage` 的打回矩阵行**，§1.2）、`app/prompts/co_dialogue.py`（`CO_CHAPTER_OUTLINE_PROMPT`）、`app/prompts/planning.py`、`StepGateBar.qml`（确定细纲/打回单元/回看世界书）、PipelinePanel。
- 回归：`probe_outline_batch` 变体 + LOL 兼容（`OUTLINE_BATCH` 自动档仍 2）+ `probe_co_outline_parse.py` + 打回级联探针 + **（r4·SEV-1）单元总纲属主探针（cw_worldbook 产物不含单元总纲、cw_unit 确定单元才写）**。

**M4 — 章节确定语义 + locked 跨档**
- 改：`app/core/versions.py`（`locked` 标记辅助）、`app/ui/bridge.py`（`saveDraft`=临时保存 / `confirmChapterLocked` + `readChapterLocked` + **`isChapterLocked`/`attemptUnlock`（§0 MED-1）** + **`regenerateStage` 对 locked 细纲/设定走跳过守卫（§0 MED-1）**）、`app/prompts/co_dialogue.py`（`CO_READBACK_PROMPT` + **`readback_on_save`/`readback_min_diff` 配置（§6.2 MED-2）**）、`Main.qml`（保存/确定双键 + 锁定徽章 + 解锁入口 + 锁定只读）、`tests/probe_chapter_lock.py`。
- 回归：版本系统既有断言 + 锁探针 + **（r4·MED-1）`probe_chapter_lock_cross_mode.py`（locked 章切自动档后 G9/regenerateStage 跳过或拒绝、attemptUnlock 放行、migrate_project_mode(to_cw) 保持 locked）**。

**M5 — Agent 接力 + 主 Agent**
- 改：`app/core/agents.py`(新)、`app/core/co_writing.py`（接力编排 + supervisor 两触发点 + **reopen 后世界书变更提示接线（§1.2 SEV-1）**）、`app/core/orchestrator.py`（supervisor 挂点，复用 review 槽）、`app/prompts/co_dialogue.py`、`Main.qml`/`CwDialogueDock`（supervisor 报告区）。
- 回归：M1-M4 全套 + `probe_agent_relay.py`（每个逻辑 Agent 只注入上环节产物/交接收尾、上下文上限断言；supervisor 触发且不产正文）+ 全自动档 `probe_gate_flow` 不破。

---

## 10. 风险与规避

| 风险 | 影响 | 规避 |
|------|------|------|
| 上下文量失控（全书变长） | 成本/质量 | 结构化交接 + 摘要链 + 上下文上限表（§7.3）+ 对话循环转写截断（§3.2）；主 Agent 不拼全文正文 |
| API 成本（每章调用次数变化） | 成本 | 共写档**用户驱动、可预期**：生成 1 + 读改揣摩（每内容有变的保存 1 次，受 `readback_on_save`/`readback_min_diff` 节流，§6.2 MED-2）+ 章节确定 1 + supervisor 1；自动档维持原次数；可配置 |
| 旧项目数据迁移（无世界书/无单元） | 兼容 | `load_preset` 缺字段容错；旧项目无世界书/单元时共写档自动补生成或用占位；`locked` 缺省=未锁；`.format` 空串占位承接（§4.4） |
| 旧流水线兼容（自动档保留） | 回归 | 两档并行：`stage` 常量并存、`OUTLINE_BATCH` 自动档仍 2、`genre_block` 不动、gateBar/panelStack/readerView objectName 不动、`chapter_microcycle`/`_chapter_review` 自动档调用点补参且空串兼容（§4.4） |
| **locked 章被自动档重写**（MED-1） | 终稿丢失 | `isChapterLocked`/`attemptUnlock` 守卫：G9/regenerateStage 跳过或拒绝 locked 章；显式解锁唯一放行；migrate 保持锁定（§0 MED-1） |
| **readback 调用开销**（MED-2） | 成本 | 每次内容有变保存 1 次 + `readback_min_diff` 阈值 + `readback_on_save` 开关（§6.2）；成本进 §10 已列 |
| Agent 接力丢上下文（交接遗漏） | 剧情断裂 | 「交接收尾」结构化块 + 主 Agent 衔接比对（上章结尾↔下章细纲↔本章开头）作为兜底 |
| 正则/世界书过度锁定 | 阉割创作 | 全部 grow_ 字段「参考不锁定」措辞护栏 + 世界书可 reopen 回看修订（§1.2 SEV-1） |
| **世界书变更影响已锁定章**（SEV-1） | 前后不一致 | supervisor 提示「世界书变更影响第 N 章」+ 用户显式解锁后重核（§1.2/§0 MED-1） |
| 确定按钮误触发 | 误操作 | 确定=总结定稿后仅小幅修改可改；需要改结构走打回；锁定章只读 |
| supervisor 槽位静默回退 | 用户困惑 | supervisor 复用 review 槽、无独立槽位（§7.1 修订），不引入静默回退链 |

---

## 附：评审漏洞清单 → 修订对照

**（r2/r3 修订对照保留，摘要）**：r2 漏洞 1-8（对话循环组件级 / 总结器 / 轻量细纲 / 执行模型 / run_mode 接线 / SLOT_SUPERVISOR / stageCards / .format 补参）+ r3 漏洞 H1/H2/M1/M2/M3/L1/L2（见文末 r4 对照之上的 r3 表）。

**【修订r4 · 新增 r4 评审漏洞 → 修订对照】**

| # | 严重度 | 评审点 | 本版（r4）修订位置 |
|---|--------|--------|--------------------|
| SEV-1 | 设计连贯性 | ① 阶段表 row4/row5 都把 `大纲/单元总纲.md` 挂为产物，同文件两属主；② 「程序大纲」为「剧情总大纲」笔误；③ 「世界书并行/可回看」与「严格串行状态机」不可调和，未裁决 | §1.1：裁决**单元总纲唯一属主 = cw_unit**，cw_worldbook 产物只写 `设定/世界书.md`+`设定/正则.md`，删 `(重构)`；全文「程序大纲」→「剧情总大纲」；§1.2：**新增世界书 reopen 回边**（cw_unit/cw_prose 非锁定章回看 → reopen 软切修订 → 刷新未锁定下游、锁定章提示显式解锁），裁决采纳「三段串行 + 可回看回边」，删「并行轨道」脚注；§5.1/§3.5/§9 M3 同步对齐 |
| SEV-2 | 回归不可执行 | `probe_worldbook_format.py` 承诺『跑 chapter_microcycle/_chapter_review』，但两者内部走 `_stream` 发真实 LLM（L396/L569），无网络探针不可执行 | §4.4 + §9 M2：**改写探针规格 = router 打桩（stub ctx + fake router 记录 prompt）+ 只断言 `.format` 组装不抛 KeyError、空串回退、缺参抛错对照**；显式「不跑完整微循环、不发 LLM」；新增 `probe_worldbook_format_co.py`（共写三 prompt 组装） |
| MED-1 | 跨档边界 | cw↔自动档切换未处理 locked 章；G9（orchestrator L167-174 os.remove）/regenerateStage（bridge L1548-1586 删细纲）会重写已锁定正文/细纲，与 M4 锁定冲突 | §0：**locked 章跨档处置**——G9/regenerateStage 跳过或拒绝 locked 章、`isChapterLocked`/`attemptUnlock` 守卫、显式解锁唯一放行、migrate(to_cw) 保持 locked、自动档不产 locked 章；§9 M4 新增 `probe_chapter_lock_cross_mode.py` |
| MED-2 | 读改触发开销 | §6.2 每次保存触发一次读改 DialogueWorker，无节流说明 | §6.2 + §9 M4 + §10：**读改触发 = 每次内容有变的保存 1 次**（复用 review 槽）+ `readback_on_save` 开关 + `readback_min_diff` 阈值 + 手动「读一遍」；成本预期写进风险表 |
| LOW-1 | 术语解释 | 「正则」解释为逻辑约束集，建议与用户确认 | §4.1：**两种结构可切换承载**（默认逻辑约束集 / 备选字面正则样本），抽象 `regex_rules(proj)` 接口，设置面板单选；因会话问询不可用，作为待确认项写清，不阻塞其余部分 |
| LOW-2 | 自检表夸大 | 「18/18+冒烟+门4/4+UI探针8/8 不破」写为已核验事实，未实跑 | 顶部定位 + §8.6/§9 + 自检表：改**「预期不破（待 M1 实施后以 assert_v099/smoke_func/probe_gate_*/probe_gate_ui 实跑复核 + 新增 CW 探针）」**，预测与实测分层标注 |
| LOW-3 | 措辞笔误 | 「程序大纲」「(重构)」残留标注；事件对接表 cw_worldbook 产物含单元总纲与 §5.2 冲突 | §1.1/§3.5/§9：清理「程序大纲」「(重构)」；单元总纲统一属主 cw_unit（§1.1 SEV-1 a），cw_worldbook 产物仅两文件 |

---

## 附：硬约束逐条自检

**【修订r4 · LOW-2：自检表『不破』改标『预期不破』，预测与实测分层】**

- **只出方案不改码**：本文件为纯设计，无 diff。✔
- **可实施可回归**：所有新增为增量（新状态/新组件/新字段/新条件分支）；既有 18/18+冒烟+门4/4+UI探针8/8 **预期不破**（§8.6/§9 M1 实施后以 `assert_v099`/`smoke_func`/`probe_gate_*`/`probe_gate_ui` 实跑复核 + 新增 CW 探针；本文标记为预测而非实测），`chapter_microcycle`/`_chapter_review` 调用点仅补空串参数（不含 KeyError），每里程碑附回归清单。✔
- **与自动流水线共存**：两档位共享状态机与槽位，自动档保留，`run_mode` 分支隔离；locked 章跨档受控（§0 MED-1）。✔
- **Agent 接力落到槽位机制**：每个逻辑 Agent = 独立提示词 + 只注入上环节产物（含交接收尾 + 转写截断），槽位共享 writing/helper/review（§7.1/§3.2）✔
- **主 Agent 职责边界**：不写内容、不抢审校槽，只做范围/衔接/逻辑，复用 review 槽（§7.4/§7.1）✔

**【修订r3 · 硬约束逐条自检（r3，保留）】**
- 可实施/自包含（H1）✔ · 世界书/正则约束到共写正文（H2）✔ · 两档互斥真正成立 `_cw_active`（M1）✔ · 状态机共存键分离 `state['cw']`（M2）✔ · 打回可落地五个 `rollback_stage`（M3/L1）✔ · 主 Agent 已接线两触发点（L2）✔

**【修订r4 · 硬约束逐条自检（r4）】**

- **设计连贯性裁决**：单元总纲唯一属主 = cw_unit；世界书阶段只产 `设定/世界书.md`+`设定/正则.md`；全文「剧情总大纲」无「程序大纲」残留；「世界书可回看」落成显式 reopen 回边（§1.1/§1.2）✔（SEV-1）
- **回归探针可执行**：世界书格式探针改为 router 打桩 + 组装期 `.format` 断言，不发 LLM、无网络依赖、可入 18/18 快速回归（§4.4）✔（SEV-2）
- **locked 章跨档自洽**：G9/regenerateStage 跳过或拒绝 locked 章、显式解锁唯一放行、migrate 保持锁定（§0）✔（MED-1）
- **读改成本显式**：每次内容有变保存 1 次 + 阈值/开关节流 + 成本入风险表（§6.2/§10）✔（MED-2）
- **正则语义可切换承载 + 待确认**：`regex_rules(proj)` 抽象，两结构二选一，不阻塞（§4.1）✔（LOW-1）
- **自检分层**：预测 vs 实测标注（顶部 + §8.6 + 自检表）✔（LOW-2）
- **残留清理**：单元总纲属主统一 cw_unit、删「程序大纲」「(重构)」（§1.1/§3.5/§9）✔（LOW-3）

---

**方法说明**：本轮为纯文档修订，未改任何程序代码（满足"只出方案"约束）。已先核对了 r4 评审所引全部代码现实：`_apply_rollback`（orchestrator.py L146-179）仅硬编码 G2/G9、G9 L167-174 对章 `os.remove`；`bridge.regenerateStage`（bridge.py L1548-1586）`ch_outline` 按 `n>=next_chapter_num` 批量删细纲；`stages.chapter_microcycle`（L377 `.format` → L396 `_stream` 发真实 LLM）确认 SEV-2 探针不能跑完整微循环。修订据此对齐真实组件。产出为经修订的完整方案 `docs/plan_co_writing_v4.md`；可回归契约（18/18+冒烟+门4/4+UI探针8/8）标注为**预期不破（待 M1 实施后实跑复核）**，仅新增探针。
