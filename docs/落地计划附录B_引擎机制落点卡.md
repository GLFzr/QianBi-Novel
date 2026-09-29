# Plan B · 引擎机制落点级施工说明（10 张落点卡）

> 波次：超级迭代「落地计划」专项 · 引擎机制落点代理
> 日期：2026-09-29 ｜ 主仓库 `G:\ai\酒馆\qianbi-novel` **只读**（本次未改任何仓库文件），唯一产出本文件。
> 锚点复核：HEAD = `2de3e9d`（v0.20.1），`git log` 与 `git status` 已确认；docs/超级迭代蓝图_v1.md 为未提交文件（untracked），与本次任务输入一致。
> 行号口径：全部 file:line 为 HEAD 2de3e9d 实测复核（对波次报告偏移 ±3 行内的已归一为本文件实测值）。
> 输入：w2_methodology（T1-T5+20 映射）、w2_proto（P1-P4）、w3_deslop（三层补丁）、w5_satisfaction（盲评协议）、w4_cowrite（F1-F3+CW 护栏+挂载结论）、w5_f123_fix（diff 级修复设计）、w2_t31_rootcause（G1-G7）、w4_refactor_plan（B0-B8）、蓝图 §1/§4。

## 0. 依赖链主轴（先读）

```
Wave 0 债            功能线                                   护栏线
B0 → B4 → B3 ──────▶ 卡3 T1 爽点账本（finalize 落库硬前置）
B6 测试批 ──────────▶ 卡1 F1-F3（test_cw_bridge_slots.py 归宿）
卡1 F1-F3 ──────────▶ 卡4 T2 钩子账本（supervisor 对账挂点）
卡9 P1 事实账本 ─────▶ 卡9 P3 四查（伏笔 evidence）＋ 卡2 T3（伏笔登记带引文）
卡10 CW-G6 看门狗 ───▶ 卡9 P1（锁定⇒账本行必须存在的对账前置）
独立可并行：卡2 T3（B4 后即可）／卡6 deslop 度量层／卡7 must 复扫闭环／卡8 G1+G3
硬前置关系（护栏→功能）：卡8 G6 记账保护 → 卡9 批量挂机 C；卡8 G1/G3 → T3 v3 长跑
```

施工顺序建议（与蓝图 Wave 0-4 对齐）：**卡1 → 卡2 → 卡6(S档) → 卡8(G1/G3) → 卡9(P2/P4) → 卡7 → 卡10 → 卡4 → 卡3 → 卡9(P1/P3) → 卡5 → 卡6(M档规则扩容)**。

---

## 卡 1 ｜ F1-F3 共写 supervisor 链三伤修复（落点核实版）

### ①现状（HEAD 2de3e9d 实测）
- **F1** `app/ui/bridge.py:4756` 与 `:4845` 类体内两次 `def _start_cw_supervisor`，Python 后者覆盖前者。4756 版（正确）：复位 `_cw_supervisor_failed`（4758）+ `worker.error.connect(self._on_cw_supervisor_error)`（4766）；4845 活版：error 接通用 `_on_cw_error`（4853）、无 failed 复位 → `_on_cw_supervisor_error`（4776）成为死代码 → QML 两颗逃生按钮（CwDialogueDock.qml:153/164 `visible: bridge.supervisorFailed && …`）永不可见。调用点三处：confirmCwStage:4340、retrySupervisor:4786、tests/probe_agent_relay.py:103（打桩替换，两版兼容）。
- **F2** `bridge.py:4933`：`self._spawn_cw_dialogue(text, st.STAGE_CW_PROSE, focus_chapter=num)` 未传 mode → 默认 `mode="discuss"`（_spawn_cw_dialogue:4212）→ DISCUSS_MODE_BLOCK 禁产成稿 + `cap_discuss_reply` 320 字截断（4279-4280）；`<<<正文>>>` 契约只挂 compose+cw_prose（prompts/co_writing.py:145-152）；4882 行 toast「已自动派写作 Agent 改写」与产出能力矛盾。手动派单 dispatchCwReport（4937）共用 `_dispatch_cw_rewrite` 同病。
- **F3** `bridge.py:4865`：`_on_cw_supervisor_done` 在 parse（4874）**之前**无条件写 `supervised[num]`（含取消路径 4868-4873）；confirmCwStage:4330-4335 见痕即直通 `confirmChapterLocked()`；`parse_supervisor_report`（co_dialogue.py:465-478）无结论行返回 `(False, "")` 与「通过」同形，bridge 走 4892-4893「衔接比对完成…确认无问题再点确定」的通过口径 toast。

### ②改动设计（w5_f123_fix 三份 diff 与 HEAD 逐行对齐核实，可直接开工）
- **F1**：删 `bridge.py:4845-4857` 整块（活版），保留 4756 版。纯减法，零行为回退。
- **F2**：4933 行改 `self._spawn_cw_dialogue(text, st.STAGE_CW_PROSE, focus_chapter=num, mode="compose")`；4882 toast 改「已自动派写作 Agent 改写（撰写模式）——产稿后在对话区点『提取正文到编辑器』落稿，改完再点『确定』复检」。**连带必改同 PR**：`tests/unit/test_cw_prose_check.py:148` 的 `_DispatchSelf._spawn_cw_dialogue(self, text, stage, focus_chapter=0)` 桩签名扩 `mode="discuss"` 形参并捕获（现桩吞掉 mode 正是 F2 逃过测试的原因）。
- **F3**：co_dialogue.py:478 后新增纯函数 `supervisor_report_has_conclusion(text) -> bool`（正则 `^[-*]?\s*结论[：:]` 逐行匹配；不改 `parse_supervisor_report` 签名——其 `(False,"")` 兜底被 test_barrier_removal.py:125-149 四测钉死）；bridge 新增 Signal `supervisorAttentionChanged`（970 行附近）+ `_cw_supervisor_attention` 旗标（1090 行附近）+ Property `supervisorAttention`；`_on_cw_supervisor_done` 痕后置：仅「解析成功 ∧ 结论=通过」置 `supervised[num]`，需调整/解析失败/取消置 attention 不置痕；`forceLockChapter`（4798）留痕分口径 `skipped:`（比对没跑成）/`overridden:`（比对被无视）；CwDialogueDock.qml:150-170 两按钮 visible OR 上 `supervisorAttention`，危险按钮文案按旗标分档。
- **测试文件落位**：三组测试全部进**新文件** `tests/unit/test_cw_bridge_slots.py`（当前不存在，已确认）——F1 的 `inspect.getsource(Bridge)` 重复定义钉测 + 行为测（error→failed 旗标）；F2 的 compose 钉测；F3 的置痕三态/无结论口径/越权留痕四测。`_SlotSelf`/`_DispatchSelfMode` 替身代码 w5_f123_fix §3.3 已给全。

### ③流水线相位与调用时机
共写档 cw_prose 阶段「确定」链：confirmCwStage → _start_cw_supervisor（review 槽）→ _on_cw_supervisor_done →（需调整）_dispatch_cw_rewrite（writing 槽 compose）→ 提取落稿 → 复检 → confirmChapterLocked。自动档（stages.py/orchestrator.py）零触碰，三 diff 全在 `_get_cw_mode()=="cw"` 守卫内。

### ④QML/UI 面
CwDialogueDock.qml 两颗按钮（visible 条件 + 分档文案）；新增 `supervisorAttention` Property。不新增组件，`probe_qml_compile.py` 照跑；`test_qml_red_lines.py` 未钉这两颗按钮（已核对）。

### ⑤先写哪条测试
`tests/unit/test_cw_bridge_slots.py::test_f1_supervisor_defined_once_with_c2_wiring`——`inspect.getsource(bmod.Bridge).count("def _start_cw_supervisor") == 1` 且活版源码含 `_on_cw_supervisor_error`/`_cw_supervisor_failed = False`。**当前即红**（活源码双定义 + 丢接线），红转绿即 F1 完成。

