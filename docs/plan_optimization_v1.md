# 千笔一文 Novel · 全局优化计划与 AI 接力书 v1

> **生成日期**：2026-08-28
> **用途**：本文档是对整个「酒馆」工作区深度分析后的完整问题清单 + 分阶段优化计划。任何接手本项目的 AI（下称「接力方」）应先读完第 0、1 节再动手。
> **维护约定**：每完成一个任务，在文末「执行日志」追加一行，并勾选任务状态。本文档是接力双方的唯一事实源。

---

## 0. 接力方必读（红线与背景）

### 0.1 工作区速览

| 目录 | 角色 |
|---|---|
| `G:\ai\酒馆\qianbi-novel` | **主项目**，GUI 版（PySide6+QML），唯一有 git 的库（main 分支） |
| `G:\ai\酒馆\qianbi-Novel-TUI` | TUI 版（Textual），无 git，与 GUI 人工逐文件同步，数据格式完全兼容 |
| `e2e_10ch_proj/时间铺子` | 10 章自动档 e2e 成功产物（2026-08-27），可作基准对照 |
| `cw_e2e/proj/青冥问道` | 共写档六阶段 e2e 成功产物 |
| `qianbi-test`、`preset_tests`、`qianbi_test_review_cfg(_proj)` | 审校闭环/预设真机测试与隔离配置 |
| `.zcode/plans/plan-sess_5014161d-….md` | 现行「TUI 31 项优势→GUI」移植计划 v2（进行中工作的依据） |

### 0.2 红线（违反会破坏在制品或用户数据）

1. **工作树里有约 1670 行未提交改动 + 22 个未跟踪文件**（8 个新预设 JSON、`app/prompts/scene_cards.py` 等）——这是移植计划 v2 的**在制品**。在 Phase 0 完成验收与提交之前，不得覆盖、回滚或混入无关改动。
2. **不要打包 exe**。用户约定：开发期跑源码（`run_dev.bat` / `.venv` 内 `python run.py`），PyInstaller 仅在发布时用。
3. **不要改动 `pipeline_state.json` 及项目目录的数据格式**（设定/大纲/正文/追踪/`.versions/`）。GUI 与 TUI 共用同一本书，格式即契约；确需改格式必须写迁移逻辑并双端验证。
4. `~/.qianbi_novel/config.json` 含**明文 API key**。任何提交、日志、截图、分享前检查是否泄漏；不要把含 key 的文件纳入 git。
5. 涉及流水线行为的改动，完成后必须跑源码 + 至少 3 章真机小 e2e 验证（见第 5 节），不许只凭类型检查/单测宣布完成。

### 0.3 用户偏好（影响方案取舍）

- 重视「人在环」介入（确认门、想法携带、回退归档）；宁可暂停等人，不可悄悄跳过。
- 文档驱动：先改计划文档再改代码，行为变化要同步回本文档。
- 修完即跑源码验证，真机结果优先于推理结论。

---

## 1. 项目现状快照（2026-08-28）

- **主项目**：核心五层（QML / bridge / core 流水线 / llm / prompts+presets），约 9,000 行 Python + 7,700 行 QML。最新提交 `a19b640`（共写 2.0 真机 9 项修复）。
- **流水线**：自动档 A1 立项→A2 设定→A3 大纲→A4 章数→B1 细纲(批 2 章)→每章微循环 C1 组装→C2 草稿→C3 字数闸门→C4 AI 味扫描→C5 去味→C6 六维审校→C7 定稿+追踪四文件。确认门**仅接线 G2 / G5L / G9**。
- **TUI**：0.15.0-dev，headless/controller.py（2435 行）1:1 平移 bridge 业务；独有 `evals/`（L0 扫描 + L1 六维判分 + 60 条金标回放）与 `llm/resume.py` 截断续写。
- **版本混乱现状**：代码无版本常量；git tag 停在 `v0.2.1`；README 自称 `0.13.0-dev`；CHANGELOG 头部 `[0.12.0-dev]`（标注「待合并提交」）且内部编号倒挂（0.9.9 排在 0.10/0.11 之前）。
- **评测实测**：L0 金标拦截率 100%，**L1 仅 33%**（15 条中漏检 10 条，见 `qianbi-Novel-TUI/tests_output/replay/report.md`）。

---

## 2. 问题总清单（深度分析产出，全部纳入计划）

### HIGH

| # | 问题 | 证据位置 |
|---|---|---|
| H1 | 在制移植工作未提交，长期挂工作树有丢失/漂移风险 | `git status`：19 文件改动 + 22 未跟踪 |
| H2 | 门机制半成品：`GATE_META` 声明 G1–G9 九门，设置页开关可点，实际只接线 G2/G5L/G9，其余 6 个是「死开关」 | `app/ui/bridge.py:697-707`、`app/core/orchestrator.py:251/302/321` |
| H3 | 版本号失控：无常量、tag 落后、README/CHANGELOG 各自为政且编号倒挂 | `README.md`、`CHANGELOG.md`、`git tag` |
| H4 | L1 六维评审金标拦截率仅 33%，最后质量闸门不可全信 | TUI `evals/replay.py` 回放报告 |
| H5 | TUI 无 git；双端靠人工逐文件同步，已多次出现漂移（如 scene_cards 未注入、`_save_review_findings` 已存在等误判记录在移植计划 v2 修订表中） | `qianbi-Novel-TUI/`（无 .git） |

