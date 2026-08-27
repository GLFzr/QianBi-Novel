# 全量 TUI 化 — 深度方案（plan_tui_v1）

> 项目：千笔一文 Novel（QianBi-Novel）·「人 AI 共写长篇小说创作台」
> 现状：PySide6 + QML 桌面 GUI（Main.qml + 五面板 + 阅读器 ≈ 4600 行 QML，bridge.py 2595 行）
> 目标：**全量 TUI 化** —— 用终端界面替换 QML 界面，**保持现有全部功能与实现方式不变**：
> 同一逻辑内核、同一数据结构（`pipeline_state.json` / `.versions/` / `.annotations/`）、
> 同一 prompt 工程、同一三槽位路由、同一断点续跑语义。
> 状态：设计文档。经源码逐层核验（bridge.py 全量接口面、orchestrator/co_dialogue Qt 耦合点、
> llm/client 回调式流式接口、QML 面板结构）。

---

## 0. 一句话结论

**TUI 化不是"重写应用"，而是"换头"**：把 `ui/bridge.py + QML` 这颗"Qt 头"换成
"Headless 控制器 + EventBus + Textual 头"。逻辑身体（core/llm/prompts/project/export/deslop，
约 3200 行，全部 Qt-free）原封不动复用。

需要动的只有三处 Qt 耦合点：

| # | 文件 | Qt 耦合 | 改造量 | 改法 |
|---|------|---------|--------|------|
| 1 | `app/core/orchestrator.py`（356 行） | `QThread` + 12 个 `Signal` | 小 | 线程基类换成 `threading.Thread`，`emit` 换成 `bus.publish`（内部 `threading.Event` 暂停/门机制**本来就 Qt-free，零改动**） |
| 2 | `app/core/co_dialogue.py`（440 行） | `DialogueWorker`/`SummarizeWorker` 两个 `QThread`（约 120 行） | 小 | 纯函数部分（transcript/handoff/compose_reference_block）零改动；两个 Worker 换成通用 `run_in_thread` 封装 |
| 3 | `app/ui/bridge.py`（2595 行） | `QObject` + 40 属性/信号 + 7 个 `QThread` Worker + QAbstractListModel ×3 | 中 | **业务逻辑下沉**到新的 Qt-free `app/headless/controller.py`，信号改 EventBus 发布；QML 侧薄壳保留到 M6 才退役 |

新增：`app/headless/`（控制器 + 事件总线）、`app/tui/`（Textual 前端）、`app/cli.py`（入口）。
QML 五面板约 4600 行**全部重写为 Textual 屏**，但只是"视图层重写"，每屏对应的命令
在 controller 上都有同名方法（从 bridge.py 1:1 平移）。

---

## 1. 现状盘点（源码核验结论）

### 1.1 分层现状

```
┌─────────────────────────────────────────────────────┐
│ QML 视图层（~4600 行）                                │
│  Main.qml + Bookshelf/Pipeline/Chapter/Notes/Settings │
│  + ReaderView + CwDialogueDock + 17 个设计系统组件     │
├─────────────────────────────────────────────────────┤
│ 桥接/控制层  app/ui/bridge.py（2595 行，Qt 重耦合）    │
│  ~100 个 Slot 方法 · ~40 Property · ~40 Signal        │
│  7 个 QThread Worker（选区改写/连接测试/想法扩写/      │
│  物料生成/共写对话/总结/细纲批）+ 3 个 ListModel        │
├─────────────────────────────────────────────────────┤
│ 编排层（部分 Qt）                                      │
│  core/orchestrator.py（QThread+Signal）★耦合点1       │
│  core/co_dialogue.py（2×QThread）★耦合点2             │
│  core/co_writing.py（纯状态机，可脱离 Qt 单测）✔       │
├─────────────────────────────────────────────────────┤
│ 纯逻辑层（全部 Qt-free）✔ 原样复用                     │
│  core/stages.py(669) state.py(254) versions.py(239)  │
│  memory.py gates.py · llm/client.py(回调式流式✔)       │
│  llm/router.py providers.py · project.py config.py    │
│  export.py deslop.py prompts/ presets/                │
└─────────────────────────────────────────────────────┘
```