### ⑥依赖与被依赖
依赖：B6 测试批提供归宿文件。被依赖：**卡4 T2**（supervisor 链不修，钩子对账挂进去就是第四个剧场——w4_cowrite §4 原话）；B8e（bridge_cw.py CwMixin 搬运）必须在本批之后。与 W3-2 S 批零交叠（仅行号漂移，PR 用符号锚）。

### ⑦人日与风险
**1.5-2 人日**（F1 0.5 / F2 0.25 / F3 1.0，含 `pytest tests/unit -k cw` + probe 套件回归）。风险：F3 行为收紧面——demo_director.cw_confirm 已核对不注入 supervisor 报告，无冲突；probe_needs_fix.py 若直接喂报告文本需按新 toast 口径核对。一个 PR 三 commit（F1/F2/F3）。

---

## 卡 2 ｜ T3 伏笔到期引擎（S，五项机制中最便宜的「写不崩」增量）

### ①现状
- 数据：`app/core/tracking_store.py:21` `_FORESHADOW_COLS = ("伏笔","类别","埋设章节","状态","计划回收","备注")`；sidecar `追踪/伏笔表.json`（`load_foreshadow:182` 从 json 或 `伏笔.md` 表格双格式读取并回写）；`apply_foreshadow_upserts:205`（写后 upsert，调用点 `stages.py:3676`）、`apply_foreshadow_diff`（memory.py:427，共写反哺 co_dialogue.py:771）、`render_foreshadow_md:232`。状态枚举只有 未埋/已埋/已回收（render_foreshadow_md 头注释：234 行）。
- 注入：`memory.py:73` `unfished_foreshadows(proj, limit=2000)` 只过滤「已回收」（81-84 行），**无 urgency 派生、无排序、无超期标记**；四个消费方全走它：stages.py:1140（细纲批）、shared_prefix.py:96（正文前缀）、co_dialogue.py:219（cw 参考块）、history_compaction.py:382（卷会话）。
- 告警通道盘点（现有可复用，无需新建 notify 基建）：①`ctx.log("warn"/"error")`（流水线日志）；②`volume_session.record_event:84` → `追踪/session_events.jsonl`（项目级事件账，cost_bench 已消费该文件——`trim_over` 先例 stages.py:1936-1941）；③L0 finding 进审校裁决（`review_l0_block` stages.py:2412-2450）；④`st.mark_chapter_need_human` → UI 待修聚合（bridge.py:437/472/2899/5767）。

### ②改动设计
- 新函数进 `app/core/tracking_store.py`（与数据同层，纯本地零 LLM）：
  ```python
  def parse_recovery_window(cell: str) -> tuple[int|None, int|None]:
      """「计划回收」列 → (min_ch, max_ch)；解析不出 → (None, None)。
      支持：40 / 第40章 / 第40-45章（区间取 [min,max]，P2 原型坑①）/ 第N单元 → None"""

  def foreshadow_urgency(data: dict, cur_num: int) -> list[tuple[dict, str]]:
      """逐行派生 urgency（程序计算不落盘）：超期N章 > 剩≤5章 > 无窗口；
      排除 状态∈(已回收,已失效)；排序超期优先（overdue 降序 → 剩余升序）"""
  ```
- 状态枚举扩「**已失效**」（显式废弃+理由写入备注列）：`render_foreshadow_md` 头注释与 `apply_foreshadow_upserts` 不过滤理由；僵尸伏笔由「已失效」终态收口。
- `memory.py:73 unfished_foreshadows` 升级：读 `load_foreshadow`（结构化）而非裸文本行过滤，输出按 `foreshadow_urgency` 排序，超期条目加`【超期N章】`前缀、无窗口条目加`【无回收窗口】`前缀；**签名不变**（四个消费方自动受益）。
- 批次 L0：`app/core/l0_checks.py` 新增 `foreshadow_findings(proj, batch_outlines, cur_num) -> list[finding]`——每条超期伏笔必须在本批某章「伏笔推进」段出现「回收」或「改期：新窗口+理由」，否则产出 `{"level":"fail候选","check":"伏笔到期",...}`；注入点 `stages.py review_l0_block`（2433-2445 与 build_v5_block 并列）与细纲批后独立校验（`stage_chapter_outlines:1101` 返回前，fail-open）。
- 告警：超期落 `record_event(proj, "foreshadow_overdue", ch=cur_num, name=…)` + ctx.log("warn")。

### ③流水线相位与调用时机
细纲批生成前（注入排序：stages.py:1140）→ 细纲批后 L0（1101 返回前，fail-open）→ 写后提取 upsert（3676，维持现状）→ 审校注入（review_l0_block 2433+）。主挂点不被 B3 阻塞（细纲批 1101-1330 与 review_l0_block 2412+ 均在 microcycle 区段 1547-2408 之外，w4_refactor §四已判定）；若后续要在 `_mc_assemble/_mc_finalize` 加挂点则等 B3。

### ④QML/UI 面
无界面，config 即入口（无新开关：纯本地判据随伏笔表存在而生效，不违反字节隔离纪律——引擎关闭的旧书伏笔表无「计划回收」章号则判 None 恒空）。可选后续：编辑器追踪面板高亮超期行。

### ⑤先写哪条测试
`tests/unit/test_foreshadow_urgency.py::test_parse_recovery_window`——断言 `"第40-45章" → (40,45)`（区间不取首数字，P2 原型坑①回归）、`"第N单元" → (None,None)`、`"40" → (40,40)`；第二支 `test_overdue_sorted_first_and_marked`——超期条目排最前且文本带【超期】前缀；第三支 `test_batch_l0_requires_payoff_or_defer`——超期伏笔无本批回收/改期 → fail候选。

### ⑥依赖与被依赖
依赖：B4（run 级安全网）后即可动工。被依赖：卡9 P3（伏笔「待登记/需决断」复用 urgency）；卡9 P1（伏笔登记带 evidence 引文是 T3 检索的长期地基——P3 原型证明无 evidence 的模糊条目正文检索不到）。B2d 同邻域不同语义，git 可并行、语义审查串行。

### ⑦人日与风险
**1.5-2 人日**。风险：区间/单元格式解析覆盖不全（回退 None 恒安全，fail-open）；「计划回收」为自由文本的存量数据兼容（解析不出只提示不判 fail）。

---

## 卡 3 ｜ T1 爽点节奏带账本（跨章判据从指令升为确定性对账；盲评出口 A 的工程闸）

### ①现状
- 引擎本体：`app/core/satisfaction.py`（87 行）——`_BEAT_LINE_RE:23`（细纲「- 本章爽点节拍：」唯一解析正则）、`_NO_BEAT_MARKERS:26`、`_BEAT_SEGMENTS:29`、`_OUTLINE_DIRECTIVE:34-43`（连排纪律只活在指令文本里）、`beat_declared:61-66`、`prose_beat_block:69-87`。开关 `writing.satisfaction_engine` 缺省 False（config.py:114）。
- 注入点：细纲两处 `stages.py:1203/1313`（`_satisfaction_outline_directive(ctx.cfg)`）；正文三支 1758-1761（`_beat_block` 双重门控：beat_declared ∧ 配置开）。L0：`l0_checks.py:106-141 beat_findings`（证据在场才检查）+ `build_v5_block:195-229`。15 例护栏 `tests/unit/test_satisfaction_engine.py`（接线护栏 :191-199 按源码正则计数钉死「正文 3 处 + 细纲 2 处」）。
- **缺的芯**：①连排 ≤2 章/每 3-5 章闭环/类型轮换三条跨章判据无可测工具（w5_satisfaction §1.5）；②无落库点；③**cw 自产细纲无节拍字段**——`app/prompts/co_writing.py:259-293 CO_UNIT_OUTLINE_PROMPT` 规格只有「核心事件+故事内容 150-180 字」，共写用户开引擎只有正文块一半生效。
- 落库点定位：finalize 追踪四文件区 `stages.py:2235-2247`（`_update_tracking` 调用在 2238）——**在 862 行 chapter_microcycle 体内，B3 硬前置**（w4_refactor §四：T1 的账本写点在切分后是 `_mc_finalize` 里一个清晰调用位）。

