# 全量 TUI 化 — 深度方案 v2（评审修订版）

> 项目：千笔一文 Novel（QianBi-Novel）·「人 AI 共写长篇小说创作台」
> 本版 = plan_tui_v1.md 经 3 路子代理深度评审后的修订版（v1 保留为过程稿）：
> ① Textual 框架联网调研（版本/IME/性能/打包 13 项实查）
> ② 代码 Qt 耦合审计（bridge/orchestrator/co_dialogue 逐行）
> ③ 逐功能 QML↔终端可行性对照（ReaderView/CwDock/StepGateBar 等）
> **总判定：功能面约 80% 可直接承载、20% 需改口径或降级；主体架构
> （命令层 1:1 + EventBus + Textual）成立，可执行。**
> 唯一 go/no-go 级风险：**中文 IME**（见 §0.1，M0.5 门槛）。

---

## 0. v1 → v2 修订摘要

| # | v1 的说法 | 评审结论 | v2 修正 |
|---|----------|---------|--------|
| 1 | 7 个 QThread Worker | **实为 10 个**：bridge 4（SelectionRewrite/_Net/_Idea/_Blurb）+ co_dialogue 6（Dialogue/Summarize/Readback/Supervisor/OutlineBatch/ReviewOutlines，约 290 行） | 工作量与测试面上调；统一 run_worker 封装覆盖全部 10 个 |
| 2 | Qt 耦合 3 处 | 实为 **4 个文件**（+app/main.py 入口）；另有 QUrl/QDesktopServices 散点（bridge.py:550/2486/2579） | main.py 由 cli.py 替换时写明；QUrl→os.path、revealPath→subprocess(explorer/xdg-open/open) |
| 3 | 阅读器"字号 5 档/行距 3 档/宋黑 = 排版参数" | **终端固有不可行**：字体族/字号/行距完全由终端仿真器决定，应用无干预 API | §4.2-R 重新设计：字号→栏宽档、行距→段距档、宋黑→移除+README 指导终端设置 |
| 4 | GateBanner"四选一（含回退到指定门）" | **虚构**：StepGateBar.qml 仅 继续/回退 两动作；resolveStepGate 仅 next/return（orchestrator._gate_return_target 已预留多门回退但 UI 未暴露） | 改为两动作+想法输入；「回退到指定门」标注为增强项（controller 已半支持） |
| 5 | 上下文档位 cycle 用 Tab | Tab 是 Textual 焦点键，TextArea 内另有语义，会破坏键盘可达性 | 换 `[` / `]` |
| 6 | 三主题 = 3 份 .tcss 热切 | CSS_PATH 多份不能热换；且 App.theme 是全局切换，阅读器需独立于全局主题 | **1 份 .tcss 吃变量 + 3 个 Theme 对象**（全局）；阅读器主题用**局部样式类+独立 palette** 实现 |
| 7 | 质量趋势"自绘或 plotext" | plotext 阻塞事件循环、与 widget 体系不融 | 删 plotext，只留字符 sparkline（▁▂▃▅█） |
| 8 | 属性 Property 平移 | Property getter 即磁盘 IO（_get_progress_percent_text/stageCards 等每次 load_state/read_file），QML 拉取式绑定无成本概念 | TUI 改为**命令+缓存**：controller 事件驱动的显式 refresh()，禁止视图层轮询式取数 |
| 9 | （未提及） | cancelSelectionRewrite 是**空操作 bug**：requestInterruption 从不被 run() 检查 | M0 顺手修：cancel Event 在 on_chunk 回调中检查并抛中断 |
| 10 | （未提及） | 全项目仅 1 个 QTimer（_draft_timer 草稿 5s 防抖）；且 Qt start() 自动重置倒计时=真防抖，threading.Timer 不可重启 | §5.2-D：controller 持 _last_edit 时间戳 + 可重启 Timer（cancel+重建）+ 写盘锁 |
| 11 | （未提及） | ListModel 内藏业务逻辑：LogListModel.append 时间戳+500 行环形截断、ConnectionListModel 槽位实时计算直读 bridge.cfg | 全部下沉 controller；ChapterListModel 纯取数可直搬 |
| 12 | （未提及） | IME 三实锤：#6667 win32 驱动丢 IME 组合事件（Shift+？！：《》打不出）、#5457 WT 候选窗错位"no easy fix"、#1469 预编辑不内联 | §0.1 新增 **M0.5 IME 真机验证门槛** + 三重缓解 |

