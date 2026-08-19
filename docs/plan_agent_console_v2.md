# Agent Console v2 — 中间共写窗口（修订版）

> 本文件为 `plan_agent_console_v1.md` 的修订版。**修订原则：已通过部分保持不动，只改评审漏洞清单点名的 7 处问题**；其余架构（跨面板中间列、三块内容、三层数据流、输入框常驻、三里程碑）沿用原方案。修订点以「【修订】」标注，并在文末《评审漏洞逐条回应》中逐条说明。

## 0. 修订摘要

| # | 评审漏洞 | 本节 | 修订动作 |
|---|---------|------|---------|
| 1 | M3 用 AnchorChanges 锚进 dockHost 不可落地 | §2.2 | 改为**运行时 parent 切换**（主方案）+ Loader 后备方案，明确重挂后 anchors/z/opacity 重算策略 |
| 2 | ui_regions 阅读器区域口径自相矛盾 | §1.5/§8 | 明确**两种 reader 形态各拍一屏**（沉浸全屏 + embedded dock），REGIONS 各给一套矩形 |
| 3 | M1 引入 24px 折叠列但 ui_regions 更新挂在 M3 | §1.4/§6 | ui_regions 坐标更新**挂进 M1 第 0 步**，措辞改为「无越界、坐标整体平移」 |
| 4 | 默认宽 1400→1600 影响 ui_drive 常量未点名 | §6 | ui_drive.py **列为 M3 必改文件**，改用真实 geometry / 放宽屏幕判定，加进回归 |
| 5 | M2 臆造冗余 sendAgentMessage 分叉 | §3.2 | **废弃 sendAgentMessage**，复用 submitIdeaScoped，薄壳 `_submit_from_console` 就挂登录 |
| 6 | L2 按章落盘是主线程同步写，未列卡顿风险 | §2.3/§7 | `_append_thinking` 只写 L1 内存 model；磁盘写移独立 QTimer 合并批次；风险表加「主线程同步写盘」条目 |
| 7 | M3 快捷键/焦点重接不完整 | §4/§7.5 | 三条全局 Shortcut 显式重写 enabled 表达式，补离屏焦点态探针 |

---

## 1. 目标与定位（保持原方案）

### 1.1 用户原话（必须逐字满足）
> “在现在工作流和阅读器的中间再加一个窗口，然后把阅读器的整体宽度放小，然后所有截断机制显示的 AI 的思考链和跟 Agent 的对话都在这个框里”

结合 Step Gates 决策门机制（产物摘要 + 想法输入 + 继续/回退）重新设计。背景：用户两轮表达「写作不透明」——AI 写的时候看不到它为什么这么写；想随时介入。本窗口即「中间共写窗口 Agent Console」，决策条输入框是其对话通道雏形。

### 1.2 硬约束（保持原方案，全部继承）
- 桌面 QML 应用，改动可实施、可回归（现有 18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 不能破）。
- 不破坏：5 面板导航、编辑器流式直播、StepGateBar 决策门、阅读器三主题/标注。
- 思考链必须**持久留存**（用户痛点：流式结束就没了），且区分槽位/阶段。
- 「跟 Agent 的对话」= 人的想法/指令 + Agent 的回应（产物摘要、决策结果）都出现在本窗口。
- 阅读器宽度放小 = 阅读器从全屏覆盖变为与流水线/主列并排或嵌入的收窄形态；全屏沉浸是已交付成熟功能，保留一键切换，不得砍掉。

### 1.3 三里程碑（保持原方案）
- **M1（思考链留存可见）**：把流式小条升级为常驻 Console 面板，思考链按槽位×阶段留存于 L1 内存环形缓冲，随结束不清空，可回看当前章。
- **M2（对话区 + 落盘）**：Console 增加对话区（人想法 + 门摘要 + Agent 回执 + 回退记录），会话内容落盘 pipeline_debug/console/。
- **M3（阅读器收窄 + 门合并）**：StepGateBar 合并为 Console 内「门状态条（Banner）」，保留 `gateBar` objectName 契约；阅读器从全屏覆盖改为右侧 embedded dock（默认），一键切全屏沉浸。

### 1.4 布局形态（保持原方案，措辞已修订）
窗口默认宽 1400→**1600**（min 仍 1080）。最终形态是跨面板常驻中间列 + 右侧阅读器 dock：