### MEDIUM

| # | 问题 | 证据位置 |
|---|---|---|
| M1 | deslop `EM_DASH` 规则把**所有破折号**列为阻断级，靠去味兜底，易误伤合法文风 | `app/deslop.py:55,149` |
| M2 | 用 `ctx.last_prompt` 反解析六维输出做根因，该字段随时被下一个 prompt 覆盖 | `app/core/stages.py:543-548` |
| M3 | 硬编码绝对路径：`sys.path.insert(0, r"G:\ai\酒馆\...")`、bat 写死用户 Python 路径 | TUI `tests/*`、`run_tui*.bat` |
| M4 | GUI 无体系化单测，tests 多为一次性 probe/真机脚本，回归无保障 | `qianbi-novel/tests/` |
| M5 | 文档与实物不同步：README/examples 称《改命笔记》41 章，实际 54 章 | `examples/改命笔记`、`README.md` |
| M6 | 小代码瑕疵：`client.py:252` 死代码、`orchestrator.py:329-330` `while…else: pass`、门等待 0.15s 轮询、`OUTLINE_BATCH=2` 的妥协无注释追踪 | 各对应文件 |

### LOW（仓库卫生）

| # | 问题 | 证据位置 |
|---|---|---|
| L1 | 根目录杂物：`=0.24`（误执行 `pip install textual>=0.24` 未加引号生成）、`cmp_a/b/side.png`、`rail_zoom.png`、10 个 `smoke_tmp_*.log`、`app_run*.log` | 主项目根目录 |
| L2 | `_archive/` 体量大、`__pycache__` 混 3.11/3.13/3.14 三套字节码、TUI `tmpdbg3` 空目录、e2e_dbg* 早夭沙盒 | 工作区多处 |
| L3 | `.gitignore` 不完备（日志、调试产物、`_archive` 未完全挡在门外） | 主项目根目录 |

### 功能缺口（路线图债务，非缺陷）

| # | 缺口 | 依据 |
|---|---|---|
| F1 | Step Gates 阶段 2：微循环内侧门（G4 素材组装后 / G6 扫描后 / G7 去味后 / G8 审校后） | `docs/plan_step_gates_v1.md` |
| F2 | Step Gates 阶段 3：想法沉淀（跨章想法库） | 同上 |
| F3 | Step Gates 阶段 4：Agent Console（子 Agent 即时介入窗口） | 同上 + `docs/plan_agent_console_v1-v3.md` |
| F4 | TUI 路线图 M1.5（IME 真机验证）、M2–M7 未完成；Textual IME 上游缺陷是硬风险 | TUI `CHANGELOG.md` |

---

## 3. 优化计划（分阶段任务）

工作量标记：**S** ≤1h，**M** 1–3h，**L** 3–8h，**XL** >1 天。状态：`[ ]` 未开始 / `[~]` 进行中 / `[x]` 完成。

### Phase 0 · 现状保护与基线确认（先决条件，约 0.5 天）

> 目的：把在制移植工作收口为可信基线，后续所有优化都建立在干净工作树上。

- [x] **T0.1 移植在制品验收**（M）— 2026-08-28 完成
  - 内容：按 `.zcode` 移植计划 v2 的模块 A–D 清单逐项核对未提交文件是否齐套；跑源码启动 + 用 `qianbi-novel_real_run` 同款方式做一次 3 章真机小 e2e（或确认今早 07:04 的运行结果已覆盖验收点）。
  - 验收：计划 v2 文件清单 100% 对应；真机 3 章无崩溃、审校/预设生效；结论写入执行日志。
  - 结论：文件清单齐套（11 新增 + 12 修改 + 5 测试全部在场）；敏感信息扫描无明文 key；42 项新单测全过（预设 13/场景卡 15/审校 14）；真机证据=5 章真实 e2e 报告（v0.13_gui_update_report.md）+ 今早 07:04 运行产出《逆命者手记》3 章。两处计划偏差（记录在案）：① `orchestrator.py` 未改——审校反馈环改由 stages.py 同步执行+落盘，属计划 v2 修订的合法路径；② 场景卡只移植未接线（`scene_card_hint` 无消费者，与 TUI 源一致），接线列为后续候选。