### 0.1 最大风险：中文 IME（go/no-go 级）

写作类应用的命根子是中文输入。Textual 8.2.x 现状（2026-08 实查 GitHub）：

- **#6667**（2026-07 开，未修）：win32 驱动 VK=0 过滤丢弃 IME 组合事件 → 微软拼音下
  `？！：《》`（Shift+符号）整类字符**打不出来**（补丁是 one-line 但未合入）
- **#5457**：Windows Terminal 下 IME 候选窗跟随行尾而非光标，维护者原话 "no easy fix"
- **#1469**：预编辑串不内联显示

**对策（三层）**：
1. **M0.5 门槛（新增里程碑，置于 M1 之前）**：在三终端（Windows Terminal / VSCode 终端 /
   conhost）真机验证 TextArea 中文输入矩阵：拼音全拼/简拼、Shift 标点、候选窗行为、粘贴。
   任一"打不出/丢字"且无绕过 → 升级决策（fork 打 #6667 补丁锁自维护版本，或转向混合方案）。
2. **应用层兜底**：编辑器配"外置输入行"模式（单行 Input 承接 IME → 回车插入正文，
   绕开 TextArea 组合输入路径）+ Ctrl+O 外部编辑器 round-trip（$EDITOR/notepad，长文编辑场景）。
3. **上游**：给 #6667 提交/催合 one-line patch，锁我们 patched 的版本。

---

## 1. 现状盘点（v2 修正数字）

分层结论同 v1（§1），修正：

- **Qt 耦合文件 4 个**：`core/orchestrator.py`、`core/co_dialogue.py`、`ui/bridge.py`、`main.py`（入口，cli.py 替代）。
- **QThread 子类 10 个**（bridge 4 + co_dialogue 6），统一抽象为一个 `run_worker`。
- 全项目 QTimer 仅 1 个：`_draft_timer`（bridge.py:386-389，单次 5s → _flush_draft）。
  `_maybe_auto_backup` 是打开项目时触发一次（:599），非周期任务。
- orchestrator 确认：import 行外近零 Qt；门机制 `threading.Event`（:49/52）；
  checkpoint 轮询 sleep(0.15)（:213-219）；失败 dump 纯文件 IO——"零改动"属实。
  `_stop` 是普通 bool（GIL 下可用，平移无害）。
- 既有文件级竞态（保持现状、回归覆盖）：OutlineBatchWorker 在 worker 线程直写细纲文件
  （co_dialogue.py:383），与主线程 state 写盘存在窗口。
- 防重入现状：cw 靠 `_cw_busy`、选区靠 `isRunning()`、_Net/_Idea/_Blurb 无保护
  ——run_worker 封装时统一加。

## 2. 目标架构（修订）

同 v1 四层（Textual 前端 / Headless controller + EventBus / Worker 池 / 纯逻辑层复用），
修订三点：

### 2.1 EventBus（v2 强化）

- **FIFO 保序**：Qt 队列连接天然保证"done 槽先于 finished 清理"（bridge
  `_release_cw_worker` :1834-1842 依赖此序）。EventBus pump 单线程按序分发，
  worker wrapper 保证 on_done 投递先于 worker 释放事件。
- **队列上限 + 流式合并**：stream_chunk/stream_reasoning 逐 token 高频，bus 队列设
  上限（如 10k）并对流式 topic 做合并批投递（攒 50ms 或 64 chunk 合一条），
  防止 UI 短暂卡顿时队列膨胀。
- **单写者**：所有状态变更集中在 controller（pump 线程）；TUI 只读快照 + 发命令。

### 2.2 run_worker（统一 Worker 封装，替代 10 个 QThread）

```python
class WorkerPool:                       # 等价 QThread parent=self 保活 + finished 清理
    _pool: dict[str, Thread]            # 强引用池（threading.Thread 无引用会被 GC 中途回收）
    def submit(self, name, fn, on_done, reentrant=False, cancel_evt=None): ...
```

