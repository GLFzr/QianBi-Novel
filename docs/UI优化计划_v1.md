# UI 优化计划 v1（深度调研版）

> 时间：2026-09-06 · 性质：UI 专项调研与分档计划，待作者评审后实施
> 依据：①本仓 `app/ui/qml` 现状（Theme.qml 设计系统 + 各面板 QML）；②`shots/` 与 `docs/*.png` 截图；
> ③v0.19 真机实测数据（46 笔调用/章、77 分钟/章）；④外部调研（Qt 美化库、写作应用 UI 模式、
> Agent 流水线可视化、Claude skill 形态审查工具、QSS/图标/中文字体素材），全部结论附来源 URL。
> 与既有方案的边界：`优化方案_用户体验轮_v1/v2.md` 是**成本/缓存轮**（前缀架构、相位思考预算、
> hit/miss 可观测），不是 UI 轮——本计划不重复其任何立项，只在数据消费端（UI）承接其产出。

---

## 〇、一个关键前提修正（先于一切结论）

**本项目 UI 是 QML（Qt Quick Controls 2 Basic style）自绘组件体系，不是 QtWidgets + QSS。**

证据：`app/ui/qml/Main.qml` 头部 `import QtQuick.Controls.Basic`；主题走 `Theme.qml` 单例
（pragma Singleton，3 套主题 × 设计 token：字号 6 档/圆角 4 档/间距 6 档）；组件族为自研
`App*` 系列（AppButton/AppCard/AppSelect/AppSwitch/AppIcon…约 26 个）。

因此任务书里"纯 QSS"一档在本仓映射为：**纯 Theme token / 字体 / 间距 / 组件属性级调整**。
调研范围内的 QSS 主题库（qt-material、QDarkStyle、PyDracula、PyQtDarkTheme、QtVSCodeStyle、
BreezeStyleSheets）**全部只作用于 QtWidgets，对本项目主程序零适用**——它们的结论列在
第二节横向表中仅作许可证与生态佐证，不进入实施计划。

---

## 一、现状速览（基于截图与代码的 5 条观察）

1. **自研设计系统已成型，底盘好**：Theme.qml 三主题（夜间/羊皮纸/纯白）token 化、明度阶梯
   有明确规则注释、模态弹窗统一遮罩（Apple modal 式）、AppIcon 用 Canvas 画 1.6px 线性图标。
   问题不在"丑"，在"打磨与信息架构"——这决定了后面所有推荐的方向：**不换皮、不引组件库，做 token 级打磨 + 模式升级**。

2. **阅读器版式有一处硬伤：无版心（行长不限）**。`ReaderView.qml` 正文 `contentWidth: width`
   全幅排布，1400-1600px 窗宽下中文一行远超舒适行长。中文长文最佳实践：**每行 35~45 字
   （上限 75）、行距 1.5~1.8 倍字号**（来源见 K1）。行距 prefs（默认 1.8）已达标，
   缺的只是"版心宽度"这一个属性。字体栈同样有隐患：`Theme.serifFont = "Source Han Serif SC"`、
   `monoFont = "JetBrains Mono"` 均为**硬编码单字体名，无 fallback**，未装字体的机器直接回退
   系统默认，阅读器 serif 形态名存实亡。

3. **控件同级平铺，视觉层级不分**。`docs/shot_co_writing.png` 左栏同屏出现：4 个"重生成"、
   "开始"（primary 全宽蓝）、"重写本章"、"打开最新"、发布物料"生成"——8+ 个同视觉权重的
   按钮，用户需要逐个读文字才能区分主次；同时阶段信息被**两套导航重复表达**（左栏阶段卡片
   组 + 中栏 6 个阶段 tabs 讲同一件事），再加 StepPills/StepGateBar，纵向叠了 4 层状态条。

4. **长任务的进度呈现远落后于数据能力**。v0.19 实测：单章 46 笔 LLM 调用、墙钟 77 分钟、
   prose 单笔均值 206s、混合命中率 73.2%、¥0.31/章——而 UI 只呈现"步骤 pills + 状态卡 +
   底栏今日 tokens/¥"。`usage.jsonl` 已落盘 `hit/miss/phase/reasoning` 列（v0.19 第三包），
   **数据全有、UI 没接**：缺每阶段耗时/命中率的实时可视，缺每笔长调用（prose 206s）的
   "正在做什么、第几笔、已花多少"的安抚层。

5. **发布链路的截图全部 tofu**。`shots/1~4.png` 中文字符全渲染为方框（截图环境缺 CJK 字体），
   `docs/shot_*.png` 正常——截图工具需要字体自检，否则对外发布素材不可用（商业向应用这点致命）。

---

## 二、候选库/素材横向表

> Star 数标注来源：标"已核实"为 GitHub 页面抓取；标"~"为搜索结果转述的约数；
> 标"未核实"为本次抓取超时未能确认。许可证全部逐个核实（PyPI/GitHub LICENSE）。
> "适用性"均针对本项目 **QML + 商业向分发** 两个约束同时判断。