**关键有利事实**（决定改造风险等级为"低-中"）：

1. `llm/client.chat_stream(prompt, system, on_chunk=..., on_reasoning=...)` 是**回调式流式接口**，
   不依赖 Qt 事件循环 —— 任何线程都能直接用。
2. `orchestrator` 内部暂停/停止/决策门用的是 `threading.Event`（`_pause/_stop/_gate_evt`），
   本来就是纯 Python 线程原语；Qt 只是外壳。
3. `co_writing.py` 状态机注释明确"可脱离 Qt 单测"；`stages/state/versions/memory/gates`
   全部是文件与纯函数操作。
4. bridge 的 `QThread` Worker 模式高度一致（构造参数 → run 里调 llm → 发信号），
   可以用一个通用 `AsyncWorker` 抽象统一替换。
5. 现有测试体系（`probe_*.py` 大多直接驱动 core/bridge，`smoke_func` 无需 API Key）
   在内核下沉后可**原样指向 controller** 继续跑 —— 回归安全网现成。

### 1.2 接口面清单（TUI 必须覆盖的能力全集）

bridge.py 暴露的命令按功能域分组（TUI 屏幕映射的依据，详见 §4 映射总表）：

- **项目管理**：newProject / openProject / recentProjects / defaultBooksRoot / projectFiles /
  readProjectFile / saveProjectFile / backupProject / _zip_backup / revealPath
- **自动流水线**：startPipeline / pausePipeline / resumePipeline / stopPipeline /
  refreshQueue / _refresh_progress + 12 路事件（stage/step/chapter/stream×3/queue/finished/failed/auto_paused/gate）
- **决策门（Step Gates）**：gateMetaList / gateEnabled / setGateEnabled / runMode / setRunMode /
  resolveStepGate(action, idea) / _on_gate
- **章节编辑**：openChapter / markEditorDirty / saveChapterText / clearEditorDirty /
  noteEditAction / _flush_draft（5s 防抖） / recoverDraft / discardDrafts
- **版本系统**：versionsForChapter / readVersion / diskTextOf / diffVersions / diffVersionWithDisk
- **局部改写**：rewriteSelection(before, selected, after, idea, mode) / selectionResult /
  cancelSelectionRewrite + 流式预览信号（chunk/reasoning/state）
- **整章重写**：rewriteChapter / rewriteChapterWithGuidance
- **质量体系**：scanChapterText（本地 AI 味） / qualityTrend / chapterFindings
- **想法/偏好**：ideasList / submitIdea / submitIdeaScoped / removeIdea / updateIdea /
  markIdeaApplied / expandIdea / writingPrefs / saveGlobalPrefs
- **统计**：statsSummary（章节/字数/今日/本周/token/成本）
- **导出**：exportProject / exportProjectOpts / exportPreviewText
- **连接管理**：getConnection / saveConnection / deleteConnection / setSlot /
  testConnection(Draft) / fetchModels / connectionOptions / providerOptions（酒馆式多连接+三槽位）
- **共写档（cw_*, 约 45 个方法）**：setCwMode / selectCwStage / submitCwMessage /
  confirmCwStage / rollbackCwStage / reopenCwWorldbook / saveCwProduct / setCwUnitRange /
  validateCwOutlines / confirmChapterLocked / unlockChapter / readbackChapter /
  setReadbackOnSave / setReadbackMinDiff / setCwPreset / saveCwIdeaInfo / clearCwReport
- **阅读器**：readerPrefs / setReaderPref / readerChapterList / readerChapter /
  readStore / addAnnotation / removeAnnotation / addReaderIdea / addBookmark /
  removeBookmark / saveReadPosition（三色标注/批注/书签/位置记忆）
