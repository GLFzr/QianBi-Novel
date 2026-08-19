# 共写工作流 2.0 — 终版方案（v5 Final）

> 项目：千笔一文 Novel（QianBi-Novel）· PySide6 + QML Windows 桌面「人 AI 共写长篇小说创作台」
> 状态：**设计文档，本轮不动任何程序代码**。经 4 轮「设计 → 深度评估 → 修订」循环（8 个评审/修订 Agent 参与，逐条对照源码核验），最终评审 5 条修法（HIGH-1/HIGH-2/MED-3/MED-4/MED-5）已在本版全部落地。v4 及此前各版作为过程稿保留在 `docs/plan_co_writing_v4.md` 等，本版为整合后的最终参照。
> 定位：与现有「自动流水线（全自动模式）」**共存**——共写档是给每个产物加一层「先讨论、后确定」的壳，最终产物结构与自动档完全一致，旧项目/自动档续跑/一键全自动全部保留。

---

## 0. 总览

现有 `orchestrator.run()` + `stages.*`（A1-A4/B1/C1-C7）一口气跑完 = **自动档（保留现状，Step Gates 决策门不变）**。
新增 **共写档（co-write）**：六阶段人机共写，每阶段「对话区讨论 → 点确定 → 讨论结果自动总结成产物」，流程严格按用户原话：

```
创建项目（选预设/自定义主题）
  → 核心设定（预设给范例 → 讨论 → ✓确定设定）
  → 剧情总大纲（给简纲+主题 → 与大纲 Agent 讨论 → ✓确定大纲 → 可小幅修改 / 打回重议）
  → 世界书+正则（生成 → 与用户一起确定 ✓确定世界书/正则）
  → 单元细纲（灵感细纲 → 定单元范围/主题(±10章) → 讨论单元 → ✓确定单元
       → 滚动生成 5 章细纲(≈200字/章) → 可直接改或 Agent 改 → ✓确定细纲）
  → 正文写作（按细纲生成 → 用户键盘改 → 保存=临时；Agent 读改揣摩 / 对话区提改
       → ✓章节确定=终稿锁定）
```

共享同一 `pipeline_state.json`、同一 `ModelRouter` 三槽位、同一产物落盘路径与版本系统。

---

## 1. 阶段状态机

### 1.1 状态定义（与自动档键分离）

`app/core/state.py` 新增独立 `STAGE_*_CW` 常量 + 独立跳转表，只写 `state['cw']['stage']`，**绝不碰**自动档 `state['stage']`。项目打开按 `state['cw']['mode']` 判定档位粘性，cw↔自动档为受控切换（`migrate_project_mode`，仅阶段空闲时可切）。

| # | key | 中文名 | 阶段产物（落盘） | 「确定」行为 |
|---|-----|--------|------------------|-------------|
| 1 | `cw_project` | 创建项目 | `设定/选题信息.md` + `pipeline_state.cw_preset` | 选预设/自定义主题，写选题信息 |
| 2 | `cw_core` | 核心设定 | `设定/题材定位.md` | 预设范例 → 对话迭代 → 确定=总结定稿 |
| 3 | `cw_outline` | 剧情总大纲 | `大纲/大纲.md` | 简纲+主题 → 讨论 → 确定=自动总结成大纲 |
| 4 | `cw_worldbook` | 世界书与正则 | `设定/世界书.md` + `设定/正则.md` | 与用户一起确定（本阶段不产单元总纲） |
| 5 | `cw_unit` | 单元细纲 | `大纲/单元总纲.md` + `大纲/细纲_第N章.md` | 单元讨论确定 → 写单元总纲 → 章细纲滚动 |
| 6 | `cw_prose` | 正文写作 | `正文/第N章.md`（+`.versions/`） | 临时草稿 → 章节确定=终稿锁定 |

**属主裁决**：`大纲/单元总纲.md` 唯一属主 = **cw_unit**（「确定单元」对话产出），cw_worldbook 只产世界书+正则两文件。

### 1.2 流转与打回矩阵