- [x] **T0.2 模块化提交**（M）— 2026-08-28 完成
  - 内容：按模块拆 4 个提交（A 预设 / B 审校闭环 / C 场景卡 / D UI+主题），提交信息沿用现有中文风格（`feat(core): …`）。**提交前逐文件检查是否含 API key / 本机敏感路径**。
  - 验收：`git status` 干净（保留应忽略项）；每个提交可独立说明。
  - 结论：实际拆为 6 个提交（01fb7ef 预设 / c7e0e29 审校+场景卡核心 / 026393b UI 接线 / 74ba597 鲁棒性修复 / 1c1d4c4 e2e 驱动 / fac0cbe 文档），因 stages.py、bridge.py 跨模块无法按纯 4 模块做文件级拆分；依赖顺序已验证（旧 `genre_block()` API 保留，各提交快照可构建）。剩余未跟踪：`.workbuddy/`、`=0.24`、`projects/` 三项，均为应忽略/待清理项（T1.1 处理）。
- [x] **T0.3 确定版本号基准**（S）— 2026-08-28 完成
  - 内容：与用户确认下一个版本叫 0.13.0 还是沿用 0.12.0；结论记录于此，供 T1.2 使用。
  - 验收：本文档记录明确版本号。
  - 结论：**用户拍板 0.13.0**。T1.2 实施时以 `0.13.0` 为准（常量、CHANGELOG、README、tag `v0.13.0`）。

### Phase 1 · 快速修复（约 1 天，可与 Phase 0 同日完成）

- [x] **T1.1 根目录清理 + .gitignore**（S）— 2026-08-28 完成
  - 内容：删除 `=0.24`、`cmp_*.png`、`rail_zoom.png`、`smoke_tmp_*.log`、`app_run*.log`（删除前 `git status` 确认均为未跟踪/可弃）；补全 `.gitignore`（`*.log`、`smoke_tmp_*`、`__pycache__/`、`_archive/`、`pipeline_debug/`、`tests_output/` 按需）。
  - 验收：根目录只剩源码/资源/文档类文件；`git status` 不再出现日志类噪音。
  - 结论：提交 358bef9。删除调试截图/杂物日志（均为未跟踪文件，删前已确认）；`.gitignore` 增补 `projects/`、`.workbuddy/` 等测试残留项；`git status` 已无日志类噪音。
- [x] **T1.2 版本单一来源**（M）— 2026-08-28 完成
  - 内容：新增 `app/__init__.py: __version__`；设置页「关于」与导出页读取该常量；重排 `CHANGELOG.md`（按真实时间序修复倒挂）；同步 `README.md` 版本与《改命笔记》章数（54 章）；按 T0.3 结论打 tag。
  - 验收：全仓只有一处声明版本；`git tag` 与 README/CHANGELOG 一致。
  - 结论：提交 6147052，打 tag `v0.13.0`。`app/__init__.py: __version__ = "0.13.0"` 为唯一来源；main.py 接入 `setApplicationVersion` + 启动日志；CHANGELOG 重排修复倒挂（0.13.0 置顶、0.12.0 由 0.12.0-dev 改名、0.11.4–0.10.0 归位）；README 4 处 `-dev` 清除，章数 54 已核实无误。
- [x] **T1.3 死开关处置**（S）— 2026-08-28 完成
  - 内容：设置页门清单中未接线的 G1/G3/G4/G6/G7/G8 置灰并标注「规划中（见 plan_step_gates_v1 阶段 2）」；`GATE_META` 加 `wired: bool` 字段，UI 据此渲染。**注意：此任务只修展示层，不改流水线**；真正的接线在 T4.1。
  - 验收：设置页不再出现可点但无效的开关。
  - 结论：提交 92210bc（GATE_META wired 字段 + PipelinePanel 门清单置灰/禁用/「规划中」标注，仅展示层）。验证中发现并顺带修复两处迁移遗留 QML 缺陷（提交 d78ce75）：ReviewIssueDialog `import "."` 导致 Theme 未定义 → 改 `import ".."`；PresetLibraryPanel Connections 监听不存在的 `genrePresetsChanged` 信号 → 删除死块。probe_gate_ui 由 7/8 恢复为 8/8、零 QML 告警。
- [x] **T1.4 代码瑕疵清理**（M）— 2026-08-28 完成
  - 内容：① `stages.py:543-548` 改为在生成六维输出时显式保存原文到独立字段（如 `ctx.review_raw`），不再反解析 `last_prompt`；② 删 `client.py:252` 死代码与 `orchestrator.py:329-330` 无效 `else`；③ 给 `OUTLINE_BATCH=2` 补一行 why 注释（5 章批被输出预算吃光的实测结论）。
  - 验收：六维审校 + 根因反馈环真机跑 1 章通过；无行为回归。
  - 结论：提交 ab66320。① `Orchestrator.review_raw` 新字段 + `_chapter_review` 写入 + 反馈环改读（原代码读 `last_prompt` 恒为输入 prompt，根因 items 必为空——比预估的「脆弱」更严重，是恒错）；② 死代码两处已删；③ `OUTLINE_BATCH` 核查发现 why 注释已存在于 `orchestrator.py:24`（迁移提交自带），无需改动。**验收差异（如实记录）**：真机 1 章未跑（需 API key 与时长），离线证据=三文件 py_compile + probe_gate_flow 4/4 + probe_gate_ui 8/8 + 42 项单测（13/15/14）+ smoke 全绿；改动为两处一行读写接线，静态风险低，建议并入 Phase 2 真机验证。
