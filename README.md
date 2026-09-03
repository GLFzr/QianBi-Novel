# 千笔一文 Novel

**人 AI 共写的长篇网文创作台** —— AI 全程透明写作，人永远是作者。

写一部长篇网文真正的难点不是「让 AI 写出一章」，而是写到第 300 章时
**设定还没崩、代价还没赖账、伏笔还记得收**。千笔一文把这件事拆成一条有闸门的流水线，
以及在每个环节都能插手的共写界面。

- 🗂️ **条目化世界书**：设定按条目登记、按锚点激活、按预算注入 —— 长设定不会在 500 章后被截成一团糊
- ⛓️ **代价必须兑现**：正则契约（must 级）+ 因果对账，金手指越界直接判阻塞
- 🤝 **共写档六阶段**：立项 → 核心设定 → 剧情总纲 → 世界书与正则 → 单元细纲 → 正文写作，每阶段可与 Agent 讨论后「确定」定稿
- 🔍 **三层审校**：本地 L0 确定性预检（零成本）→ 6 维 LLM 终审（引证验真 + 3 票投票降噪）→ 反馈环定向修复
- 🔄 **剧情反哺**：正文里冒出来的新设定回写世界书/伏笔表，并约束后文 —— 而不是各写各的
- 🎨 **10 套题材预设**：修仙·凡人流 / 都市改命 / 克苏鲁 / 规则怪谈 / 无限流 / 末日废土 / 历史权谋 …，每套含 6 阶段特化提示
- 🔑 **BYOK + 全本地**：自带模型 Key，书稿、配置、版本历史全在你机器上（MIT 开源，无云端）
- 🖥️ **Windows 桌面应用**：PySide6 + QML，安装包开箱即用，无需 Python

![共写档：六阶段导航 + 与写作 Agent 的多轮讨论 + 正文实时预览](docs/shot_co_writing.png)

---

## 下载

| 方式 | 文件 | 说明 |
|---|---|---|
| **安装版（推荐）** | `QianBi-Novel-v0.15.0-setup.exe` | Inno Setup，per-user 安装（免管理员）；**创建桌面快捷方式**，在「设置 → 应用」里可卸载，卸载时**保留书稿** |
| **便携版** | `QianBi-Novel-v0.15.0-portable.zip` | 解压双击即用；**不建快捷方式、不写注册表、无卸载入口**（删文件夹即清除）。包内附《使用说明.txt》 |

两者数据共用 `%USERPROFILE%\.qianbi_novel\`，换着用最方便。

→ **[Releases](https://github.com/GLFzr/QianBi-Novel/releases/latest)** ·
每个版本附 `SHA256SUMS.txt`，校验后再运行。

系统要求：Windows 10/11 x64。无需安装 Python。

---

## 两种档位，同一套内核

### 自动档 —— 你定方向，AI 跑完全程

```
立项 → 核心设定 → 全书大纲 → 章节细纲 → 〔每章微循环 ×N〕 → 完本
```

每章微循环：

```
① 上下文组装   核心设定 + 题材预设 + 条目化世界书 + 正则契约 + 细纲 + 场景卡
               + 前 3 章摘要 + 角色状态 + 未回收伏笔 + 上一章结尾
② 草稿生成     写作槽，流式（thinking → 生成 → 完成，可暂停阅读已生成部分）
③ 字数闸门     本地判定，不足扩写 / 超标压缩，带防注水约束
④ AI 味扫描    本地正则，零成本
⑤ 去味改写     最多 2 轮
⑥ 6 维终审     审校槽，L0 预检先行
               ├─ PASS / PASS-WITH-NOTES → 可锁定
               └─ REJECT → 反馈环（根因溯源 → 定向改稿 → 再审，3 轮熔断）