```
cw_project ─✓─▶ cw_core ─✓─▶ cw_outline ─✓─▶ cw_worldbook ─✓─▶ cw_unit ─✓─▶ cw_prose
                    │◀─打回──│◀─打回──────│◀─打回──────────│◀─打回──────│◀─打回本章(确定前)
```

- **✓确定按钮语义（全局统一）**：点击 = 把该阶段对话区**已收敛的讨论**做一次「总结定稿」调用，写成结构化产物 = 锁定该产物，状态机前进。
- **↩打回按钮**：`rollback_stage(stage_key)` 级联失效下游产物并归档 `pipeline_debug/rollback/`：
  - core 打回 → 失效 大纲/全部细纲/世界书/正则/单元总纲
  - outline 打回 → 失效 全部细纲（大纲重拟）
  - worldbook 打回 → 失效 全部细纲（世界书变了契约）
  - unit 打回 → 失效 全部细纲；单元内打回 → 重开单元讨论
  - cw_prose 章节确定前打回 → 重写本章
- **世界书回看回边（reopen）**：cw_unit / cw_prose（非锁定章）提供「回看世界书」入口 → `reopen_stage('cw_worldbook')` **软切**（保留下游转写与已锁定产物）→ 修订后重确定 → 写回世界书/正则 → **自动刷新未锁定下游的世界书引用**，已锁定章不自动改，由 supervisor 提示「世界书变更影响第 N 章，建议显式解锁后重核」。
  - reopen 与打回的区别：reopen 不级联删除、只刷新引用；打回才级联。

---

## 2. 预设体系升级

现有六字段（`style_hint/world_rules/plot_conventions/taboos/deslop_extra/review_extra`）**保留不动**（`genre_block()` 回归不破）。新增四个「共写参考字段」`grow_*`，全部带「仅供参考、不得锁定死」护栏，且**不进 genre_block**、由共写档阶段 Agent 单独经 `presets.grow_block(preset_id, field)` 读取：

```jsonc
{
  "id": "cultivation", "name": "修仙·凡人流", "version": 2,
  // 既有六字段不动…
  "grow_core_template":     "同类型核心设定的优秀设计参考（金手指/成长线/读者契约/核心期待债…）",
  "grow_outline_template":  "同类型大纲的体量划分/卷级/终局储备范式…",
  "grow_worldbook_direction":"同类型世界书应覆盖哪些板块（境界/势力/资源规则/限定与代价…）",
  "grow_unit_logic":        "同类型小单元细纲逻辑：爱情线/案件单元/副本单元的开-承-转-合模板…",
  "grow_regex_direction":   "同类型适合固化成'必须成立约束'的规则清单方向…"
}
```

- 自定义主题 = 空预设流程（`cw_preset=""`，跳过 grow_* 块，通用主干 prompt），其余流程完全一致。
- 用户导入的旧 JSON 缺字段 → 占位「该预设未提供此参考」，不报错。

---

## 3. 共写对话机制（含 Agent 交接的提示词落地）

### 3.0 提示词注入方式【HIGH-1 落地 · 必须二选一，推荐①】

**事实**：现有代码**没有** per-slot system prompt——`llm/router.py` 的 `client(slot)` 只做连接路由，所有 `chat/chat_stream` 调用走默认 `system=""`（stages.py L133/525/535/568/627、bridge.py L64/272/300 均已核对）。「每个子 Agent 有自己的提示词」= **新增机制**，两种实现：

- **方案①（推荐）**：把各阶段 Agent 的完整提示词（角色职责+该阶段约束+参考块）**拼进 user body**，走现有 `chat_stream(prompt)`——不改 client 调用签名、零回归、与现有上下文组装方式一致。
- **方案②**：给 `LLMClient.chat_stream` 调用点新增 `system=` 传参（client 已支持 system），**只对共写新路径注入**，自动档保持 `system=''` 不破。
- 落地时按方案①对齐全文措辞；选②则只改新路径调用点。

### 3.1 执行模型

