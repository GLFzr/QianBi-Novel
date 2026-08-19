# Agent Console v3 — 中间共写窗口（第二轮修订版）

> 本文件为 `plan_agent_console_v2.md` 的第二轮修订版。**修订原则：已通过部分保持不动，只改本轮评审漏洞清单点名的 7 处问题**；其余架构（跨面板中间列、三块内容、三层数据流、输入框常驻、三里程碑 M1/M2/M3）沿用 v2 已通过部分。修订点以「【修订v3】」标注，并在文末《评审漏洞逐条回应》中逐条说明。
>
> 本轮评审结论为「有条件通过」。7 处漏洞标注「【M3·重点】/【M1/M2·重点】/【M3】/【全plan】」共 7 条，逐条全部采纳；本轮先把每条漏洞的**事实核验**写清（对照源码行），再给**修订动作**，避免 v2 中「凭印象改、未真读文件」的问题。

## 0. 本轮修订摘要

| # | 评审漏洞（优先级） | 本节 | v2 的问题 | 修订动作 |
|---|---------|---------|----------|---------|
| 1 | ReaderView 常驻 dock 与 F5/Escape/翻页冲突（【M3·重点】） | §2.2 | v2 点3「embedded 常态 opacity:1 常驻」使 `visible`(opacity>0.01) 恒真 → F5 永禁用、翻页抢焦；未定义沉浸/常驻两种可见性语义 | 引入 `property bool immersive`；F5/Escape/翻页全部改绑 `immersive`；`visible` 只管渲染、不再兼任「沉浸状态」判据 |
| 2 | 思考链按槽位×阶段×章分组缺信号管线（【M1/M2·重点】） | §2.4 | v2 §3.3 直接要求分组，但 `sig_stream_reasoning=Signal(str)` 只带文本，槽位/阶段没接线程 | 新增带上下文的流式思考信号并全链接线：stages `_stream(slot)` → orchestrator → bridge `_append_thinking(slot,stage,章,text)` → QML |
| 3 | gateBar.doNext(idea) 与 ideaInput/consoleInput 焦点未闭环（【M3】） | §4 | v2 焦点表只盯 `consoleInput.activeFocus`，没删 ideaInput、没说 showGate() 聚焦谁、没删其 Keys 短路 | M3 明确移除 ideaInput：showGate() 聚焦 consoleInput，doNext(idea) 内部 resolve，删 StepGateBar L106-107 Keys 短路；焦点表单一以 consoleInput 为准 |
| 4 | ui_drive.py L86「必改」是误判（【M3】） | §6.3 | v2 把 `right-left>=1800 && bottom-top>=900` 当「必改」并对 app 几何下手 | 撤销必改要求：该常量是 `clear_occluders()` 对 `Chrome_WidgetWin_1` 全屏浏览器遮挡窗的启发式识别，与应用自身（Qt 窗口）无关；保持不动，仅加注释，绝不下调/改 app geometry |
| 5 | 24px 折叠带 vs 280–480 Console 常量自相矛盾（【M1/M3】) | §1.4/§6.1 | v2 全篇用「+24 整体平移」算 REGIONS，又写展开 280–480；M1 交付「可回看链的面板」不可能 24px | 定义折叠 24px / 展开 280px 两态、各给一套 REGIONS；M1=24px 折叠带+一键展开（展开后才可见链）；展开态按 +280 平移（非 +24），或两态分别校准 |
| 6 | 「阅读」按钮与 openReader() 默认态互相矛盾（【M3】） | §2.2/§8 | v2 点4 又说 openReader 默认全屏、又说阅读按钮默认 embedded，而阅读按钮正是调 openReader() | 定死入口：「阅读」按钮→`readerView.toEmbedded()`；`openReader(immersive=true)` 仅作全屏沉浸入口；openReader 按参数决定 parent 与 immersive |
| 7 | ui_regions「8 屏」数量臆造（【全plan】） | §6/§8 | v2 反复称「全部 8 屏」，实际 REGIONS 有 17 屏 | 「8 屏」替换为真实屏名清单（5 面板主屏+3 settings 标签+5 对话框+4 reader 沉浸=17）；M1 只平移主界面坐标、reader 沉浸坐标不受 24px 影响，两类分开列回归 |

> 说明：v2 已正确修复的 5/6（冗余 `sendAgentMessage` 分叉、L2 主线程同步写盘卡顿）不在本轮漏洞清单内，本版**保持 v2 修订结果不动**，仅在 §3/§2.3 保留其结论。

---

## 1. 目标与定位（保持 v2 已通过部分）

### 1.1 用户原话（必须逐字满足）
> “在现在工作流和阅读器的中间再加一个窗口，然后把阅读器的整体宽度放小，然后所有截断机制显示的 AI 的思考链和跟 Agent 的对话都在这个框里”

结合 Step Gates 决策门机制（产物摘要 + 想法输入 + 继续/回退）重新设计。背景：用户两轮表达「写作不透明」——AI 写的时候看不到它为什么这么写；想随时介入。本窗口即「中间共写窗口 Agent Console」，决策条输入框是其对话通道雏形。