⑦ 定稿落库     正文 + 追踪四文件 + 摘要链 + 章级生成配置快照
```

### 共写档 —— 每个阶段都能插手

六个阶段各自与对应 Agent 多轮讨论，谈拢了点「确定」总结定稿、进入下一阶段：

| 阶段 | 对话对象 | 「确定」做什么 |
|---|---|---|
| 创建项目 | — | 立项信息落盘 |
| 核心设定 | 设定 Agent | 总结定稿 → 交接块给下一阶段 |
| 剧情总纲 | 大纲 Agent | 同上 |
| 世界书与正则 | 世界书 Agent | 逐条对账契约 |
| 单元细纲 | 细纲 Agent | 校验衔接 → 滚动生成下一批 5 章 |
| 正文写作 | 写作 Agent | 主 Agent 衔接比对 → 终稿锁定 |

外加两个角色：**主 Agent（Supervisor）** 做跨章衔接比对与范围控制，
**读改 Agent（Readback）** 揣摩你手改的意图并反推该改哪些上游。

![自动档驾驶舱：阶段卡片 + 步骤闸门 + 质量趋势](docs/shot_pipeline.png)

---

## 值得单独说的几件事

### 条目化世界书引擎 `app/wb.py`

整本设定字符串塞进 prompt，是长篇写到中后期崩掉的头号原因 —— 预算不够就截断，
截断就丢规则。这里改成条目级：

- `parse(doc)` 兼容四种现存写法（粗体反哺行 / `### 名` + 属性行 / `- 名：述` / 表格行），同名条目按「归一化名#节」合并
- 每条有稳定 `id` 与 `content_hash` —— 能区分「条目还在但内容变了」
- `assemble(proj, num, budget, preset=…, phase=…, anchors=…)` 按优先级入预算：
  **常驻 > 本章命中 > 近章登记 > 节权重**，返回 `activated` / `dropped` 留痕
- 选择顺序 ≠ 渲染顺序：注入按优先级挑，输出恒按文件原序（避免同一章每次读到的设定顺序都不同）
- 快速路径不变式：整本装得进预算时逐字返回原文件

### 契约与代价：正则 must 级

设定里的硬规则写成 `规则描述｜level：must｜scope：全书`。must 级规则会：

- 注入正文 prompt 的【正则约束】块，并要求**逐条给出本章落点**
- 给不出落点、又与本章事件冲突时，Agent 必须先问你，不得自行绕开
- 进审校维 D 因果对账，违反即 fail

「主角每次改命必须索回代价」这种话，不该只靠模型心情。

### 三层审校

| 层 | 成本 | 作用 |
|---|---|---|
| **L0 确定性预检** `app/core/scan.py` | 零 | 专名错乱、≥15 字重复串、数字矛盾、钩子缺失、术语漂移 —— 先拦硬伤 |
| **6 维 LLM 终审** | 审校槽 | 黄金开章 / 爽点闭环 / 金手指一致 / 因果对账 / 人物弧光 / 钩子 |
| **引证验真 + 投票** | 同上 | 每条问题必须带原文引证，规范化子串 + 种子锚定模糊匹配；**验真失败的引证降级为 marginal 且不进修复环**。k=3 投票取维级众数，平票从严 |

第三层是为了解决一个很烦的实际问题：审校模型会**编造引证**。
编出来的「原文」根本不在正文里，修复环照着改就永远改不完。

### 剧情反哺

正文阶段模型常会冒出细纲里没写的新设定。反哺链把它接住：

```
锁定章节 → MemoryBackflowWorker 提取
   ├─ 新实体 / 新规则 → 幂等写入世界书「## 追加登记」分区（原位合并，保留首见章号）
   ├─ 伏笔变动       → 更新追踪表（新增去重，回收只命中未回收行）
   ├─ 偏离点         → 转 marginal findings 登记
   └─ 一句话摘要     → 进摘要链
```

世界书被人工改过之后，已锁定章节会收到影响提示（建议显式解锁复核），未锁定章节按新契约续写。

### 章级配置快照与「固化为模板」

每章生成时落 `正文/.annotations/第N.json`：预设、采样、分相位参数、
本章实际激活/丢弃了哪些世界书条目、每次 LLM 调用的 slot/model/prompt_hash。
**不进 state.json**，所以不会把状态文件撑爆。

队列里右键「查看生成配置…」可以看到某章到底是怎么长出来的，
满意就「固化为模板」—— 把这一章的两层参数存成用户预设，下本书直接复用。

### 提示词装配基线（防「悄悄丢字段」）

`tests/probe_prompt_baseline.py` 在固定夹具书下录 43 个装配点 prompt 的 sha256。
改装配必须显式 `--update-baseline`，否则红。

配套 `wiring_check()` 做**正例断言**：填了值的预设字段必须出现在承载它的 prompt 里，
缺槽即 `WIRING FAIL`。动机很实在 —— 曾有一个 `deslop_extra` 字段是零调用死字段，
84–238 字的题材腔调配额从每一张正文 prompt 里静默消失，而字节基线永远测不出来。

---

## 界面