共写档 = **主线程驱动的交互状态机** `co_writing.CoWriting`：阶段内讨论 = 用户敲字 → 主线程启动**一次性 `DialogueWorker`**（QThread，不常驻不阻塞 UI）→ 组装「上环节交接块 + 转写摘要 + 本轮输入」为 user 消息 → 流式回进 `CwDialogueDock` → 完成即退出。每轮用户输入独立启动新 worker。不进 `orchestrator.run()`。

### 3.2 交接协议【HIGH-2 落地 · 交接块有唯一属主】

**事实**：此前「结构化字段交接（3-6 条关键事实+开放问题）」无属主无生成步骤，接力链第 N 段上下文来源悬空。

**落地**：
- `SummarizeWorker`（阶段「确定」时的总结定稿调用）输出结构强制为两段：
  1. **产物正文**（沿对应阶段产物结构，见 §9 跨档契约）；
  2. **文末固定小节「→ 下阶段交接」**：3-6 条关键事实 + 开放问题，≤800 字。
- 交接小节由**唯一生成者**产出：`build_handoff(stage, transcript)`（落 `co_dialogue.py`），写进 `CO_SUMMARIZE_*_PROMPT` 的格式要求（该节必须输出）。
- 下一阶段 Agent 的上下文 = **只读上一阶段交接小节**（≤800 字）+ 该阶段参考块 + 用户对话转写（最近 ≤4k 字）。
- 对话转写截断累积：多轮讨论只保留最近 ≤4k 字摘要，防止对话区无限膨胀。

### 3.3 确定按钮的「总结定稿」与「小幅修改」

- 确定 = 对已收敛对话做一次总结调用（`SummarizeWorker`），不是新开讨论。
- 确定后产物可**小幅修改**（用户在产物编辑器直接改，改完点「保存修改」）；要改结构 → 走打回。

---

## 4. 世界书与正则

### 4.1 「正则」语义【MED-5 落地 · 默认值先行】

**事实**：此前把「正则」列为待确认项，但审校/主 Agent 的「必须成立约束」依赖它，核心路径不能悬空。

**落地**：
- 抽象接口 `project.regex_rules(proj) -> list[dict]`（每条：`{rule, level: must/should, scope}`）。
- **M2 默认按「逻辑约束规则集」落地**（不是字面正则表达式），写入 `设定/正则.md`；设置面板提供「『正则』语义」单选（逻辑约束集 / 字面正则样本），**只影响解析实现与写入结构，不阻塞核心路径**。
- 用户首次进入世界书阶段时 UI 提示二选一（先默认、可后改）。
- 生成流程：世界书 Agent 依据 核心设定+大纲+grow_worldbook_direction/grow_regex_direction 生成草案 → 对话区与用户逐条讨论 → ✓确定 → 落盘 `设定/世界书.md`+`设定/正则.md`。
- 注入：写作/审校/主 Agent 的 prompt 组装一律 `.format` 注入世界书/正则块，**空串回退**（旧项目无此文件时用占位，不抛 KeyError）。

### 4.2 世界书格式回归探针（SEV-2 已落地）

`probe_worldbook_format.py` 规格 = **router 打桩 + 组装期 `.format` 断言**（不跑完整微循环、不发 LLM、无网络）：断言三段 prompt 组装不抛 KeyError、空串回退、缺参抛错对照；`probe_worldbook_format_co.py` 覆盖共写三 prompt。

---

## 5. 细纲二级结构（单元 → 章）

- **灵感细纲**：进入 cw_unit 时，细纲 Agent 按预设提示词先给「紧接着上文内容的附近几章细纲」作灵感。
- **确定单元**：用户定单元范围（起始章 ~ 目标完结章，±10 章内可提前/延后完结）+ 单元主题 → 与用户**深度讨论单元故事** → ✓确定单元 → `大纲/单元总纲.md` 落盘（单元主题/章节范围/主线推进/起止状态）。
- **章细纲滚动生成**：确定单元后**只生成下一批 5 章**（如写到第 5 章、单元讨论第 6-50 章，则只做 6-10 章），每章 ≈200 字（核心事件+故事内容），写完 5 章再滚下一批。
- **细纲可直接编辑**：像改小说一样在编辑器改 `大纲/细纲_第N章.md`；或对话区提思路由 Agent 改。改完 ✓确定细纲 = Agent **自动重读一遍**用户修改的细纲并校验（与既定剧情/世界书/上文结尾的衔接），有问题在对话区指出。
- 与自动档兼容：自动档 `OUTLINE_BATCH` 仍为 2，互不影响。