### 1.2 硬约束（保持 v2 已通过部分，全部继承）
- 桌面 QML 应用，改动可实施、可回归（现有 18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 不能破）。
- 不破坏：5 面板导航、编辑器流式直播、StepGateBar 决策门、阅读器三主题/标注。
- 思考链必须**持久留存**（用户痛点：流式结束就没了），且区分槽位/阶段/章。
- 「跟 Agent 的对话」= 人的想法/指令 + Agent 的回应（产物摘要、决策结果）都出现在本窗口。
- 阅读器宽度放小 = 阅读器从全屏覆盖变为与流水线/主列并排或嵌入的收窄形态；全屏沉浸是已交付成熟功能，保留一键切换，不得砍掉。

### 1.3 三里程碑（保持 v2 已通过部分）
- **M1（思考链留存可见）**：把流式小条升级为常驻 Console 面板，思考链按槽位×阶段×章留存于 L1 内存环形缓冲，随结束不清空，可回看当前章。
- **M2（对话区 + 落盘）**：Console 增加对话区（人想法 + 门摘要 + Agent 回执 + 回退记录），会话内容落盘 pipeline_debug/console/。
- **M3（阅读器收窄 + 门合并）**：StepGateBar 合并为 Console 内「门状态条（Banner）」，保留 `gateBar` objectName 契约；阅读器从全屏覆盖改为右侧 embedded dock（默认），一键切全屏沉浸。

### 1.4 布局形态 【修订v3 · 漏洞 5】

**v2 的问题**：v2 §1.4/§6.1 用「整体 +24 平移」算 REGIONS（topbar 350→374 等），但 M3 又写 Console 展开 280–480；而 M1 交付物是「可回看当前章思考链的面板」——能显示思考链的面板不可能只有 24px 宽。若 M1 交付 24px 折叠占位则「思考链可见/可回看」落空，若交付 280px+ 面板则「+24 平移」算错（应为 +280，且折叠/展开两态 REGIONS 不同）。

**【修订v3】定义两态宽度，废除「+24」单一口径：**

```
:CONSOLE 两态（跨面板常驻中间列）:
  · 折叠态 fold        : 宽 24px   —— 常驻占位条（一个细窄把手图标，点击一键展开）
  · 展开态 expanded     : 宽 280px  —— 真正可见思考链/对话区/门 Banner 的 Console 面板
  （可调上限仍 280–480，但「默认折叠 → 展开为 280」是两态，折叠≠可见）
```

- **M1 交付物 = 24px 折叠带 + 一键展开的 Console（展开后宽 280px 才可见思考链）**。这样「可回看当前章」由展开态兑现，24px 折叠带只是进入入口，不与「面板能显示内容」自相矛盾。
- **坐标平移口径（两态分别校准，废除「整体 +24」）**：
  - **折叠态**：nav/panel 不动，`pipeline_default` 的 topbar 等主列坐标**整体 +24**（topbar x=350→374、editor-body x=352→376）。
  - **展开态**：主列坐标**整体 +280**（topbar x=350→630、editor-body x=352→632 等）。
  - **两态各给一套 REGIONS**（§6.1 展开态校准 + §6.3 新四/五列布局再改一次），不得用单一「+24」同时糊折叠与展开。
- **窗口宽度**：默认宽 1400→**1600**（min 仍 1080）。M1 阶段窗口仍 1400（仅引入 24px 折叠带）；M3 终态 1600 四/五列。

```
M3 终态 1600 宽（折叠/展开两种各可拍）：
┌──┬─────┬──────────┬─────────────┬──────────┐
│48│ 300 │ Console  │ 主编辑列     │ 阅读 dock │
│  │     │24/280     │(fill 剩余)  │ ~460     │
│  │     │(折叠/展开)│             │(embedded)│
└──┴─────┴──────────┴─────────────┴──────────┘
```

### 1.5 三块内容（保持 v2 已通过部分；阅读器口径按 §8）

三块内容 = 门状态条（M3 Banner）+ 对话区 + 思考链区，见 §3。阅读器「两种形态并存、各给一套矩形」按 §8（本版在 §8 修正为真实屏名清单，见漏洞 7）。

---

## 2. 布局与数据流（保持 v2 已通过部分，修订两处）

### 2.1 布局容器（保持 v2 已通过部分）
Main.qml 主布局：左 nav rail | panelStack | 右侧主编辑列。新增 `ConsoleDock`（跨面板常驻中间列，可折叠 24/280–480px）与 `ReaderDockHost`（右侧阅读 dock 宿主）。

### 2.2 阅读器嵌入机制 +「沉浸/常驻」可见性语义 【修订v3 · 漏洞 1 · 漏洞 6】

**v2 的问题（漏洞 1）**：v2 §2.2 点 3 要求 embedded 态「常态 opacity:1 常驻」，而现 ReaderView.qml 是 `visible: opacity > 0.01`（L17）+ `z:50`（L16）+ 初始 `opacity:0`（L18）。Main.qml 的全局快捷键用 `!readerView.visible`（F5, L74）与 `readerView.visible`（Escape/Left/Right, L79/84/89）来判「是否处于沉浸」。若 embedded 态 `opacity:1`，则 `visible = true` **恒为真** → F5 永禁用（无法切回全屏沉浸）；且 Escape/翻页在 dock 态常驻触发、抢焦点/翻页。**v2 没重定义 `visible` 语义，也没引入「沉浸覆盖层」与「dock 常驻」两个不同的可见性判据。**