| | |
|---|---|
| **书架** 多书管理、新建时选题材预设 | ![书架](docs/shot_shelf.png) |
| **章节队列** 状态徽标、过期结论提示、待修汇总与一键修复 | ![章节](docs/shot_chapters.png) |
| **预设库** 10 套内置 + 自定义导入导出、6 阶段提示预览 | ![预设库](docs/shot_library.png) |
| **设置** 多连接档案、写作/辅助/审校三槽位路由、采样参数 | ![设置](docs/shot_settings.png) |

阅读器：全屏沉浸（F5）、3 主题（夜间/羊皮纸/纯白，Ctrl+T 循环）、
选中标注三色高亮 + 批注 + 灵感直通创作笔记、每章位置记忆、多书签。

版本：保存驱动 —— 只有点「保存」才产生版本（30 版/章，diff 与回退），
5s 防抖草稿暂存 + 崩溃恢复。导出 txt / epub，项目 zip 一键备份 + 每日自动备份。

---

## 从源码运行

```bash
git clone https://github.com/GLFzr/QianBi-Novel.git
cd QianBi-Novel
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python run.py
```

首次启动在「设置 → 连接与模型」填 API Key。
**Key 存进 Windows 凭据管理器**（`app/secrets.py`），`config.json` 里只留指纹，不落明文；
崩溃 dump、日志、遥测出口统一脱敏。

> **提示词适配范围**：内置 prompt 工程（正文/去味/审校等）按 **DeepSeek API** 的
> thinking / reasoning_effort / 参数习惯调校。内置官方预设只有 DeepSeek 官方与 OpenCode Go 官方两家；
> 其余（中转、本地 Ollama / LM Studio）可用「自定义（OpenAI 兼容）」接入，
> 但写作质量与闸门稳定性可能打折。

---

## 测试

```bash
# 离线单测（无需 API Key，约 2 秒）
.venv/Scripts/python -m pytest tests/unit -q        # 316 项

# 离线探针：真实 Bridge + QML 无头驱动，覆盖闸门/锁定/反哺/接力/导出等链路
.venv/Scripts/python tests/probe_agent_relay.py
.venv/Scripts/python tests/probe_word_block.py
.venv/Scripts/python tests/probe_backflow_chain.py
# …… 共 35 个 probe_*.py
```

| 探针 | 覆盖 |
|---|---|
| `probe_prompt_baseline.py` | 43 个装配点 prompt 摘要 + 预设字段接线正例断言 |
| `probe_agent_relay.py` | 共写接力编排：每 Agent 只注入上环节产物、Supervisor 上下文上限、锁定触发点 |
| `probe_word_block.py` | 字数闸门、锁定拦截、强锁留痕、陈旧队列 |
| `probe_backflow_chain.py` | 反哺全链路：幂等、外部直改、缺细纲、中断、补跑队列 |
| `probe_packaged.py` | 打包态资源清单审计 + 开发态/打包态装配摘要对拍 |
| `probe_panel_fit.py` | 六面板横溢/纵溢/压扁/越界 |

**真实 LLM e2e**（需 Key，约 20 分钟 / ¥0.07 量级）：

```bash
.venv/Scripts/python tests/test_5ch_e2e.py
```

---

## 项目结构

```
app/
  wb.py                 ★ 条目化世界书引擎（parse / assemble）
  secrets.py            ★ API Key 入凭据管理器 + 统一脱敏
  selftest.py           ★ 打包态自检（导入/资源/装配摘要/QML 装载）
  usage.py              token 与成本计量
  update_check.py       GitHub Releases 检查更新
  singleinstance.py     单实例锁（二次启动唤起既有窗口）
  crash.py / logger.py / diagnostics.py / telemetry.py
  config.py             连接档案 / 槽位路由 / 闸门策略
  project.py            项目读写（设定/大纲/正文/追踪）
  deslop.py             本地 AI 味扫描（零成本）
  export.py             txt / epub 导出
  llm/                  OpenAI 兼容客户端（流式/重试/退化档）+ 服务商预设
  prompts/              planning / writing / review / memory / co_writing / scene_cards
  core/
    orchestrator.py     调度（QThread / 断点续跑 / 暂停停止）
    stages.py           阶段实现 + 6 维审校 + 反馈环 + 记录链
    scan.py           ★ L0 确定性预检（双端镜像）
    state.py            断点状态 / 陈旧判定 / 需人工标记
    gates.py            字数 / AI味 / 审校闸门 + 字数预检
    memory.py           摘要链、追踪、反哺写回、世界书修正提案
    versions.py         保存驱动版本（30 版滚动 + diff）
    co_writing.py       共写档状态机
    co_dialogue.py      共写 Worker（Dialogue/Summarize/Readback/Supervisor/Backflow）
  presets/              10 套 v2 题材预设
  ui/
    bridge.py           Python↔QML 桥
    qml/                Main + 6 面板 + Theme（3 主题）
      components/       24 个组件（ReaderView / CwDialogueDock / ReviewIssueDialog / …）
scripts/
  build_release.py      一键发布流水线（质量闸门 → 版本资源 → 打包 → 冒烟 → 摘要对拍）
  dual_sync_check.py    共享层漂移检查（文件级 + 符号级 AST 摘要）
tests/
  unit/                 29 个文件 / 316 项离线单测
  probe_*.py            35 个无头链路探针
  evals/                prompt 装配基线 + 审校金标集
docs/                   设计与计划文档、隐私说明
```