### ②改动设计
- sidecar `追踪/爽点账本.json`（`app/core/satisfaction.py` 新增读写，结构沿用伏笔表 sidecar 形态）：
  ```python
  _LEDGER_COLS = ("num", "declared", "beat", "closed", "pp", "defer_hits")
  def load_satisfaction_ledger(proj) -> dict        # {"version":1,"rows":[...]}
  def ledger_upsert(proj, num: int, *, declared: bool|None, beat: str = "",
                    closed: bool|None = None, pp: int|None = None) -> None
  def rhythm_findings(rows: list, batch_range: tuple[int,int]) -> list[dict]
      # 规则1 无节拍空档连排>2（含上一批尾）→ fail候选
      # 规则2 每批(5章)≥1 次完整闭环（declared ∧ closed is not False）→ fail候选
      # 规则3 近10章同主码连排≥3 → 核对（REP 同质化）
  ```
- 双通道回写：`declared/beat/pp` 在细纲批解析时落账（`_generate_outline_batch:1159` 解析出 outlines 后逐章 `beat_of_outline/beat_declared` 回写；cw 侧挂 `OutlineBatchWorker` done 后 `_on_cw_batch_done` bridge.py:4460-4477）；`closed` 由审校 B_PAYOFF 结论回写（`stages.py` FINAL_REVIEW 解析处，pass→True / fail 推迟→False / 不评→None）。
- 批次 L0：`rhythm_findings` 挂 `review_l0_block`（与卡2 并列）+ 细纲批后独立校验；开关 `writing.satisfaction_ledger`（新，缺省 False，**与 satisfaction_engine 解耦**——纯本地零 LLM 增量不受字节隔离纪律约束，作为 on 的前置热身，w2_methodology §4-T1）。
- cw 细纲字段扩展（w5_satisfaction §1.5 修复）：`CO_UNIT_OUTLINE_PROMPT` 细纲规格增三行「- 本章爽点节拍：…（格式同自动档）」「- 章尾钩子：…（期待度：强/中/弱；钩型：…）」「- 字数目标：N 字」（最后一项同时修 cw 字数目标恒回落 3000 的断链，w4_cowrite §2.1）。cw 手动审校可选 → 账本需要 `closed=None`（declared_absent）显式语义，不把缺审校当违约。

### ③流水线相位与调用时机
细纲批（1159 解析后落账 declared/beat）→ 正文微循环（不变）→ 审校（B_PAYOFF 回写 closed）→ **finalize 追踪区（2235-2247，B3 切分后为 `_mc_finalize` 调用位）落账合并**。cw 档：批次生成后（_on_cw_batch_done）+ 批次校验 blocking 分支（_on_cw_validate_done 4421-4431 已有 BLOCKING 短路结构）。

### ④QML/UI 面
无界面，config 即入口（`writing.satisfaction_ledger`）。pp 曲线/账本视图留共写回顾页后续批次。

### ⑤先写哪条测试
`tests/unit/test_satisfaction_ledger.py::test_rhythm_no_beat_run_over_two`——构造含上一批尾 2 空档 + 本批 1 空档的 rows，断言 `rhythm_findings` 恰出 1 条「爽点空档」fail候选（含跨批边界）；配套 `test_closure_rule_uses_closed_not_false`（closed=None 不算违约）与 `test_ledger_off_byte_identical`（开关关 → 装配零增量，仿 test_satisfaction_engine 字节钉测形态）。

### ⑥依赖与被依赖
依赖：**B3 硬前置**（finalize 写点在函数体内）——B3 前只能先落 satisfaction/l0_checks 侧纯逻辑与 schema（不接流水线，w4_refactor §四原话）；cw 字段扩展依赖卡1（无直接耦合但同在共写链，先修 F1-F3 避免剧场叠加）。被依赖：盲评协议出口 A 的工程闸（w5_satisfaction §3.7：「默认 on 必须在 T1-lite 进 L0 或账本落地之后」）；卡5 T5 共享账本基建与「- 桥段：」字段槽位。

### ⑦人日与风险
**4-5 人日**（schema+读写 1、回写双通道 1.5、rhythm_findings+L0 1、cw 字段扩展 0.5、测试 1）。风险：①cw 手动审校可选导致 closed 长期 None——用显式语义兜住；②接线护栏测试（:191-199）会因新增注入点需要同步更新计数——改码时必须显式跑该测试并更新钉值，防止静默解线；③B_DELAY：B3 未完成前禁止把写点塞进 862 行函数。

---

## 卡 4 ｜ T2 钩子追读链账本（7 钩型受控词表 + 分档路由，前置 = F1-F3 修复）

### ①现状
- 细纲字段壳：`app/prompts/planning.py:202`「- 章节定位：（高压/推进/修炼试错/关系回收/低压生活/信息整理）」——**分档路由的现成输入**；`:206`「- 章首钩子：」**空壳无填写指引**（壳中之壳）；`:239`「- 章尾钩子：（具体内容，期待度：强/中/弱；与下一章如何承接）」——有烈度档无钩型枚举、无跨章账本。
- 审校：`app/prompts/review.py:169-175` 维 F（F_HOOK）已有事件钩/烈度/结构指纹快数判据，但**无钩型枚举、无结构化回写**；F 维回写点在 FINAL_REVIEW 解析处（`parse_final_review_v2`）。
- 承接对账：只靠承接铁律提示（writing.py:41），无确定性对账；最自然的执行者是 supervisor（`co_dialogue.py:391 SupervisorWorker`——已注入上章结尾 +800、本章正文 ：3000、下章细纲 ：600），但 supervisor 现状是「结论不设门+错误死路+派单剧场」（卡1）。
- 两档共用约束：W0c 逐字节钉测 `tests/unit/test_cw_prose_check.py:95-101` 把共写与流水线终审 prompt 焊死——T2 改 F 维 rubric 即同时改两档，必须按「两档共用、呈现分档」走（w2_methodology §5）。

### ②改动设计
- **词表文件**：`app/prompts/hook_vocab.py`（新，代码内受控常量而非 assets——与 scene_cards 同形态，便于测试 import 与 preson 校验）：
  ```python
  HOOK_TYPES = ("悬念缺口", "危机迫近", "反转揭示", "两难抉择", "承诺威胁", "意象异变", "情绪定格")
  HOOK_TYPE_CRITERIA = {"危机迫近": "存在明确时限或逼近中的威胁且本章未解除", ...}  # 每型一条命中判据，进 F 维 rubric 与账本枚举
  HOOK_ROUTE = {"高压": HOOK_TYPES, "推进": HOOK_TYPES,
                "低压生活": ("意象异变", "情绪定格"), "信息整理": ("意象异变", "情绪定格"), ...}
  # 13+7 式提纯重写，MIT 原文（chinese-novelist hook-techniques.md）只作离线参考，不逐字进 prompt
  ```