- **编辑器/杂项**：editorPrefs / setEditorPref / chapterWordTarget / setChapterWordTarget /
  reviewEnabled / setReviewEnabled / regexSemantics / setRegexSemantics / stepConfirm /
  setStepConfirm / genrePresets / projectPreset / setProjectPreset / importGenrePreset /
  autoBackupEnabled / setAutoBackup / blurbText / generateBlurb / readFileText

---

## 2. 目标架构

```
                        ┌──────────────────────────────┐
                        │   Textual TUI（app/tui/）     │
                        │  屏幕/组件/主题/键位/命令面板    │
                        └───────────┬──────────────────┘
                                    │ 订阅事件 / 调用命令（同线程投递）
                        ┌───────────┴──────────────────┐
                        │  Headless 控制器               │
                        │  app/headless/controller.py   │
                        │  （bridge.py 业务逻辑 1:1 平移， │
                        │    Qt-free，可独立单测）        │
                        │  app/headless/bus.py  EventBus │
                        └───────┬──────────────┬───────┘
                                │              │
              ┌─────────────────┴──┐     ┌─────┴─────────────┐
              │ Worker 池（线程）    │     │ 纯逻辑层（复用）    │
              │ orchestrator(Thread)│     │ stages/state/     │
              │ DialogueWorker→fn   │     │ versions/memory/  │
              │ SelectionRewrite    │     │ gates/co_writing  │
              │ NetWorker/…         │     │ llm(回调流式)/     │
              │ 全部经 bus.publish   │     │ project/export/   │
              └─────────────────────┘     │ deslop/prompts    │
                                          └───────────────────┘
```

### 2.1 EventBus（`app/headless/bus.py`，~80 行）

Qt Signal 的直接等价物，线程安全：

```python
@dataclass(frozen=True)
class Ev:
    topic: str          # "stream_chunk" / "gate_asked" / "toast" / "cw_chunk" / ...
    data: dict

class EventBus:
    def publish(self, topic: str, **data): ...      # 任意线程调用；入队
    def subscribe(self, topic: str, fn): ...        # TUI 主循环注册
    def pump(self): ...                             # Textual 每 50ms 调度一批
```

- **topic 一一对应现有 Signal 名**（`sig_chunk→stream_chunk`、`gateAsked→gate_asked`、
  `toast→toast`…），bridge 的 `_on_*` 槽函数平移为 controller 的 `@on("...")` 处理器，
  逻辑逐行保留。
- 分发模型：worker 线程只 publish；**所有状态变更集中在 controller（单写者）**，
  TUI 只是订阅者 + 命令发起者 —— 与现在"Bridge 持状态、QML 绑定"的模型同构，
  迁移时不需要改任何业务判断。
- 为什么不直接用 Textual 的 `call_from_thread`/`post_message`：controller 必须可脱离
  TUI 单测（延续 `probe_*.py` 直接驱动 core 的传统），EventBus 是唯一绑定点且可替换。

### 2.2 Controller（`app/headless/controller.py`）

- 从 bridge.py **机械平移**：`__init__` 状态字段、全部 `_get_*`（改普通属性）、
  `_on_*` 事件处理、`_flush_draft` 防抖、`_maybe_auto_backup`、`stageCards`、cw 状态刷新等。
- 删除的只有：`QObject` 基类、`Property/Signal/Slot` 装饰、QThread Worker、3 个 ListModel
  （列表数据改为 controller 持普通 list，TUI 屏自己渲染 DataTable）。
- Worker 统一封装：

```python
def run_worker(name, fn, on_done=None):   # 替代 7 个 QThread 子类
    t = threading.Thread(target=_wrap(fn, name, on_done), daemon=True)
```

  各 Worker 的 `run()` 主体（llm 调用 + 回调）原样搬入 `fn`，`emit` 改 `bus.publish`。

### 2.3 Orchestrator 去 Qt 化（耦合点 1）