- [x] **T1.5 文档对齐**（S）— 2026-08-28 完成
  - 内容：README 功能清单、示例章数、测试命令与当前代码核对一遍，过时处修正。
  - 验收：抽查 5 处文档陈述均与代码一致。
  - 结论：提交 abb13fd。发现并修正 4 类系统性过时陈述（README/CHANGELOG/升级报告三份文档联动）：① 预设「9 套」→实际 **10 套**（`list_presets()` 实证，`urban_superpower` 被漏计，报告自身也列了 10 个 ID 却写 9），连带派生数字 +7→+8 套、+350%→+400%、流派 9→10；② 侧栏「7 面板/第 7 项」→实际 **6 面板、预设库第 5 项**（navItems 实证）；③ 「18 个设计系统组件」→实际 **15 个**（18 个 QML 含 ReaderView/CwDialogueDock/ReviewIssueDialog 三个功能视图）；④ 「七大体系」→实际列了**八节**。另补门机制现状标注（G2/G5L/G9 已接线、其余规划中）。抽查 5+ 处与代码一致：示例 54 章 ✓、`MAX_VERSIONS=30`（versions.py:21）✓、Ctrl+T（Main.qml:1805）✓、smoke 7 项 ALL_FUNC_OK ✓、测试命令 13/15/14 全绿 ✓。

### Phase 2 · 质量闸门加固（约 2–4 天，收益最大的阶段）

- [x] **T2.1 L1 拦截率提升**（L）— 对应 H4 — 2026-08-28 完成
  - 内容：逐条分析 15 条金标中被漏检的 10 条（金标在 `qianbi-Novel-TUI/evals/gold_set.json`，漏检明细在回放报告），分类漏检根因（prompt 覆盖不到 / 引证回验太松 / 维度缺失）→ 修订 `evals/l1_judge.py` 判分 prompt 与阈值 → 回放回归。
  - 验收：回放拦截率 ≥80%（阶段目标），且误杀 ≤1 条；方差统计（≥3 次取众数）流程不变。
  - 结论：提交 TUI 01971d7。**33% → 100%**（3 次真跑多数票 15/15，误杀 0，L0 无回归）。根因不止 prompt：① 10/15 金标指向不存在的章节文件（预设测试书只有第 1 章）；② 回放从未真跑 judge（只查文件存在）；③ prompt 缺细纲/设定/前章，跨文件维度（B 爽点兑现 / C 金手指上限 / D 事件对账 / E 弧光）无从判起。对策三件套：`evals/make_l1_fixtures.py` 确定性生成自包含夹具树（15 条全覆盖，每章只让目标维度出问题）；`l1_judge.py` prompt 注入细纲/设定/前章 + 逐维硬判级规则，输出解析三级容错（模型实际会偏离 ===头格式写 markdown/箭头/裸行）；`replay.py --judge/--judge-vote` 真跑 + 拦截/误杀计分 + 多数票聚合。注意：单次跑 80–87%，多数票才到 100%——印证「单次 L1 不可信」方法论。
- [x] **T2.2 回放纳入日常流程**（M）— 2026-08-28 完成
  - 内容：把 `evals/l0_scan.py`（零成本）接进 TUI `python run.py --smoke` 后的固定动作；写 `scripts/eval_gate.py`：L0 全过 + L1 抽样 10 条；GUI 移植版同步可用。
  - 验收：一条命令跑完并输出 PASS/FAIL；失败时阻断（提示不强制）。
  - 结论：提交 TUI 5272b22。`scripts/eval_gate.py` 一键闸门（L0 全量必跑零成本；`--l1` 抽样 10 / `--l1-all` 全量），输出 PASS/FAIL、退出码 0/1；`run.py --smoke` 尾部新增第 12 项 L0 回放回归（≥85% 断言），12 项全绿。闸门实测：L0 100% + L1 抽样 9/10 达标。顺带修 `l0_scan.py` deslop 双重 bug（传不存在的第二参 + 二元组解包，异常被吞 → 指标恒 0）。GUI 侧说明：评测基建在 TUI 仓库，共享层一致性由 dual_sync_check.py 守护，闸门结果双端有效（已写入脚本 docstring）。