```
1600 宽（M3 终态，四/五列）：
┌──┬─────┬──────────┬─────────────┬──────────┐
│48│ 300 │ Console  │ 主编辑列     │ 阅读 dock │
│nav│panel│280–480   │(fill 剩余)   │ ~460     │
│  │stack│(默认折叠→)│             │(embedded)│
└──┴─────┴──────────┴─────────────┴──────────┘
```

- **M1 第 0 步**：在左侧 panel 与主编辑列之间**引入 24px 常驻折叠带**（默认折叠态的 Console 占位）。这句话不是「几何零变化」——它会让默认屏**所有 x 坐标整体右移 24**（nav/panel 不动，Console 折叠带 +24，此后 editor 系全部 +24）。正确表述：**无越界、坐标整体平移 +24**。

### 1.5 三块内容（保持原方案；按本文 §8 修订阅读器口径）

**【修订】阅读器口径：M3 不是「零改动→reader 系列不出新坐标」，而是「两种 reader 形态并存、各给一套 REGIONS 矩形」，详见 §8。** 其余两块内容（门状态条、对话区、思考链区）沿用原方案：见 §3。

---

## 2. 布局与数据流（保持原方案，修订两处）

### 2.1 布局容器（保持原方案）
Main.qml 主布局：左 nav rail | panelStack | 右侧主编辑列。新增 `ConsoleDock`（跨面板常驻中间列，可折叠 280–480px）与 `ReaderDockHost`（右侧阅读 dock 宿主）。

### 2.2 阅读器嵌入机制 【修订 · 漏洞 1】

**原方案（错误）**：§1.5/§2.2 计划用单个 ReaderView 实例 + States + `AnchorChanges` 把它「锚进 dockHost」。**此写法不可落地**：`AnchorChanges` 只能在**同一 parent 内**改锚点/宽高，无法把 ReaderView 从 `ApplicationWindow.contentItem`（现 Main.qml 第 836 行最后子项，ReaderView.qml 内部 `anchors.fill: parent` + `z:50` + `visible: opacity>0.01`）重挂到右侧 RowLayout 的 dockHost 下——**重挂父级必须动态 `parent =` 或换 Loader**。

**【修订】主方案 —— 运行时 parent 切换（方案 b）**

```
ReaderDockHost（右侧 dock，宽 ~460）:
  Rectangle { id: dockHost }
ReaderView { id: readerView }   // 仍是单实例，Main.qml 顶层声明

Main.qml 状态切换（M3）：
embedded : readerView.parent = dockHost     // 填充 0~460 窄列
fullscreen: readerView.parent = mainWindow.contentItem  // anchors.fill + z:50 覆盖层
```

**重挂后 anchors/z/opacity 恢复策略（必须写死，避免残留）：**

1. **anchors 不残留**：ReaderView.qml 的 `anchors.fill: parent` 是**静态绑定的关系表达式**，重挂 parent 后它会自动重新填充**新 parent**——embedded 填 dockHost（窄列），fullscreen 填 contentItem（全窗）。**无需在 gap 里写 anchor 组合恢复代码**，只要不改成一次性赋值即可。
2. **z 必须随状态分支**：ReaderView.qml 把内部 `z` 从硬编码 `50` 改为可绑定属性：
   ```qml
   property bool fullscreen: false
   z: fullscreen ? 50 : 0
   ```
   embedded 时 `z:0`（靠 dockHost 内的兄弟 z 序即可，不压到主列/导航）；fullscreen 时 `z:50`（覆盖全窗）。
3. **opacity/visible 恢复**：ReaderView 用 `visible: opacity > 0.01`。embedded 态常态 `opacity:1`（常驻）；fullscreen 用一次性 `opacity:1` + `z:50` 覆盖。切回 embedded 时 `opacity` 回 1、`z` 回 0，靠 dockHost 宽度约束收窄，不要用 opacity:0 隐藏（dock 态需要常驻显示）。
4. **入口分工**：Main.qml `openReader()` 保留为**全屏沉浸默认入口**（`win.openReader()` 走的路径不变，见 §8）；新增 `readerView.toEmbedded()` 把 parent 切到 dockHost（M3 后「阅读」按钮默认走 embedded，F5/工具栏「阅读」仍需一个显式 `openReader(embedded=false)` 全屏入口以保测试与用户可选）。
5. **回归探针**：新增 `probe_reader_dock.py`，在进程内按 `embedded ↔ fullscreen ↔ embedded` 两轮切换，断言 `readerView.parent`、`readerView.z`、`readerView.anchors.fill` 目标随父级正确重算，且两态下 reader 内容仍可读（进度由 `savePosition`/`readStore` 持久化，见 §7.4）。