```python
class Orchestrator(threading.Thread):        # QThread → Thread
    # 12 个 Signal 定义删除，改为 self.bus = bus（构造注入）
    # self.sig_stream_chunk.emit(text)  →  self.bus.publish("stream_chunk", text=text)
```

- `run()` 主体、checkpoint 暂停语义、`_gate_evt` 门等待、失败 dump —— **零改动**。
- bridge 中 `orch.started.connect(...)` 等接线，改为 controller 构造时 `bus.subscribe(...)`。

### 2.4 入口与共存

- 新入口 `app/cli.py`：`python run.py --tui`（M1-M6 期间）/ TUI 成默认后 `--gui` 反选 QML。
- `run.py` 参数分发：无参数 = TUI（M7 起），`--gui` = 旧 QML（M7 退役前保留做回归对照）。
- 配置文件复用 `~/.qianbi_novel/config.json`，新增 `tui` 段（主题/键位/编辑器行为）。

---

## 3. TUI 框架选型

| 维度 | **Textual**（选它） | Rich（库非框架） | urwid | prompt_toolkit |
|------|------|------|------|------|
| 组件丰富度 | DataTable/TextArea/RichLog/TabbedContent/ProgressBar/TreeView/Modal 全有 | 无 | 中 | 弱 |
| 主题/样式 | CSS 变量系统，三主题=3 份 .tcss，完美承接"深夜编辑部" | 手工 | 手工 | 弱 |
| 异步/worker | asyncio + `run_worker` 原生，与 EventBus pump 天然契合 | - | 回调风格 | 好 |
| 鼠标支持 | 点击/拖选/滚动（局部改写、阅读翻页依赖） | - | 有 | 有 |
| 中文宽字符 | 基于 Rich，wcwidth 正确 | ✔ | ✔ | ✔ |
| 测试 | **Pilot 无头驱动 + snapshot 快照测试**（替代 UIA+截图真机驱动） | - | 弱 | 弱 |
| Windows 终端 | Win10+ 终端/Windows Terminal 良好；PyInstaller 可打包 | ✔ | 一般 | ✔ |

决策：**Textual**（本机 Python 3.11/3.13 均支持）。理由权重最高的一条：
CHANGELOG 0.12.0 显示当前 GUI 真机测试靠 UIA+PostMessage+PrintWindow 截图驱动，
成本极高；Textual 的 `Pilot` 可以在无头环境直接"按键驱动+断言"，TUI 化顺带把
**测试驱动成本降一个数量级**。

---

## 4. 功能映射总表（六大体系 → TUI 实现）

原则：**命令层 1:1 保留**（方法名、参数、语义不变），只重设计"呈现与操作"。

### 4.1 屏幕结构（对应 QML 五面板 + 阅读器 + dock）

```
TUI 主框架（Screen 数量 7）
├─ BookshelfScreen      ← BookshelfPanel.qml（书架/最近项目/新建向导）
├─ PipelineScreen       ← PipelinePanel.qml（阶段 stepper+队列+日志+流式区）
├─ ChaptersScreen       ← ChapterPanel.qml（章节列表+编辑器+版本+diff）
├─ NotesScreen          ← NotesPanel.qml（想法列表+全局偏好+质量趋势）
├─ SettingsScreen       ← SettingsPanel.qml（连接/槽位/闸门/预设/备份）
├─ ReaderScreen(Modal)  ← ReaderView.qml（F5 全屏沉浸阅读）
└─ CwDock(DockVisible)  ← CwDialogueDock.qml（共写六阶段对话，随 runMode 出现）
全局：CommandPalette(Ctrl+K) · Toast 通知 · GateBanner 模态 · HelpScreen(F1)
```

### 4.2 逐体系映射