**【修订v3】给 ReaderView 加独立 `property bool immersive`，与 `visible`（渲染可见性）解耦：**

```qml
// ReaderView.qml
property bool immersive: false     // true=沉浸覆盖层(全窗)  false=embedded dock 常驻
z: immersive ? 50 : 0              // 沉浸压制全窗；dock 态不压主列/导航
visible: immersive ? (opacity > 0.01) : (dockShown)   // 渲染可见性，不再兼任「沉浸状态」
opacity: 1                          // dock 态常态可视；沉浸态也 opacity:1
```

- **immersive 语义**：`immersive===true` ⇔ 沉浸覆盖层（全窗、z:50、抢 Escape/翻页/F5 对立面）；`immersive===false` ⇔ embedded dock 常驻窄列（不抢全局快捷键）。
- **Main.qml 全局快捷键全部改绑 `immersive`（漏洞 1 核心修法）：**
  ```qml
  Shortcut { sequence: "F5";      enabled: !readerView.immersive ... onActivated: mainWindow.openReader(/*immersive=*/true) }   // dock 态能 F5 进沉浸
  Shortcut { sequence: "Escape";  enabled: readerView.immersive; onActivated: readerView.close() }      // 仅沉浸态响应
  Shortcut { sequence: "Left";    enabled: readerView.immersive; onActivated: readerView.pageStep(-1) }  // 仅沉浸态响应
  Shortcut { sequence: "Right";   enabled: readerView.immersive; onActivated: readerView.pageStep(1) }
  ```
  dock 常驻态（immersive=false）下 Escape/翻页全局快捷键不触发，翻页交 dock 内自有的窄列控件/滚动；不再有「dock 常驻抢 Escape/翻页」。
- **anchors 不残留**：ReaderView 的 `anchors.fill: parent`（L15）是静态绑定关系表达式，重挂 parent 后自动重新填充新 parent（embedded→dockHost 窄列，fullscreen→contentItem 全窗），无需在切换代码里写 anchor 恢复。
- **入口分工（漏洞 6 定死）：**
  - Main.qml **「阅读」按钮**（L385-392，现调 `mainWindow.openReader()`）→ 默认改调 **`readerView.toEmbedded()`**（进 embedded dock）。
  - F5 / 工具栏「阅读」保留的**显式全屏沉浸入口** = `openReader(immersive=true)`（内部设 `readerView.immersive=true`、`readerView.parent=mainWindow.contentItem`）。
  - `mainWindow.openReader()` 保留为**兼容签名**，按参数决定 parent 与 immersive（无参时保持旧全屏语义，供既有测试 `win.openReader()` 复拍沉浸全屏用，见 §8）。
  - `ReaderView` 新增 `toEmbedded()`：设 `readerView.immersive=false`、`readerView.parent = dockHost`。
- **回归探针**：新增 `probe_reader_dock.py`，在进程内按 `embedded ↔ immersive ↔ embedded` 两轮切换，断言：`readerView.immersive`、`readerView.parent`、`readerView.z`（0↔50）、`anchors.fill` 目标随父级重算，且**三态下三条快捷键的 `enabled` 符合上表**（F5 仅 dock 态可用、Escape/翻页仅沉浸态可用），杜绝「dock 态 Eescape 抢焦/翻页」。

**后备方案 —— Loader（方案 a，仅在 parent 切换经同一组件树验证失败时启用）**
`ReaderDockHost` 内含 `Loader { id: readerLoader }`；embedded 态把 ReaderView 实例 `setSource` 到 Loader 下。退全屏时卸载会丢滚动位置，但阅读进度已由 `savePosition`/`readStore` 持久化（§7.4）。**默认不采用 Loader**（丢滚动 + 实例重建代价高于 parent 切换），且 `immersive` 语义在 Loader 下仍由属性维持。

### 2.3 L2 落盘与节流解耦（保持 v2 修订结果 · 漏洞 6 已修，本版不动）

v2 已正确修复「主线程同步写盘」：`_append_thinking` 只写 L1 内存 model（拼接+硬截断+入 ring buffer），不做任何 `open/write`；磁盘写交给独立 QTimer(1000ms) 合并批次，或移 worker 线程；章节结束/流水线结束刷一次 pending 队列。**本版保持此结论**（风险表见 §7.1）。

### 2.4 思考链信号管线（槽位×阶段×章） 【修订v3 · 漏洞 2 · 重点】

**v2 的问题**：v2 §3.3 直接要求「按 writing/helper/review 槽位 × 阶段 × 章 分组」，但现链路只有纯文本：
- `orchestrator.py:36 sig_stream_reasoning = Signal(str)` 只带文本；
- `bridge.py:1144 _on_stream_reasoning(text)` 只 `_reasoning_text += text`；
- `llm/client.py chat_stream` 的 `on_reasoning(r)` 回调（L251）无槽位/阶段上下文；
- `stages.py:121 _stream(ctx, slot, prompt, label)` 虽然**握着 `slot`**（`on_reasoning` 闭包在 L131-132 定义），但 `ctx.stream_reasoning(r)` 把它丢掉了。

**硬约束「区分槽位/阶段」在现状下无从谈起——必须把 slot/stage 从 llm client → orchestrator → bridge → QML 一路带上。**