**后备方案 —— Loader（方案 a，仅在 parent 切换经同一组件树验证失败时启用）**
`ReaderDockHost` 内含 `Loader { id: readerLoader }`；embedded 态把 ReaderView 实例 `setSource` 到 Loader 下。退全屏时卸载会丢滚动位置，但阅读进度已由 `savePosition`/`readStore` 持久化，符合 §7.4 底线。**默认不采用 Loader**（丢滚动 + 实例重建代价高于 parent 切换）。

### 2.3 L2 落盘与节流解耦 【修订 · 漏洞 6】

**原方案（错误）**：§7.1 只提 QML delegate/120ms 节流防刷 UI，漏了 L2 主线程同步文件写卡顿：流式最密时每 120ms 在 `_append_thinking` 里做硬截断 + 拼接 + 写 `pipeline_debug/console/ch<章>.md`，这是**桥槽在 Qt 主线程上的阻塞 IO**；单阶段十几万字链时每次节流 tick 的写盘 + append 会造成打字机/滚动同步卡。

**【修订】写入链路两级解耦：**

```
L1（内存，快）  ← _append_thinking 只做：拼接 + 硬截断 + 追加进 ConsoleListModel（120ms 节流）
L2（磁盘，合并批量） ← 独立 QTimer(1000ms) 定时 trigger：
       把该 QTimer 周期内攒下的多条 delta 合并成一段，一次性 append 写文件一次
```

- `_append_thinking` **只写 L1 内存 model**（拼接 + 硬截断 + 入 ring buffer），不做任何 `open/write`。
- 磁盘写交给一个**独立 QTimer（1000ms）**：攒批合并，把 120ms 内的多条 delta 写成一段，一秒最多一次写盘；或把 MD 追加搬进 orchestrator 线程的 worker（异步不阻塞主线程）。二选一，M2 落地。
- §7 风险表新增条目：**「主线程同步写盘」→ 缓解：L2 独立 QTimer 合并批次 / 移 worker 线程；`_append_thinking` 只写 L1**。
- 章节结束/流水线结束（现 `_on_chapter_done`/`_on_finished`）时**刷一次 pending 队列**，保证 `ch<章>.md` 完整落盘，不留半段。

---

## 3. 三块内容与对话通道（保持原方案，修订漏洞 5）

### 3.1 门状态条（M3 合并 StepGateBar，保留 gateBar objectName 契约）
沿用原方案：M3 把编辑列下方的 StepGateBar 上移合并进 Console 顶部的「门状态条（Banner）」，保留 `gateBar` objectName，UI 探针与既有断言不受影响。门等待时显示：产物摘要 + 想法输入 + 继续/回退按钮。

### 3.2 对话区 + 输入框 【修订 · 漏洞 5】

**废弃冗余 `sendAgentMessage`。** 原方案 §3.2 新增 `sendAgentMessage` 再开一条「入想法队列」的槽，与既有 `submitIdeaScoped(text, scope)`（bridge.py L804–818，走 `st.add_idea`/`take_ideas` 同一条队列，state.py 真实存在）变成**两条平行注入路径**，后续注入逻辑会分叉。

**【修订】唯一注入通道 + 薄壳登录：**

- 「发消息给 Agent」**直接调用既有** `bridge.submitIdeaScoped(text, 'next')`（或 `submitIdea`），**不新建队列槽**。
- 在 bridge 层包一个**薄壳** `_submit_from_console(text, scope)`：内部先走 `submitIdeaScoped`（同一 add_idea 队列），成功后在对话区落一条 `👤 人` 消息并追加进 consoleModel / L2 记录。**对话区的进出登录全部挂在这个薄壳上**，逻辑单一、不重复造队列。
- **门等待态**仍走 `resolveStepGate('next', idea)`（真回执，返回产物摘要/决策结果进对话区）；**非门态**走 `_submit_from_console`（进入想法队列，等待后续注入）。两条通道明确分工：门态→resolve、非门态→idea 队列，中间层仅登录不做第二队列。

### 3.3 思考链区（按槽位×阶段×章分组）
沿用原方案：按 `writing / helper / review` 槽位 × 阶段（A2/A3/B1/C1…C7）× 章 分组，硬截断 + 摘要/完整切换。历史思考链持久留存（不停流式清空）。