- 细纲字段升级（planning.py:206/239）：章尾钩子行加「钩型：七选一」；章首钩子行补一句填写指引（「首 500 字内的事件/异象/数字压力，禁止纯环境白描」——引子七式「闪前碎片」「倒计时」并入此指引，不新增独立引子段）。
- sidecar `追踪/钩子账本.json`：`{"num":21,"type":"危机迫近","strength":"强","is_event_hook":true,"event_kw":"灵石失窃"}`；回写：细纲解析钩型（主）+ F 维结论回写 strength/is_event_kw（辅，FINAL_REVIEW 解析处）；`event_kw` 从钩子内容提取 1-2 个事件关键词。
- L0：`l0_checks.py` 新增 `hook_findings(rows, num, outline) -> list`——①连弱钩（近 2 章全弱钩/非事件钩 → 核对级）；②钩子未应（上章 event_kw 在本章细纲「承接锚点+内容概括」无字面命中 → fail候选；无字面关键词的钩子弃权转 LLM 轨，P3 原型坑③）。
- 分档路由注入：细纲模板按 `章节定位` 字段映射 HOOK_ROUTE 提示可用钩型（低压章只提示 意象异变/情绪定格，对齐 lowkey 卡「不强求钩子」哲学 scene_cards.py:110-118）。
- supervisor 对账域：`CO_SUPERVISOR_PROMPT`（prompts/co_writing.py:353-397）报告增一节「上章钩子回应核对」——确定性输入（上章 event_kw）+ LLM 判定，进卡1 修复后的结论门。

### ③流水线相位与调用时机
细纲批生成（模板按章节定位路由）→ 细纲解析落账 → 正文 → 审校 F 维（rubric 增钩型判据，回写 strength）→ supervisor 衔接比对（cw 档 + 定稿前）核对上章钩子应答。共享侧（F 维 rubric + STYLE_DISCIPLINE 钩子铁律）两档同步变化（W0c 钉测需同步更新测试意图，**显式改钉不静默绕开**）。

### ④QML/UI 面
共写档：confirmChapterLocked 的 lockBlockedDetail 信号模式（bridge.py:4499-4534）旁加「钩型登记卡」（作者可改，先享分档呈现）；全自动档账本静默 + L0 出证据。两档同一套词表，只有呈现层分档。

### ⑤先写哪条测试
`tests/unit/test_hook_ledger.py::test_hook_type_vocab_closed`——断言 7 型常量与判据字典键集相等且每条判据非空（受控词表封闭性）；`test_weak_hook_run_detected`（近 2 章弱钩 → 核对级 finding）；`test_unanswered_hook_fail_candidate`（上章 event_kw 在本章细纲零命中 → fail候选）；`test_route_low_pressure_subset`（低压定位可用钩型 ⊆ {意象异变, 情绪定格}）。

### ⑥依赖与被依赖
依赖：**卡1 F1-F3 硬前置**（supervisor 链）；B6（bridge 槽级测试形态）。被依赖：卡5（钩子 2 码 YQ/KT 与钩型词表互引）；w4_cowrite 挂载结论「修 F1/F2/F3 → T2（确认卡先行、对账后行）」。

### ⑦人日与风险
**3.5-4.5 人日**（词表+判据 1、细纲字段+解析 1、F 维回写+账本 1、supervisor 对账 0.5、L0+测试 1）。风险：①W0c 钉测破盲面——共享 rubric 改动必须两档同验；②event_kw 提取是启发式，字面命中判据对含蓄钩子弃权（转 LLM 轨，不硬判）；③钩型自报可能失真（模型乱填型别）——F 维复核+受控枚举校验兜底。

---

## 卡 5 ｜ T5 桥段码账本与打法卡路由（36 码表 + 打法卡 schema；「弹药库→引擎」运输线）

### ①现状
- `app/prompts/scene_cards.py`：6 卡 `SCENE_CARDS:10-119`（battle/payoff/emotion/dialogue/mystery/lowkey，含 method_zh/axes/example）；中英文关键词路由 `_KEYWORDS:147-223`、`chapter_to_cards:189`；`craft_block` 唯一生产消费点 `stages.py:1754`（正文 draft 轮注入）；example 不注入的既定纪律（scene_cards.py:280-282 附近，「示例句会被模型当成情节抄」）。缺口：卡粒度粗（无 DB大比/TP突破/SF身份揭露/DC内斗）；关键词路由会漏（细纲不含关键词即落 lowkey）；无跨章同卡连排检测。
- 码表来源：本机拆解框架 §3 枚举实为 **36 码**（框架自称 28 码，w2_methodology §1.2 逐点枚举 8+5+6+6+4+2+5=36——命名坑：SJ 收获兑现与 SJ2 闭关跳时撞前缀，数据文件需显式区分）。桥段字段在细纲**不存在**（对比：爽点节拍行 B1 已落）。
- 技法卡 schema（框架 §3）：骨架拍数→蓄压手法→兑现机制→典型跨度→与章钩衔接→失败模式→证据章节；qianbi scene_cards 是同思想粗粒度版。

### ②改动设计
- **数据文件**：`app/prompts/bridge_codes.py`（新，代码内常量；版权绿档路径——码表为自写受控词表，直接取自本机拆解框架的自产内容，不涉第三方版权文本）：
  ```python
  BRIDGE_CODES: dict[str, dict] = {
      "DL": {"name": "打脸", "group": "爽点", "spans": (1, 3),
             "route_kw": ("打脸", "当众", "揭穿"), "card": "payoff"},   # card=映射到场景卡
      "DB": {"name": "大比", "group": "冲突", "spans": (3, 8), ...},   # 36 条完整枚举
      "WATER": {"group": "反例", "advisory_only": True, ...},          # 反例 5 码只进审校不进路由
  }
  def parse_bridge_code(outline: str) -> tuple[str, str]:   # "DL(主)+MX(次)" → (主码, 次码)
  ```
- **打法卡 schema**（自写表达，引用框架的技法卡字段思想但措辞全自产）：`app/prompts/bridge_cards.py` 新增 4 卡（DB大比/TP突破进阶/SF身份揭露/DC派系内斗），字段 `beats`（拍数）/`buildup`（蓄压）/`payoff`（兑现）/`span`（跨度）/`hook_joint`（章钩衔接）/`failure_modes`（失败模式）——与现有 SCENE_CARDS 的 method/axes 结构同形，复用合并现有 payoff/battle/mystery 的手法行，只加轴变体与路由词；example 字段沿用「不注入」纪律。
- 细纲字段：planning.py 细纲模板「- 爽点：」行后增「- 桥段：DL(主)+MX(次)（受控码表，低压章可写 LX/LX2 过渡码）」；cw 侧 CO_UNIT_OUTLINE_PROMPT 同步（与卡3 字段扩展同批）。
- 账本与 L0：`追踪/桥段账本.json`（细纲解析落账，与爽点账本同形可共享读写基建——**与卡3 同批实施**）；`l0_checks.py` 新增 `bridge_findings(rows, outline)`——码表外提示 + 近 10 章同主码连排 ≥3 → 核对级（REP）。
- 路由：`chapter_to_cards` 增桥段码优先路由——细纲有「- 桥段：」行且码 ∈ BRIDGE_CODES → 直接路由到对应卡（绕过关键词匹配），无行回退现有关键词路由（防路由会漏）。

### ③流水线相位与调用时机
细纲批（字段指令进模板 planning/co_writing）→ 细纲解析落账 → 正文 draft 轮 craft_block（stages.py:1754，桥段码优先路由）→ 审校（反例码 advisory 注入 review_l0_block）。L2 批注技法卡 JSONL 产出后按 M17 管线灌入（hard→审校规则、soft→craft_block），注入纪律 ≤30%（框架 §6）。

### ④QML/UI 面
无界面，config 即入口（数据文件+细纲字段即入口）。

### ⑤先写哪条测试
`tests/unit/test_bridge_codes.py::test_code_table_complete_and_disjoint`——断言 36 码全枚举、无前缀撞车（SJ/SJ2 显式区分）、每码含 group/spans/route_kw 字段；`test_bridge_code_priority_over_keywords`（细纲有码行时路由绕过 _KEYWORDS）；`test_same_code_run_three_flagged`（近 10 章同主码 ≥3 → 核对级）。