**【修订v3】新增带上下文的流式思考信号并全链接线（采用评审修法 2 的「更丰富信号」主案）：**

```
（选主案 A：信号带 slot；备选 B：orchestrator current_stream_slot 属性）

--- 链路（从下游到上游，实际加 slot 处是 stages._stream） ---
① llm/client.py chat_stream(..., slot=None, on_reasoning=None)
   : `on_reasoning(r)` 回调增透传签名为 on_reasoning(slot, r)；本层不产 slot，仅把传入 slot 透传
② stages.py _stream(ctx, slot, prompt, label)
   : `def on_reasoning(r): ctx.stream_reasoning(slot, r)`   // slot 即本步槽位(writing/helper/review)，闭包持有
③ orchestrator.py
   : sig_stream_reasoning = Signal(str, str)   // (slot, text)  ← 主案 A；或保留 (str) + 加 sig_stream_slot
   : def stream_reasoning(self, slot, text): self.sig_stream_reasoning.emit(slot, text)
   : （备选 B）def current_stream_slot 随各槽位 `_stream` 调用前更新；stage 由既有 self._cur_step 承担（bridge 已有 _cur_step）
④ bridge.py
   : sig connect 改为 on(slot, text) → `_append_thinking(slot, self._cur_step, self._cur_num, text)`
   : _append_thinking(slot, stage, chapter, text)：以 (slot, stage, chapter) 作 L1 环形缓冲分组键，追加进 ConsoleListModel（120ms 节流）
   : L0 `reasoningText`/`_reasoning_text` 保持旧流式语义不清除（§5 兼容）
⑤ QML：Console 思考链区按 (slot × stage × 章) 折叠分组展示，硬截断 + 摘要/完整切换
```

- **slot 来源**：由执行当前步的槽位决定——`stages._stream(ctx, slot, ...)` 在增/细纲/裁剪/去味/审校等各步已显式传 `cfg_mod.SLOT_WRITING/SLOT_HELPER/SLOT_REVIEW`（stages.py L463/525/535/568 等真实存在）。`_stream` 内 `on_reasoning` 闭包恰好拿到该 slot，是这里最干净的加 slot 点，无需侵入每个 stage。
- **stage 来源**：orchestrator `self._cur_step`（L194，`step()` 时更新，随 `sig_step` 同步到 bridge `_cur_step`），即当前流水线阶段 key（A2/A3/B1/C1…C7）。
- **chapter 来源**：orchestrator `self._cur_num`（L193）；bridge `_cur_num` 已有。
- **M1 必须落地本管线**（思考链区需要槽位×阶段×章分组），非等 M3：M1 交付的 Console 思考链区就按这条管线展示。

---

## 3. 三块内容与对话通道（保持 v2 已通过部分）

### 3.1 门状态条（M3 合并 StepGateBar，保留 gateBar objectName 契约）
沿用 v2 已通过部分：M3 把编辑列下方的 StepGateBar 上移合并进 Console 顶部的「门状态条（Banner）」，保留 `gateBar` objectName，UI 探针与既有断言不受影响。门等待时显示：产物摘要 + 想法输入 + 继续/回退按钮。

### 3.2 对话区 + 输入框（保持 v2 修订结果 · 漏洞 5 已修，本版不动）
沿用 v2：废弃冗余 `sendAgentMessage`；唯一注入通道 = 既有 `bridge.submitIdeaScoped(text,'next')`，包薄壳 `_submit_from_console(text)` 只做「登录 + 入对话区」；门等待态走 `resolveStepGate('next', idea)`、非门态走 idea 队列，两条通道明确分工，不重复造队列（详见 v2 §3.2，本版不改）。

### 3.3 思考链区（按槽位×阶段×章分组）
沿用 v2 已通过部分 + 信号管线已在 §2.4 接线程：按 `writing / helper / review` 槽位 × 阶段（A2/A3/B1/C1…C7）× 章 分组，硬截断 + 摘要/完整切换。历史思考链持久留存（不停流式清空）。

### 3.4 输入框常驻快捷键契约
沿用 v2 已通过部分 + 按 §4 修订后的焦点互斥表（**输入框唯一化为 consoleInput**，见漏洞 3）。门等待：Enter=带想法继续 / Ctrl+Enter=直接继续 / R=回退；非门态：Enter=发消息给当前 Agent（`_submit_from_console`）。

---

## 4. M3 快捷键 / 焦点重接 【修订v3 · 漏洞 3 · 漏洞 7 之焦点】

**v2 的问题（漏洞 3）**：v2 §4 把全局 Shortcut 改成 `gateBar.doNext(consoleInput.text)`、焦点表只用 `consoleInput.activeFocus`，却没说明 **ideaInput 合并后删/留、showGate() 聚焦谁、ideaInput 的 Keys 短路是否移除**。现 StepGateBar.qml `doNext()` 无参（L38-42）读 `ideaInput.text`、`showGate()` 里 `ideaInput.forceActiveFocus()`（L35）、`ideaInput` 有 `Keys.onReturnPressed/onEnterPressed → doNext()`（L106-107）。M3 后若两个输入框并存，焦点可落 ideaInput 而焦点表只盯 consoleInput，v2 想防的「编辑器打字+门等待误触发继续」依然存在。