| 现有功能（README 六大体系） | TUI 实现方式 | 命令（不变） |
|---|---|---|
| 书架/新建/最近项目 | DataTable 书目列表 + AppButton→表单 Modal（题材预设 chips→Textual SelectionList） | newProject/openProject/recentProjects |
| 阶段状态机卡片/stepper | 顶部 StageStepper（Textual 自绘组件，横排 ●─●─○） | stageCards/regenerateStage |
| 流式 thinking→生成→完成 | RichLog 流式区：阶段标签切换清屏；reasoning 折叠为可展开 Tag；打字机=节流逐字渲染 | sig_stream_chunk/reasoning/stage |
| 打字机/即时速度 | 渲染节流间隔 2 档（`tui.stream_speed` 配置，同 editorPrefs） | editorPrefs/setEditorPref |
| 暂停读已生成/光标跟随 | RichLog 随流 append，自动滚底可关（Ctrl+End 手动接管） | pausePipeline/… |
| 章节队列 | DataTable（QueueRow → 行内徽章：草稿/审校/定稿/失败） | refreshQueue |
| 章节编辑器 | TextArea（等宽中文排版，限宽=软换行宽度档位）+ dirty 徽章 + F2 保存 | openChapter/saveChapterText/markEditorDirty |
| 5s 防抖草稿/崩溃恢复 | controller 原逻辑不动；TUI 启动时检测 hasRecoverableDraft 弹恢复 Modal | recoverDraft/discardDrafts |
| **局部改写（选段）** | TextArea 原生支持 Shift+方向键选区；选中后底部浮出命令条（改写/扩写/精简/按想法改/上下文四档）→ 侧栏流式预览（j/K 翻阅）→ 应用/放弃/再改/多段连改（队列显示 N 段待改） | rewriteSelection/cancelSelectionRewrite |
| 整章重写 | 确认 Modal（含旧稿归档提示） | rewriteChapter(WithGuidance) |
| 版本 diff/回退 | 版本列表 DataTable → 统一 diff 着色渲染（Dm Crimson/+/Green）→ 回退确认 | versionsForChapter/readVersion/diffVersions/diffVersionWithDisk |
| 质量闸门 | 章视图 findings 侧栏（行号+AI 味标记）+ 质量趋势 sparkline（自绘或 plotext） | scanChapterText/qualityTrend |
| 想法/创作笔记 | DataTable（状态/范围列）+ 编辑表单；范围 SelectionList（下一章/通用/指定章） | ideasList/submitIdeaScoped/updateIdea/… |
| 全局写作偏好 | 表单三栏（文风/禁忌/节奏） | writingPrefs/saveGlobalPrefs |
| 统计面板 | 侧栏卡片：章节/字数/今日/本周/token/成本（TabularReport） | statsSummary |
| 导出 | 导出 Modal：格式单选+分隔+标题格式 → 预览区（前两章）实时刷新 → 导出报告 toast | exportProjectOpts/exportPreviewText |
| 设置-连接与模型 | 连接 DataTable + 表单（酒馆式增删改/测试/拉模型），三槽位路由 SelectionList（写作/辅助/审校） | saveConnection/testConnection/fetchModels/setSlot |
| 闸门开关/运行模式 | Switch 列表 + 单选（自动续写/逐步确认） | gateMetaList/setGateEnabled/setRunMode/setStepConfirm |
| 题材预设导入 | 文件选择 Modal + 导入报告 | genrePresets/importGenrePreset |
| 备份 | 立即备份按钮 + 每日自动备份开关 | backupProject/setAutoBackup |
| **阅读器** | F5 进 ReaderScreen：三主题=Textual 主题切换（夜间/羊皮纸/纯白 .tcss）；字号 5 档/行距 3 档=排版参数；←→ 翻页=j/K 或方向键；右侧目录→左侧抽屉 Tree；未定稿徽章=状态栏 | readerChapterList/readerChapter/readerPrefs |
| 标注/批注/书签 | 阅读屏内选中行 → 命令条（三色高亮/批注/灵感标记）；标注管理抽屉回跳 | addAnnotation/addReaderIdea/addBookmark/saveReadPosition |
| **共写档六阶段** | CwDock：左侧阶段 stepper+产物预览，右侧 RichLog 对话流+输入框；确定/打回/重看=输入框上方常驻按钮条；单元表单=Modal | setCwMode/submitCwMessage/confirmCwStage/rollbackCwStage/reopenCwWorldbook/… |
| 细纲滚动批/校验 | 进度条 + 完成后 findings 列表 | validateCwOutlines/_start_cw_outline_batch |
| 章节锁定/读改揣摩 | 锁定徽章；保存触发读改对比（min_diff 阈值同 now） | confirmChapterLocked/unlockChapter/readbackChapter |
| 发布物料 | Modal 生成标签+简介，结果可直接复制 | generateBlurb/blurbText |
| **Step Gates 决策门** | GateBanner 全屏模态：摘要+四选一（继续/带想法继续/回退重做/回退到指定门）+想法输入框；gate_asked 事件弹出，resolveStepGate 解除 | gateAsked/resolveStepGate/gateMetaList |