- `reentrant=False`：重复提交直接拒绝并 toast（统一防重入，修复现有三处不一致）。
- `cancel_evt`：可取消任务（选区改写/共写对话/细纲批）在 on_chunk 回调里检查并抛
  中断——顺带修掉 cancelSelectionRewrite 空操作 bug（bridge.py:848 从不查
  isInterruptionRequested，"取消"目前只是丢弃结果不中断请求）。

### 2.3 草稿防抖（QTimer 语义等价）

Qt `_draft_timer.start()` 每次重置 5s 倒计时（真防抖）。threading.Timer 不可重启：
controller 维护 `_last_edit_ts`，每次 markEditorDirty 时 `timer.cancel(); timer=Timer(5, flush)`。
注意 Timer 回调在 timer 线程执行 → _flush_draft 写盘经 controller 写锁（与章节切换/
保存互斥），与现状（GUI 线程串行）等价。

## 3. TUI 框架选型（v2 补充实证）

维持选 **Textual**，锁 **8.2.x**（数周一版，破坏性变更走大版本）。评审实证：

| 能力 | 判定 | 要点 |
|------|------|------|
| TextArea 选区（编程式 anchor/head/Shift+方向/鼠标拖选） | ✔ | 2 万字中文按行渲染缓存，无性能问题 |
| RichLog 流式（max_lines 环形/auto_scroll 可关） | ✔ | append-only+50ms 批写即其设计用法 |
| 主题热切换 | ✔（改法） | **1 份 .tcss + 3 个 Theme 对象**（register_theme + App.theme= 即时刷新）；不是多份 CSS_PATH |
| Screen 栈/强制模态/Dock | ✔ | ModalScreen 不绑 escape 即"不可 Esc 关" |
| DataTable | ⚠ | 大表慢（社区基准 1 万行 3.8s）；队列 <100 行 + 50ms 合并刷新可承受；兜底 textual-fastdatatable |
| 线程→UI | ✔ | call_from_thread 官方推荐；EventBus+pump 等价且更可测（跨线程直改 UI 会直接报错） |
| Pilot + snapshot | ✔ | pytest-textual-snapshot SVG 快照 diff 成熟；中文断言无限制 |
| PyInstaller | ⚠ | .tcss 不自动进包：--add-data + sys._MEIPASS 适配（沿用现 resource_path 模式） |
| CJK 宽度 | 基本✔ | 汉字=2 列正确；避免 ambiguous 宽度字符（★等）做对齐；emoji ZWJ 在 VSCode xterm.js 落后——沿用 ASCII 降级开关 |
| 长跑内存 | ⚠ | #6665/#6666 泄漏未根治（8.1.0 已改进）；长流水线测试需盯 RSS，避免高频 mount/unmount |
| **中文 IME** | **✖/⚠** | **§0.1，M0.5 门槛** |
| 字体/字号/行距干预 | ✖ | 终端完全决定，应用无 API（WT 无字体控制转义序列） |

## 4. 功能映射（v2 修订版）

映射总表以 v1 §4.2 为基线，以下条目**替换/修订**：

### 4.2-R 阅读器排版（重新设计，替代 v1"排版参数"口径）

| QML 现实现 | TUI 判定 | v2 设计 |
|-----------|---------|---------|
| 字号 5 档（pixelSize） | **固有不可行** | 改为**栏宽 5 档**（每行 32/38/42/46/50 全角字，居中排版，两侧留白）+ 状态栏提示「字号请用终端缩放（WT: Ctrl+滚轮）」 |
| 行距 3 档（lineHeight 1.5/1.8/2.2） | **固有不可行** | 改为**段距 3 档**（段间 0/1/2 空行）；段内行距恒定，README 说明 |
| 宋/黑字体切换 | **彻底丢失** | 设置项移除，改为「推荐终端字体」说明（如 Sarasa/更纱黑体、Cascadia+中文字体） |
| 首行缩进 2em | 等价 | 段首 2 全角空格 |
| 三主题（独立于全局） | 等价 | **局部样式类 + 独立 palette**（不用 App.theme 切换，避免波及全局）；夜间/羊皮纸/纯白三套色板映射现 ReaderView 色值 |
| 翻页 0.88 视口步进 + contentY/maxY 比例记忆 | 等价+补 | 按视口行数步进；位置写同一 0~1 字段（readPosition 语义不变）；**补 v1 遗漏：页尾触界自动跳下章/触顶回上章**（pageStep 溢出语义，QML 有） |
| 三色高亮（quote 全部出现处染色） | 等价 | Rich Style 背景色叠加；批注维持抽屉式 + 行尾 `◆` 标记 |
| 选中标注（选中≥2 字浮出跟随工具条） | **降级** | 阅读器正文用**只读 TextArea 承载**（RichLog/Static 无拖选，需自研鼠标收集不划算）；命令条固定底部不跟随光标；hover/呼吸动画丢失为可接受代价 |
| 未定稿徽章+流式实时刷新 | 等价 | 状态栏徽章（无动画） |