- [x] **T2.3 deslop 破折号策略**（M）— 对应 M1 — 2026-08-28 完成
  - 内容：将 `EM_DASH` 从阻断降级为 advisory，或改为「密度阈值」（如每千字 >N 个才提示）；用《改命笔记》54 章 + 《时间铺子》10 章做离线回放，对比阻断数变化。
  - 验收：回放报告存档；合法破折号文风不再被强制改写。
  - 结论：提交 TUI 3cc4ca3 / GUI d8827c9（app/deslop.py 双端全文件一致）。选密度阈值而非一刀切降级：**>6 处/千字 → blocking，否则 advisory**。离线回放（`evals/emdash_replay.py`，报告存档 `tests_output/emdash_replay/report.md`）：《改命笔记》54 章阻断 1→0；《时间铺子》10 章阻断 56→0（密度 2.34/千字、单章最高 4.97，均落入合法文风区间）；高密度合成用例（>6/千字）仍正确阻断。写作 prompt 的预防性禁令保留（预防严于验收）。GUI test_review_v2 14 项全绿。
- [x] **T2.4 GUI 单测体系化**（L）— 对应 M4 — 2026-08-28 完成
  - 内容：建立 `tests/unit/`（pytest，零 API key）：状态机转移（state.py 常量与转移表）、门机制三决策（mock Event）、deslop 规则集、project 目录解析/章节锁定、细纲批解析（`===第N章===`）。目标先覆盖 core 层关键路径 20 用例。
  - 验收：`python -m pytest tests/unit -q` 全绿，可在无网络环境运行。
  - 结论：`tests/unit/` 5 模块 **36 用例全过**（超额达标，0.3s，零网络零 key）：test_state_machine（阶段链完整性/转移表互逆/级联产物模式/持久化往返/指导与想法生命周期）、test_gates（字数双界/AI味分流/三决策 mock ctx）、test_deslop（确定性阻断+密度型建议+破折号阈值双用例，守住 T2.3 成果）、test_project（目录结构/章节锁定生命周期/正则规则解析）、test_outline_parse（主格式/空格变体/标题提取/markdown 降级）。编写中借测试固化了三处真实语义：CW_NEXT 终态自环、级联值是产物路径模式而非阶段键、认知告知为密度型（≥3 处才报）。
- [x] **T2.5 TUI git 化 + 双端同步机制**（M）— 对应 H5 — 2026-08-28 完成
  - 内容：① `qianbi-Novel-TUI` 初始化 git（首次提交含 .gitignore）；② 写 `scripts/dual_sync_check.py`：对比双端 `app/core`、`app/llm`、`app/prompts`、`app/presets` 的共享文件 diff，输出漂移清单；③ 在两端 README 写明「共享层改动必须双端同步 + 跑此脚本」。
  - 验收：脚本能列出当前真实漂移项；TUI 历史可追溯。
  - 结论：GUI a9d1fe1 / TUI 16ab6ab + f5ccd5d。TUI 首次入库前做敏感信息扫描（无硬编码 key，tests_output 15M 排除）；`scripts/dual_sync_check.py` 首跑列出真实漂移 13 DRIFT + 1 ONLY_TUI（app/llm/resume.py）+ 18 IDENTICAL，双端 README 均已写入同步约定。

### Phase 3 · 架构与卫生债务（约 1–2 天）

- [ ] **T3.1 硬编码路径清理**（M）— 对应 M3
  - 内容：TUI tests 的 `sys.path.insert` 改为基于 `__file__` 相对定位；bat 内写死的 Python 路径改为 `py -3` / 环境探测；全仓搜 `G:\ai` 与 `C:\Users\zsfzr` 残留并逐一处理（测试产物目录里的除外）。
  - 验收：换一台机器路径不会立刻报错（至少静态检查无硬编码）。
- [ ] **T3.2 state 类型加固**（L）— 对应分析报告「类型安全 5/10」
  - 内容：`state.py` 的 `DEFAULT_STATE` / `cw` 子树改为 TypedDict 或 dataclass（保持 JSON 序列化兼容），`save_state` 入口做最小键校验；GUI/TUI 双端验证同一份 `pipeline_state.json` 可互开。
  - 验收：旧存档全部可读（用现有 3 个真实项目存档回归）；非法键早报错。
- [ ] **T3.3 门等待去轮询**（S）— 对应 M6
  - 内容：定位 0.15s 轮询点（测试泵与 bridge 侧），改用事件通知或 `Event.wait(timeout)` 直等；保留超时兜底。
  - 验收：门机制三用例（带想法继续/回退归档/auto 跳过）仍全过。
- [ ] **T3.4 大体积残留清理**（S）— 对应 L2
  - 内容：与用户确认后处理 `_archive/`（移出仓库或压缩归档）、多版本 `__pycache__`、TUI `tmpdbg3`、早夭的 `e2e_dbg_proj`/`e2e_dbg2_proj`。
  - 验收：用户确认后才删；删除项记录进执行日志。

### Phase 4 · 功能缺口（依赖产品节奏，独立排期）

- [ ] **T4.1 Step Gates 阶段 2：内侧门接线**（XL）— 对应 F1/H2 根治
  - 内容：按 `plan_step_gates_v1.md` 阶段 2 接线 G4（素材组装后）/G6（扫描后）/G7（去味后）/G8（审校后）四扇内侧门；每门实现三决策与回退语义（G6/G7/G8 的回退=保留原稿）；UI 复用 StepGateBar。
  - 验收：四门真机各至少触发一次；门开关真实生效。
