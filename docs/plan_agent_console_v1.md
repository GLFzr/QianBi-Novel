# 改版计划 v1：中间共写窗口 Agent Console

> 目标版本：V1.0 前最后一个大改版。把「AI 流式写作 + 决策门确认」升级为
> 「中间常驻的共写窗口」：**AI 为什么这么写（思考链持久留存）、你跟 Agent 说了什么
> （对话实录）、每步决策在什么状态（门状态）** 全部收进同一个框。
> 阅读器从全屏覆盖收敛为右侧收窄 dock，全屏沉浸模式保留一键切换（不砍已交付功能）。
>
> 关联文档：[plan_step_gates_v1.md](./plan_step_gates_v1.md)（决策条输入框 = 本窗口对话通道雏形，本计划正式落地 P4 远期目标）。

---

## 0. 结论速览（先看这张表）

| 决策点 | 结论 |
|---|---|
| 新窗口形态 | **常驻中间列（可折叠）**，不是独立 OS 窗口，也不是 panelStack 面板 |
| 摆放位置 | `导航栏(48) → 面板Stack(300) → AgentConsole(360) → 主编辑列(弹性) → 阅读器dock(0/460)` |
| 默认状态 | Console 展开 360px；阅读器 dock 默认关闭（F5/「阅读」打开） |
| 最小/最大宽度 | Console 280–480，可折叠到 24px 细条；阅读器 dock 400–520 |
| 思考链 | 会话内存环形缓冲 + 按章落盘归档；按 槽位×阶段 分组；硬截断 + 摘要/完整切换 |
| 对话 | 人的想法/决策 + Agent 的摘要/决策结果/回退记录，统一进对话流 |
| 与 StepGateBar 关系 | M1/M2 并存（回归优先）；M3 合并进 Console，门条保留 `gateBar` objectName 契约 |
| 阅读器 | 新增 `embedded` 嵌入模式做 dock；原全屏沉浸模式保留为「全屏」按钮 |
| 兼容性 | 18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 全绿；ui_regions 裁剪坐标随布局更新 |

---

## 1. 布局方案（最关键）

### 1.1 现状解剖（已核对代码）

```
┌─────────────────────────────────────────────────────────────────────┐
│ 应用窗口 1400×900（min 1080×700）                                    │
├────┬──────┬──────────────────────────────────────────────────────────┤
│导航 │面板  │  主编辑列（顶栏44 / 编辑器 / StepGateBar / 思维链条150 / 扫描条 / 日志）│
│48  │300   │  （fills 剩余 ≈1052px）                                   │
├────┴──────┴──────────────────────────────────────────────────────────┤
│ 状态栏 24                                                             │
└─────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│ ReaderView：anchors.fill:parent 全窗口覆盖层 │  ← F5 打开，z=50，opacity 淡入
└─────────────────────────────────────────────┘
```

- 五个面板在 `panelStack`（StackLayout，300px 固定列），与编辑列是 **RowLayout 兄弟关系**。
- ReaderView 是**覆盖层**（`anchors.fill: parent` + `z: 50`），打开时盖住整个界面。
- 思维链：`bridge.reasoningText` 仅流式期间累积，`_on_stream_stage / _on_stream_done /
  _on_chapter_done / _on_finished` 四处清空（bridge.py 1133-1191）；UI 只在
  `showReasoning && isStreaming` 时显示 150px 小条。**流式结束即蒸发，用户痛点坐实。**

### 1.2 三种候选形态的取舍

| 形态 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **A. 常驻中间列（推荐）** | 与流水线/编辑列并列，思考链+对话随时可见；切换面板不丢上下文；折叠后零回归 | 占横向宽度；小窗口需压editor | ✅ 主方案（这也是「中间共写窗口」字面形态） |
| B. 可折叠侧栏 | 省空间，形态像 IDE 侧栏 | 收起来就看不见了，违背「随时介入」意图；与 StepGateBar 对话通道距离远 | 作为 A 的折叠态补充，不是独立方案 |
| C. dock 阅读器 | 阅读变侧栏，成熟 ReaderView 全部组件可复用 | 若不保留全屏会砍掉已交付体验；单独存在时看不到编辑列 | ✅ 阅读器采用（与 A 组合）；全屏模式保留为可切换项 |
| D. 独立 OS 窗口（废弃） | 极简口语化「再加一个窗口」 | 多窗口标题栏/置顶/z 序与全屏阅读器冲突；QML 多 Window 生命周期与单窗口测试基建（grabWindow 全窗口截图）不兼容 | ❌ 不采用；「窗口」在桌面 QML 里应实现为 Dock 列 |