### 4.2-C 共写 Dock 与决策门（修订）

- **CwDock**：Textual Dock/Horizontal 布局可行；但"主区与 dock 同时操作"在单焦点模型下降级
  为 **Tab/Ctrl+Tab 焦点轮换**——v1 未写明，此为终端固有交互差异，README/F1 说明。
- **GateBanner**：两动作（继续/带想法继续 ｜ 回退重做）+ 想法输入框，对齐 StepGateBar.qml
  与 resolveStepGate(next/return) 现实；「回退到指定门」列为增强项（orchestrator.
  _gate_return_target 已预留，controller 侧补 API 即可，不承诺本期 UI）。

### 4.2-Q 质量趋势

字符 sparkline（`▁▂▃▅█` 单行，Rich 着色）+ 数值表；**删除 plotext**（阻塞事件循环）。

### 4.2-E 选中改写命令条

- 上下文档位 cycle：`[` / `]`（**弃 Tab**——Textual 焦点键，TextArea 内有缩进语义）。
- 数字键选择命令：命令条激活时**独占焦点态（模态）**，避免与 TextArea 文本输入冲突。

### 4.2-K 快捷键（v2 修订）

| 键 | 修订 |
|----|------|
| F5 沉浸阅读 | 保留 + **备选 `r`**（tmux/screen/老 SSH 可能不透传 F 键） |
| Ctrl+B 书签 | 保留，但**键位全部可配置**（tmux prefix 撞键，config tui.keymap） |
| Ctrl+S | 保留（raw mode 下无 XOFF 问题，个别 SSH 组合在 README 提示） |
| 新增 Ctrl+O | 外部编辑器 round-trip（$EDITOR，IME 兜底 + 长文编辑习惯） |

### 4.2-D 数据与配置共享

GUI/TUI 共用 config 时，`fontScale/lineHeight/serif` 在 TUI 失效——TUI 设置页对应项
显示「由终端控制」只读说明，避免"GUI 改了 TUI 不变"的困惑；`readPosition` 等语义字段
两界通用，交替使用安全。

## 5. 关键技术方案（v2 修订）

- **§5.1 流式**：维持 50ms 批量渲染；增加 bus 侧合并（§2.1），UI 卡顿不回压 worker。
- **§5.2 防抖**：见 §2.3。
- **§5.4 主题**：见 §3 表（1 份 .tcss + Theme 对象）；阅读器局部 palette 见 §4.2-R。
- **§5.5 Windows**：强制推荐 Windows Terminal（README 明示）；conhost 兼容降级
  （ASCII 徽章、无鼠标拖选提示）；WT_SESSION 检测做能力分级。
- **§5.7 打包（新增）**：PyInstaller --add-data 打包 .tcss + sys._MEIPASS 适配
  （复用现 resource_path 模式）；console onefile。
- **§5.8 长跑稳定性（新增）**：#6665/#6666 内存泄漏未根治——避免高频 mount/unmount、
  RichLog 一律 max_lines、M2/M4 长流水线验收含 RSS 观察（跑完一本书样例内存无持续增长）。

## 6. 里程碑（v2：插入 M0.5，调整 M1/M5）

- **M0 内核下沉**（同 v1，补充）：
  - run_worker 覆盖全部 10 个 Worker + 统一防重入 + cancel_evt 真取消
    （修 cancelSelectionRewrite 空操作 bug）；
  - LogListModel/ConnectionListModel 业务逻辑（时间戳/环形截断/槽位计算）下沉；
  - QTimer→可重启 Timer + 写锁；属性 getter 改 refresh() 命令+缓存。
  - 验收同 v1（assert_v099 / smoke_func / probe 全绿 + GUI 共写冒烟）。