---

## 6. 正文写作语义升级

### 6.1 两级提交

| 动作 | 语义 | 落盘 |
|------|------|------|
| **保存（临时）** | 现有 `saveChapterText` 语义不变，内容**可能再改** | `.drafts/` 防抖 + 5s 暂存，不产生版本语义变化 |
| **✓ 章节内容确定** | **终稿锁定**：内容不再改动 | 新增 `locked` 标记（存 `正文/.annotations/第N章.json`【MED-3 落地】），编辑器只读 + 「已确定（终稿锁定）」徽章 |

### 6.2 锁守卫放对层级【MED-3 落地】

**事实**：G9 回退发生在 orchestrator QThread worker（`_apply_rollback` L167-174 `os.remove` 删正文），worker 里**没有 bridge 引用**，此前「bridge 守卫」设计在 worker 侧不成立。

**落地**：
- 锁读写全部下沉 `project.py`：`project.is_chapter_locked(proj, n)` / `set_chapter_locked` / `attempt_unlock`——**worker 与 UI 同进程读取**，桥只留 UI 侧封装（`isChapterLocked/attemptUnlock`）。
- 自动档 G9 对 locked 章**直接拒绝**（「该章已锁定，请先在共写档显式解锁」）；`regenerateStage('ch_outline')` 不删 locked 章的细纲（锁定细纲视为已定契约）。
- 显式解锁是唯一放行通道（解锁前终稿仍留 `.versions/`）。
- `migrate_project_mode(to_cw)` 保持 locked 不降级；自动档本身不产 locked 章。

### 6.3 用户改稿 → Agent 读改揣摩

- 用户键盘改稿后点**保存**：若内容有变，触发**读改揣摩**——Agent 读一遍改动、揣摩用户意图，在对话区输出（如「你把这句改成…，是想让主角更克制？」）。
- 节流：`readback_on_save`（默认开）+ `readback_min_diff`（最小改动量阈值，低于不触发）+ 手动「读一遍」按钮。每次内容有变的保存 = 1 次调用（复用 review 槽），成本显式入风险表。
- 另一条路：用户在对话区提出本章修改 → 写作 Agent **自动改本章正文 + 本章细纲**两处，改完流式预览 → 用户保存/放弃。

---

## 7. Agent 接力架构

### 7.1 角色清单与槽位映射

**修正措辞**：不是「每槽独立 system prompt 已存在」，而是「每个逻辑 Agent = 独立提示词（§3.0 方案①/②）+ 独立上下文窗口，槽位共享」。supervisor 复用 review 槽，不新增 `SLOT_ORDER`。

| 角色 | 槽位 | 职责边界 | 只注入的上下文（唯一来源） |
|------|------|----------|---------------------------|
| 设定 Agent | writing | 生成核心设定参考稿+讨论收敛 | 选题信息 + grow_core_template + 用户对话 |
| 大纲 Agent | writing | 大纲稿+讨论+自动总结 | 设定产物 + grow_outline_template + 用户对话 |
| 世界书 Agent | helper | 世界书/正则草案+对账 | 核心设定 + 大纲 + grow_worldbook_direction/grow_regex_direction |
| 细纲 Agent | helper | 单元讨论+章细纲滚动+重读校验 | 单元剧情 + 世界书/正则 + 上文结尾 + grow_unit_logic |
| 写作 Agent | writing | 章正文生成/改稿/对话区修改 | 本细纲 + 世界书/正则 + 上文结尾 + 摘要链 + 用户改动意图 |
| 审校 Agent | review | 单章一致性（沿用 _chapter_review，加正则比对）| 本章正文 + 世界书/正则 + 全局摘要 + 角色状态 + 伏笔 + 时间线 |
| **主 Agent（Supervisor）** | **复用 review 槽** | 范围控制/审文/去AI味/衔接比对/逻辑一致性（**不产正文**）| 全量摘要 + 上一章结尾 + 下一章细纲 + 世界书/正则（≤6k 字） |