### ⑥依赖与被依赖
依赖：卡3（共享账本基建与细纲字段槽位，w2 建议同批）；蓝图定位 T5 在 Wave 4（版权绿档路径确认后）。被依赖：M17 拆文→注入管线（L2 技法卡 JSONL 的运输线终端）。

### ⑦人日与风险
**4-6 人日**（码表文件 1、4 张打法卡 1.5、细纲字段+解析落账 1、路由改造 0.5、L0+测试 1、cw 同步 0.5）。风险：①模型自报码别失真——审校复核兜底；②码表与场景卡双轨重叠期维护（过渡期 card 映射字段保持单一事实源）；③框架自称 28 码 vs 枚举 36 的口径差——对外文档统一「36 码」并注明枚举口径。

---

## 卡 6 ｜ deslop 度量层 + 规则 28→45（从零到一的一层 + 规则扩容）

### ①现状
- 度量层为零：`app/deslop.py:378-387 summarize_findings` 是死函数（全仓仅定义行；w4_refactor B1 已列为可删——**本卡把它从死函数复活为指标聚合基础**，与 B1 互斥、B1 让位）；`app/report_bundle.py`（WP-28 报障包 zip，app 顶层非 core）无 deslop 内容；共写 before/after counts（co_dialogue.py:639/665，before_counts/after_counts）算完只存内存。
- Finding 形状（deslop.py:14-21 dataclass）：`rule/level/message/text/start/end/fix_hint`——分规则命中表的现成数据源。`_in_dialogue:118-124` 全文开合计数（引号判断基建弱）；trailer 规则全文匹配（:40-53）。
- 规则基数：**28 个 rule id（10 blocking + 12 advisory 密度 + 6 结构）**——蓝图 §6 已裁决的统一口径（行文可「约 30」）。
- 出口：`gates.py:38-46 GateResult.to_record` 只有 words/deslop_blocking/deslop_advisory/review_blocking/status；编辑器扫描面板 bridge.py:2746-2757。
- **规则来源与 MIT 合规（已核实）**：oh-story `LICENSE` = MIT（Copyright 2025-2026 oh-story-claudecode）；humanizer `LICENSE` = MIT（Copyright 2025 Siqi Chen）；lieflat 已 vendored（app/vendor/lieflat-less-ai-tone/LICENSE = MIT）。合规姿势：①借鉴**判据与阈值数字**（事实性内容）；②规则措辞/修法文案全部自写；③vendor 目录先例保留版权声明文件；④阈值校准数字引用处注明来源（deslop.py 既有注释惯例 :57-61,199-201）。

### ②改动设计
- **S 档（度量层从零到一）**：新建 `app/deslop_metrics.py`（纯本地零 token）：
  ```python
  def compute_metrics(text: str, findings: list[Finding]) -> dict:
      return {"aid": Σ(命中数×权重)/千字,            # 权重 blocking=3/advisory=1 可配置
              "by_rule": {rule: {"count": n, "per_kilo": x, "review": "mechanical|semantic"}},
              "rhythm": {"sent_len_mean/var", "para_len_mean/var", "short_para_ratio", "max_short_run"},
              "connectivity": {"func_per_kilo", "conn_per_kilo", "long_bridge_ratio"},
              "special": {"dialog_tag_ratio", "gaze_per_kilo", "brake_per_kilo", "quote_emphasis"},
              "guard": {"chars_kept_ratio", "para_delta", "new_must_violations"}}
  ```
  复活 `summarize_findings` 进 `by_rule` 聚合；`GateResult.to_record`（gates.py:38-46）扩 metrics dict（改前/改后/轮次）随章记录落盘；去味完成后生成 `追踪/去味报告.md`（改前/改后 Δ 表 + 分规则命中表）；report_bundle 出口：`build_bundle` 增收去味报告与 metrics.json（app/report_bundle.py 主函数加一收集项）。
- **S 档存量修复**：trailer 收窄文末 600 可见字窗口（deslop.py:40-53 加窗口参数）；共写 `_run_deslop` before/after 升级为完整指标对比。
- **M 档（规则 28→≥45）**：按 w3_deslop §3 合并库补 C3/C6/C8/C9/C10/A7/D7/D9/B6/E4 等；`Finding` 加 `review` 字段（mechanical/semantic 二轴，未登记即运行期报错的守卫纪律）；`maskQuoted` 等长占位替换 `_in_dialogue`（118-124 重写，偏移不漂移、未闭合引号不吞全章）；书级豁免 `projects/<book>/deslop_whitelist.txt` + `<!-- 去味:跳过 -->` 段级豁免；D9 退化检测复用 `app/core/shared_prefix.py` 复读判定。

### ③流水线相位与调用时机
scan 相位（stages.py:1956 首扫 = 改前 metrics）→ deslop 每轮复扫（2013/2034 = 改后 metrics）→ G7 后 metrics 随 to_record 落章记录 → finalize 生成去味报告。编辑器实时扫描（bridge.py:2746）加指标条（AID + top3 规则，成组展示不做单一总分排序——防 AID 博弈注水，w3 §7 风险2）。

### ④QML/UI 面
编辑器 findings 面板指标条（mechanical/semantic 分两组显示）；共写档去味前后指标对比展示；无新页面。

### ⑤先写哪条测试
`tests/unit/test_deslop_metrics.py::test_metrics_match_hand_computation`——构造含 ≥10 类毒句式的示例文本，`scan_text` 命中 ≥9 类，`compute_metrics` 输出与手算一致；`test_trailer_window_narrowed`（正文中段埋「没人知道」不报 trailer、文末埋的仍报）；M 档：`test_new_rule_missing_review_axis_raises`（未登记 review 字段的新规则导致扫描报错——守卫生效）。

### ⑥依赖与被依赖
依赖：无硬前置（deslop.py 与 stages 接口不动，`scan_text(text) -> list[Finding]` 契约保持）。被依赖：卡7（must 复扫闭环的 new_must_violations 指标项）；第三方送检流程（导出送检包+人工回填，w3 §4.3，本卡只留 metrics 出口）；B1 死函数清理批让位（summarize_findings 从删除名单移出）。

### ⑦人日与风险
**S 档 1.5-2 人日 + M 档 3-4 人日 ≈ 5-6 人日**。风险：①oh-story 校准数不能直接当误报保证——M 档必须用自备真人样例重跑每条 blocking 规则（语料不足降 advisory）；②pinned 缺省开的回归面（stages.py:921 span 拼回历史失败版教训）——翻缺省前跑既有 e2e；③lieflat 并集字节同步约束（writing.py:214-240 三消费点同源）——改 DESLOP_REWRITE_PROMPT 必须同步切片。

---

## 卡 7 ｜ must 机器复扫闭环（violation_keys 生产接线 + 改写验收双复扫）

### ①现状
- `app/mustscan.py:68-70` `violation_keys(findings) -> set`：`{(pattern, mode, level)}` 违规指纹 API——**全仓零生产调用方**（grep 证实：唯一调用在 tests/unit/test_must_contract.py:153-158 的单测）。docstring:5-6 自承「中间三次整章重写不带契约……只能等终审概率性地抓」（注：deslop prompt 现已注入 must 文本，docstring 该句过时，但**机器验收**确实缺位——注入文本 ≠ 确定性复扫）。
- 改写回环：`stages.py:1952-2044`——1956 首扫（G6 前）、1976-2013 去味循环每轮 `blocking, advisory = gates.scan_deslop(prose)`（2013 复扫只查 deslop）、2034 G7 回退后复扫。`scan_proj:73-79`、`contract_precheck:99-116`（锁定/审校前置闸）已备。
- 整章重写轮无膨胀护栏（pinned 模式有 grow_over_25pct 回退 stages.py:962-966，整章轮没有）。