### 2.1 Qt 美化库/主题（调研范围逐个给判断）

| 名称 | Star | 许可证（已核实） | Qt6/PySide6 | 维护状态 | 引入成本 | 与本项目匹配度 |
|---|---|---|---|---|---|---|
| **PyQt-Fluent-Widgets** (zhiyiYo) | 8.1k（已核实） | **GPLv3 + 商业双授权** | ✅（PySide6-Fluent-Widgets 包） | 活跃 | 中 | **★☆☆ 不可用**。双重不匹配：①GPLv3 有传染性——闭源商业分发必须整库购买商业授权，否则被迫开源整个应用（风险点名见 2.3）；②库本体面向 QtWidgets，**无 QML 版** |
| **qt-material** (UN-GCPDS→dunderlab) | ~2.9k | BSD-2-Clause（PyPI 已核实） | ✅ | 原 2025-04 迁移至 dunderlab/qt-material，长期维护曾存疑 | 低 | ★☆☆ 不适用：Material 风 QSS，仅 QtWidgets |
| **PyQtDarkTheme** (5yutan5) | 未核实 | MIT（GitHub 已核实） | ⚠️ 2.1.0（2022-12）与 PySide6 ≥6.8 不兼容（启动即崩，issue #262 挂起） | **实质停更**，社区 fork `pyqtdarktheme-fork` 接管 | 低 | ★☆☆ 不适用（QSS/QWidgets）+ 已停更 |
| **PyDracula** (Wanderson-Magalhaes) | 未核实（数千级） | **非标许可**：仅口头"free for any use + 保留 credits"，无 OSI 许可证文本 | ✅ PySide6/PyQt6 | **2021 起冻结**，作者转向 PyOneDark | 低 | ★☆☆ 不适用（QWidgets 模板工程）；非标许可法律状态模糊，不作代码级依赖 |
| **QDarkStyle** (ColinDuquesnoy) | 未核实 | MIT（PyPI 3.2.3 已核实，2023-11） | ✅ | 稳定但低频（两年无新版） | 低 | ★☆☆ 不适用（QSS/QWidgets） |
| **SuperQt** (pyapp-kit) | 未核实 | BSD-3-Clause（PyPI 0.8.2 已核实，2026-05 仍在发版） | ✅ | 活跃 | 低 | ★☆☆ 组件不适用（全是 QtWidgets 扩展件）；其"补充 Qt 没有的高质量组件"定位与本仓 App* 自研族同思路，可作为组件规格参考 |
| **FluentUI** (zhuzichu520/FluentUI) | ~4k（约数，未精确核实） | **MIT**（README 已核实） | ✅ 主分支 Qt6 | **活跃**（2025 年仍有 FluSplitLayout/i18n 重写等 release）；但 PyPI 的 `PySide6-FluentUI-QML` 绑定停在 1.6.7（2024-01），文档 WIP | **高** | ★★☆ 唯一形态匹配的组件库（QML 原生）。**不建议整体引入**：与现有 Theme.qml 自研体系设计语言冲突、C++ 编译/版本绑定成本高、Python 绑定滞后。**建议只作组件交互规格参考**（InfoBar/Toast、NavigationView、进度类组件的交互定义） |
| **Qt 内建 Quick Controls 2 styles**（Basic/Material/Universal） | — | LGPLv3（Qt 本体） | ✅ | Qt 官方 | 低 | ★☆☆ 项目已选 Basic 自绘（正确选择）；Material/Universal 风格与"中文写作工作台"气质不符，不切换 |

### 2.2 图标与字体素材

| 素材 | 许可证（已核实） | 用法（QML 场景） | 匹配度 |
|---|---|---|---|
| **Lucide Icons** | ISC（宽松，可闭源） | 本仓 `AppIcon.qml` 是 Canvas 自绘线性图标体系（1.6px 描边）——**不改渲染管线，把 Lucide 的 24×24 path data 录入 AppIcon 的 name 注册表**，即可零依赖获得 1500+ 一致图标。python-lucide 包可辅助批量导出 SVG string | ★★★ 直接采纳（推荐） |
| Tabler / Feather Icons | MIT | 同上备选；Feather 是 Lucide 的上游祖先，风格一致但更新停滞 | ★★☆ 备选 |
| **qtawesome** (spyder-ide) | MIT（字体 SIL OFL） | 图标字体方案（QML 亦可用 Text+图标字体），但与本仓 Canvas 方案重复，不引入 | ★☆☆ |
| **霞鹜文楷 · 屏幕阅读版** (lxgw/LxgwWenKai-Screen) | SIL OFL 1.1（允许嵌入商业分发，须保留版权声明） | `Theme.serifFont` 的**内置兜底**：作者专为 PC 屏幕阅读调过字重（原版 Regular 偏细），与 Roboto 度量对齐；子集化（fonttools pyftsubset，常用 3500 字）后体积可控 | ★★★ 直接采纳（推荐） |
| 思源宋体 SC (adobe-fonts/source-han-serif) | SIL OFL 1.1 | 现已硬编码为 serifFont；改为"用户已装→优先，未装→回退内置霞鹜文楷"的双层栈 | ★★☆ 已在用，补栈即可 |