**一本小说在磁盘上**（用户目录，全部本地）：

```
<书名>/
  设定/    题材定位 · 选题信息 · 世界书 · 正则 · 简介与标签 · 世界观/角色/势力/
  大纲/    大纲.md · 单元总纲.md · 细纲_第NNN章.md
  正文/    第NNN章_章名.md
    .versions/     保存驱动版本
    .annotations/  章级生成配置快照 + 批注
    .drafts/       防抖草稿
  追踪/    角色状态 · 伏笔 · 时间线 · 上下文 · 章节摘要 · 全局摘要
  pipeline_state.json
```

---

## 开发

```bash
.venv/Scripts/python scripts/build_release.py     # 完整发布流水线
.venv/Scripts/python scripts/dual_sync_check.py   # 共享层漂移检查
```

本项目与同源的 `qianbi-Novel-TUI`（Textual 终端版）共享业务核心层：
`app/core`、`app/llm`、`app/prompts`、`app/presets` 与 `app/wb.py`。

共享层改动必须双端同步。除了文件级比对，还有**符号级门禁**：
对关键符号做 AST 结构哈希（注释/空行/换行符不计），绕开文件级豁免；
GUI 先行暂不同步的符号要在 `DEFERRED_SYMBOLS` 登记「原因 + TUI 当时水印」——
水印变了说明 TUI 也动过，直接炸。

---

## 隐私与安全

- **数据不出本机**。书稿、配置、版本历史、日志全在 `~/.qianbi_novel/` 与项目目录。
- **API Key 存 Windows 凭据管理器**，配置文件不落明文；日志与崩溃 dump 统一脱敏。
- **遥测默认关闭**，且只写本地文件、不上传。详见 [docs/PRIVACY.md](docs/PRIVACY.md)。
- 依赖与字体第三方声明见 [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md)。

---

## 已知边界

诚实列一下，避免踩坑：

- **仅 Windows 打包**。Linux/macOS 需自行从源码跑，未做发行验证。
- **提示词按 DeepSeek 调校**。换其他家模型时闸门判定会更抖（审校相位已统一低温运行来缓解）。
- **长请求受端点稳定性影响**。部分兼容网关在单次输出较长时会断连，客户端有重试与退化档，
  但换模型/换网关仍可能遇到。
- **流水线没有上游重做环**。改设定后需要手动解锁受影响章节重跑（共写档有对应入口）。
- **`is_chapter_need_human`** 由反馈环写入，但自动档目前不消费它（只作队列标记）。
- 3 轮反馈环不收敛的章节会标记待人工，不会无限重试。

---

## 版本

版本号唯一来源是 `app/__init__.py` 的 `__version__`。
完整变更见 [CHANGELOG.md](CHANGELOG.md)。

| 版本 | 主题 |
|---|---|
| **v0.15.0** | 世界书条目化激活 + 预设组装层（工艺卡/分相位采样/章级快照/固化为模板）+ 审核三层 + 剧情反哺 + 字数闸门 + 打包一致性门禁 |
| v0.14.0 | 商业化封装：安装器与便携包、单实例锁、崩溃处理、Key 入凭据管理器、检查更新、首启向导 |
| v0.13.0 | TUI 优势功能完整移植：10 套 v2 预设、6 维终审 + 反馈环、6 类场景卡、3 主题 |

---

## License

MIT License © 2026 GLFzr