**【修订v3】M3 明确移除 ideaInput，输入框唯一化为 consoleInput：**

1. **删除 StepGateBar.qml `ideaInput`**（L91-108）：`showGate()` 不再 `ideaInput.forceActiveFocus()`；删 L106-107 `Keys.onReturnPressed/onEnterPressed` 短路——避免双 Enter 路径。
2. **doNext 扩展为可选 idea 参数**：`function doNext(idea) { ... bridge.resolveStepGate("next", idea === undefined ? consoleInput.text : idea); waiting=false }`——无论带参（全局 Shortcut）还是无参（门内按钮点击）都归一读 consoleInput 文本。
3. **showGate() 改聚焦 consoleInput**：门等待弹起时 `consoleInput.forceActiveFocus()`，单一焦点目标。
4. **焦点互斥表（M3 生效，单一判据 = consoleInput.activeFocus）：**

| 焦点态 | `consoleInput.activeFocus` | Return | Ctrl+Return | R | 说明 |
|--------|:--:|:--:|:--:|:--:|------|
| 门等待 + 编辑器聚焦 | false | ✅ doNext(consoleInput.text) | ✅ doNext("") | ✅ doReturn | 沿旧行为，读输入框文本 |
| 门等待 + 输入框聚焦 | true | ❌（交 consoleInput onAccepted） | ❌ | ❌ | Enter=提交消息，不误触发继续 |
| 门等待 + 全局失焦 | false | ✅ | ✅ | ✅ | 沿旧行为 |
| 非门态（任意焦点） | —— | 触发 consoleInput onAccepted（发消息） | 无 | 无 | 门未等，Shortcut 整体 disabled |

5. **三条全局 Shortcut 显式重写（含焦点互斥）：**
   ```qml
   Shortcut { sequence: "Return";     enabled: gateBar.waiting && !consoleInput.activeFocus
             onActivated: gateBar.doNext(consoleInput.text) }
   Shortcut { sequence: "Ctrl+Return"; enabled: gateBar.waiting && !consoleInput.activeFocus
             onActivated: gateBar.doNext("") }
   Shortcut { sequence: "R";           enabled: gateBar.waiting && gateBar.rollbackable && !consoleInput.activeFocus
             onActivated: gateBar.doReturn() }
   ```
   非门态三条整体 disabled（`gateBar.waiting` 为 false 即停用），Enter 由 consoleInput 自身 `onAccepted → _submit_from_console` 承担。
6. **离屏焦点态探针**：新增 `probe_console_focus.py`（或并入 probe_gate_ui），三类焦点态各一例：`consoleInput 聚焦` / `编辑器聚焦` / `全局失焦`，断言三条 Shortcut 的 enabled 与 onActivated 目标符合上表，防 M3 后误触发回归。

---

## 5. 数据流三层（保持 v2 已通过部分）
- **L0 旧 reasoningText 兼容**：`bridge.reasoningText` 保持流式语义（现有 UI/探针依赖），M1 后在其上叠加 L1 留存，不破坏既有契约。
- **L1 会话环形缓冲 ConsoleListModel**（120ms 节流、2000 条上限）：思考链、对话（👤/🤖）、门摘要、回退记录统一入列，**分组键 = (slot × stage × 章)**（§2.4）。
- **L2 按章落盘**（写入按 §2.3 解耦）：`pipeline_debug/console/ch<章>.md` + 追踪/决策记录.md。

---

## 6. 里程碑计划与回归 【修订v3 · 漏洞 3/4/5/7】

### 6.1 M1 —— 思考链留存可见 【修订v3 · 漏洞 5 · 漏洞 7】

任务：
1. **【修订v3】第 0 步：引入 24px 常驻折叠带 + 一键展开（展开态宽 280px），两态各校准 REGIONS**。新增 Console 折叠列后，立即重算 `ui_regions.py`：
   - **折叠态**：nav/panel 不动，`pipeline_default` 的 topbar `x=350→374`、editor-body `x=352→376` 等**整体 +24**（M1 基线）。
   - **展开态**：主列坐标**整体 +280**（topbar `x=350→630`、editor-body `x=352→632` 等），M1 交付「可回看当前章思考链」必须按展开态抓图校准。
   - 两态各一套 REGIONS，不得用单一「+24」糊折叠与展开。
2. **【修订v3】思考链信号管线落地（§2.4）**：Console 思考链区按槽位×阶段×章分组展示，L1 环形缓冲留存（结束不清空）。
3. 回归：
   - `probe_console_model`（L1 model 条目/分组键=slot×stage×章/上限 2000）
   - `probe_gate_*`（门不变）
   - `check_layout`（无越界）
   - **【修订v3】ui_regions（折叠+展开两态主界面屏，真实屏名清单见 §8）**：M1 交付后必须能按平移后的坐标抓出**所有主界面屏名**（`pipeline_default` / `notes` / `chapters` / `shelf` / `settings_conn` / `settings_writing` / `settings_appearance` / `settings_system`），少任一屏名即失败。reader 沉浸屏（`reader_night`/`reader_toc`/`reader_marks`/`reader_prefs`）为全窗覆盖层，**不受 24px 面板平移影响**，M1 不需改其坐标（与主界面屏分开列）。