### 2.3 许可证对商业分发的风险点名（本节为合规要点，非空谈）

- **GPLv3（qfluentwidgets）= 硬红线**：只要以任何形式链接/引入并分发应用，整份应用须按
  GPLv3 开源；闭源商业分发唯一合法路径是购买作者的商业授权（Pro/企业授权）。在"引入即
  付费或开源"的意义上，本项目（商业向）**不引入**，也不建议为省皮肤工作量去谈判授权。
  来源：[GitHub 仓库许可声明](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)、
  [官方定价页](https://qfluentwidgets.com/pages/install/)。
- **LGPLv3（PySide6/Qt 本体）= 可闭源但有条件**：动态链接 + 允许用户替换 Qt 库 + 发布
  LGPL 声明。PySide6 官方绑定即按此设计，现有做法合规，无需改动。
- **MIT / BSD / ISC（FluentUI、qt-material、QDarkStyle、SuperQt、qtawesome、Lucide、Tabler、Feather）**：
  允许闭源商业分发，义务仅"保留版权与许可声明"——采纳无障碍。
- **SIL OFL 1.1（霞鹜文楷/思源宋体）**：允许随应用嵌入分发（含商业），义务为保留版权声明、
  不单独出售字体本身、若改名需遵守 Reserved Font Name 规则——**内置字体走"子集化+保留
  LICENSE 文件"即可**。
- **PyDracula 的"free for any use + credits"**：非标准许可、无法律文本，作品级借鉴（看布局）
  可以，代码级复制不建议。

---

## 三、写作应用与 Agent UI 的模式拆解（外部素材 → 本项目映射）

### 3.1 长文写作应用的可借鉴模式

| 产品 | 模式 | 来源 | 对本项目的映射 |
|---|---|---|---|
| **Ulysses** | 三栏经典结构 Library → Sheet List → Editor；组（卷）-稿（章）两级；键盘跨栏导航 | [官方帮助：Library & Editor](https://help.ulysses.app/en_US/getting-started/first-steps-library-editor)、[Sheets & Groups](https://help.ulysses.app/567894-sheets-groups) | 本仓 nav+面板+中央编辑器已是三栏骨架；差距在 ChapterPanel 列表缺"卷-章"两级分组与键盘跨栏（详见 M4） |
| **iA Writer** | Focus Mode（句/段聚焦、其余淡化）；版式极简（专用字体、大留白）；Content Blocks 转缀引用 | [Write With Focus](https://ia.net/writer/how-to/write-with-focus)、[对比评述](https://mariusmasalar.me/ulysses-vs-ia-writer-a-new-comparison-7015c899e883) | ReaderView 已有全屏沉浸入口（M3 设计文档），升级为"当前段高亮/其余降灰 + 打字机滚动"（R1） |
| **Typora** | Focus Mode + Typewriter Mode（当前行垂直居中） | [社区综述](https://www.reddit.com/r/ObsidianMD/comments/njywki/for_those_who_like_to_outline_in_obsidian_the/) 及多篇对比 | 同上，归入 R1 |
| **Obsidian (Longform 插件)** | 项目=工作区：每本书记住自己的面板布局；scene 卡片逐场起草后一键编译成稿 | [Longform 插件](https://www.obsidianstats.com/plugins/longform)、[工作流示例](https://www.hedonic.ink/obsidian-workflow-for-writing/) | 书架每书独立项目已具备；补"每书记住面板/阅读器布局"属低成本加分项（M5） |
| **Novelcrafter** | Plan（拖拽场景板）/ Write（干净稿面）/ Chat（AI 对话）/ Review 四模式；Codex 世界资料库；AI 按章注入 Bible 上下文 | [App Layout 官方文档](https://www.novelcrafter.com/help/docs/app/app-layout)、[Kindlepreneur 评测](https://kindlepreneur.com/novelcrafter-review/)、[SelfPublishing 评测](https://selfpublishing.com/novelcrafter-review/) | 其"四模式"正是本仓 7 个 nav 的收敛目标态（R3）；Codex 对应契约/世界书面板的卡片化（R2） |
| **Sudowrite** | Story Bible 卡片流（角色/世界观/大纲各为卡片，逐段链式生成、卡片即上下文） | [Story Bible 官方文档](https://docs.sudowrite.com/using-sudowrite/1ow1qkGqof9rtcyGnrWUBS/what-is-story-bible/jmWepHcQdJetNrE991fjJC)、[工作原理](https://sudowrite.com/blog/how-sudowrite-works/) | 契约面板（ContractPanel）与世界书目前是文档形态，卡片化是 R2 的样板 |

### 3.2 Agent/流水线可视化的可借鉴模式（长任务 LLM 调用 10-30 分钟/章）

| 产品 | 模式 | 来源 | 对本项目的映射 |
|---|---|---|---|
| **LibreChat** | **Smooth Streaming**：流式新词淡入（纯视觉层，不延迟 token 送达）；多步 agent 的分步进度显示 | [Smooth Streaming 官方文档](https://www.librechat.ai/docs/features/smooth_streaming) | ConsoleDock/阅读器流式输出的排版处理（M2）：长段流式不再"硬刷"，按句淡入 |
| **open-webui** | 使用仪表盘：消息量、**token 消耗与成本跟踪**的聚合可视 | [官方 Features 文档](https://docs.openwebui.com/features/) | UsageDialog 升级为分 phase 的命中率/token/费用表（M1），数据源就是 usage.jsonl |
| **AgentGPT** | 任务列表 + 每任务"thinking→执行→结果"实时滚动 feed | [GitHub](https://github.com/reworkd/agentgpt)、[产品页](https://agentgpt.reworkd.ai/) | ConsoleDock 的阶段分组折叠结构样板（M2） |
| **Langflow** | React Flow 节点画布 + Playground 边跑边看中间产物 | [官网](https://www.langflow.org/)、[入门教程](https://medium.com/@swachalantech/a-guide-for-newbies-in-langflow-8287a1ab2f68) | **画布不搬**（本仓流水线是线性固定阶段，画布性价比低，见 R4"明确不做"）；但"边跑边看中间产物"思路用于门（gate）审查：审校票/清算报告在阶段时间线上点开即看（M1） |

### 3.3 Claude/Agent skill 形态的 UI 审查工具（方法论搬到桌面 QML）

| 素材 | 内容 | 来源 |
|---|---|---|
| **anthropics/skills 内的 frontend-design skill** | Anthropic 官方示例 skill：指导"有辨识度、有意图"的视觉设计，用 aesthetic anchors 锁定 palette/typography/texture 到设计 token | [仓库动态（含 #1293 添加记录）](https://github.com/anthropics/skills/activity)、[PR #210 提升可操作性](https://github.com/anthropics/skills/pull/210) |
| **claude-code 内置 frontend-design 插件** | 同源 skill 的 Claude Code 插件形态 | [SKILL.md](https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md)、[插件 README](https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/README.md) |
| **jezweb/claude-skills 的 design-review skill** | UI 审查清单：layout / typography / spacing / colour / hierarchy / consistency / interaction / responsive 逐项过检 | [design-review/SKILL.md](https://github.com/jezweb/claude-skills/blob/main/plugins/frontend/skills/design-review/SKILL.md) |
| **awesome 类索引确认生态** | frontend-design / design review / testing 已是 skill 生态的成熟品类 | [awesome-skills 目录](https://awesome-skills.com/)、[Snyk: Top Claude Skills for UI/UX](https://snyk.io/articles/top-claude-skills-ui-ux-engineers/) |

**迁移方式**：把上述审查维度桌面化为《QML UI review 检查表》——responsive → 窗口断点
（1080/1400/1600/1920，即 Main.qml 的 minimumWidth~常用宽四档）；DOM 树 → QML 对象树；
CSS token → Theme.qml token。**执行形态**：让 agent 逐面板读 QML + 对照截图跑一遍检查表，
产出问题清单（这正是本计划 v2 轮的验收工具之一）。前端 skill 的 anchor 锁定法与 Theme.qml
的"禁止字面量散落"规则天然同构，可直接复用其措辞作为代码评审守则。

### 3.4 QSS 主题库（明确结论：仅存档）

QSS 主题生态（[QtVSCodeStyle](https://github.com/5yutan5/QtVSCodeStyle)、
[BreezeStyleSheets](https://github.com/Alexhuszagh/BreezeStyleSheets)、
[qtass-pyside6](https://github.com/githubuser0xFFFF/qtass-pyside6) 等）对 QtWidgets 有效，
本项目主程序为 QML，**全部不适用、不立项**。唯一例外场景：若未来给 TUI（`plan_tui_v2.md`）
之外再做小型 QtWidgets 工具窗（如独立托盘/导出器），可回看此清单。

---

## 四、UI 优化计划（分三档）

> 每项四要素：**解决什么问题 / 改哪里 / 证据来源 / 验收标准**。
> 总原则：不换设计系统、不引第三方 UI 组件库（理由见第二章）；全部改动落在 `app/ui/qml`。

### 第一档：快赢（纯 token/字体/间距级，合计 1 天内）

#### K1 阅读器加"版心"（正文列宽上限）
- **问题**：正文行宽随窗口无限拉伸，1600px 窗下一行 ≈ 90+ 字，远超中文舒适行长；长时间
  阅读/校对疲劳（观察 #2）。
- **改哪里**：`components/ReaderView.qml`（沉浸阅读态）与 `Main.qml` 中央编辑列的正文
  TextEdit：内容列加 `maximumWidth`（建议 `font.pixelSize × 42 字当量 ≈ 640~700px`）并水平
  居中，两侧留白透出 bgPage。
- **证据**：中文多行正文 35~45 字/行最佳、上限 75
  （[人人都是产品经理：行长研究](https://www.woshipm.com/pd/5823078.html)、
  [W3C《中文排版需求》](https://www.w3.org/TR/clreq/)）；
  [蒙纳字库：理想行长 65 字符](https://cn.monotype-asia.com)。
- **验收**：1080~1920px 窗宽下，正文每行 ≤45 个中文字符（截图量测）；三主题下两侧留白区
  无分界线突兀感（与 bgPage 同色）。

#### K2 字体栈兜底 + 内置阅读字体
- **问题**：`serifFont="Source Han Serif SC"`、`monoFont="JetBrains Mono"` 硬编码，未装字体
  的机器静默回退系统默认，阅读器 serif 形态与等宽日志形态双双失效（观察 #2）；商业分发
  不能假设用户装了什么。
- **改哪里**：`Theme.qml` 改用 `font.families` 列表（Qt 6.2+ 支持多族回退）：
  serif = `"Source Han Serif SC","LXGW WenKai Screen","Georgia",serif`；并**内置子集化霞鹜文楷
  屏幕阅读版**（pyftsubset 常用 3500 字 + 存 qrc，附 OFL LICENSE）；设置面板加"正文字体"
  三选（系统黑体/思源宋/内置文楷）。
- **证据**：[霞鹜文楷屏幕阅读版仓库](https://github.com/lxgw/LxgwWenKai-Screen)（作者说明
  原版 Regular 屏幕偏细，屏幕版专为长时间阅读调校）；OFL 许可允许嵌入分发
  （[SIL OFL 1.1](https://openfontlicense.org/)）。
- **验收**：一台未装思源宋体/JetBrains Mono 的干净 Windows 上，阅读器为楷体观感、日志为
  等宽观感；安装包体积增量 ≤6MB；LICENSE 文件随包分发。

#### K3 按钮视觉层级分级
- **问题**：左栏同屏 8+ 个等权重按钮，主操作（开始/继续）淹没在"重生成"群里（观察 #3）。
- **改哪里**：`components/AppButton.qml` 增加 `hierarchy: primary|secondary|ghost` 三档
  （primary 用 accent 填充、secondary 描边、ghost 纯文字）；`PipelinePanel.qml` 左栏每组操作
  只保留 ≤1 个 primary（"开始/继续"），"重生成"全降 ghost；"重写本章"这类破坏性操作改
  danger-ghost 并挪入章节级菜单。
- **证据**：截图 `docs/shot_co_writing.png` 左栏现状；层级化按钮是
  frontend-design skill 的首查项
  （[anthropics frontend-design SKILL.md](https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md)）。
- **验收**：任意面板同屏 primary 按钮 ≤1；新截图与旧图对比主操作 3 秒内可辨识。

#### K4 截图链路字体自检
- **问题**：shots/ 全部 tofu，发布素材不可用（观察 #5）。
- **改哪里**：截图脚本（或手工流程 checklist）前置一步：渲染一个"千"字并检查字形非方框，
  失败即报"环境缺 CJK 字体"。
- **证据**：`shots/1_bookshelf.png` ~ `4_settings.png` 现状。
- **验收**：重跑截图脚本产出的 PNG 无 tofu。

#### K5 离峰挂机文案对齐 v4 价格表
- **问题**：v0.19 遗留项——设置面板离峰挂机的时段说明与 v4 价格表口径需更新。
- **改哪里**：`SettingsPanel.qml` 离峰挂机说明文案。
- **证据**：`docs/v0.19_实现报告.md` 第五节"后续"。
- **验收**：文案中的时段与当前价格表一致；首次开启时有"为什么省钱"一句解释。

### 第二档：中期（组件升级与信息架构调整，2-4 天）

#### M1 阶段时间线 + 成本面板（把 v1/v2 成本轮的数据接上 UI）
- **问题**：单章 46 笔调用/77 分钟的等待期只有 pills 状态；hit/miss/phase/reasoning 已落盘
  却无 UI 呈现（观察 #4）。
- **改哪里**：`PipelinePanel.qml` 的 StageStepper/StepPills 升级为**阶段时间线**：每阶段一行
  （名称/状态/耗时/token 迷你条/命中率色点），长阶段（prose 206s 均值）运行中显示"第 N 笔 ·
  已 x 秒 · 已 x tok"；`components/UsageDialog.qml` 升级为分 phase 聚合表（命中率/输出/
  费用），口径与 `tests/report_cache.py`（v2 体验轮 C3'）对齐；审校票、清算报告等中间产物
  点时间线行即弹开（Langflow Playground"边跑边看"的降维版）。
- **证据**：v0.19 实测数据（`docs/v0.19_实现报告.md` 第三节）；
  [open-webui usage dashboard](https://docs.openwebui.com/features/)；
  多阶段长任务进度是 Agent UI 成熟品类（[AgentGPT](https://github.com/reworkd/agentgpt)）。
- **验收**：连跑 1 章全程，不打开日志即可回答三个问题：现在在哪个阶段、这阶段跑了多久/
  花了多少、本章累计花了多少钱；UsageDialog 数字与 report_cache.py 报表一致（±1%）。

#### M2 流式输出排版（Smooth Streaming + 阶段折叠）
- **问题**：prose/共写长流式输出硬刷不可读；ConsoleDock 平铺日志式，找不到"这一轮做了什么"。
- **改哪里**：`components/ConsoleDock.qml` + `components/CwDialogueDock.qml`：流式新句淡入
  （150ms opacity 动画，逐句不逐 token，避免性能税）；按阶段分组折叠（AgentGPT 任务 feed
  式），折叠头显示"阶段名 + 耗时 + 结果状态"；`ReaderView.qml` 写作中流式正文同用淡入。
- **证据**：[LibreChat Smooth Streaming](https://www.librechat.ai/docs/features/smooth_streaming)
  （明确说明纯视觉层、不延迟 token）；[AgentGPT 任务 feed 模式](https://agentgpt.reworkd.ai/)。
- **验收**：一章 prose 流式期间阅读区无可感知闪烁；ConsoleDock 默认折叠为 ≤7 个阶段组，
  展开任一组可看完整中间输出；滚动性能无回退（现有几何基线测试通过）。

#### M3 图标系统 Lucide 化（零依赖升级）
- **问题**：AppIcon Canvas 手绘图标数量有限、新增图标边际成本高、一致性问题。
- **改哪里**：`components/AppIcon.qml` 的 name 注册表批量录入 Lucide path data（写一个
  python 脚本从 lucide 包导出 path 字符串生成 QML 注册表）；渲染管线（Canvas + stroke）不动。
- **证据**：[Lucide](https://lucide.dev/)（ISC 许可、24×24 描边网格，与现有 1.6px 描边风格
  天然一致）；QML 内渲染 SVG path 无需 Qt SVG 插件（Canvas 直接画）。
- **验收**：全部 nav/面板图标一次性替换/补齐（含契约/笔记/预设库等低频面板）；三主题下
  换色正常；视觉走查无混搭感。

#### M4 ChapterPanel 卷-章两级 + 状态列规范（Ulysses Sheet List 式）
- **问题**：章节列表平铺，章多之后（目标连写 11-20 章起步、全书数百章）没有卷分组；
  状态色点含义靠猜。
- **改哪里**：`ChapterPanel.qml` 列表加卷分组头（折叠）；行结构规范为：
  章号+标题 / 字数+日期（次要行）/ 状态徽章（定稿·审校带注·待修，复用 AppBadge 统一语义色）；
  键盘 ↑↓ 选择、→ 进阅读（Ulysses 跨栏导航习惯）。
- **证据**：[Ulysses Sheets & Groups](https://help.ulysses.app/567894-sheets-groups)、
  [三栏结构](https://help.ulysses.app/en_US/getting-started/first-steps-library-editor)；
  连写规模依据 `docs/优化方案_用户体验轮_v1.md` G8。
- **验收**：100 章项目下列表滚动不卡；每章状态不看 tooltip 可辨；全键盘可完成"选章→读章"。

#### M5 导航轻收敛 + 每书布局记忆
- **问题**：7 个 nav 面板 + 左栏阶段卡 + 中栏阶段 tabs 三层导航表达同一流水线（观察 #3）；
  每书切换后面板位置不记忆。
- **改哪里**：**轻收敛**（不动架构）：中栏阶段 tabs 仅在"流水线活跃"时显示，闲置态收合为
  一行阶段点（StageStepper 复用）；nav 分组为"写作（书架/流水线/章节）/ 资料（契约/笔记/
  预设库）/ 设置"三组，组间加分隔；每书记住（bridge → cfg）上次的激活面板与阅读器宽窄。
- **证据**：Novelcrafter 用模式切换替代功能平铺
  （[App Layout](https://www.novelcrafter.com/help/docs/app/app-layout)）；Obsidian Workspaces
  的"每项目布局记忆"（[Longform 工作流](https://www.hedonic.ink/obsidian-workflow-for-writing/)）。
- **验收**：新书首次进入默认落在"书架"，开始生成后自动切"流水线"；重开应用回到上次布局；
  同一阶段信息不再同时出现两处可点入口。

### 第三档：远期（交互模式重构，另行立项评审）

#### R1 沉浸写作模式（Focus + Typewriter）
- **问题/目标**：定稿后的人工润色需要"只看当前段"的专注态；现沉浸只是全屏。
- **改哪里**：`ReaderView.qml`：F5 沉浸态内加"段落聚焦"（当前段全亮、前后段降灰 40%）、
  可选打字机滚动（当前行固定于视口 1/3）；与 M3 设计文档的 dock/immersive 双形态状态机
  合并实现（其 `immersive` 属性设计已定稿待实施，直接衔接）。
- **证据**：[iA Writer Focus Mode](https://ia.net/writer/how-to/write-with-focus)、
  `docs/design_agent_console_m3.md` 阅读器双形态。
- **验收**：聚焦态下视觉噪声（边栏/其余段）显著降低的盲测；打字机滚动无抖动；Escape 退出
  路径与 M3 状态机一致。

#### R2 契约/世界书 Story Bible 卡片化
- **问题/目标**：设定现在是文档形态，与"清算器逐章校验、自动提案"的 Agent 能力不匹配；
  卡片化后每张卡（角色/地点/伏笔/规则）可独立挂"最近出场章、命中状态、待回收"元数据。
- **改哪里**：`ContractPanel.qml` + 世界书视图重构成卡片流（Sudowrite Story Bible 式），
  卡片详情右侧抽屉；清算提案直接以"卡片 diff"呈现一键采纳（与 v1 体验轮 D1 日历回写提案
  的 toast 交互统一）。
- **证据**：[Sudowrite Story Bible](https://docs.sudowrite.com/using-sudowrite/1ow1qkGqof9rtcyGnrWUBS/what-is-story-bible/jmWepHcQdJetNrE991fjJC)、
  [Novelcrafter Codex 评测](https://kindlepreneur.com/novelcrafter-review/)；
  清算器能力依据 `docs/优化方案_用户体验轮_v1.md` 第十章。
- **验收**：一条伏笔从入册→回收全生命周期在卡片上可见；清算提案采纳操作 ≤2 次点击。

#### R3 信息架构终态：四模式壳
- **问题/目标**：M5 轻收敛的完成态——nav 收敛为 Plan（设定/大纲/世界书）/ Write（流水线+
  章节+阅读）/ Chat（共写）/ Review（审校与清算报告）四模式，与产品心智"书是一条流水线"
  对齐；7 面板变为模式内 tab/抽屉。
- **证据**：[Novelcrafter 四模式](https://www.novelcrafter.com/help/docs/app/app-layout)、
  本仓 `plan_agent_console_v3.md` 已有的 Console/编辑/阅读四列几何设计。
- **验收**：新用户 10 分钟引导内完成"建书→跑通 1 章"全程不迷路（可用性测试脚本另立）。

#### R4 明确不做
- **节点画布/流程图编辑器**（Langflow 式）：本仓流水线阶段固定、线性编排，画布只增加
  认知负担与实现成本，不立项。
- **引入任何 GPL 组件库**（含 qfluentwidgets 及其社区 Pro 复刻
  [PySide6-Fluent-Widgets-Pro](https://github.com/Fairy-Oracle-Sanctuary/PySide6-Fluent-Widgets-Pro)
  ——后者许可证状态更模糊，风险更高）。
- **换设计系统**（切 Qt Material/Universal style 或整体引入 FluentUI QML）：自研 Theme 体系
  是资产，替换是负收益。

---

## 五、与 v1/v2 用户体验轮（成本/缓存轮）的衔接清单

| 已做/在做（成本轮） | 本 UI 计划的承接点 | 不重复的边界 |
|---|---|---|
| C1'/C2' usage.jsonl 落盘 hit/miss/phase（已上线，见 v0.19） | M1 的数据源，UI 零schema改动只做呈现 | UI 计划不碰 client.py/usage.py |
| C3' `tests/report_cache.py` 报表（v2 轮验收工具） | M1 UsageDialog 的口径基准（数字对齐它） | 报表工具本身不动 |
| B1' 相位思考预算 → 机械相位秒级返回 | M1 时间线的"长阶段"只剩 prose/outline/review，阶段粒度按此设计 | 预算配置不进 UI（设置面板不加开关，避免误配） |
| 离峰挂机（offpeak_run，已上线） | K5 文案对齐 | 不改 offpeak.py |
| D1 日历偏差提案 toast（规划中） | R2 的"卡片 diff 一键采纳"复用其交互 | 提案生成逻辑不碰 |
| G8 连写 11-20 章实测场 | M4 章列表按百章规模验收 | 不动流水线 |
| M3 设计文档（阅读器 dock/immersive 状态机，设计定稿未实施） | R1 直接在其状态机上叠加聚焦/打字机 | 不另起炉灶 |
| header审计/前缀架构（成本轮核心） | 与 UI 无关，本计划零涉及 | — |

**实施顺序建议**：K1→K2→K3→K5（半天~1 天，一次主题走查顺带完成）→ M3（半天，脚本化）→
M1→M2（1.5~2 天，连跑一章实测验收）→ M4→M5（1 天）→ R 档另行立项。
每档合并前跑既有几何基线 + 607 单测（UI 改动应零 core 测试漂移，若漂移即越界）。

---

## 六、来源索引（全部外链汇总）

**Qt 库/许可证**：
- PyQt-Fluent-Widgets：https://github.com/zhiyiYo/PyQt-Fluent-Widgets （GPLv3+商业双授权，8.1k）
  商业定价：https://qfluentwidgets.com/pages/install/
- qt-material：https://github.com/UN-GCPDS/qt-material （BSD-2，2025-04 迁移
  https://github.com/dunderlab/qt-material ，见 issue https://github.com/UN-GCPDS/qt-material/issues/120 ）
  PyPI：https://pypi.org/project/qt-material/
- PyQtDarkTheme：https://github.com/5yutan5/PyQtDarkTheme （MIT，停更；
  PySide6 6.8 崩溃 issue https://github.com/5yutan5/PyQtDarkTheme/issues/262 ）
- PyDracula：https://github.com/Wanderson-Magalhaes/Modern_GUI_PyDracula_PySide6_or_PyQt6 （非标许可，冻结）
- QDarkStyle：https://github.com/ColinDuquesnoy/QDarkStyleSheet / https://pypi.org/project/QDarkStyle/ （MIT，3.2.3）
- SuperQt：https://github.com/pyapp-kit/superqt / https://pypi.org/project/superqt/ （BSD-3，0.8.2 活跃）
- FluentUI（QML，MIT，Qt6 活跃）：https://github.com/zhuzichu520/FluentUI ；
  PySide6 绑定：https://pypi.org/project/PySide6-FluentUI-QML/ （1.6.7，2024-01）
- qtawesome（MIT）：https://github.com/spyder-ide/qtawesome
- QtVSCodeStyle（MIT）：https://github.com/5yutan5/QtVSCodeStyle ；
  BreezeStyleSheets：https://github.com/Alexhuszagh/BreezeStyleSheets ；
  qtass：https://github.com/githubuser0xFFFF/qtass-pyside6

**写作应用模式**：
- Ulysses 三栏：https://help.ulysses.app/en_US/getting-started/first-steps-library-editor 、
  https://help.ulysses.app/567894-sheets-groups 、https://tidbits.com/2016/08/13/writing-app-ulysses-blends-power-and-simplicity/
- iA Writer：https://ia.net/writer/how-to/write-with-focus 、
  https://mariusmasalar.me/ulysses-vs-ia-writer-a-new-comparison-7015c899e883
- Obsidian Longform：https://www.obsidianstats.com/plugins/longform 、
  https://www.hedonic.ink/obsidian-workflow-for-writing/
- Novelcrafter：https://www.novelcrafter.com/help/docs/app/app-layout 、
  https://kindlepreneur.com/novelcrafter-review/ 、https://selfpublishing.com/novelcrafter-review/
- Sudowrite Story Bible：https://docs.sudowrite.com/using-sudowrite/1ow1qkGqof9rtcyGnrWUBS/what-is-story-bible/jmWepHcQdJetNrE991fjJC 、
  https://sudowrite.com/blog/how-sudowrite-works/

**Agent/流水线可视化**：
- LibreChat Smooth Streaming：https://www.librechat.ai/docs/features/smooth_streaming
- open-webui Features（token/成本仪表盘）：https://docs.openwebui.com/features/
- AgentGPT：https://github.com/reworkd/agentgpt 、https://agentgpt.reworkd.ai/
- Langflow：https://www.langflow.org/ 、
  https://medium.com/@swachalantech/a-guide-for-newbies-in-langflow-8287a1ab2f68

**UI 审查 skill**：
- https://github.com/anthropics/skills/activity （frontend-design skill 入库）
- https://github.com/anthropics/skills/pull/210
- https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md
- https://github.com/jezweb/claude-skills/blob/main/plugins/frontend/skills/design-review/SKILL.md
- https://awesome-skills.com/ 、https://snyk.io/articles/top-claude-skills-ui-ux-engineers/

**图标/中文字体/版式**：
- Lucide（ISC）：https://lucide.dev/ ；python-lucide：https://pypi.org/project/python-lucide/ ；
  Feather：https://feathericons.com/ ；Iconify：https://icon-sets.iconify.design/
- 霞鹜文楷屏幕阅读版（OFL）：https://github.com/lxgw/LxgwWenKai-Screen
- Qt SVG 图标机制：https://doc.qt.io/qtforpython-6/PySide6/QtSvg/QSvgRenderer.html 、
  https://forum.qt.io/topic/138430/rendering-svg-images-in-qicons-natively-not-supported
- 行长/行距研究：https://www.woshipm.com/pd/5823078.html 、https://www.w3.org/TR/clreq/