### 1.3 目标布局（v1 定型）

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 应用窗口默认 1600×940（min 1080×700）· 状态栏 24 不变                          │
├────┬──────┬────────────┬────────────────────┬──────────────┤
│导航 │面板  │ AgentConsole│ 主编辑列（弹性）     │ 阅读器 dock（0│
│48  │300   │ 360 (280-480)│ 顶栏44+编辑器+决策条  │ 或 400-520， │
│    │      │ 对话/思考链/  │ （floor 380）       │ 嵌入门条）    │
│    │      │ 门状态条      │                     │ （F5/阅读打开；│
│    │      │              │                     │  全景按钮→全屏）│
├────┴──────┴────────────┴────────────────────┴──────────────┤
│ 状态栏                                                            │
└────────────────────────────────────────────────────────────────────────────┘

结构关系：
- AgentConsole 与 panelStack、editorHolder 并列，直接作为 RowLayout 的第三个子项
  → 它**不是 panelStack 的面板**（5 面板切换时它不动），是**跨面板常驻列**。
  理由：流水线写作在后台进行时，用户正可能在翻书架/笔记；思考链与对话不能随面板切走。
- 阅读器 dock 是 RowLayout 最右子项；ReaderView 自身加 `embedded` 模式。
```

### 1.4 宽度与缩放策略（硬数字）

| 项 | 值 | 规则 |
|---|---|---|
| 窗口默认 | 1600×940 | 允许 1080p 全屏容纳四列共存 |
| 窗口最小 | 1080×700（不变） | 小窗口不承诺四列共存，走自动降级 |
| Console 展开 | 360（`Layout.preferredWidth`） | 可拖分隔条 280–480 |
| Console 折叠 | 24px 细条（仅图标+竖排标题） | 折叠时对旧回归测试几何零影响 |
| 编辑器 floor | 380 | `Layout.minimumWidth: 380` |
| 阅读器 dock | 460（400–520） | 打开后 editor 与 console 自动压缩 |
| 压扩顺序 | 开阅读器 → console 先压到 300 → editor 压到 380 → 仍超窗口则阅读器退回全屏模式 | 窗口缩放时 editor 是弹性主吃亏方 |

缩放策略：
- `windowWidth ≥ 1488`：四列共存（48+300+360+380+460）。
- `1400 ≤ windowWidth < 1488`：打开阅读器时 console 自动压到 300。
- `< 1400`：打开阅读器自动走**全屏沉浸**（旧行为，弹 toast 提示），不硬塞四列。
- 阅读器 dock 内文本宽度复用 ReaderView 现有 `Math.min(flick.width-56, 740)` 逻辑 → 460 宽的 dock 自动缩到 404 排版列，无需新排版引擎。

### 1.5 ReaderView 改造（%不砍全屏%）

保留单实例（`ReaderView { id: readerView }`），新增：

```qml
// ReaderView.qml 增量
property bool embedded: false          // false=旧全屏覆盖层；true=dock 列
property int  dockWidth: 460

// 全屏态维持 anchors.fill:parent + z:50 + opacity 淡入（原样）
// 嵌入态用 QML States + AnchorChanges 切换到 dock 容器几何：
states: State { name: "embed"; when: embedded
    AnchorChanges { target: reader
        anchors.left:  undefined; anchors.right: dockHost.right
        anchors.top:   dockHost.top; anchors.bottom: dockHost.bottom } }