- **接力 = 只吃上一环节交接块**：每个 Agent 上下文 = 上阶段 `build_handoff` 交接小节（≤800 字）+ 本阶段参考块 + 对话转写摘要。没有任何子 Agent 的上下文含「全书正文」。
- **主 Agent 触发点**：① 每章定稿前（衔接比对：上章结尾↔本章↔下章细纲）；② 世界书变更后（影响提示）。产出报告进 `CwDialogueDock` 报告区，与审校槽 Findings 分开展示（审校→G9 门；主 Agent→对话区）。
- **去重锚**：审校=单章内一致性（BLOCKING/ADVISORY）；主 Agent=章间衔接+全文范围+逻辑封闭，不重复产同一份 Findings。

### 7.2 上下文量上限表

核心设定 ≤4k 字｜大纲 ≤4k 字｜世界书/正则 ≤4k 字｜当前单元条目 ≤1.5k 字｜上章结尾/文风样本 ≤800 字｜摘要链 ≤2k 字｜主 Agent 全量 ≤6k 字｜交接块 ≤800 字｜对话转写 ≤4k 字。

---

## 8. UI 更改设计

### 8.1 布局演进（M1 默认，Console v3 为后置可选升级）

```
ApplicationWindow (1400 宽，M1 不加宽) {
  RowLayout {
    NavRail(48)                       // 保留 5 图标
    PanelStack                        // 5 面板不变
    ColumnLayout {                    // 主编辑列（既有 304 内叠加）
      RowLayout {
        CwDialogueDock {              // M1 自带（主编辑列内部），非 Console v3
          currentAgent                // setting/outline/worldbook/unit/prose/supervisor/readback
          GateBanner                  // ✓确定 / ↩打回 / 回看世界书；沿用 gateBar objectName 契约
          DialogArea                  // run_mode=='cw'：发送→submitCwMessage；appendAgentReply(agent,text)
        }
        EditorView {                  // 当前阶段产物 / 正文；锁定章 readOnly
          // 顶栏：保存（临时）｜✓确定章节（锁定）｜解锁（锁定章）
        }
      }
      StageToolbar { StageStepperCW } // run_mode=='cw' 六卡（自动档仍 4 卡）
      StepGateBar {}                  // 既有 541，自动档用
      StatusBar { agent/槽位/上下文量 }
    }
    ReaderDockHost { ReaderView {} }  // 既有 836 全屏沉浸层；dock 收窄属 Console v3 升级
  }
}
```

- 阶段切换 = `CwDialogueDock.currentAgent` 切换 + 编辑器载入对应产物文件。
- 每阶段一个 ✓确定 + ↩打回；cw_unit/cw_prose（非锁定章）另有「回看世界书」。
- 章节锁定：编辑器只读 + 顶栏「✓ 已确定（终稿锁定）」徽章 + 解锁入口。
- **回归不破**：全部为新增组件/属性/条件分支，不动 gateBar/panelStack/readerView objectName 与既有数据契约。

---

## 9. 跨档产物契约【MED-4 落地 · 保证 cw↔自动档可互续】

**事实**：自动档读取器有硬结构依赖：`stage_volume_outline` 读 `题材定位.md[:4000]`；`_roster` 正则抽 `## 主要角色表`；`_unit_contract` 正则解析 `大纲.md` 的 `第N章/N-~M章` 块；`planned_chapters` 读 `选题信息.md` 字数。cw 总结产物若不带这些结构，切回自动档会静默生成错误细纲。

