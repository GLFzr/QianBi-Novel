# Agent Console M3 设计文档 —— 阅读器收窄 + 门合并（仅设计，实施另期）

> 状态：**设计定稿，待排期实施**。上游依据：`docs/plan_agent_console_v3.md` §1.4/§2.2/§4/§6.3/§8（第二轮修订版，7 处评审漏洞已收口）。
> 前置：M1（思考链留存）+ M2（对话区+落盘）已交付（提交 8f9b0d4）。
> 范围红线：M3 不改共享层（app/core|llm|prompts|presets），仅动 `app/ui`、`bridge.py` UI 侧接线、`tests/` 探针与几何基线——不触发双端同步。

---

## 1. 阅读器双形态（embedded dock + 全屏沉浸）

### 1.1 目标形态

主窗 1600 宽四列布局，阅读器默认收窄为右侧 ~460px embedded dock，全屏沉浸作为显式入口保留：

```
┌──┬─────┬──────────┬─────────────┬──────────┐
│48│ 300 │ Console  │ 主编辑列     │ 阅读 dock │
│nav│panel│24/280    │(fill 剩余)  │ ~460     │
│  │     │(折叠/展开)│             │(embedded)│
└──┴─────┴──────────┴─────────────┴──────────┘
```

### 1.2 可见性语义重构（核心修法）

现状问题（`app/ui/qml/components/ReaderView.qml` L15-18）：`anchors.fill: parent` + `z: 50` + `visible: opacity > 0.01`，而 `Main.qml` 用 `readerView.visible` 判沉浸（F5 L90、Escape/Left/Right L95/100/105）。dock 态若常驻可见，`visible` 恒真 → F5 永禁用、Escape/翻页在 dock 态抢焦。

修法：引入独立 `property bool immersive`，与渲染可见性解耦：

```qml
// ReaderView.qml
property bool immersive: false     // true=沉浸覆盖层(全窗)  false=embedded dock 常驻
z: immersive ? 50 : 0
visible: immersive ? (opacity > 0.01) : dockShown
opacity: 1                          // dock 态常态可视
```

- `immersive===true` ⇔ 全窗覆盖、z:50、抢 Escape/翻页，F5 为对立面；
- `immersive===false` ⇔ dock 窄列常驻，不抢全局快捷键，翻页交 dock 内控件。

### 1.3 入口与快捷键改绑

| 入口 | 现状 | M3 后 |
|---|---|---|
| 工具栏「阅读」按钮（Main.qml L417） | `mainWindow.openReader()` 全屏 | `readerView.toEmbedded()`（进 dock） |
| F5（Main.qml L88-91） | `enabled: !readerView.visible` | `enabled: !readerView.immersive` → `openReader(immersive=true)` |
| Escape/Left/Right（L93-106） | `enabled: readerView.visible` | `enabled: readerView.immersive` |
| `mainWindow.openReader()`（L64） | 全屏语义 | 保留为兼容签名：无参=全屏沉浸（供既有探针复拍），带参决定 parent/immersive |

新增 `ReaderView.toEmbedded()`：设 `immersive=false`、`parent=dockHost`（anchors.fill 为绑定表达式，重挂 parent 自动重算，无需手写 anchor 恢复）。后备方案 Loader（v3 §2.2 方案 a）仅在 parent 切换验证失败时启用，默认不用（丢滚动位置）。

---

## 2. StepGateBar → Console 门 Banner 合并（契约迁移核对表）

门状态条从编辑列下方上移进 ConsoleDock 顶部 Banner；**`gateBar` objectName 契约保留**，UI 探针与既有断言不受影响。

### 2.1 现有契约清单（`app/ui/qml/components/StepGateBar.qml`，实施前逐项核对）