### 4.3 快捷键总表（对齐现有 Ctrl+S/F5/Esc/←→/Ctrl+B/Ctrl+E）

| 键 | QML 现行为 | TUI 行为 |
|----|-----------|----------|
| Ctrl+S | 保存章节（产生版本） | 同（TextArea→controller.saveChapterText） |
| F5 | 沉浸阅读 | 同（切换 ReaderScreen） |
| Esc | 退出阅读/关闭弹窗 | 同（Screen 栈弹出） |
| ←/→ | 阅读翻页 | 同 |
| Ctrl+B | 阅读书签 | 同 |
| Ctrl+E | 编辑器 | 同（跳 ChaptersScreen 当前章） |
| Ctrl+K | —（新增） | 命令面板（全部 bridge 命令可搜索执行，兜底覆盖长尾功能） |
| F1 | —（新增） | 键位帮助 |
| Ctrl+P | 暂停/恢复流水线 | 暂停/恢复切换 |
| Ctrl+. | 停止流水线 | 同 |

> Ctrl+K 命令面板是"全量功能保留"的**保险丝**：任何暂未做专属控件的命令
> （如 setCwPreset、setReadbackMinDiff）都能通过面板以表单方式调用，确保 M 阶段
> 过渡期功能零缺失。

---

## 5. 关键技术方案

### 5.1 流式输出 → TUI 渲染（高频事件，性能关键）

- LLM chunk 可达每秒数十次；直接逐 chunk 刷新 RichLog 会闪烁。
- 方案：controller `bus.publish` 不节流（保持逻辑原样）；**TUI 侧合并渲染**——
  Textual 消息泵 50ms 周期 `pump()` 批量取出同 topic 事件，`RichLog.write` 一次追加
  合并文本。实测口径：单章 6000 字全程流式不掉帧（验收项）。
- 打字机效果=渲染侧逐字延迟（`tui.stream_speed`：typewriter/instant 两档），
  与现在 QML 的实现位置一致（视图层），不碰 controller。

### 5.2 决策门阻塞语义（gate）

- 现状：orchestrator 工作线程 `_gate_evt.wait()` 阻塞，UI 弹 StepGateBar，
  `resolveStepGate(action, idea)` 置位事件。
- TUI：`gate_asked` 事件 → push GateBanner 模态（不可 Esc 关闭，与现 QML 一致）→
  用户选择 → `controller.resolveStepGate(...)`。**工作线程侧零改动**。
- CHANGELOG 问题 #3（确定连点）在 controller 层顺手修：resolveStepGate 加重入锁。

### 5.3 选区局部改写（交互最重的功能）

- Textual `TextArea` 支持 shift+方向/鼠标拖选，`selection` 属性给出起止行列 →
  换算 `before/selected/after` 三段（与 bridge.rewriteSelection 签名对齐）。
- 选中即浮出底部命令条（Button row + 快捷键数字键），上下文档位 cycle 用 `Tab`。
- 预览：右半屏 Split，流式渲染替换稿；j/K 对照原文；Y 应用 / Q 放弃 / R 再改；
  多段连改=队列计数徽章，应用后自动跳下一段（对齐"多段连改"现有行为）。