### 3.4 输入框常驻快捷键契约
沿用原方案 + 按 §4 修订后的焦点互斥表。门等待：Enter=带想法继续 / Ctrl+Enter=直接继续 / R=回退；非门态：Enter=发消息给当前 Agent（`_submit_from_console`）。

---

## 4. M3 快捷键 / 焦点重接 【修订 · 漏洞 7】

**原方案（不完整）**：现 Main.qml L551–565 三条 Shortcut `Return / Ctrl+Return / R` 短路直接 `gateBar.doNext()/doReturn()` 且只判 `gateBar.waiting`。M3 后 gateBar 成 Banner、且要读 Console 输入框文本（新增 `consoleInput`），若短路条件不按焦点互斥重写，会出现「编辑器里打字 + 门同时在等」时误触发继续。

**【修订】三条全局 Shortcut 显式重写（含焦点互斥表）：**

```qml
// —— M3 后 ——
item: consoleInput  // id 归属：Console 对话区输入框
Shortcut {
    sequence: "Return"
    enabled: gateBar.waiting && !consoleInput.activeFocus
    onActivated: gateBar.doNext(consoleInput.text)   // 门等待 + 输入框失焦 → 带想法继续
}
Shortcut {
    sequence: "Ctrl+Return"
    enabled: gateBar.waiting && !consoleInput.activeFocus
    onActivated: gateBar.doNext("")                  // 门等待 + 输入框失焦 → 忽略输入直接继续
}
Shortcut {
    sequence: "R"
    enabled: gateBar.waiting && gateBar.rollbackable && !consoleInput.activeFocus
    onActivated: gateBar.doReturn()
}
```

**焦点互斥表（M3 生效）：**

| 焦点态 | `consoleInput.activeFocus` | Return | Ctrl+Return | R | 说明 |
|--------|:--:|:--:|:--:|:--:|------|
| 门等待 + 编辑器聚焦 | false | ✅ doNext(text) | ✅ doNext("") | ✅ doReturn | 沿旧行为，读输入框文本 |
| 门等待 + 输入框聚焦 | true | ❌（交输入框 onAccepted） | ❌ | ❌ | Enter=提交消息，不误触发继续 |
| 门等待 + 全局失焦 | false | ✅ | ✅ | ✅ | 沿旧行为 |
| 非门态（任意焦点） | —— | 触发输入框 onAccepted（发消息） | 无 | 无 | 门未等，Shortcut 整体 disabled |

- `gateBar.doNext` 扩展为可选 `idea` 参数，默认空串（保持既有调用兼容）。
- **离屏焦点态探针**：新增 `probe_console_focus.py`（或并入 probe_gate_ui），三类焦点态各一例：`consoleInput 聚焦` / `编辑器聚焦` / `全局失焦`，断言三条 Shortcut 的 enabled 与 onActivated 目标符合上表，防 M3 后误触发回归。

---

## 5. 数据流三层（保持原方案）
- **L0 旧 reasoningText 兼容**：`bridge.reasoningText` 保持流式语义（现有 UI/探针依赖），M1 后在其上叠加 L1 留存，不破坏既有契约。
- **L1 会话环形缓冲 ConsoleListModel**（120ms 节流、2000 条上限）：思考链、对话（👤/🤖）、门摘要、回退记录统一入列。
- **L2 按章落盘**（写入按 §2.3 解耦）：`pipeline_debug/console/ch<章>.md` + 追踪/决策记录.md。

---

## 6. 里程碑计划与回归（修订漏洞 3、4）

### 6.1 M1 —— 思考链留存可见

任务：
1. **【修订】第 0 步：引入 24px 常驻折叠带 + ui_regions 坐标平移**。新增 24px Console 折叠列后，立即重算 `ui_regions.py` REGIONS 的 x 偏移：nav/panel 不动，`pipeline_default` 的 topbar `x=350→374`、editor-body `x=352→376` 等**整体 +24**，补齐 M1 基线。**这是 M1 强制项，不等 M3。**
2. Console 面板 + 思考链区按槽位×阶段分组，L1 环形缓冲留存（结束不清空）。
3. 回归：
   - `probe_console_model`（L1 model 条目/分组/上限）
   - `probe_gate_*`（门不变）
   - `check_layout`（无越界）
   - **【修订】ui_regions（8 屏）**：M1 交付后必须能按平移后的坐标抓出全部 8 屏部位（本轮读一遍 REGIONS 断言覆盖）。