### 6.2 M2 —— 对话区 + 落盘（保持 v2 已通过部分）
任务：
1. 对话区（👤/🤖/门摘要/回退记录）+ `_submit_from_console` 薄壳（v2 §3.2）。
2. L2 落盘解耦落地（v2 §2.3，独立 QTimer 合并批次）。
3. 回归：M1 全套 + **新 probe_console_model 断言对话区条目 + 落盘文件存在性与内容**。

### 6.3 M3 —— 阅读器收窄 + 门合并 【修订v3 · 漏洞 3 · 漏洞 4 · 漏洞 6 · 漏洞 7】

任务：
1. StepGateBar 合并为 Console 门状态条 Banner（保留 gateBar objectName）+ §4 焦点/快捷键重写（删 ideaInput、单一 consoleInput）。
2. **【修订v3】阅读器 embedded dock（§2.2 immersive parent 切换）+ 全屏沉浸保留（§8 双形态）+ 快捷键改绑 immersive（漏洞 1/6）**。
3. **【修订v3】撤销 ui_drive.py L86「必改」要求（漏洞 4）**：`right-left>=1800 && bottom-top>=900` 属 `clear_occluders()` 的遮挡窗启发式——识别并最小化**全屏浏览器遮挡窗**（class `Chrome_WidgetWin_1`），与应用自身窗口（Qt 窗口，不匹配该 class）**无关**。应用 1400→1600 后仍 <1800，永不触发该分支，**不存在 v2 所言的回归**。**保持 1800/900 不动，绝不照 v2「下调到 1080×900 或读 app geometry」改动**——那反而会把 1600 宽应用误判为遮挡窗直接最小化、破坏点击自动化。如需登记，仅在该行上方加一行注释「遮挡检测启发式：识别全屏浏览器窗，与 app 自身尺寸无关」。
4. **【修订v3】ui_drive 其余几何假设**：若 ui_drive 全窗口抓图/点击用到 1400 常量（与 app 自身相关者），按新 1600 宽重算；区分「app 几何」与「遮挡启发式常量」两类，后者不改。
5. **【修订v3】ui_regions 按新四/五列布局再改一次 + 两种 reader 形态**（§8：折叠/展开两态 + reader 沉浸 4 屏 + 新增 dock 形态）。
6. 回归：M2 全套 + `ui_drive`（保持遮挡启发式原值、仅 app 几何重算）+ `probe_reader_dock` + `probe_console_focus` + 双形态 reader ui_regions（真实屏名清单，少任一屏名即 fail）。

---

## 7. 风险与取舍

### 7.1 性能（保持 v2 修订结果）
- 打字机/滚动防卡：L1 delegate 轻量元素 + 120ms 节流（沿用 v2）。
- 主线程同步写盘（v2 已修）：`_append_thinking` 只写 L1；磁盘写独立 QTimer(1000ms) 合并批次 / 移 worker 线程；会话结束 flush。

### 7.2 兼容
- `reasoningText`（L0）、`gateBar` objectName、5 面板导航、阅读器三主题/标注/翻页路径保持兼容；18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 通过。
- **可见性语义变更（漏洞 1）**：`readerView.visible` 从「沉浸判据」降级为纯渲染可见性，沉浸判据改 `immersive`。对既有探针的影响：凡是代码用 `readerView.visible` 判沉浸态的（如测试/`win.openReader`），改为用 `readerView.immersive`；`visible` 在沉浸态仍为 true（opacity:1），行为不变。

### 7.3 阅读器形态
- 全屏沉浸是已交付成熟功能，**不砍**：M3 后默认 embedded dock（阅读按钮→toEmbedded），F5 保留显式全屏入口 `openReader(immersive=true)`；两种形态并存，回归双覆盖（§8）。

### 7.4 进度/位置
- embedded↔immersive 切换由 `savePosition`/`readStore` 持久化阅读进度，切态不丢（Loader 后备方案退全屏丢滚动也在可控范围）。

---

## 8. ReaderView 双形态与 ui_regions 口径 【修订v3 · 漏洞 2(口径)· 漏洞 7】

**v2 的问题（漏洞 7）**：v2 §6.1/§6.3/§8 反复称「全部 8 屏…少一端即失败」是臆造——`tests/ui_regions.py` REGIONS（L141-200）实有 **17 个屏名**（5 面板主屏 + 3 settings 标签 + 5 对话框 + 4 reader 沉浸）。且 v2 把「M1 只需平移的主界面屏」与「reader 全屏沉浸屏（不受 24px 影响）」混成一个「8 屏」。

**【修订v3】真实屏名清单（对照 ui_regions.py REGIONS，共 17 屏）：**

| 类别 | 屏名 | 现状矩形要点（1400 宽） |
|------|------|------|
| 5 面板主屏 | `pipeline_default` / `notes` / `chapters` / `shelf` / `settings_conn` | navrail(0,0,48,856)、topbar(350,2,1046,40)、editor-body(352,48,…) 等 |
| 3 settings 标签 | `settings_writing` / `settings_appearance` / `settings_system` | (50,52,296,820) |
| 5 对话框 | `dlg_versions` / `dlg_export` / `dlg_stats` / `dlg_unsaved` / `dlg_rewrite` | 各 dialog 部位 |
| 4 reader 沉浸 | `reader_night` / `reader_toc` / `reader_marks` / `reader_prefs` | reader-topbar(2,2,1396,50)、drawer(1102,56,294,788) 等 |