### 5.4 主题系统（深夜编辑部 → Textual）

- `app/tui/themes/`：`night.tcss`（默认，对应现 QML 深色）、`parchment.tcss`（羊皮纸）、
  `plain.tcss`（纯白）。变量命名对齐现 `Theme.qml`（bgPanel/bgActive/textPrimary…）。
- 阅读器三主题与 TUI 全局主题独立切换（同现 ReaderView 行为）。

### 5.5 Windows 终端兼容

- 启动时 `sys.stdout.reconfigure(encoding="utf-8")`；禁用 emoji 时降级为 ASCII 徽章
  （`tui.ascii_fallback`，检测 `WT_SESSION`/传统 conhost）。
- 鼠标：Textual 开启 mouse=True；传统 conhost 下提示使用 Windows Terminal（README 注明）。
- 打包：PyInstaller console 模式单 exe（现 spec 为 windowed，TUI 版改 console onefile）。

### 5.6 数据零迁移

TUI 不引入任何新数据文件；所有状态仍在 `pipeline_state.json` + 各 md + `.versions/` +
`.annotations/` + `~/.qianbi_novel/config.json`。**GUI 与 TUI 可打开同一本书、交替使用**
（M1-M6 共存期回归手段；版本锁机制沿用现有 `cw_locked`，跨进程互斥用 `pipeline_state.json`
加 `last_opened_by` 提示即可，不引入文件锁）。

---

## 6. 里程碑

> 每期独立可交付、可回归；M0 完成后 QML 必须全绿（桥未变），此后 QML 只读不修。

### M0 — 内核下沉（改桥不换头）★地基
- 新建 `app/headless/bus.py` + `controller.py`：bridge.py 逻辑 1:1 平移，Qt-free。
- `bridge.py` 改为 controller 的**薄 Qt 适配壳**（Property/Signal 转发），QML 行为不变。
- orchestrator/co_dialogue 去 Qt 化（耦合点 1/2）。
- 验收：`assert_v099` 18/18 · `smoke_func` ALL_FUNC_OK · `probe_gate_flow` 4/4 ·
  全部 9 个共写探针 · GUI 真机抽查共写六阶段冒烟。

### M1 — TUI 骨架 + 书架 + 项目打开
- Textual App 框架、7 屏骨架、主题系统、Ctrl+K 命令面板、Toast。
- BookshelfScreen：书目/最近/新建向导（含题材预设）。
- 验收：TUI 内完成 新建→打开→看到阶段卡片；Pilot 无头用例 3 条。