```

- 嵌入态差异化（全部可降级为「紧凑 chrome」，不动阅读内核）：
  - 顶栏：隐藏「字数」、标题 elide 加强；按钮保持。
  - 底栏：上一章/下一章只显图标；进度条 220→120。
  - 抽屉宽度：`Math.min(300, dockWidth * 0.62)`。
  - 排版设置面板：宽度 `min(300, dockWidth-16)`。
- 打开路由：`openReader(embedded)` 双入口；F5/「阅读」按钮默认 `embedded=true`；
  阅读器顶栏新加「全屏」按钮 → `embedded=false` 瞬时切换（切换前 `savePosition()`，
  切换后恢复 `store.position` 比例，阅读位置不丢）。
- 三主题/标注/书签/目录/翻页/位置记忆代码路径零改动 → ui_regions 的 reader 系列截图仍可复拍。

---

## 2. 内容模型（窗口分几块）

### 2.1 分块

```
AgentConsole
├─ ① 门状态条（Top Banner, ~64px）
│    ⏸ G5 · 第7章 · 草稿完成（3,214字 · 开头：…）  [继续] [回退]
│    这里是决策门的主入口（M3 起，旧 StepGateBar 合并进来）
├─ ② 对话区（Agent Transcript, 60% 高）
│    ┌────────────────────────────────────────────┐
│    │  👤 你 · 12:03:41 ▸ 想法：这章多用冷清氛围   │
│    │  🤖 写作槽 · 草稿 ▸ 已按你的想法注入草稿指令   │
│    │  ⏸ 门 G5 开启 · 产物摘要：3,214字…          │
│    │  👤 你 · 12:05:02 ▸ 继续                    │
│    │  🤖 审校槽 · 审校 ▸ 0 阻塞 · 3 建议…        │
│    └────────────────────────────────────────────┘
│    输入行： [对这一步的想法 / 直接跟 Agent 说话…] [继续] [回退]
├─ ③ 思考链区（Reasoning, 40% 高，可拖分隔条）
│    筛选：全部 ▍写作槽 ▍辅助槽 ▍审校槽   [摘要|完整] [清空] [导出]
│    ▸ 写作槽 · 草稿 第7章        [摘要▼]  ……AI 为什么这么写（3,182 字符截断）
│      ├ 头部 120 字………
│      └ [已省略 2,900 字]…（点「完整」从归档取全文）
│    ▸ 辅助槽 · 细纲             [完整▲]  全文（<阈值不截断）
└─ 折叠态：24px 竖条，点击展开（保留「有新思考/新对话」红点提示）
```

- 三块固定顺序：门状态条永远在顶（决策是当前最高优先级）；对话与思考链上下分栏
  用 `SplitView`（QtQuick.Controls）拖分隔线，默认 60/40。
- 「截断机制」语义：单条思考链超过阈值（默认 4000 字符）→ 显示
  `头120字 + […已省略 N 字…] + 尾200字`，全文按章落盘，点「完整」按需取回。
- 槽位/阶段分组：同一 `slot+stage+chapter` 的链合并为一个折叠头，展开看全部增量。

### 2.2 QML 组件树草图

```
Main.qml (RowLayout)
├─ navRail(48)
├─ panelBox(300) → StackLayout#panelStack (5 面板, 不变)
├─ AgentConsole.qml                        ← 新增中间列
│   ├─ (1) GateBanner   objectName:"gateBar"  ← M3 起承接门条契约
│   ├─ SplitView
│   │   ├─ DialogPane
│   │   │   ├─ ListView (model: bridge.consoleModel, 角色: kind/slot/stage/chapter/seq/ts/text/head/truncated/fullLen)
│   │   │   │   ├─ delegate: 按 kind 分派 → HumanBubble / AgentBubble / GateEvent / RollbackEvent
│   │   │   ├─ InputRow (TextField#consoleInput + 继续 + 回退 + 附注提示)
│   │   └─ ThinkingPane
│   │       ├─ Toolbar (槽位筛选 Chip ×3 + 摘要/完整 + 清空 + 导出)
│   │       ├─ ListView (model: bridge.consoleModel 代理分组, 或独立 thinkingModel)
│   │       └─ DetailPane (ScrollView TextArea, 完整链展示, 懒加载全文)
│   └─ (4) 折叠条 (width:24, 红点 = consoleModel 有新项且未聚焦)
├─ editorHolder(ColumnLayout, floor 380)   ← 顶栏/编辑器/扫描条/日志, 除入门外不动
└─ ReaderDockHost(Rectangle, width: readerOpen?460:0, clip)
    └─ ReaderView.qml (embedded: true 时锚到本容器)
ReaderView.qml (同一实例, embedded:false 时 anchors.fill:mainWindow)  ← overlay 保留
```

`consoleModel` 用现有 `QAbstractListModel` 模式（参考 bridge.py 的 `LogListModel`），
避免 QML 侧 ListModel 手工同步。

---

## 3. 数据流（思考链从桥到窗口的持久方案）

### 3.1 信号改造（多槽位分流）

现状：`ctx.stream_reasoning(text)` 无槽位/阶段信息，UI 只有一个 `reasoningText` 混着所有槽位。
方案（推荐显式参数；前缀编码为备选）：

```python
# orchestrator.py
sig_stream_reasoning = Signal(str, str, str)   # text, slot, stage
def stream_reasoning(self, text, slot="", stage=""):
    self.sig_stream_reasoning.emit(text, slot, stage)

# stages.py _stream(): 调用处补上上下文
def on_reasoning(r):
    ctx.stream_reasoning(r, slot, label)   # label 即阶段名，如“草稿 第7章”
```
兼容：`bridge._on_stream_reasoning(text, slot="", stage="")` 带默认值，
SelectionRewriteWorker 的 `sig_reasoning(str)` 不强制改签名，桥内用
`slot=SLOT_WRITING, stage="局部改写"` 包装 → 局部改写对话框的思考链也进 Console。
（备选：不碰 orchestrator 签名，桥里按 `stage 前缀` 解析 —— 省改动但字符串解析脆弱，
不推荐；多槽位是刚需，显式参数一次到位。）

### 3.2 持久化策略（三层）

```
┌─ L0 流式瞬时（保留现状，兼容旧小条）
│    bridge.reasoningText 仍逐字累积、仍随阶段清空 —— 旧 UI 逻辑零改
├─ L1 会话内存环形缓冲（Console 主数据源）
│    ConsoleListModel（max 2000 条；超上限把最老条目折叠为摘要并通知 UI）
│    每条: {kind, slot, stage, chapter, seq, ts, head, text, truncated, fullLen}
│    写入节流：QTimer 120ms 合并增量，不逐字操作 model（性能关键）
├─ L2 按章落盘（M2 起，可回溯可导出）
│    pipeline_debug/console/ch<章号>.md   —— 该章全部思考链+对话全文
│    追踪/决策记录.md                     —— 追加门事件/人想法/决策结果（与 gates 计划一致）
│    归档时机：章级 gate G9 触发时；_on_chapter_done；窗口关闭时 flush
└─ 阶段切换归档：_on_stream_stage 切换即调用 _flush_think_delta()，
    把当前 槽位×阶段 的链固化为一条 console 条目 → 稍后进入下一阶段时，
    上一阶段自动折叠成组（“草稿的思考链在进入审校时折叠归档”即此机制）
```

```python
# bridge.py 增量（M1 核心）
CONSOLE_MAX   = 2000
THINK_HARD_CH = 4000       # 单条硬截断阈值（界面默认摘要）
THINK_HEAD    = 120
THINK_TAIL    = 200

class ConsoleListModel(QAbstractListModel):
    # roles: kind/slot/stage/chapter/seq/ts/head/text/truncated/fullLen
    def append(self, entry): ...      # beginInsertRows + 超限折叠最老条
    def collapse_oldest(self): ...    # 保留 head+tail，fullLen 记下，标记 truncated

self._console = ConsoleListModel(self)          # 暴露为 consoleModel 属性
self._think_buf = {"slot": "", "stage": "", "text": ""}
self._think_timer = QTimer(self); self._think_timer.setInterval(120)
self._think_timer.timeout.connect(self._flush_think_delta)

def _on_stream_reasoning(self, text, slot="", stage=""):
    self._reasoning_text += text                    # L0 兼容旧条
    self._think_buf["slot"]  = slot  or self._think_buf["slot"]
    self._think_buf["stage"] = stage or self._think_buf["stage"]
    self._think_buf["text"] += text
    self.reasoningChanged.emit()
    if not self._think_timer.isActive(): self._think_timer.start()

def _flush_think_delta(self):
    self._think_timer.stop()
    b = self._think_buf
    if b["text"]:
        self._append_thinking(b["slot"], b["stage"], b["text"])  # 截断/落盘/append
        b["text"] = ""

def _on_stream_stage(self, label):   # 阶段切换 = 归档点
    self._flush_think_delta()
    ...现状逻辑原样...

@Slot(int, result=str)
def consoleEntryFull(self, row):      # 摘要→全文懒加载（读内存 or L2 文件）
    ...

@Slot(str)  def sendAgentMessage(self, text): ...   # M2
@Slot(str)  def consoleExport(self, path=""): ...   # M2，默认 追踪/决策记录.md
```

### 3.3 事件转化表（谁进对话区 / 谁进思考链区）

| 上游事件 | 去处 | 内容 |
|---|---|---|
| sig_stream_reasoning(slot,stage) | 思考链区（L0 同步兼容旧条） | 按 槽位×阶段 分组的链 |
| gateAsked(key, chapter, summary) | 对话区 GateEvent + 门状态条 | 门开启、产物摘要 |
| resolveStepGate(next/return, idea) | 对话区 👤 Human + 🤖 Agent 回执 | 你的想法/决策 + “已带想法继续/已回退重做” |
| _on_chapter_done(record) | 对话区 Agent 消息 | 定稿摘要（字数/审校阻塞数） |
| 局部改写 _on_sel_reasoning / _on_sel_done | 思考链区 + 对话区 | slot=writing, stage=局部改写 |
| sendAgentMessage(text) | 对话区 👤 消息 + 想法队列 | 注入下一门/下一步（非流中直接打断） |
| _apply_rollback 返回值 | 对话区 RollbackEvent | 回退目标 + 归档路径提示 |

---

## 4. 交互设计

### 4.1 输入框 = 对话通道（含门语义）

输入框常驻对话区底部（永远可用 = 随时介入）：

| 焦点/状态 | 回车 Enter | Ctrl+Enter | R | 说明 |
|---|---|---|---|---|
| 门等待中 + 输入框有文字 | **带想法继续** | 直接继续（忽略输入） | 带想法回退 | 与现有 StepGateBar 语义一致 |
| 门等待中 + 输入框为空 | 直接继续 | 直接继续 | 回退 | 快捷路径不丢 |
| 非门状态（流式/空闲） | **发送给当前 Agent** | 发送 + 存为正式想法 | 无效 | 进想法队列，注入下一步；不打断流中调用 |
| 编辑器焦点 + 门等待 | 继续（沿用现有全局 Shortcut） | 继续 | 回退 | 输入框失焦时键盘仍可决策 |

- 发送通道复用现有 `st.add_idea / take_ideas` 与 `pending_guidance` 机制
  （`sendAgentMessage(text)` → 入想法队列 → 下个门/下一章注入正文 prompt 指令区）。
- 每条你的消息在对话区可见 → “跟 Agent 的对话都在这个框里”逐字满足。

### 4.2 历史回看 / 清空 / 导出

- 回看：对话/思考链双 ListView 均支持按 章、槽位、阶段 过滤；顶部筛选 Chip + 章节下拉。
- 清空：只清 L1 内存缓冲（“不再显示”），L2 落盘档案保留；二次确认弹窗，防误删审计轨迹。
- 导出：`consoleExport()` → `追踪/决策记录.md`（门+对话）与
  `pipeline_debug/console/<章>.md`（思考链全文）；导出 >10MB 时弹体积警告。
- 折叠条红点：consoleModel 新增且窗口未聚焦时亮点，展开即消。

---

## 5. 与 StepGateBar 的关系（取舍）

**结论：分三阶段走：M1/M2 并存 → M3 合并，且合并后保住探针契约。**

| 阶段 | 关系 | 理由 |
|---|---|---|
| M1/M2 | 面板区旧 StepGateBar 原样保留；Console 被动镜像门事件 | 回归优先；probe_gate_ui 8 项依赖 gateBar 现形态，先不做结构手术 |
| M3 | StepGateBar 合并进 Console：门 Banner 化（objectName 仍为 `gateBar`，`waiting/visible/rollbackable` 属性语义不变；继续/回退按钮读 Console 输入框文本）；编辑器下方改为**门激活时的 1px 提示条**（点击聚焦 Console 输入框） | 唯一决策入口，消除双输入框同屏冗余；输入框即对话通道，门只是对话的“当前待办” |

不合并的代价（维持现状并行）：两个输入框（编辑器下 & Console）语义重叠、焦点/快捷键
竞争，用户会困惑“往哪个框写”；且“对话都在一个框里”无法成立。合并的代价是
M3 一次结构手术 — 用 objectName/属性契约 + 回归测试兜底，风险可控。

---

## 6. 实施步骤（3 个里程碑）

### M1 — 思考链留存可见（先解决“流式结束就没了”）

改动文件：
- `app/ui/bridge.py`：`ConsoleListModel`、`consoleModel` 属性、`_think_buf + _flush_think_delta` 节流、`_on_stream_reasoning/_on_stream_stage` 双写（L0 旧条不变 + L1 缓冲）、截断/摘要常量、`consoleEntryFull`。
- `app/core/orchestrator.py`：`sig_stream_reasoning` 扩参 + `stream_reasoning(text, slot, stage)`（带默认值，向后兼容）。
- `app/core/stages.py`：`_stream()` 的 `on_reasoning` 传 `(r, slot, label)`。
- `app/ui/qml/components/AgentConsole.qml`（新增）：仅思考链 Tab + 筛选 + 摘要/完整 + 折叠态。
- `app/ui/qml/Main.qml`：RowLayout 插入 AgentConsole（**默认折叠 24px**，几何零变化）；“显示思考”按钮改为打开 Console 思考链 Tab；旧 150px 思维链小条暂留。

回归：`probe_gate_flow.py`(4/4) + `probe_gate_ui.py`(8/8) + `assert_v099.py`(18/18) +
`smoke_func.py` + `check_layout.py` + **新增** `tests/probe_console_model.py`
（10 项：append/分组/截断/超限折叠/阶段归档/懒加载全文/旧条兼容/flow 不回归）。

### M2 — 对话区 + 门事件入册 + 落盘

改动文件：
- `app/ui/bridge.py`：`sendAgentMessage`、`_on_gate / resolveStepGate / _on_chapter_done` 事件入册、L2 落盘（`pipeline_debug/console/ch<num>.md` + `追踪/决策记录.md` 追加）、`consoleExport / consoleClear`。
- `app/ui/qml/components/AgentConsole.qml`：SplitView 双栏、对话区气泡 delegate、输入行、门状态条（被动镜像）、导出/清空 UI。
- `app/ui/qml/Main.qml`：输入行键盘语义表落地、红点提示。
- `app/ui/qml/SettingsPanel.qml`（外观页）：中间窗口默认宽度/默认展开 开关。

回归：M1 全套 + `ui_audit.py` + `shot_ui.py` + 手工冒烟（流式直播中发消息不打断）。

### M3 — 布局改造：阅读器收窄 + 门合并

改动文件：
- `app/ui/qml/components/ReaderView.qml`：`embedded` 模式 + States/AnchorChanges + 紧凑 chrome + 抽屉/面板宽度规则 + 「全屏」切换按钮 + 位置保持。
- `app/ui/qml/Main.qml`：ReaderDockHost 入 RowLayout；`openReader(embedded)` 双路由与窗口宽度降级策略；默认窗口 1600×940；StepGateBar 合并（gateBar 契约搬到 Console 门 Banner）；Shortcut 接线（Enter/Ctrl+Enter/R 语义表）。
- `app/ui/qml/components/StepGateBar.qml`：文件保留但 Main 不再实例化（或删除后由 Console 内的 Banner 承担 objectName；二选一，推荐后者并同步 probe 注释）。
- `tests/ui_regions.py`：按新布局更新 REGIONS 坐标（topbar/editor-body 的 x 偏移 + console 列新区域 + reader 系列改 dock 尺寸）。
- `tests/check_layout.py`：新增“console 展开 + 阅读器 dock 打开”两种几何跑法（只查越界，不查绝对坐标）。

回归：M2 全套 + `ui_drive.py` + `long_run.py`（轻量档）＋人工验证：F5 开 dock、全屏切换、
阅读器三主题/标注/书签、编辑器流式直播、门 4 语义、窗口缩放降级。

---

## 7. 风险与边界

1. **流式高频信号卡 UI**
   思维链增量可能 >50 次/秒 → 所有 QML 副作用走 `_think_timer` 120ms 合并；模型操作/属性变更按批；ListView delegate 最小化；流式期间关闭动画（typewriter 已是 33ms 节流，不叠加）。
2. **数据体积（几十万字小说）**
   L1 内存只留 2000 条摘要；L2 按章落盘单文件（估算每章思考链 20–60KB，300 章 ≈ 6–18MB，可接受）；提供归档保留策略（默认保留最近 50 章 + 导出 zip）；导出 >10MB 弹警告。
3. **回归兼容（逐项对照流水线）**
   - assert_v099：纯桥层 + `navItems` 不变 → 不受影响。
   - smoke_func：纯桥层 → 不受影响。
   - probe_gate_flow：orchestrator 门语义零改动（stream_reasoning 扩参带默认值）→ 4/4。
   - probe_gate_ui：M3 门 Banner 保留 `gateBar` objectName + `waiting/visible/rollbackable`；新组件不得引入白名单外的 QML 告警类别（Layout/anchor/cycle/hovered/containsMouse/drawer/Unable to assign 已在白名单，新代码避免 binding loop）。
   - check_layout：M1/M2 折叠态默认 → 几何与今日一致；M3 补跑展开态。
   - ui_regions：裁剪坐标是“审计口径”非断言，随布局更新后仍能产出全部 8 屏部位图。
4. **意图判定：全屏 vs dock 双形态**
   用 `embedded` 单实例切换，避免双实例状态分裂；切换前 `savePosition` + 恢复比例。风险点是 States/AnchorChanges 的锚点切换 —— 底线方案：用 Loader 换实例（退回时仅丢当前滚动位置，阅读进度已持久化）。
5. **键盘焦点竞争**
   输入框获得焦点时，全局 `Shortcut`（Return）需 `enabled: gateBar.waiting && !consoleInput.activeFocus` 之类互斥，避免一边打字一边触发“继续”。逐焦点态测试覆盖。
6. **回退/删除联动**
   章级 G9 回退删除正文时，L2 档案按章归档不受影响（档案是只读审计轨迹）；G2 回退波及大纲时，思考链按时间线保留（附 gateKey 标记，便于回溯“为什么当时重拟”）。
7. **老设备性能边界**
   折叠态 Console 不创建 ListView 场景（load 惰性 / `visible:false` 时 delegate 不渲染）；最低窗口 1080 下阅读器强制回全屏，不做四列硬塞。

---

## 8. 验收口径（对应现有脚本）

| 脚本 | 期望 |
|---|---|
| tests/assert_v099.py | TOTAL 18 / 18 |
| tests/smoke_func.py | ALL_FUNC_OK |
| tests/check_layout.py | 0 OVERFLOW（折叠态与展开态双跑） |
| tests/probe_gate_flow.py | TOTAL 4 / 4 |
| tests/probe_gate_ui.py | TOTAL 8 / 8 + 无新增 QML 告警 |
| tests/probe_console_model.py（新增） | TOTAL 10 / 10 |
| tests/ui_regions.py | REGIONS_DONE + 全部部位图可复拍（坐标已更新） |
| tests/ui_drive.py / ui_audit.py / shot_ui.py | 通过 |

---

*Version 1.0 · 由现状代码核对后成稿：Main.qml 1671 行 / bridge.py 1890 行 /
orchestrator.py 352 行 / stages.py 650 行 / ReaderView.qml 922 行 / StepGateBar.qml 138 行。*