**两种 reader 形态并存，各给一套矩形：**
- **保留全屏沉浸测试入口**：`win.openReader()` 语义不变（全屏沉浸，reader 覆盖全窗，走 `immersive=true`）。这样 `win.openReader()` 复拍的就是**全屏沉浸**一屏，与旧坐标一致。
- **新增 embedded dock 形态**：`readerView.toEmbedded()` 进 dock 态；REGIONS **新增** dock 形态矩形（窄列 0~460）。

| 屏名 | 形态 | 矩形（1600 宽示意） | 说明 |
|------|------|------|------|
| `reader_night` / `reader_toc` / `reader_marks` / `reader_prefs` | 沉浸全屏 | reader-topbar(2,2,1596,50)、drawer(1102,56,494,788) 等（全窗坐标按 W/H 重算） | **保持现状全窗口坐标**，W/H 更新后按全窗重算 |
| `reader_night_dock`（新增） | embedded dock | reader-dock-topbar(1140,2,460,50)、reader-dock-bottom(1140,852,460,44) 等 | **新增 dock 形态，只覆盖 0~460 窄列** |

**W,H 口径：**
- M1 阶段窗口仍 1400：ui_regions 保持 W,H=1400 基准，仅对**主界面屏**执行折叠/展开两态平移（§6.1）。
- **M3 把 `W,H = 1400,900` 更新为 `1600, 940`**，所有**主界面 + 阅读器沉浸 4 屏 + 新增 dock 屏**成体系重算（nav/panel/console/editor + 右侧 reader dock 460 列）。
- **回归必加**：两种 reader 形态（沉浸全屏 4 屏 + embedded dock 新矩形）的 ui_regions **都能抓出全部屏名**——沉浸侧 `reader_night/toc/marks/prefs` + 主界面侧 5 面板/3 settings/5 dialog + dock 新增 `reader_night_dock`，**少任一屏名即失败**；不可再用「8 屏」概称。

---

## 9. 评审漏洞逐条回应 【修订v3】

> 每条先给**源码事实核验**，再给动作。7 条全部采纳。

**漏洞 1（【M3·重点】ReaderView 常驻 dock 与 F5/Escape/翻页冲突）—— 采纳。**
- 事实核验：Main.qml L72-91 用 `!readerView.visible`（F5,L74）+ `readerView.visible`（Escape/Left/Right,L79/84/89）；ReaderView.qml L16 `z:50`、L17 `visible: opacity>0.01`、L18 `opacity:0`。v2 点3「embedded 常态 opacity:1 常驻」⇒ `visible=true` 恒真 ⇒ F5 永禁用、Escape/翻页 dock 态抢焦。成立。
- 动作：给 ReaderView 加 `property bool immersive`；F5 改绑 `!immersive`、Escape/Left/Right 改绑 `immersive`；`visible` 只作渲染可见性、不再兼任沉浸判据（§2.2）。

**漏洞 2（【M1/M2·重点】思考链分组缺信号管线）—— 采纳。**
- 事实核验：orchestrator.py:36 `Signal(str)` 只带文本；bridge.py:1144 `_on_stream_reasoning(text)` 只累加文本；llm/client.py chat_stream `on_reasoning(r)`（L251）无槽位/阶段；stages.py:121 `_stream(ctx, slot,…)` 握着 slot 却在 L131-132 `on_reasoning→ctx.stream_reasoning(r)` 丢掉。硬约束分组无从谈起。成立。
- 动作：新增带上下文的流式思考信号并全链接线 `stages._stream(slot)` → `orchestrator.sig_stream_reasoning(slot,text)` → `bridge._append_thinking(slot, cur_step, cur_num, text)`（L1 分组键 = slot×stage×章）→ QML 折叠分组（§2.4）。M1 落地。

**漏洞 3（【M3】gateBar.doNext(idea) 与 ideaInput/consoleInput 焦点未闭环）—— 采纳。**
- 事实核验：StepGateBar.qml `doNext()` 无参读 `ideaInput.text`（L38-42）、`showGate()`→`ideaInput.forceActiveFocus()`（L35）、`ideaInput` Keys.onReturnPressed/onEnterPressed→doNext（L106-107）。v2 焦点表只盯 consoleInput，未删 ideaInput。成立。
- 动作：M3 删 ideaInput；`showGate()` 聚焦 consoleInput；`doNext(idea)` 内部 `resolve(action, idea ?? consoleInput.text)`；删 L106-107 Keys 短路；焦点互斥表单一以 consoleInput 为准（§4）。

**漏洞 4（【M3】ui_drive.py L86「必改」是误判）—— 采纳。**
- 事实核验：tests/ui_drive.py L86 `right-left>=1800 && bottom-top>=900` 在 `clear_occluders()` 里匹配 class `Chrome_WidgetWin_1`（全屏浏览器遮挡窗），与应用自身窗口（Qt，不匹配该 class）无关；应用 1400→1600 仍<1800 永不触发，无 v2 所言之回归。成立。
- 动作：**撤销对 ui_drive.py L86 的必改要求**；保持 1800/900 不动，绝不下调/改 app geometry；仅加注释「遮挡启发式，与 app 尺寸无关」；若 ui_drive 有 app 自身几何常量（非遮挡启发式）才按 1600 重算（§6.3）。