### ②改动设计
- **接线点**：deslop 循环每轮采纳改写稿前（stages.py:2011-2013 附近，`prose = rewritten` 之后、`gates.scan_deslop` 复扫处扩为双复扫）：
  ```python
  must_before = mustscan.violation_keys(mustscan.scan_proj(proj, pre_round_prose))
  must_after = mustscan.violation_keys(mustscan.scan_proj(proj, prose))
  new_breaches = must_after - must_before
  if new_breaches:
      # 本轮改写稿不采纳：rollback_to(t_round) + 记 trim_over 式事件改写_retry
      # 并入现有 max_deslop_rounds 熔断；轮次烧完仍新增 → G7 门描述携带「must 新增违规」
  ```
  G7 回退路径（2034）同款双复扫（还原原稿语义下 must_after ⊆ must_before 恒成立，做对账断言即可）。
- 逐条规则契约：`findings_to_prompt_text`（deslop.py:390-398）升级带规则 ID + 正例修法 + 负例（「不许把 B 写成新的否定铺垫」）；复扫验收按规则 ID 归零或降档计算，写进 G7 门文案（2024 附近自然携带）。
- 替换防复用：每轮改写后对 diff 新增高频 3-gram（≥3 次）自动追加本轮 tic_blacklist（会话级不落盘）。
- 整章轮膨胀护栏：补 pinned 同款字数漂移检查（>±15% 回退本轮）。
- metrics 出口：new_must_violations 计入卡6 `compute_metrics` 的 guard 组。

### ③流水线相位与调用时机
deslop 相位每轮采纳点（2011-2013）+ G7 回退点（2034）；不新增相位，不与 ±20% 字数纪律拉扯（mustscan 契约注释 :106-109 既定纪律——不另起自动重试环，借既有轮次熔断）。

### ④QML/UI 面
无界面，config 即入口（无新开关：随 must 规则存在而生效，零 must 规则的书零开销）。

### ⑤先写哪条测试
`tests/unit/test_deslop_must_rescan.py::test_rewrite_not_adopted_on_new_must_breach`——假客户端：初稿 0 违规、改写稿引入一条 forbid 命中 → 断言改写稿被回退（prose 保持改写前）、复扫日志含「must 新增违规」、`gr.deslop_rounds_used` 递增；`test_no_must_rules_zero_overhead`（无 must 规则 → 双复扫跳过，字节不变）。

### ⑥依赖与被依赖
依赖：卡6（metrics 出口，弱依赖可后接）；无 B3 依赖（插入点在 deslop 区段，B3 切分后为 `_mc_deslop` 内清晰位——若 B3 先完成则落在切分后函数上，两者不冲突）。被依赖：卡8 G1（trim 链同款「改写不得更糟」哲学）；L 档送检流程。

### ⑦人日与风险
**1-1.5 人日**。风险：①must forbid 正则写坏（不可编译 → advisory，mustscan.py:60-63 已兜）不致回退风暴；②回退换策略重试可能烧轮次——并入 max_deslop_rounds 熔断即为上界；③scan_proj 只扫前 8000 字（_PROSE_WINDOW）——超标章的尾部违规不在指纹内，与 G1 断路器互补。

---

## 卡 8 ｜ G1-G7 护栏（T3-1 三类病的七道保险丝；每 G 精确插入点）

### ①现状与②改动设计（按 G 逐条；插入点均为 HEAD 实测）
- **G1 字数预算断路器**（S）：插入点 = 首稿字数检查后、trim 循环前（`stages.py:1814-1819` 取 `(low_ok, high_ok, actual)` 之后、1907 `while not high_ok` 之前）。`actual > target×(1+tol)×N`（出厂 N=3，新配置 `gates.word_overflow_breaker`）→ 不进 trim/deslop/审校，mark_continue 标 needs_fix+word_overflow 跳章、strict 走 `resolve_failed`→auto_pause。**trim 采纳加最低压缩量守卫**：1924 行 `prose = _rewrite_phase(...)` 无条件采纳处，压缩量 < cut_pct/2 视为该轮失败（对照：扩写环 1897 有守卫、审校修复环 2163 有「未改善即弃」、唯独 trim 没有）；trim_over 事件（1936-1941 已有）升 error。
- **G2 截断稿识别**（M）：`app/llm/client.py:518-532` finish_reason 现仅用于空内容重试——新增 `last_finish_reason` 属性透出；microcycle 对 prose/trim/deslop 相位 length 截断稿按 G1 处理（无效稿不得进闸门链）。
- **G3 跨章待修断路器**（S）：插入点 = orchestrator 章循环收尾（orchestrator.py:489-493，record→append_history 区）；维护连续 needs_fix/need_human 计数，≥K（出厂 3，新配置 `gates.consecutive_fail_pause`）→ 即使 mark_continue 也 `auto_pause`（orchestrator.py:135-139），sig_auto_paused 带章号区间与阻塞摘要；need_human 落章 warn 升 error（stages.py:2179-2183 现为 warn）。**review_max_rounds 到头处**（stages.py:2176-2187 `mark_chapter_need_human` 后）同步发聚合事件。
- **G4 相位看门狗**（M）：插入点 = orchestrator 章循环收尾 append_history 后（492-493）：零成本校验「第 N 章落库 ⇒ 存在第 N 章 tracking/摘要产物（或账本行）」，缺 → error + 计数，连续 ≥2 章 → auto_pause/常驻横幅。
- **G5 usage 台账准实时告警**（M）：插入点 = `app/usage.py:157-194 record()` 落盘后挂纯本地规则：①prose 单笔 out ≥ 0.8×max_tokens（顶格）→ error；②单章成本 > 滚动中位 ×5 → warn；③章推进但 N 章无 tracking 行 → error。事件写 `state.anomalies`（**state.py 新键**，validate_state 键型表 :343 同步加 `"anomalies": dict`）供 UI 常驻横幅。项目级事件账复用 `volume_session.record_event:84`。
- **G6 记账不可中断区**（S/M，治本于 30 章停摆）：插入点 = `stages.py:2235` `project.write_file(chapter_path, prose)` 之后置 `ctx.in_epilogue = True`：`checkpoint()`（2236/2248 两处）在记账窗口不再抛 PipelineStopped，停止请求推迟到章界；最起码把 2248 的 checkpoint 移入 try 内统一收口。**与 long_run orch.stop 的竞态修法**：外部 stop 到达时记「pending_stop」，记账四相位（2237-2408）全部完成后在章界统一 stop——「已落库未记账」状态不再产生。
- **G7 检测口径与短章地板**（M）：`gates.py:131-160 word_count_precheck` 只查下限（148-150 `actual >= floor` 直接放行）——加上限侧报告（超标不拦但必须出现在 findings）+ 短章（<floor×0.5）禁止静默定稿；阻断数按千字归一入章记录（deslop 密度阈值已按千字 deslop.py:142，无需重做）。

### ③流水线相位与调用时机
G1 在 enrich 相位入口；G2 在每次 LLM 响应解析后；G3/G4 在章循环收尾；G5 在每次 usage.record；G6 覆盖 finalize 全窗口；G7 在锁定/审校前置。优先级：G1+G3 先做（T3 复跑保护立竿见影）→ G4+G5（零告警翻案对）→ G6（语义修复）→ G2/G7 随 v2 复盘。

### ④QML/UI 面
G3/G4 触发 auto_pause → 既有暂停横幅（sig_auto_paused）；G5 anomalies → 新常驻横幅（Main.qml 一条 binding）；G1/G2/G7 无新 UI（日志+章记录字段）。