- **M0.5 IME 真机验证（新增，go/no-go 门槛）**：
  三终端输入矩阵（全拼/简拼/Shift 标点 `？！：《》`/候选窗/粘贴/外部编辑器 round-trip）；
  全过 → 进 M1；有硬伤 → 决策：patch fork 锁版本 或 混合方案（TUI 为主、编辑弹外部）。
- **M1 TUI 骨架+书架**（补充）：外置输入行组件、keymap 配置、Ctrl+O 外部编辑器、
  ASCII 降级开关在骨架期就位（后续所有屏受益）。
- **M2 设置+流水线监控**（补充）：DataTable 行数上限+合并刷新验证；长跑 RSS 基线记录。
- **M3 编辑器+版本+想法**：同 v1；含防抖语义等价测试（连续输入仅 5s 静默后一次 flush）。
- **M4 共写六阶段**：同 v1（修 CHANGELOG 9 问题之 #1-#4/#8；#9 按钮溢出在 TUI 重排时自然消解）。
- **M5 阅读器**（验收口径改写）：
  - 栏宽/段距档位、三局部 palette、翻页+触界跳章、位置记忆（同一 0~1 字段）；
  - 标注：只读 TextArea 选区 + 底部命令条（降级已获用户知情）；
  - **不再验收字号/行距/字体切换**（固有不可行，README 指导终端设置）。
- **M6 改写+质量+导出**：同 v1；质量趋势=sparkline。
- **M7 退役 QML**：同 v1。

## 7. 测试策略（v2 补充）

- 同 v1 四条；追加：
  - **Worker 时序回归**：done→released 保序（对应 _release_cw_worker 依赖）；
  - **防抖等价**：连续 markEditorDirty 只触发一次 flush，且 5s 窗口滑动正确；
  - **取消语义**：cancel_evt 后 worker 线程在下一 chunk 边界退出且 on_done 不执行；
  - **文件竞态回归**：细纲批写盘 vs 主线程 state 写盘（现状保持，加探针覆盖）；
  - **IME 手工矩阵**：M0.5 报告归档 tests_output/ime/。

## 8. 风险清单（v2）

| 风险 | 等级 | 对策 |
|---|---|---|
| **中文 IME 硬伤**（#6667/#5457/#1469） | **高（go/no-go）** | M0.5 门槛 + 外置输入行 + Ctrl+O 外部编辑器 + 上游 patch |
| 阅读器排版三档（字号/行距/宋黑） | 高→已消解 | v2 重新设计为栏宽/段距 + README；获用户知情后为"特性差异"而非风险 |
| bridge 平移行为漂移 | 中 | 同 v1 双跑回归 + 本版新增的时序/防抖/取消专项测试 |
| Worker GC/时序（threading 无 parent 保活） | 中 | WorkerPool 强引用池 + FIFO pump + on_done 先投递 |
| DataTable 大表 | 低（行数少） | 上限+合并刷新；textual-fastdatatable 备选 |
| 长跑内存泄漏（#6665/#6666） | 中 | 锁 8.2.x 盯 issue；RichLog max_lines；RSS 验收 |
| 终端键位冲突（tmux Ctrl+B/F5） | 低 | keymap 全可配 + 备选键 |
| plotext/多 .tcss 等技术误选 | 已消解 | v2 已删改 |

## 9. 非目标

同 v1。追加：不做"终端内改字号/字体"（不可能）；「回退到指定门」UI 不在本期承诺
（controller API 预留）。

## 10. 评审记录（v2 依据）

- textual-research：Textual 8.2.x 13 项实查（IME 三实锤 #6667/#5457/#1469、主题/打包/
  DataTable/内存泄漏等，证据=官方文档与 GitHub issue）
- code-audit：10 Worker 清单、QTimer 唯一性、ListModel 藏逻辑、getter 磁盘 IO、
  cancel 空操作 bug、Worker 保活/时序依赖（bridge.py 行号见 §0 表与 §1/§2）
- feature-gap：ReaderView 逐条对照（排版四项缺口、pageStep 溢出语义遗漏、选中标注降级、
  CwDock 焦点轮换、GateBanner 两动作事实、Tab/plotext/主题实现路径纠错、键位冲突）