**漏洞 5（【M1/M3】24px 折叠带 vs 280–480 Console 常量自相矛盾）—— 采纳。**
- 事实核验：v2 §1.4/§6.1 用「+24 整体平移」，M3 又写 console 280–480；M1 交付「可回看链的面板」不可能 24px。两头都占。成立。
- 动作：定义折叠 24px / 展开 280px 两态、各给一套 REGIONS；M1=24px折叠带+一键展开（展开后 280px 才可见链）；展开态按 +280 平移（非 +24）或两态分别校准；废除「整体 +24」单一口径（§1.4/§6.1）。

**漏洞 6（【M3】「阅读」按钮与 openReader() 默认态矛盾）—— 采纳。**
- 事实核验：Main.qml L385-392「阅读」按钮调 `mainWindow.openReader()`；v2 §2.2 点4 既说 openReader 默认全屏、又说阅读按钮默认 embedded——同一入口两默认。成立。
- 动作：定死入口——「阅读」按钮默认调 `readerView.toEmbedded()`；`openReader(immersive=true)` 仅作全屏沉浸入口（F5/保留测试标准 `win.openReader()` 全屏语义）；openReader 按参数决定 parent 与 immersive（§2.2/§8）。

**漏洞 7（【全plan】ui_regions「8 屏」数量臆造）—— 采纳。**
- 事实核验：tests/ui_regions.py REGIONS 实际 **17 屏**（5 面板主屏 + 3 settings 标签 + 5 对话框 + 4 reader 沉浸），不是「8 屏」；且 M1 只需平移主界面屏、reader 全屏沉浸本不受 24px 影响，v2 把两类混成一个「8 屏」。成立。
- 动作：以真实屏名清单替换「8 屏」（§6.1 M1 列 8 个主界面屏名 + §6.3/§8 列全 17 屏 + 新增 dock 屏，少任一屏名即 fail）；明确 reader 沉浸屏坐标不受 24px 面板平移影响、dock 屏为新增矩形（§8）。

---

## 10. 待落地文件清单（修订后）

- `app/ui/qml/Main.qml`：24px 折叠带 + 一键展开（M1）、ConsoleDock/ReaderDockHost（M3）、`immersive` 快捷键改绑 F5/Escape/Left/Right（漏洞 1）、`openReader(immersive)` 入口定死 + 「阅读」→`toEmbedded()`（漏洞 6）、三条门 Shortcut 重写（漏洞 3）。
- `app/ui/qml/components/ReaderView.qml`：`property bool immersive` + `z: immersive?50:0` + 渲染可见性重定义（漏洞 1）；`toEmbedded()`/`open(immersive)` 入口。
- `app/ui/qml/components/StepGateBar.qml`：删 `ideaInput`（L91-108）+ Keys 短路（L106-107）；`showGate()` 聚焦 consoleInput；`doNext(idea)` 归一（漏洞 3）。**保留 `gateBar` objectName 契约。**
- `app/core/orchestrator.py`：`sig_stream_reasoning = Signal(str, str)`（slot,text）+ `stream_reasoning(slot,text)`（漏洞 2）。
- `app/core/stages.py`：`_stream` 内 `on_reasoning(r)→ctx.stream_reasoning(slot, r)`（漏洞 2）。
- `app/llm/client.py`：`chat_stream(..., slot=None)` + `on_reasoning(slot, r)` 透传（漏洞 2）。
- `app/ui/bridge.py`：`_append_thinking(slot, stage, chapter, text)`（L1 分组键）+ 对话薄壳 `_submit_from_console`（M2，v2 已定）+ L1/L2 解耦 + L2 QTimer 合并写盘（M2，v2 已定）。
- `tests/ui_regions.py`：M1 折叠/展开两态主界面屏平移（§6.1）；M3 W/H=1600,940 重算 + 全 17 屏 + 新增 `reader_night_dock` 矩形（§8，漏洞 7）。
- `tests/ui_drive.py`：**保持 L86 遮挡启发式常量不动**，仅加注释 + 若存在 app 自身几何常量按 1600 重算（漏洞 4）。
- `tests/probe_reader_dock.py`（新）：immersive/parent/z/anchors + 三态快捷键 enabled（漏洞 1/6）。
- `tests/probe_console_focus.py`（新）：consoleInput 聚焦/编辑器聚焦/全局失焦三态（漏洞 3）。
- `tests/probe_console_model.py`（新/扩）：L1 分组键（slot×stage×章）+ 对话区 + 落盘（漏洞 2）。

---

**第二轮修订完成。** 本轮 7 处漏洞全部采纳并逐条回应；每条都先做源码事实核验再给动作，纠正了 v2 中「未真读文件」的三处误判（ui_drive L86 遮挡启发式、REGIONS「8 屏」实为 17 屏、+24 单口径）。已通过部分（三里程碑、三块内容、三层数据流、输入框契约、sendAgentMessage 废弃、L2 落盘解耦）保持不动。完整方案保存于 `docs/plan_agent_console_v3.md`。