### ⑤先写哪条测试
`tests/unit/test_word_overflow_breaker.py::test_ten_fold_draft_skips_downstream`——假客户端返回 10 倍稿 → 断言 rewrite/审校调用数=0、record 带 word_overflow；`test_trim_equal_length_rejected`（等长稿被最低压缩量守卫拒绝）；`tests/unit/test_consecutive_fail_pause.py::test_three_rejects_pause_once`（连续 3 章 REJECT → orch.paused==True 且只触发一次、pass 即清零）；`test_watchdog_missing_tracking_pauses`（模拟 stop 杀在记账窗口 → 下一章开写前看门狗触发；正常跑零误报——回放 T3 v1 台账 1705 行应命中 ch41-44 顶格+相位真空、ch1-40 零误报）。

### ⑥依赖与被依赖
依赖：G1/G3/G4 动 orchestrator/stages 主链——B4 测试网先行（w4_refactor：B4 是「stages 侧任何动刀」的前置）；G6 与批量挂机 C（Wave 3）硬前置关系。被依赖：卡9 P1（CW-G6 同款对账思想）；盲评协议闸 1 五哨兵的口径来源（w5_satisfaction §3.4 逐字引用 G1/G3/G5）；T3 v3 预注册长跑（蓝图 Wave 4：护栏全开）。

### ⑦人日与风险
**合计 8-10 人日**（G1 1 / G2 1.5 / G3 1 / G4 1.5 / G5 2 / G6 1-1.5 / G7 1）。风险：①G6 改 stop 语义涉及 orchestrator.run（191 行无直接单测过程式单体）——B4 测试网是硬前置；②G5 阈值误报（0.8×max_tokens 对不报 max_tokens 的渠道退化为不判）；③G1 的 N=3 出厂值需按题材长文校准（文青书 P90 16k 字 vs 目标 3k 已 >5×——**N 必须可配**，且对细纲登记高目标的章按登记值算）。

---

## 卡 9 ｜ P1-P4 四原型移植（脚本 → 模块；_scratch\superiter\proto\）

### ①现状
四原型已跑通（stdlib-only，qianbi venv Python 3.13.14，三真实项目只读副本）：`p1_quote_anchor.py`（normalize:142 / anchor_strict:148 / anchor_norm:151；108 条真实抽取 normalized 锚定 100%、三类幻觉 36/36 拦截）、`p2_state_card.py`（build_sections:193 / trim_to_budget:246；12288B 硬上限 + P5→P0 优先级裁剪）、`p3_post_write_check.py`（check_characters:135 / check_foreshadows:163 / check_arc:190 / check_reader:212 / checklist:237）、`p4_rule_qc.py`（r1_wordcount:66 / r2_repeat:76 / r3_sensitive:90；55% 断流闸在真实章命中真缺陷）。qianbi 侧对应落点：定稿流程 `_do_lock_chapter`（bridge.py:4565，已挂 `_maybe_backflow` 4578）；cw 参考块 `compose_reference_block`（co_dialogue.py:196-235，手工四块拼装）；gates/deslop 增量位。

### ②改动设计（逐原型移植路径）
- **P2 状态卡 → `app/core/memory.py` 渲染器**（S，可先行）：新函数 `build_state_card(proj, num, *, budget=12288) -> str`（七栏：当前位置/长期约束/核心角色/活跃伏笔/近三章速记/下一章承诺/连贯性风险；输入全是现有追踪文件 + `worldbook_text/regex_block` 现成接口）；落点：cw `compose_reference_block` STAGE_CW_PROSE 分支整体替换 + supervisor 上下文；自动档正文组装近场注入与 `追踪/上下文.md` 槽位择优替换。裁剪口径与现有预算（1500/1200 字符）统一，防两套截断哲学并存。**区间计划回收取 [min,max]**（原型坑①）、角色过滤「全文本出现过 ∨ 题材定位角色表登记」（坑②）、容忍行首「（暂无）」脏数据（坑③）三条修正随移植。
- **P4 质检 → `gates.py` + deslop 旁**（S）：`gates.py` 新增 `check_collapse(text, target) -> bool`（55% 断流闸，返回值并入 GateResult 作独立于 word_ok 的 crash 信号——**90% 质量闸（扩写）与 55% 故障闸（停机）语义不同绝不合并**，原型坑②）；触发走 strict 停机而非 mark_continue；`repeat_check()`（~30 行）进 deslop 模块旁（blocking 附 60 字引文）；敏感词词库 `assets/sensitive_words.txt` 数据文件 + advisory 只提示。
- **P1 引文锚定 → stages 定稿流程 + `追踪/事实账本.jsonl`**（M）：新模块 `app/core/fact_ledger.py`：`extract_facts`（LLM 结构化调用 facts[{claim, evidence}]，schema 复用 canon_audit 写后提取风格）+ `normalize()`（NFKC+去空白+引号统一，**原型代码直接搬**）+ 两级锚定闸门（strict→normalized）+ 逐条拒收（整笔拒绝在真实数据连坐丢 124 条真事实——原型结论）+ 拒收日志；挂点 = 自动档 finalize 追踪区（2238 `_update_tracking` 后）与共写 `MemoryBackflowWorker._run_backflow`（co_dialogue.py:700-790，锁定语义保证文本稳定——**共写是 P1 最佳首挂点**，w4_cowrite §4）；产物 append-only `追踪/事实账本.jsonl`（字段 chapter/claim/evidence/anchored），**不进 state['cw']**（worker 线程 load→save 已是丢失更新窗口，账本进 state 会放大）。对照样本注入（paraphrase/cross_chapter/width_variant 三类）保留为验收探针。
- **P3 四查 → `app/core/maintenance.py`**（M）：四函数 `check_characters/check_foreshadows/check_arc/check_reader` 平移 + `maintenance_block(proj, num) -> str` 拼装；挂点 = `_do_lock_chapter`（bridge.py:4565-4574，锁定事件后、反哺旁）与自动档 finalize；checklist 注入下一章 prompt 组装（cw 走 compose_reference_block，与 P2 同注入口）；**「待确认卡片」形态**（确定性轨召回好精度中——新实体不自动登记，GUI 待确认卡是 qianbi 相对 skill 的结构优势）；**不进 `cw["report"]` 单槽**（state.py:403，已被 supervisor 报告/世界书通知/clearCwReport 三共抢）——独立通道 `cw["maintenance"]` 或转写系统条目；四查项未处理时锁定弹确认卡（绑真闸，防复制 supervisor「无牙报告」命运）。

### ③流水线相位与调用时机
P2：prompt 组装（每章 draft 前 / cw 每轮对话前）。P4：draft 相位后字数闸旁（collapse 判定先于扩写循环）。P1：finalize 记账相位（追踪更新后）。P3：锁定事件（cw）+ finalize（自动档）。全链与 G6 记账保护互锁：P1/P3 挂在记账窗口内，必须等 G6（卡8）或 CW-G6 看门狗（卡10）就位。

### ④QML/UI 面
P2：状态卡预览页（可选，编辑器侧栏）；P1：拒收事实/待确认卡片流（作者在环核心卖点）；P3：待确认卡片（新实体勾选登记）；P4：无新 UI（collapse 走停机文案 + 敏感词 advisory 进审校块）。

### ⑤先写哪条测试
P1：`tests/unit/test_fact_ledger.py::test_hallucination_triple_blocked`——原型三类幻觉样本（显式标 synthetic）断言改写/跨章全拦、噪声 100% 被归一化救回；P2：`test_state_card_under_budget_and_trim_log`（压力样本裁剪后 ≤12288B 且审计日志 N 项）；P4：`test_collapse_gate_at_55pct`（1382/3000=46% → crash 信号，90% 闸不联动）；P3：`test_new_entity_requires_confirm_card`（新实体出待确认项而非自动写库）。

### ⑥依赖与被依赖
依赖：P1 ← 卡10 CW-G6（锁定⇒账本行必须存在的对账）；P3 ← P1（伏笔 evidence 闸门——两个原型最重要的联动结论）；P2/P4 无前置可先行。被依赖：P1 事实账本 → 卡2 T3 伏笔检索长期地基 + 下一章 prompt 组装；P3 伏笔「待登记推进/回收」回写伏笔表强制带 evidence。