**落地**：
- `CO_SUMMARIZE_PROJECT_PROMPT` / `CO_SUMMARIZE_OUTLINE_PROMPT` 强制保留：`## 主要角色表` 块、`第N章/N-~M章` 章节区间块、`预计总字数` 字段——**沿既有 VOLUME_OUTLINE_PROMPT / CORE_SETTING_PROMPT 结构总结**。
- 新增 `probe_cw_to_auto_compat.py`：用 cw 总结产物喂自动档读取器，断言 (a) `_roster` 抽得到角色表；(b) `_unit_contract` 抽得到章节区间；(c) `stage_volume_outline` 正常 format；(d) `planned_chapters` 读得出字数。入 M2/M5 回归。

---

## 10. 实施里程碑

| 里程碑 | 内容 | 回归 |
|--------|------|------|
| **M1** | CwDialogueDock + 阶段状态机骨架（state['cw'] 键分离、_cw_active 互斥）+ run_mode 加 'cw' + 确定/打回按钮 + DialogueWorker/SummarizeWorker/build_handoff | assert 18/18 + smoke + probe_gate_* + CW 状态机探针（六阶段推进/打回矩阵/reopen 回边）+ 对话循环探针 |
| **M2** | 预设 grow_* 四字段 + 世界书/正则（regex_rules 默认逻辑约束集）+ 跨档契约 prompt + 注入空串兼容 | probe_worldbook_format（router 打桩）+ probe_worldbook_format_co + probe_cw_to_auto_compat |
| **M3** | 细纲二级结构：单元讨论/±10章/滚动5章/200字/直接编辑/确定细纲重读校验 | probe_co_outline_parse + 打回级联探针 + 单元总纲属主探针 |
| **M4** | 章节确定锁定语义：saveDraft/confirmChapterLocked + project 层锁守卫 + 读改揣摩（readback_on_save/readback_min_diff）+ 保存/确定双键 + 锁定徽章/解锁 | probe_chapter_lock + probe_chapter_lock_cross_mode（G9/regenerateStage 拒 locked、attemptUnlock 放行、migrate 保持） |
| **M5** | Agent 接力编排 + 主 Agent（supervisor 两触发点、复用 review 槽）+ 报告区 | probe_agent_relay（每 Agent 只注入上环节产物/交接块、上限断言；supervisor 不产正文）+ 全自动档 probe_gate_flow 不破 |

---

## 11. 风险与规避

| 风险 | 规避 |
|------|------|
| 上下文量失控 | 结构化交接块（≤800 字）+ 转写截断（≤4k）+ 上下文上限表；主 Agent 不拼全文 |
| API 成本 | 共写档用户驱动可预期：生成1+读改（内容有变保存1次，节流开关）+章节确定1+supervisor1；自动档次数不变；可配置 |
| 旧项目迁移（无世界书/单元） | 缺字段占位容错；无世界书时共写档自动补生成；locked 缺省=未锁；.format 空串回退 |
| locked 章被自动档重写 | project 层锁守卫，G9/regenerateStage 拒绝或跳过；显式解锁唯一放行；migrate 保持锁定 |
| Agent 接力丢上下文 | 交接块有唯一属主（build_handoff）+ 主 Agent 衔接比对兜底 |
| 正则/世界书过度锁定 | grow_* 全部「参考不锁定」护栏 + 世界书 reopen 回看修订 |
| 确定按钮误触发 | 确定后可小幅修改；结构改动走打回；锁定章只读 |
| cw↔自动档互续产物结构不兼容 | §9 跨档契约 + probe_cw_to_auto_compat 强制结构保真 |

---

## 12. 需要你拍板的开放项（不阻塞实施顺序）

1. **提示词注入方式**（§3.0）：推荐方案①（user body 注入，零回归）；选②则给 LLMClient 新增 system= 传参只走新路径。
2. **「正则」语义**（§4.1）：默认「逻辑约束规则集」先行；字面正则表达式为备选结构，设置面板单选。你确认默认值即可。
3. **读改揣摩触发**（§6.3）：默认「每次内容有变的保存触发 1 次 + 最小改动阈值节流」，可全关（手动读一遍按钮）。

以上三项我建议都按默认（①/逻辑约束集/开+阈值），你如无异议即按此实施。