| 成员 | 行号 | 类型 | 迁移处理 |
|---|---|---|---|
| `id: gateBar` / `objectName: "gateBar"` | L12-13 | id/契约名 | **保留原名**（探针依赖） |
| `gateKey` (string) | L23 | property | 原样迁移 |
| `gateChapter` (int) | L24 | property | 原样迁移 |
| `gateSummary` (string) | L25 | property | 原样迁移（Banner 显示产物摘要） |
| `waiting` (bool) | L26 | property | 原样迁移（全局快捷键开关判据） |
| `rollbackable` (bool = gateKey !== "G5L") | L27 | property | 原样迁移 |
| `showGate(key, chapter, summary)` | L29 | function | 迁移；内部 `ideaInput.text=""`/`forceActiveFocus()`（L33/L35）改为指向 consoleInput（见 §3） |
| `doNext()` | L38 | function | 扩为 `doNext(idea)` 可选参（见 §3） |
| `doReturn()` | L44 | function | 同上归一 |
| `ideaInput` | L92-107 | 内部输入框 | **删除**（被 consoleInput 取代） |
| 门信号消费方：`onGateClosed`（Main.qml L655-657，清残留） | — | 接线 | 保持 `bridge.gateClosed → gateBar.waiting=false` |

### 2.2 ConsoleDock 侧承接（`app/ui/qml/components/ConsoleDock.qml`）

- 现有：`objectName: "consoleDock"`、`expanded: bridge.consoleExpanded`、thinkingList（L83）、dialogueList（L130）、consoleInput（L158，objectName `consoleInput`）。
- 新增：顶部门 Banner 容器，内嵌迁移后的 gateBar 组件（门等待时显示：产物摘要 + 继续/回退按钮；想法输入统一走 consoleInput）。
- bridge 侧 `consume_gate_idea` 就地消费语义不变（T4.1 已接线）。

---

## 3. 焦点模型重写（输入框唯一化）

### 3.1 删除项

- `StepGateBar.ideaInput`（L92-107）整体删除；`showGate()` 不再 `ideaInput.forceActiveFocus()`；删 `Keys.onReturnPressed/onEnterPressed → doNext()`（L106-107），避免双 Enter 路径。

### 3.2 归一逻辑

```qml
// gateBar（Banner 内）
function doNext(idea) {
    bridge.resolveStepGate("next", idea === undefined ? consoleInput.text : idea)
    waiting = false
}
// showGate() 弹起时：consoleInput.forceActiveFocus()（单一焦点目标）
```

### 3.3 全局门快捷键重写（Main.qml L659-673，新增焦点互斥）

```qml
Shortcut { sequence: "Return";      enabled: gateBar.waiting && !consoleInput.activeFocus
           onActivated: gateBar.doNext(consoleInput.text) }
Shortcut { sequence: "Ctrl+Return"; enabled: gateBar.waiting && !consoleInput.activeFocus
           onActivated: gateBar.doNext("") }
Shortcut { sequence: "R";           enabled: gateBar.waiting && gateBar.rollbackable && !consoleInput.activeFocus
           onActivated: gateBar.doReturn() }
```

焦点互斥表（单一判据 = `consoleInput.activeFocus`）：

| 焦点态 | Return | Ctrl+Return | R | 说明 |
|---|:--:|:--:|:--:|---|
| 门等待 + 编辑器聚焦 | ✅ | ✅ | ✅ | 沿旧行为，读输入框文本 |
| 门等待 + 输入框聚焦 | ❌ | ❌ | ❌ | Enter=提交消息（consoleInput.onAccepted → `_submit_from_console`），不误触发继续 |
| 门等待 + 全局失焦 | ✅ | ✅ | ✅ | 沿旧行为 |
| 非门态 | — | — | — | 三条整体 disabled（waiting=false） |

---

## 4. 窗口几何与回归基线重算

### 4.1 窗口 1400 → 1600

`ui_regions.py` 基准 `W, H = 1400, 900` → **`1600, 940`**（min 仍 1080）。

### 4.2 ui_regions 17 屏重算清单（真实屏名，对照 `tests/ui_regions.py` REGIONS L141-200）