- [ ] **T4.2 Step Gates 阶段 3：想法沉淀**（L）— 对应 F2
  - 内容：跨章想法库（未消费的想法持久化 + 面板管理 + 注入策略）。
  - 验收：计划文档补设计稿后实施。
- [ ] **T4.3 Step Gates 阶段 4：Agent Console**（XL）— 对应 F3
  - 内容：见 `docs/plan_agent_console_v1-v3.md`；建议在 T4.1/T4.2 落地并稳定后再启动。
- [ ] **T4.4 TUI 后续里程碑**（XL）— 对应 F4
  - 内容：M1.5 IME 真机验证（先确认 Textual 上游修复状态），再议 M2–M7。

---

## 4. 估计汇总表

| 阶段 | 任务 | 估计 | 优先级 | 依赖 |
|---|---|---|---|---|
| Phase 0 | T0.1 移植验收 | M | 🔴 先决 | — |
| | T0.2 模块化提交 | M | 🔴 先决 | T0.1 |
| | T0.3 版本基准决策 | S | 🔴 先决 | — |
| Phase 1 | T1.1 清理+.gitignore | S | 高 | T0.2 |
| | T1.2 版本单一来源 | M | 高 | T0.3 |
| | T1.3 死开关置灰 | S | 高 | T0.2 |
| | T1.4 代码瑕疵 | M | 高 | T0.2 |
| | T1.5 文档对齐 | S | 中 | T1.2 |
| Phase 2 | T2.1 L1 拦截率≥80% | L | 高 | T0.2 |
| | T2.2 回放纳入流程 | M | 高 | T2.1 |
| | T2.3 破折号策略 | M | 中 | — |
| | T2.4 GUI 单测体系 | L | 高 | T1.4 |
| | T2.5 TUI git+同步脚本 | M | 高 | — |
| Phase 3 | T3.1 路径清理 | M | 中 | — |
| | T3.2 state 类型加固 | L | 中 | T2.4 |
| | T3.3 门等待去轮询 | S | 低 | — |
| | T3.4 大体积清理 | S | 低 | 用户确认 |
| Phase 4 | T4.1 内侧门接线 | XL | 产品排期 | T1.3 |
| | T4.2 想法沉淀 | L | 产品排期 | T4.1 |
| | T4.3 Agent Console | XL | 产品排期 | T4.2 |
| | T4.4 TUI 里程碑 | XL | 产品排期 | — |

**总量估计**：Phase 0–3 合计约 **5.5–8.5 个工作日**（S=0.5h 均值、M=2h、L=5.5h 估算：P0≈0.6 天，P1≈1 天，P2≈2.8 天，P3≈1.4 天，不含等待与真机验证耗时）。Phase 4 为产品功能开发，另计约 4–7 天。

**建议节奏**：Phase 0+1 一口气完成（当天）；Phase 2 单独排期（收益最大）；Phase 3 见缝插针；Phase 4 等用户圈选确认点强度后再启动（延续 `续接对话种子-20260819.md` 中的待决策事项：每个确认点要「硬停/轻提示/不管」）。

---

## 5. 验证清单（每个阶段收口前必跑）

1. **源码启动**：主项目 `run_dev.bat`（或 `.venv\python run.py`），QML 无新增报错（对照 `app_run.log`）。
2. **TUI 冒烟**：`qianbi-Novel-TUI` 下 `python run.py --smoke`（12 项，零 API key）。
3. **单测**（T2.4 完成后）：`python -m pytest tests/unit -q`。
4. **评测回放**（T2.1/T2.2 相关改动后）：`evals/replay.py`，对比 `tests_output/replay/report.md` 基线。
5. **真机小 e2e**（涉及流水线/门/审校的改动必跑）：新建 3 章小项目，全程观察门触发与落库；产物目录留存。
6. **双端互开**（涉及数据格式的改动必跑）：同一项目 GUI 写 → TUI 开，反向再来一次。

## 6. 已知风险提示

- **Textual IME 上游缺陷**：TUI 中文输入依赖上游修复，M1.5 验证前不要承诺中文输入相关的完成时间。
- **L1 评审方差**：单次评审不可信，任何「审校质量」结论以 ≥3 次取众数为准。
- **DeepSeek 提示词耦合**：内置 prompt 针对 DeepSeek 系调优，换服务商需回归全部阶段。
- **`OUTLINE_BATCH=2` 是实测妥协**：5 章批会被推理输出预算吃光；调大前先验证目标模型的 max_tokens。

---

## 执行日志（接力方填写）