### 6.2 M2 —— 对话区 + 落盘

任务：
1. 对话区（👤/🤖/门摘要/回退记录）+ `_submit_from_console` 薄壳（§3.2）。
2. L2 落盘解耦落地（§2.3，独立 QTimer 合并批次）。
3. 回归：M1 全套 + **新 probe_console_model 断言对话区条目 + 落盘文件存在性与内容**。

### 6.3 M3 —— 阅读器收窄 + 门合并

任务：
1. StepGateBar 合并为 Console 门状态条 Banner（保留 gateBar objectName）。
2. 阅读器 embedded dock（§2.2 parent 切换）+ 全屏沉浸保留（§8 双形态）。
3. 三条全局 Shortcut 按 §4 重写 + `probe_console_focus.py`。
4. **【修订】ui_drive.py 列为必改文件（漏洞 4）**：M3 后默认宽 1600，`ui_drive.py` L86 的 `right-left>=1800 && bottom-top>=900` 判定与全窗口抓图几何假设需同步。改成**读取窗口实例真实 geometry**（`win.property('width')` / `height`）或把屏幕判定下限下调到 `1080×900`。**未改则直接红，列为 M3 强制项不加省略。**
5. **【修订】ui_regions 按新四/五列布局再改一次 + 两种 reader 形态**（§8）。
6. 回归：M2 全套 + `ui_drive`（含新版窗口判定）+ `probe_reader_dock` + `probe_console_focus` + 双形态 reader ui_regions。

---

## 7. 风险与取舍

### 7.1 性能（修订）
- 打字机/滚动防卡：**L1 delegate 用轻量元素 + 120ms 节流（沿用原方案）**。
- **【修订】主线程同步写盘**：`_append_thinking` 只写 L1 内存 model；磁盘写移独立 QTimer(1000ms) 合并批次 / 移 worker 线程（§2.3）。会话结束 flush 一次（§2.3）。

### 7.2 兼容
- `reasoningText`（L0）、`gateBar` objectName、5 面板导航、阅读器三主题/标注/翻页路径保持兼容；18/18 断言 + 冒烟 + 门 4/4 + UI 探针 8/8 通过。

### 7.3 阅读器形态
- 全屏沉浸是已交付成熟功能，**不砍**：M3 后默认 embedded dock，F5/工具栏保留显式全屏入口 `openReader(embedded=false)`；两种形态并存，回归双覆盖（§8）。

### 7.4 进度/位置
- embedded↔fullscreen 切换由 `savePosition`/`readStore` 持久化阅读进度，切态不丢（Loader 后备方案退全屏丢滚动也在可控范围）。

---

## 8. ReaderView 双形态与 ui_regions 口径 【修订 · 漏洞 2】

**原方案（自相矛盾）**：§1.5 声称三主题/标注/翻页路径「零改动→reader 系列截图仍可复拍」，§8 又写「reader 系列改 dock 尺寸」。M3 后 F5/「阅读」默认走 embedded dock，而 `ui_regions.py` 的 `reader_night/toc/marks/prefs` 走 `win.openReader()` **全屏抓全窗口**（topbar x=2 宽 1396、drawer x=1102）。到底拍沉浸全屏还是 460px dock 未定，把 8 屏审计直接悬空。

**【修订】两种 reader 形态并存，各给一套矩形：**

- **保留全屏沉浸测试入口**：`win.openReader()` 语义不变（全屏沉浸，reader 覆盖全窗）；另加显式 `readerView.openEmbedded()` 进 embedded dock 态。这样 `win.openReader()` 复拍的就是**全屏沉浸**一屏，与旧坐标一致。
- **REGIONS 按两种形态各给一套**：

| 屏名 | 形态 | 矩形（1600 宽示意） | 说明 |
|------|------|------|------|
| `reader_night` | 沉浸全屏 | `reader-topbar (2,2,1596,50)`、`reader-chip (2,58,260,38)`、`reader-bottom (2,852,1596,44)` | **保持现状全窗口坐标**（W/H 更新后按全窗重算） |
| `reader_toc / reader_marks / reader_prefs` | 沉浸全屏 | drawer `(1102,56,494,788)` 等（全窗坐标按 W/H 重算） | 保持现状 |
| `reader_night_dock` | embedded dock | topbar 只覆盖窄列，如 `reader-dock-topbar (1140,2,460,50)`、`reader-dock-bottom (1140,852,460,44)` | **新增 dock 形态，topbar 只覆盖 0~460 窄列** |