### M2 — 设置 + 连接 + 自动流水线监控
- SettingsScreen 全量（连接/槽位/闸门/运行模式/预设/备份/编辑器偏好）。
- PipelineScreen：stepper/队列/日志/**流式三态**（thinking 折叠→生成→完成）/暂停停止。
- 验收：真实 API Key 跑通 1 章微循环全程监控；probe 改造指向 controller 后全绿。

### M3 — 编辑器 + 版本 + 想法
- ChaptersScreen：TextArea 编辑/5s 防抖/崩溃恢复 Modal/Ctrl+S 版本。
- 版本列表+diff 着色+回退；NotesScreen（想法 CRUD/范围/全局偏好/统计）。
- 验收：编辑→保存→diff→回退闭环；想法注入下一章生效（真 API 1 例）。

### M4 — 共写档六阶段（最重的一期）
- CwDock + 六阶段对话流 + 确定/打回/重看世界书 + 单元表单 + 细纲滚动批 + 校验。
- **顺手修 CHANGELOG 9 项中的 #1/#2/#3/#4/#8**（runMode 同步、预设选择 UI、
  重入锁、空转写拦截、busy 计时+取消——busy 计时在 TUI 天然好做）。
- 验收：无头 Pilot 驱动六阶段状态机走查 + 真 API 走到"单元细纲确定"。

### M5 — 阅读器体系
- ReaderScreen：三主题/字号行距/翻页/目录抽屉/位置记忆/书签/未定稿徽章。
- 标注：三色/批注/灵感直通笔记 + 标注管理回跳。
- 验收：阅读 54 章《改命笔记》样书，标注/书签/位置记忆断点续读。

### M6 — 局部改写 + 质量闸门 + 导出
- 选区命令条 + 预览 Split + 多段连改；AI 味扫描侧栏 + 质量趋势 + 去味改写；
  导出 Modal（预览/选项/报告）+ 发布物料。
- 验收：真 API 完成"选段改→预览→应用→连改 2 段"；导出 txt+epub 与 GUI 版产物 byte 级对比一致。

### M7 — 退役 QML，TUI 成默认
- `run.py` 默认 TUI；QML/bridge 薄壳/PySide6 依赖移除（或移 `_archive/`）。
- 打包 `QianBi-Novel-TUI.exe`（console onefile）；README/CHANGELOG 更新。
- 验收：全量回归（M0 基线 + 各期验收项）+ 新旧产物一致性抽检。

---

## 7. 测试策略

1. **内核测试零重写**：`probe_*.py`/`smoke_func`/`assert_v099` 的 import 从 bridge
   改 controller（M0 一次性机械替换），断言不变。
2. **TUI 层新测试**：Textual `Pilot` 无头驱动（run_test）——按键序列 + 断言屏内控件
   状态，替代 UIA+PostMessage+截图 的真机驱动（CHANGELOG 0.12.0 的最大痛点）。
3. **snapshot 测试**：核心屏（书架/流水线/编辑器/共写 dock/阅读器）保存快照，
   样式回归自动 diff。
4. **一致性验收**：同一测试项目分别用 TUI 与 QML（M7 前）跑同一操作，
   对比 `pipeline_state.json` 与产物文件。
5. 真机（Windows Terminal）手工走查清单沿用 `tests/walk_v099.py` 的用例设计。

## 8. 风险清单

| 风险 | 等级 | 对策 |
|---|---|---|
| bridge 平移引入行为漂移 | 中 | M0 保持 bridge=controller 薄壳双跑；全部 probe 回归；平移按函数逐个 diff review |
| 终端中文/emoji/宽字符异常 | 中 | M1 即建终端兼容矩阵（Windows Terminal/conhost/VSCode 终端）；ASCII 降级开关 |
| 选区改写在某些终端鼠标受限 | 中 | 键盘选区为主路径（Shift+方向键），鼠标为增强；conhost 提示 |
| 流式高频刷新性能 | 低 | 50ms 批量渲染；RichLog 行缓冲；验收压测单章 6000 字 |
| Textual 版本 API 变动 | 低 | 锁版本（requirements pin）；snapshot 测试兜底 |
| 功能遗漏（长尾命令） | 低 | §1.2 接口面清单为验收底册 + Ctrl+K 面板兜底全命令 |
| 共写档已知 9 缺陷带入 TUI | 中 | M4 集中修 #1-#4/#8（修法已拟定于 CHANGELOG），#5-#7/#9 属交互/prompt 层在 TUI 重设计时自然消解或按原修法处理 |

## 9. 非目标（本轮不做）

- 不改任何 prompt 工程、闸门策略、版本/断点/摘要链语义。
- 不引入新数据格式、不做数据迁移。
- 不做 Web/远程界面（EventBus 架构已为此留门，但不在本计划内）。
- 不做多用户/并发编辑。

## 10. 工作量估算（相对值）

| 期 | 内容 | 占比 |
|----|------|------|
| M0 | 内核下沉+去 Qt | 25%（最高风险密度，值得慢） |
| M1-M2 | 骨架+设置+流水线监控 | 20% |
| M3 | 编辑器+版本+想法 | 15% |
| M4 | 共写档 | 20% |
| M5-M6 | 阅读器+改写+导出 | 15% |
| M7 | 退役+打包+回归 | 5% |