### ⑦人日与风险
**P2 1 / P4 1 / P1 2.5-3 / P3 2.5-3 ≈ 7-8 人日**。风险：①P1 的 LLM 抽取 schema 与重试（闸门本身 S，抽取 M）；②P3 精度中等——上线必须是待确认卡而非自动写库；③P4 敏感词高误报（悬疑修仙文「血/杀」高频）——只 advisory 是正确设计，词库按平台维护。

---

## 卡 10 ｜ CW-G1~G7 共写护栏 + B6 测试批映射（共写成为「可兑现的作者在环」的收尾批）

### ①现状
七条护栏出自 w4_cowrite §5.1（验收判据已给全）；其中 **CW-G1/G2/G3 = 卡1 F1-F3 的护栏编号**（一一对应，随卡1 落地）。余下四条的现状：CW-G4 锁定闸只查下限（bridge.py:4499 `word_count_precheck`；`check_word_bounds` 在 bridge/co_dialogue 零调用 grep 证实）+ 细纲全量校验 O(全书)（`_start_cw_outline_validation` bridge.py:4402-4417 取 `project.list_outlines` 全部，无 [:N] 截断）；CW-G5 `_cw_cancelled` 单旗标无 worker 代际校验（bridge.py:4259/4272-4276）+ OutlineBatchWorker 先写文件后 emit done 的半提交（co_dialogue.py:529-537）；CW-G6 反哺失败后无对账看门狗（恢复只有手动 runBackfill bridge.py:4650-4680；启动无「已锁定 ∧ ¬backflow_is_fresh」扫描）；CW-G7 打回级联不确认（`_rollback_to` bridge.py:5227-5237 只 toast 归档数，已锁定章/追踪不回滚且无提示）。

### ②改动设计（仅余四条；G1-G3 见卡1）
- **CW-G4 上限入账 + 校验输入截断**：锁定闸加「超标报告」（不拦但必须出现在 lockBlockedDetail.violations，复用 T3-1 G7 口径）；`_start_cw_outline_validation` 按最新批 + 相邻 ±2 截断（对齐 OutlineBatchWorker:507-510 口径），全量模式显式入口。
- **CW-G5 取消代际化 + 半提交对账**：`_cw_cancelled` 换 worker 代号（spawn 自增 token，done 带 token 比对）；OutlineBatchWorker 被取消但已写文件时，done/error 路径补「已落盘 X 章细纲」对账回执（写转写 + last_outline_batch）。
- **CW-G6 反哺对账看门狗**（P1 前置）：项目打开（`_open_project` bridge.py:1312）/锁定时扫描「已锁定 ∧ ¬backflow_is_fresh」集合 → 常驻横幅 + 一键入队补跑；沿用 T3-1 G4 判据。
- **CW-G7 打回边界确认**：级联目标存在已锁定章或非空追踪时，打回前确认卡列出「将删除 X 个产物；已锁定第 a,b,c 章与追踪/伏笔表不会回滚」；顺手清 `supervised/auto_fix` 下游键。
- **B6 测试批映射**（w4_refactor B6 + w4_cowrite §5.2 Top5 缺口）：新文件 `tests/unit/test_cw_bridge_slots.py`（=卡1 三组测试的宿主文件）+ `tests/unit/test_cw_state_machine.py`（CoWriting 迁移表全覆盖）。w4_cowrite §5.2 五缺口 → 批内落位：缺口1（supervisor 错误→逃生门链）与缺口2（M5 派单模式钉测）进 test_cw_bridge_slots（卡1）；缺口3（cancel 交叠完成序）与缺口5（打回级联×已锁定章）进 test_cw_state_machine（CW-G5/G7 先以注入代际 done 序写红）；缺口4（两 save 之间崩溃一致性）进 test_cw_state_machine（monkeypatch 第二次 save 抛异常）；附带缺口6（校验输入长度界：60 章夹具 → `ReviewOutlinesWorker.last_prompt ≤ cap`）。

### ③流水线相位与调用时机
全部在共写 bridge 编排层（`_get_cw_mode()=="cw"` 守卫内），自动档零触碰；CW-G6 在项目打开与锁定事件两时机。

### ④QML/UI 面
CW-G4 violations 字段（既有 lockBlockedDetail 管道）；CW-G6 常驻横幅；CW-G7 打回确认卡（CwDialogueDock/Main 确认卡流）；CW-G5 无新 UI（转写回执）。

### ⑤先写哪条测试
`tests/unit/test_cw_state_machine.py::test_cancel_token_overlapping_done`——注入两代 worker 交叠 done 序列 → 断言新回复入转写、旧回复丢弃（CW-G5 前半，先写红）；`test_rollback_with_locked_chapters_shows_confirm`（3 锁定章 + 伏笔表非空 → rollback(cw_core) → 锁定标记/伏笔表原样 + 确认卡文案含锁定章名单）。

### ⑥依赖与被依赖
依赖：B0；卡1（G1-G3 与 F1-F3 同链，先修后测）。被依赖：CW-G6 → 卡9 P1（挂载顺序 P2 → CW-G6 → P1 → F1-F3 → T2 → T1 → P3，w4_cowrite §4）；B8e（共写族 mixin 搬运）在本批与卡1 之后（新增 Signal 遵守 mixin 策略放 Bridge 主类声明区）。

### ⑦人日与风险
**余四条 3.5-4.5 人日**（G4 1 / G5 1.5 / G6 1-1.5 / G7 0.5）+ B6 测试批 2 人日（w4_refactor 口径）≈ **5.5-6.5 人日**（含与卡1 共享宿主文件的协同）。风险：①bridge worker 编排层是 unit 测试盲区（F1-F3 三伤全在此层，AST 级重复定义无测试形态能抓——inspect 源码钉测是唯一解）；②`_DispatchSelf` 型替身签名要随生产码同步扩参（F2 教训）；③CW-G5 token 化触碰所有 cw worker done/error 槽——回归面大，需 `pytest tests/unit -k cw` 全量 + probe_cw_* 三探针。

---

## 附：总账与口径

| 卡 | 内容 | 人日 | 关键前置 |
|---|---|---|---|
| 1 | F1-F3 修复（=CW-G1/G2/G3） | 1.5-2 | B6 宿主文件 |
| 2 | T3 伏笔到期引擎 | 1.5-2 | B4 |
| 3 | T1 爽点节奏带账本 | 4-5 | **B3 硬前置** |
| 4 | T2 钩子追读链账本 | 3.5-4.5 | **卡1** |
| 5 | T5 桥段码账本（36 码） | 4-6 | 卡3 同批 |
| 6 | deslop 度量层 + 28→45 | 5-6 | 无（B1 让位） |
| 7 | must 机器复扫闭环 | 1-1.5 | 无 |
| 8 | G1-G7 护栏 | 8-10 | **B4**（G6→批量挂机 C） |
| 9 | P1-P4 移植 | 7-8 | CW-G6→P1→P3 |
| 10 | CW-G4~G7 + B6 映射 | 5.5-6.5 | 卡1 |
| **合计** | | **≈41-48 人日** | |

- **口径统一**：deslop 规则数用蓝图 §6 裁决值「28 个 rule id」；码表用「36 码（枚举口径）」；伏笔表行号以本文件实测为准（tracking_store.py:21）。
- **版权合规**：oh-story/humanizer/lieflat 三源 LICENSE 均为 MIT（已核实原文）；规则与判据内化时保留版权声明、措辞自写、阈值注明来源；36 码表与打法卡为本机自产拆解框架内容，绿档。
- **纪律**：本文件为只读施工说明，未改主仓库任何文件；所有 diff 落点已在 HEAD 2de3e9d 实测对齐；未触碰任何 T3 相关在跑进程。