- **W,H 口径**：M1 阶段窗口仍 1400（ui_regions 保持 1400，仅执行 +24 平移）；**M3 把 `W,H = 1400,900` 更新为 `1600, 940`，所有矩形成体系重算**（nav/panel/console/editor 四列 + 右侧 reader dock 460 列）。
- **M3 回归必加一条**：两种 reader 形态（沉浸全屏 + embedded dock）的 ui_regions **都能抓出全部 8 屏部位**（各 reader 屏 + 主界面屏），少一端即失败。

---

## 9. 评审漏洞逐条回应

**漏洞 1（M3 核心机制不可落地）**：采纳。不再用 `AnchorChanges` 锚进 dockHost；改为运行时 `readerView.parent = dockHost` ↔ `readerView.parent = mainWindow.contentItem` 单实例切换（§2.2 主方案），并明确 `anchors.fill: parent` 为静态关系表达式自动重算、`z` 改为 `fullscreen ? 50 : 0`、opacity/visible 按态恢复、入口分工与 `probe_reader_dock` 回归。Loader 作后备（§2.2 方案 a）。

**漏洞 2（ui_regions 阅读器区域自相矛盾）**：采纳。§8 把阅读器口径改为「两种形态并存、各给一套矩形」：沉浸全屏屏名沿用旧坐标（`win.openReader()` 复拍全屏沉浸），另增 embedded dock 形态屏名与窄列矩形；REGIONS 按 W/H 重算，M3 回归双形态 8 屏全覆盖。

**漏洞 3（M1 就引入 24px 折叠列但 ui_regions 更新只挂在 M3）**：采纳。ui_regions 坐标平移**挂进 M1 第 0 步**（topbar x=350→374、editor-body 等整体 +24），措辞改成「无越界、坐标整体平移」（§1.4/§6.1）。M3 再按新四列布局改一次。

**漏洞 4（默认宽 1400→1600 影响 ui_drive 常量）**：采纳。ui_drive.py 列为 M3 **必改文件**：读窗口真实 geometry 或把屏幕判定下限下调到 1080×900；加进 M3 回归清单（§6.3）。

**漏洞 5（M2 臆造冗余 sendAgentMessage 分叉）**：采纳。废弃 `sendAgentMessage`；直接复用 `bridge.submitIdeaScoped(text,'next')`，包薄壳 `_submit_from_console` 只做「登录 + 入对话区」，门态 `resolveStepGate`、非门态 idea 队列，两条通道明确分工、不重复造队列（§3.2）。

**漏洞 6（L2 按章落盘是主线程同步文件写，未列入卡顿风险）**：采纳。`_append_thinking` 只写 L1 内存 model（快）；磁盘写移独立 QTimer(1000ms) 合并批次 / 移 worker 线程；§7 风险表新增「主线程同步写盘」条目与缓解；会话结束 flush（§2.3/§7.1）。

**漏洞 7（M3 快捷键/焦点重接不完整）**：采纳。三条全局 Shortcut 显式重写 bounds 表达式（§4），含焦点互斥表与离屏焦点态探针 `probe_console_focus.py`，覆盖输入框聚焦 / 编辑器聚焦 / 失焦三态，防 `activeFocus` 误触发。

---

## 10. 待落地文件清单（修订后）
- `app/ui/qml/Main.qml`：24px 折叠带（M1）、ConsoleDock/ReaderDockHost（M3）、parent 切换、三条 Shortcut 重写（M3）。
- `app/ui/qml/components/ReaderView.qml`：`z` 改可绑定 `fullscreen ? 50 : 0`；`openEmbedded()`/全屏入口。
- `app/ui/bridge.py`：`_submit_from_console` 薄壳（M2）、L1/L2 解耦 + L2 QTimer 合并写盘（M2）、`gateBar.doNext(idea)` 配合。
- `tests/ui_regions.py`：M1 平移 +24（第 0 步）；M3 W/H 重算 + 双 reader 形态矩形。
- `tests/ui_drive.py`：M3 窗口判定改真实 geometry / 放宽到 1080×900。
- `tests/probe_console_focus.py`（新）、`tests/probe_reader_dock.py`（新）、`tests/probe_console_model.py`（新/扩）。