| 类别 | 屏名 | 重算口径 |
|---|---|---|
| 5 面板主屏 | `pipeline_default` / `notes` / `chapters` / `shelf` / `settings_conn` | 四列布局：nav 48 + panel 300 + Console 24/280（两态各一套）+ 主编辑列 + 阅读 dock 460；topbar/editor-body 等主列坐标随 Console 态平移 |
| 3 settings 标签 | `settings_writing` / `settings_appearance` / `settings_system` | 左侧面板列坐标随布局重算 |
| 5 对话框 | `dlg_versions` / `dlg_export` / `dlg_stats` / `dlg_unsaved` / `dlg_rewrite` | 居中对话框按新 W/H 重算 |
| 4 reader 沉浸 | `reader_night` / `reader_toc` / `reader_marks` / `reader_prefs` | 保持全窗语义，按 1600×940 全窗坐标重算（reader-topbar、drawer 等） |
| **新增** | `reader_night_dock` | embedded dock 形态矩形（右侧 0~460 窄列：dock-topbar、dock-bottom 等） |

回归硬门槛：**以上全部屏名一个不能少**（沉浸 4 + 主界面 13 + dock 新增 1），少任一屏名即 fail；禁用「8 屏」概称。

### 4.3 ui_drive 几何分类（两类区别对待）

- **遮挡启发式常量（不改）**：`ui_drive.py` L86 `right-left>=1800 && bottom-top>=900` 是 `clear_occluders()` 识别全屏浏览器遮挡窗（class `Chrome_WidgetWin_1`）的阈值，与 app 自身窗口无关；1600 < 1800 永不触发。**保持原值**，仅加注释说明，绝不下调。
- **app 几何常量（按 1600 重算）**：全窗口抓图/点击中引用 1400 的位置，逐一排查按新宽重算。

---

## 5. 分阶段落地序与回滚点

| 阶段 | 内容 | 验收/回滚点 |
|---|---|---|
| S1 | ReaderView `immersive` 属性 + Main.qml 快捷键改绑 + `toEmbedded()` + dockHost 容器 | `probe_reader_dock.py` 过（embedded↔immersive 两轮切换：immersive/parent/z/anchors 断言 + 三快捷键 enabled 矩阵）；不过则回滚本提交，阅读器维持全屏 |
| S2 | StepGateBar→Console Banner 迁移 + ideaInput 删除 + doNext(idea) 归一 | `probe_console_focus.py` 过（三类焦点态 × 三快捷键断言）；gateBar objectName 探针不回归 |
| S3 | 窗口 1600 + ui_regions 17+1 屏重算 + ui_drive app 几何重算 | ui_regions 全屏名抓取通过；ui_drive 全流程点击自动化无偏移 |
| S4 | M2 全套回归 + probe_gate_flow 6/6 + probe_gate_ui 8/8 + probe_console 10/10 + 真机 17 屏坐标回归 | 任一探针红则按阶段回滚（每阶段独立提交） |

每阶段独立提交，回滚粒度 = 单阶段。

## 6. 风险

1. **QML parent 切换**：ReaderView 实例在 contentItem ↔ dockHost 间重挂 parent 是 M3 最大未知数；先做 S1 最小验证，失败则启用 Loader 后备方案（丢滚动位置，但阅读进度已由 savePosition/readStore 持久化兜底）。
2. **焦点回归**：双输入框合并后「编辑器打字误触发继续」是 v2 评审漏洞 3 的原场景，必须用离屏焦点态探针（probe_console_focus）锁死，不能只靠人工试。
3. **快照基线全量重拍**：窗口 1400→1600 + 四列布局使既有全部截图基线失效（tests_output 下 17 屏及探针截图），需一次性重拍并登记，期间避免并行其他 UI 改动。
4. **Console 两态 × reader 两态组合爆炸**：折叠/展开 × dock/沉浸 共 4 组合，ui_regions 至少覆盖「折叠+沉浸」「展开+沉浸」「展开+dock」三个代表组合，其余靠探针断言兜底。
5. **预估工作量**：3-5 天（XL），含真机视觉迭代；建议独立排期，不与共享层改动同轮（避免双端同步与 UI 回归相互干扰）。