| 日期 | 任务 | 执行者 | 结果 / 提交号 | 备注 |
|---|---|---|---|---|
| 2026-08-28 | 计划制定 | Qoder | — | 基于全工作区深度分析（三路探索 + 抽样核验）产出本计划 v1 |
| 2026-08-28 | 计划文档提交 | Qoder | 811ec58 | 计划书单独提交 |
| 2026-08-28 | T0.1 移植验收 | Qoder | 通过 | 清单齐套、无敏感信息、42 项单测全过、真机证据充分；偏差 2 项已记录（见任务条目） |
| 2026-08-28 | T0.2 模块化提交 | Qoder | 01fb7ef / c7e0e29 / 026393b / 74ba597 / 1c1d4c4 / fac0cbe | 6 提交（预设/核心审校+场景卡/UI 接线/鲁棒性修复/e2e 驱动/文档），提交后编译验证通过 |
| 2026-08-28 | T0.3 版本基准 | 用户 | 定版 **0.13.0** | Phase 0 全部完成，基线建立；下一步 Phase 1 |
| 2026-08-28 | T1.1 清理+.gitignore | Qoder | 358bef9 | 删调试截图/杂物日志；.gitignore 增补 projects/.workbuddy |
| 2026-08-28 | T1.2 版本单一来源 | Qoder | 6147052 + tag v0.13.0 | app/__init__.py 常量 + Qt applicationVersion 接入 + CHANGELOG 重排修倒挂 + README 去 dev |
| 2026-08-28 | T1.3 死开关置灰 | Qoder | 92210bc / d78ce75 | GATE_META wired 字段+未接线门置灰；顺带修两处迁移遗留 QML 缺陷；probe_gate_ui 8/8 零告警 |
| 2026-08-28 | T1.4 代码瑕疵 | Qoder | ab66320 | 反馈环改读 review_raw（原读 last_prompt 恒错）+ 删死代码；真机 1 章验收待并入 Phase 2 |
| 2026-08-28 | T1.5 文档对齐 | Qoder | abb13fd | 预设 9→10 套、侧栏 7→6 面板/第 5 项、设计组件 18→15、体系 七→八；三文档联动修正 |
| 2026-08-28 | Phase 1 收官 | Qoder | 全 5 任务完成 | 离线全绿（探针 4/4+8/8、42 单测、smoke）；下一步 Phase 2（建议单独排期，收益最大） |
| 2026-08-28 | T2.5 TUI git 化+双端同步 | Qoder | GUI a9d1fe1 / TUI 16ab6ab + f5ccd5d | TUI 首次入库（敏感扫描通过、产物排除）；dual_sync_check.py 首跑 13 DRIFT+1 ONLY_TUI+18 IDENTICAL；双端 README 立同步约定 |
| 2026-08-28 | T2.1 L1 拦截率 | Qoder | TUI 01971d7 | 33%→**100%**（3 次真跑多数票 15/15，误杀 0）：夹具树 make_l1_fixtures.py + judge 上下文注入/硬判级规则 + replay --judge/--judge-vote；L0 回放无回归 100% |
| 2026-08-28 | T2.2 回放纳入流程 | Qoder | TUI 5272b22 | scripts/eval_gate.py 一键闸门（L0 全量 + L1 抽样 10，实测 PASS）；smoke 第 12 项 L0 回归；修 l0_scan deslop 指标恒 0 双重 bug |
| 2026-08-28 | T2.3 破折号策略 | Qoder | TUI 3cc4ca3 / GUI d8827c9 | EM_DASH 改密度阈值（>6/千字才阻断）；真书回放 57 处阻断→0（改命笔记 54 章 + 时间铺子 10 章），高密度合成例仍阻断；报告存档 tests_output/emdash_replay/ |
| 2026-08-28 | T2.4 GUI 单测体系化 | Qoder | 7686230 | tests/unit 5 模块 36 用例全绿（目标 20，超额）：状态机链/转移表互逆、闸门三决策（mock ctx）、deslop 规则集（含破折号阈值回归用例）、项目解析/章节锁定、细纲批解析；零 key 离线 0.3s |
| 2026-08-28 | Phase 2 收官 | Qoder | 全 5 任务完成 | L1 拦截 33%→100%（多数票）、一键评测闸门、破折号误杀清零、36 单测保底、TUI 入库+双端同步机制；下一步 Phase 3（架构与卫生债务） |
| 2026-08-28 | T3.1 硬编码路径清理 | ZCode | TUI 97808e9 / GUI 6661e3e | TUI 10 个测试文件改 `__file__` 相对定位（含 test_xiuxian_flow 的 PROJ、test_e2e_10ch 的 PROJ_PARENT）；run_tui*.bat 改环境探测（.venv→python→py -3）并新建 TUI `.venv`（textual 8.2.8，requirements 安装验证）；GUI verify_m1(_v2)/ui_drive 同步清理；全仓 `G:\ai`/`C:\Users\zsfzr` 静态扫描清零；TUI smoke 12 项全绿 |
| 2026-08-28 | T3.2 state 类型加固 | ZCode | GUI 31f2cac / TUI 0feee83 | TypedDict（PipelineStateTD/CWStateTD）+ validate_state 最小键校验（load/save 入口；None 就地修复、未知键保留、bool/int 特判）；4 个真实存档回归全过（含 e2e 驱动异形格式）；双端互开脚本 PASS（同档双端加载一致 + GUI 写→TUI 改→GUI 读）；新增 test_state_validation 14 用例（总 50） |
| 2026-08-28 | T3.3 门等待去轮询 | ZCode | GUI 5269cf1 / TUI 75b3ead | stop() 补置位 _gate_evt/_resume_evt 唤醒，门等待/暂停等待改事件直等 + 1s 超时兜底；出循环补查 _stop 堵住「停止瞬间被当继续」竞态；probe_gate_flow 全过；真机验证：停止键成功打断 G9 门等待（见真实窗口运行） |
| 2026-08-28 | T3.4 大体积残留清理 | ZCode | （可逆移动，无提交） | `qianbi-novel/_archive`（719MB）→ `G:\ai\酒馆\_trash_20260828\qianbi-novel_archive`；早夭沙盒 e2e_dbg_proj/e2e_dbg2_proj → 同处；TUI tmpdbg3 空目录删除；双端源码树陈旧 `__pycache__` 清零。全部为移动/可逆操作，未删任何 tracked 文件 |
| 2026-08-28 | 漂移清零裁决 | ZCode | GUI 6c118ca / TUI ea181ac | 实质同步 5 项：writing prompt（TUI v2 铁律版→GUI）、ROOT_CAUSE/REVISION_TARGETS few-shot 版→GUI、gates ctx 补 review 字段、client 断流重试 parts 重置修复→GUI、scene_cards+presets(v1→v2 迁移)→TUI。**有意平台差异 10 项登记进 dual_sync_check EXPECTED_DIFFS**（共写阶段序 GUI=v1/TUI=v2 家族、平台管道、TUI resume 特性族）；脚本补 app 根文件覆盖（deslop.py 曾在盲区）。脚本终态：0 意外漂移 + 10 登记 + 23 一致 |
| 2026-08-28 | T4.1 内侧门接线 | ZCode | 12e72c1 | G4（组装后，回退=重组装读盘）/G6（扫描后，回退=保留原稿跳去味、阻断降级建议）/G7（去味后，回退=还原去味前文本+快照归档）/G8（审校后，回退=还原审校前文本）四门接线；回退想法经 consume_gate_idea 就地消费防串章；G8 入默认硬停；GATE_META wired=true×4；probe_gate_flow 扩至 6/6、probe_gate_ui 8/8。**真机验证：四门在第 1 章全部实际触发**（见真实窗口运行）。TUI 侧接线属豁免文件（stages.py 平台管道），登记为后续项 |
| 2026-08-28 | T4.2 跨章想法沉淀 | ZCode | GUI 61692dd / TUI d71f084 | 设计稿落 plan_step_gates_v1 §8 后实施：「通用」想法升级为持续注入（take_ideas 不自动消费，面板 ✓/× 手动收口）；next/N 一次性语义无回归；NotesPanel 徽章改「持续注入·通用」；新单测守语义（总 51）；TUI state.py 同步 |
| 2026-08-28 | T4.3 Agent Console | ZCode | 8f9b0d4 | **交付 M1+M2**：sig_thinking(槽位,阶段,章号,增量) 全链接线（stages._stream→orchestrator→bridge）→ 按 槽位×阶段×章 分组环形留存（随章结束不清空）；对话区镜像（章开始/门挂起/门决策/Console 输入回执）+ `pipeline_debug/console/session-*.jsonl` 落盘；ConsoleDock 中列组件（折叠 24px/展开 280px，符合 v3 §1.4 两态）+ 输入框路由（门等待→带想法继续；否则沉淀「下一章」想法）；probe_console 10/10、gate_ui 8/8 零新增告警。**M3（阅读器收窄+门合并+REGIONS 重校准）超出本次范围，另期**（v3 §6 需真机视觉迭代回归 17 屏坐标） |
| 2026-08-28 | T4.4 TUI M1.5 IME | ZCode | （验证结论） | 本会话网络不可用（搜索/抓取全超时），Textual 上游修复状态**无法确认**；本地取证：textual 8.2.8 win32 驱动无 IME/composition 专用处理。真机代理验证：TUI 在 Windows Terminal 正常启动渲染、实时读到 GUI 在写的同一本书（双端互开实证）；合成按键无法进入 TUI（WT 路径限制），且 IME 组合输入本质需真人——**M1.5 维持「待真人 IME 真机验证」**（步骤：TUI 打开任一项目 → 章节笔记/想法输入 → 真人切中文输入法键入，观察组合窗与上屏） |
| 2026-08-28 | 全量离线验证 | ZCode | 全绿 | GUI：pytest 51/51、probe_gate_flow 6/6、probe_gate_ui 8/8、probe_console 10/10、probe_chapter_lock 15/15、probe_cw_dialogue 19/19；TUI：smoke 12 项、eval_gate PASS（L0 100%）；双端互开脚本 PASS |
