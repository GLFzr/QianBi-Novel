# Plan C · 生态与发布落地：skill 仓施工 + 物料防腐 + 渠道执行 + 0.21 发版 Runbook

> 锚点：**HEAD 2de3e9d5f74d0a01928ba739b150a43d7eeb2daa = v0.20.1**（本代理 2026-09-29 复核通过；`app/__init__.py:9`=0.20.1，根 `latest.json` 仍 0.20.0——漂移活体，发版日刷新）。
> 输入：w3_skill_export / w4_growth / w4_docs / w5_update / w5_copyright / plan_a_construction（更新链+文档防腐批次卡）/ 蓝图 v1 §4；样例包实物 `_scratch/superiter/skill_export_mvp/`（实测 21 文件：5 顶层 + 3×3 skill 三件套 + 7 金标夹具；任务书「13 文件」为目录条目口径）。
> 纪律：主仓与 qianbi-promo 只读已遵守（本文件是唯一产出）；本文是**所有者/施工批的执行清单**，不改代码。
> 衔接：本文填 plan_a 缺口 **G5**（SKILL-S 触点）与 **G6**（PROMO 防腐触点清单）；细化 C03（check_docs 五项）、C13（排障页 13 条）、C09（M-CI/M-SCH 发版侧消费方式）、C18（0.21 发版准备）、C28（skill 包 S 件）。不重复 plan A 已定批次顺序。

---

## §0 合规闸门（横切：每个交付物过此门后才可发布）

### 0.1 三层分级（w5_copyright §3 裁决原文套用）

| 层 | 内容 | 对发布动作的含义 |
|---|---|---|
| **绿**（可随发行物分发） | 拆解框架分类学/36 码表本体/schema、L1 统计的**形式化带宽结论**（不带书名）、自创规则与阈值、公版语料（corpus_pd） | 可进 skill 包 / README / 视频 / 帖子 |
| **黄**（仅本地，不入仓不分发） | 逐书 L1 画像 8 份、L2/L3 批注与节引、拆解稿底稿、_scratch 各波报告、七书→预设映射表 | 永不出现在发布物料、截图、demo 里 |
| **红**（绝不能进任何发行物） | 14,547 个原文章文件、逐章 manifest 全量、≥短句原文连续片段、`H:\番\` 母本（连路径都不出现） | 物料截图/录屏前必须核对画面与文件树 |

### 0.2 逐交付物绿档检查表（发布前逐项打勾）

**A. skill 包（qianbi-skills）**
- [ ] 包内零语料派生物：无逐书数值表、无书名×统计绑定表、无原文片段（grep 书名七件 + 抽 13 字 n-gram 抽查）
- [ ] lieflat 衍生方法论走「自研转述 + attribution」：rule-basis.md 与 README **双处**写明上游链 `shiujan/less-ai-tone (MIT) → qianbi 衍生 → 本包`，附上游仓库链接；**不整体再分发其 SKILL.md 原文**；PolyForm Noncommercial 同系列另两件零携带
- [ ] LICENSE = MIT (c) 2026 GLFzr（与主仓 `qianbi-novel/LICENSE:1-4` 同文），diff 一致
- [ ] 三个 SKILL.md 边界节在位：「不承诺通过任何 AIGC 检测器」「不碰非中文虚构文本」
- [ ] 引流位仅文档层（SKILL.md 末节环境与故障一行 + README 对照表），报告产物无水印/广告行

**B. README（主仓重构后）**
- [ ] 「方法论来源与语料合规声明」节落位（模板见 0.4）；不带书名总览表（G2 保守版；若所有者裁决带书名则声明后追加书目行）
- [ ] 零检测器百分比（grep `朱雀|检测率|AIGC 检测` 零命中或仅出现在免责句）；94-96% 必带「同带对照口径」括号；¥0.25 必带「13 章离峰真跑」口径
- [ ] 已知边界 10 条原样保留（信任资产，禁动）

**C. 视频（54.6s 品牌片 + 8 分钟演示片 + 切片）**
- [ ] 无版本号硬编码、无检测器字样、成本数字带口径括号（§2 逐项）
- [ ] 录屏画面不含 `网文拆解/`、`H:\番`、黄层画像文件（录前关窗口、查文件树）

**D. 渠道帖（linux.do/V2EX/知乎/B 站）**
- [ ] 零检测率承诺：不提任何检测器通过率；标准答复「不承诺检测器数字，承诺每一处可定位可复检」
- [ ] 章数修辞禁用：「300 章不崩」只在 README 已有修辞位置复述，**不进任何渠道标题**（蓝图 §7-4；T3 重跑数据出来前）
- [ ] 竞品可引公开 issue 号，不写「吊打/碾压」；「数据开放」一格主动打平
- [ ] 不做互 star；不承诺修复只承诺响应（48h）

### 0.3 口径钉死（防「数字打架」，蓝图 §6 表延伸）

| 数字 | 唯一口径 | 备注 |
|---|---|---|
| 主仓测试 | 1132 单测（`pytest tests/unit --collect-only -q`）+ 50 探针（`ls tests/probe_*.py \| wc -l`） | 1061/1122/594/49 全是腐烂值，check_docs 抓 |
| deslop 规则数 | 主仓 28 个 rule id（行文可「约 30」）；**skill 包是导出子集**（金标 16 命中口径），两套数字不得混用 | |
| 成本 | ¥0.25/章 = v0.19.8 同书 13 章离峰真跑（`CHANGELOG.md:152-154`）；¥0.79 = 0.19.9 时代 28 章口径，二选一统一（§2 P-p4） | |
| 命中率 | 94-96%（同带对照口径），诚实括号不能丢 | |
| 更新通道 | 「4 在线 + 2 本地」（蓝图裁决统一） | |
| 版本锚 | 0.20.1；latest.json 0.20.0 是漂移；发版后刷新 | |

### 0.4 致谢/免责模板落位（goink NOTICE 四位置法）

模板正文用 w5_copyright §5.2 草案原文（「方法论来源与语料合规声明」三段），落位四处：
1. 主仓 README「方法论与语料声明」节（文档导航节之前）；
2. GUI「关于」对话框一行 + 链接（随 DOC-10 内嵌帮助批，T+7）；
3. skill 包 README 底部 + `rule-basis.md` 头部（双重 attribution，T-14 随包发布）；
4. 文档索引页 `docs/README.md` 页脚（T-0 前随索引页）。
另有三件零代码小事归所有者本地执行（不在本计划施工面）：7 份拆解 manifest 增补 license 字段、`docs/小说质量评测标准_v2.md:94` 预留位挂分级引用、主仓夹具改名（已排 plan A C12）。

---

## §1 skill 仓施工：GLFzr/qianbi-skills 完整建仓清单

> 对应 w3 T1-T9；填 plan A 缺口 G5 / 批次 C28。关键路径决策：**T-14 死线用「样例包直发」达成，单源管线随后落主仓**——样例包已在金标夹具上实跑验证（deslop 16 命中 / outline 4 缺陷 / l0 3 发现 / verify 1 不通过），不阻塞在 T1/T2 的导出管线上。

### 1.1 时序总表（w3 T1-T9 → 相对时间点）

| w3 任务 | 内容 | 时点 | 载体 |
|---|---|---|---|
| **T5** | 发布仓建仓 + 样例包直发 + README 实证 + issue 模板 | **T-14（首发）** | qianbi-skills |
| T9 前半 | 方法论引流文《把去 AI 味做成确定性 lint》（带可复现命令 + 真实对照输出） | T-10 ~ T-7 成稿 | 知乎专栏草稿 + linux.do 回帖素材 |
| T1 | 主仓 PR：`skills/` + `scripts/skill_export/extract_sources.py`（AST 抽常量 → sources.json） | T-7 ~ T-3 | 主仓（plan A 插队批，S-M） |
| T2 | build_skills.py 渲染三 skill（生成物与样例等价、重跑幂等） | T-7 ~ T-3 | 主仓 |
| T3 | 金标夹具进主仓 `tests/skill_fixtures/` + 冒烟断言 | T-3 ~ T-1 | 主仓 CI |
| T4 | drift_check + 规范校验 + path-filter 提醒 workflow | T-3 ~ T-1 | 主仓 CI |
| T8 | 主仓 CHANGELOG 模板加「skill 包影响」复选框 + 发版流程一步「跑 build_skills + bump」 | T-1（随 0.21 前流程固化） | 主仓 |
| T6 | deslop 第二批扩容（密度型 10 条，附人类基线数字） | T+7 后 | 主仓→包 |
| T7 | must 正则契约扩展（`--extra-rules`） | T+7 后 | 包 |
| T9 后半 | awesome-claude-code + VoltAgent awesome-agent-skills 投递 | T-0 ~ T+7 | 站外 |

### 1.2 目录结构（照样例包 1:1 映射，实测 21 文件）

```
qianbi-skills/
├── README.md                          # 手写层：安装命令 + 实证 lint 对照 + 「与千笔 GUI 的关系」对照表 + 方法论声明
├── CHANGELOG.md                       # 手写层：每条注明「对应 qianbi-novel ≥x.y.z」
├── LICENSE                            # MIT (c) 2026 GLFzr
├── VERSION                            # 单行 "0.1.0"
├── .claude-plugin/marketplace.json    # 一仓三 skill（样例已备：name qianbi-skills, source ./, skills 三目录）
├── qianbi-deslop/{SKILL.md, scripts/deslop_check.py, references/rule-basis.md}
├── qianbi-outline-check/{SKILL.md, scripts/outline_check.py, references/outline-contract.md}
├── qianbi-consistency-audit/{SKILL.md, scripts/l0_scan.py, references/audit-schema.md}
├── tests/                             # 金标夹具 7 件（deslop_sample / outline_sample / consistency_ch13+ch14+roster+ledger+quotes.json）
└── .github/workflows/ci.yml           # §1.4
scripts/（仓内新增，2 件）
├── check_spec.py                      # 规范校验（§1.4 job spec）
├── run_fixtures.py                    # 金标冒烟断言（§1.4 job smoke）
└── sync_check.py                      # 单源落地后的反向同步检查（§1.4 job sync-check，T1/T2 落地后启用）
```
前置校验（建仓前一次）：`npx skills add` 本地路径装一次冒烟；SKILL.md frontmatter 只用 agentskills 规范 6 字段（多一个键 CC 打包即报错——w1 实证），name==父目录名，description ≤1024 字符，正文 ≤200 行。

### 1.3 LICENSE 与 attribution 裁决

- 主仓 MIT（实查 `LICENSE:1-4`，Copyright (c) 2026 GLFzr）→ skill 包 MIT 无障碍，接受被搬运（MIT 战略，w3 §5.2）。
- lieflat 上游：`app/prompts/skill_rules.py:14-16` 实查上游 less-ai-tone 为 MIT (c) 2026 shiujan；同系列另两件 PolyForm Noncommercial **绝不携带**。
- 落法：deslop 的「改写纪律」以自研转述呈现（不搬上游 SKILL.md 原文）；`rule-basis.md` 头部与包 README 底部双处 attribution 链；搬运识别靠 `metadata.qianbi` 锚点 + CHANGELOG 对账。

### 1.4 CI 设计（drift check 与金标冒烟怎么接）

两阶段：**阶段一（T-14 首发，本仓独立）**只有 spec+smoke；**阶段二（T1/T2 落主仓后）**drift 责任移到主仓 CI（源就在旁边），本仓加反向同步检查。

```yaml
# qianbi-skills/.github/workflows/ci.yml
name: skills-ci
on: { push: {branches: [main]}, pull_request: {}, workflow_dispatch: {}, schedule: [{cron: "0 3 * * 1"}] }
jobs:
  spec:            # 阶段一起
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: python scripts/check_spec.py
      # 规则：frontmatter 仅 6 字段白名单(name/description/license/compatibility/metadata/allowed-tools)
      #      name==父目录名；name≤64 合法字符；description≤1024（CC 截断 1536 留余量）；正文<500 行
  smoke:           # 阶段一起：金标冒烟（=w3 §1.4 CI 第 3 步，夹具随仓走，零网络零依赖）
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: python scripts/run_fixtures.py
      # 断言（照样例包实测值钉死）：deslop_sample→16 blocking 全命中；outline_sample→4 类缺陷全抓；
      # consistency_ch13/14→L0-NAME blocking+L0-NUM advisory+L0-HOOK blocking；
      # --verify quotes.json→伪造引证判不通过退出码 1
  sync-check:      # 阶段二（主仓 skills/ 单源落地后启用）：发布视图 ≠ 单源即红
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/sync_check.py
      # 实现：urllib(ProxyHandler({})) 拉 https://api.github.com/repos/GLFzr/qianbi-novel/tarball/main
      # → 抽 skills/ 子树 → 与本仓三 skill 目录逐字节 diff（手写层 README/CHANGELOG/LICENSE/VERSION 豁免）
      # → 不一致=FAIL（本仓落后于主仓单源，提醒重导出重发）
```

**主仓侧 drift check**（T4，落主仓 `.github/workflows/tests.yml` 新 job 或复用现 job 尾步；此时源与生成物同仓，无需网络）：
`python scripts/skill_export/build_skills.py && git diff --exit-code skills/`——改了源没重导出即红。**定位主仓抽源**的答案：drift check 的「抽源」动作发生在主仓 CI（`extract_sources.py` 对本地 `app/deslop.py` 等 5 文件 import/AST 抽取，见 w3 §1.3 技术决策），qianbi-skills 仓不做抽源、只做「与主仓 skills/ 发布视图比对」的反向检查（sync-check，API 直连在 Actions 天然可用）。path-filter（`app/deslop.py`、`app/core/scan.py`、`app/core/l0_checks.py`、`app/prompts/planning.py`、`app/core/satisfaction.py`）命中即打「需同步 skill」label；语义变化=minor、新增规则=minor、阈值/文案=patch。

### 1.5 发版流程（semver + VERSION + CHANGELOG）

- 版本三处同步：根 `VERSION` + `marketplace.json` plugins[0].version + 各 SKILL.md frontmatter `metadata.version`（同一字符串，check_spec.py 顺带断言三处相等）。
- semver 规则（w3 §1.4）：规则语义变化=minor；新增规则=minor；阈值调参/文案=patch；主仓大版本不必然带动（只随 5 个源文件变更走）。
- 每次发版固定序列：改源（主仓）→ build 幂等重跑 → 夹具冒烟绿 → bump 三处 + CHANGELOG（注「对应 qianbi ≥x.y.z」）→ commit → tag → release（命令见 §1.6）→ 主仓 CHANGELOG「skill 包影响」复选框核对（T8）。

### 1.6 首次发布 step-by-step（gh 命令原文；所有者亲自）

环境事实：本机 git 全局代理 127.0.0.1:7897 常不在跑 → 推送一律 `git -c http.proxy= -c https.proxy= push …`；**若首推已含 `.github/workflows/`，改用 `env -u GITHUB_TOKEN -u GH_TOKEN git push …`**；GitHub API 直连可用（urllib+`ProxyHandler({})`，参照 `_scratch/gh_search.py`）。

```bash
# 0) 样例包就位（从 scratch 复制，唯一写入点）
mkdir qianbi-skills && cp -r "G:/ai/酒馆/_scratch/superiter/skill_export_mvp/." qianbi-skills/
cd qianbi-skills && mkdir -p scripts   # 补 §1.4 三脚本后进 git

# 1) 建仓（所有者账号）
gh repo create GLFzr/qianbi-skills --public \
  --description "千笔网文方法论 skill 包：去AI味 lint / 细纲契约校验 / 一致性审计（确定性脚本+引证验真，纯 stdlib 零依赖）" \
  --homepage "https://github.com/GLFzr/qianbi-novel"

# 2) 首推（含 workflow 文件 → 用 env -u 形式）
git init -b main && git add -A && git commit -m "qianbi-skills 0.1.0：三 skill 首发（deslop / outline-check / consistency-audit），金标夹具实测通过"
git remote add origin https://github.com/GLFzr/qianbi-skills.git
env -u GITHUB_TOKEN -u GH_TOKEN git -c http.proxy= -c https.proxy= push -u origin main

# 3) topics（蹭生态搜索面；品类词给 README 吃，仓库名保品牌）
gh repo edit GLFzr/qianbi-skills --add-topic claude-skills --add-topic novel-writing \
  --add-topic deslop --add-topic chinese-nlp --add-topic webnovel --add-topic writing-tools

# 4) tag + Release
git tag v0.1.0 && env -u GITHUB_TOKEN -u GH_TOKEN git -c http.proxy= -c https.proxy= push origin v0.1.0
gh release create v0.1.0 --title "qianbi-skills 0.1.0（对应 qianbi-novel ≥0.20.0）" --notes CHANGELOG.md

# 5) 安装验收（w3 T5 判据，两路都要过）
npx skills add GLFzr/qianbi-skills -y          # Skills CLI（CC/ZCode 等）
# Claude Code 内：/plugin marketplace add GLFzr/qianbi-skills → /plugin install qianbi-skills@qianbi-skills
# 本地冒烟：python qianbi-deslop/scripts/deslop_check.py tests/deslop_sample.txt → 16 blocking
```

收尾：issue 模板一件（正文强制「先贴脚本原始输出」+ 环境/客户端版本）；README 底部挂「同源桌面应用 → qianbi-novel」链接；主仓 README 加一行「方法论 skill 包见 →」（随文档重构节 13 导航）。验收信号：首周 skill 仓 ≥10★（蓄水信号，w4_growth §5.1）。

---

## §2 发布物料防腐与重建施工

> 对应 w4_growth §2.2 腐蚀清单 + w4_docs 全文；填 plan A 缺口 G6，细化 C03/C13。所有行号 2026-09-29 实查（样例包同日复核）。

### 2.1 qianbi-promo 逐项修法（P-p1~p6 全部 T-0 前必须；合计 0.5 天）

| # | 位置（实查） | 现状 | 修法 | 验收 |
|---|---|---|---|---|
| P-p1 | `src/scenes/SceneProduct.tsx:130` | 「版本 0.19.9，公测进行中。」 | **删版本号**（版本号会一直腐烂）：改「公测进行中。」或整行删 | 渲染帧无版本字样 |
| P-p2 | `src/scenes/SceneCTA.tsx:121` | 「版本 0.19.9，MIT 开源，Windows 10/11 可用。」 | 改「MIT 开源 · Windows 10/11 可用。」 | 同上 |
| P-p3 | `src/components.tsx:173` | 片头印章「版本 0.19.9」 | 删版本行，印章只留品牌字 | 同上 |
| P-p4 | `src/scenes/SceneVersion.tsx:87,122` | `useCountUp(0.79,…)` + 「新书 28 章试跑，全部笔次成本」 | **推荐 A**：统一 README 主口径——`useCountUp(0.25,74,42,2)`，文案改「13 章离峰真跑，每章全链成本」（口径括号纪律）；**备选 B**：保留 ¥0.79 但 label 补「（28 章合计 · 0.19.9 实测）」 | 与当日 README/帖文数字同口径，无双口径同屏 |
| P-p5 | `src/scenes/SceneVersion.tsx:89,124` | `useCountUp(1100,…)` + 「测试套件，全部通过 N 件」 | **推荐**：value 改字符串「1100+」（防腐下界，视频不可随版本重渲）；或回填 1132 并在发布日核对 | 视频数字 ≥ 实际且不随时间变谎 |
| P-p6 | `public/shot_{co_writing,library,pipeline}.png`（mtime 2026-09-19，0.19 UI） | 三张旧截图 | `probe_ui_gallery` 重截 0.20 共写六阶段版，覆盖 public/ 同名文件（分辨率 1920×1080 对齐） | 截图 UI 与 0.21 当日一致 |
| P-g2 | promo `README.md`（仍 Remotion 脚手架默认） | 未写用途 | 补三段：这是什么（54.6s 品牌片工程）/ `npm run dev` / `npx remotion render` 输出与发布位 | 新人可复现渲染 |
| P-g3 | 投稿文案包 | 无 | 按 §3 渠道清单产出各渠道标题+正文包（存 promo 仓 `copy/` 或 scratch） | 五渠道每渠道一文件 |

防腐纪律（写进 promo README）：**视频里永不放版本号与逐周腐烂数字**；要数字只放下界式（「1100+」）或带口径的比例句。8 分钟演示片（P-g4）按 w4_growth §5.3 脚本录制：**T-0 前尽力争成，最迟 T+7**——不阻塞 T-0 引爆（B 站 T-0 位由 54.6s 品牌片占住）。渲染验收：`npx remotion render` 出片 + 全片无「0.19.9」+ 帧质检两轮流程沿用。

### 2.2 主仓 README 重构：13 节骨架 → 有序任务（w4_docs §2.5 落地卡）

| 节 | 内容 | 素材来源 | 验收 | 时点 |
|---|---|---|---|---|
| 1 | 标题+徽章+一句话定位+痛点宣言 ≤5 行 | 现 `README.md:10-14` 保留让位（不重写） | 前 30 行对照 w4_docs §2.1 拟骨架 | **T-0 前** |
| 2 | 数字证据条 6 卡 | ¥0.25=`CHANGELOG.md:152-154`；94-96% 带口径（`docs/论文_前缀缓存命中率工程_实证研究.md:21,263`）；1132/50=两条命令；6 通道+Ed25519（`update_check.py:58-65,45-47`）；全本地=PRIVACY.md；5 分钟演示=`app/ui/demo_pack.py:40-48` | check_docs 检查 1 绿；无「205 源码文件」类不可复现数 | **T-0 前** |
| 3 | hero 图去重 | hero 位换 `docs/shot_pipeline.png`；`hero_cw.png`≡`shot_co_writing.png`（SHA256 同 339,326B）二选一删 | `cmp` 不再 IDENTICAL | **T-0 前** |
| 4 | 3 步开写卡 + 折叠「下载细节」 | w4_docs §2.3 拟卡；SmartScreen 蓝框路径；「先看 5 分钟演示」分流 | 安装门槛小白可走通 | **T-0 前** |
| 5 | 5 分钟无 Key 演示（独立小节，证据链第一环） | `assets/demo`、手册 §1.2 | 节内含「0 元、不用装对吧（源码 run.py 也行）」 | **T-0 前** |
| 6 | 卖点 15→8 条 | 世界书/must 契约/三层审校/剧情反哺/共写六阶段/Agent 操作层/成本架构/BYOK | 合并后无信息丢失（导入/预设/快照并子句） | **T-0 前** |
| 7 | 对比表加「skill 插件类」第四列 | w4_docs §2.4 表格原文 | 措辞纪律：不贬低、数据格打平、issue 号可引 | **T-0 前** |
| 8 | 证据链区块（产出物三样例 + usage.jsonl 三行账本） | examples/minimal-book.md、门停靠三件套（`bridge.py:4483-4562`）、`docs/成本台账.md` | 每样例注明仓库出处文件 | 可 T+7（0.21.x） |
| 9 | 两档与微循环 | 保留现结构 | 零改动 | — |
| 10 | 更新与数据安全 | README:91/96 口径改「4 在线+2 本地」（**T-0 前**）；「全程不用离开应用」句**等 U-A 静默版落地才许写**（plan A C22）；50 行长文下沉 `docs/更新与数据安全.md`（可 T+7） | 口径与蓝图 §6 表一致 | 拆分 |
| 11 | 测试与开发（修数字） | 1061→1132（`:383`）、探针 50 | check_docs 检查 1 绿 | **T-0 前** |
| 12 | 已知边界 10 条 | **原样保留** | diff 为空 | — |
| 13 | 文档导航三栏 + skill 包一行 | 新作者→手册/排障页；老手→examples/术语表；开发者→CONTRIBUTING/裁决/台账 | 三栏齐 + 「方法论 skill 包见 →」 | **T-0 前** |

EN 同步（QW-D4/C04）：数字（594→1132、44→50）+「V4 Pro」死文清零 + 顶部滞后声明——**T-0 前**；EN 首屏三节重写可 T+7。体量纪律：砍更新长文与卖点冗余 ≈80 行、加证据条/演示/skill 列 ≈60 行，总 ~620 行不膨胀。

### 2.3 check_docs.py 五项检查规格（plan A C03 施工面细化）

```python
# scripts/check_docs.py —— 五项检查，全部红/绿可判定；退出码非 0 即红
# 1 数字口径核对：真值 = pytest tests/unit --collect-only -q（解析 collected 数）
#    与 ls tests/probe_*.py | wc -l；正则抽取 README.md / README.en.md / latest.json
#    中「N 项测试 / N passed / N 支探针 / collected N」→ 不一致即红（当场抓 1061/1122/594/49）
# 2 面板覆盖核对：find app/ui/qml -name "*.qml" 取 objectName 生成 42 项清单；
#    手册各章 front-matter panels:[...] 比对输出未覆盖红名单（判据 C 专用，v2 前先空转报 SKIP）
# 3 内链核对：扫三份 README + 手册 + 排障页全部 ](xxx.md) 相对链接，目标不存在即红
# 4 手册行数下限：用户手册_v2.md ≥500 行（v2 未建前报 SKIP 不报红）
# 5 排障表条数 ≥10（数表行）+ 排障页出现的报错文案必须能在 app/ 源码 grep 到
#    （防文档文案与屏幕文案漂移——排障页生命线）
```
接入：`.github/workflows/tests.yml` 现 job 尾部加一步（不新开 job）+ `scripts/build_release.py` 六道闸后加第 7 道「文档口径」。验收：CI 红绿各演示一次（临时改坏一个数字验红）。根治（可 T+7，M）：`bump_readme_numbers.py` 发布流水线自动回填。

### 2.4 排障页 v1：13 条素材落位（plan A C13；文案逐字抄代码）

结构=每条「你看到什么（屏幕原文）→ 意味着什么 → 现在做什么 → 还不行→报障包」。A 组 13 条来源：

| # | 屏幕文案 | 来源（grep 锚） |
|---|---|---|
| 1 | SmartScreen「已保护你的电脑」 | README:114-118、手册 Q1 |
| 2 | 「这条连接还没选模型——…」 | `app/llm/client.py:461,614` |
| 3 | 「请求超时…」 | `client.py:551,740` |
| 4 | 「接口地址为空…」 | `client.py:795` |
| 5 | 「不支持『xx:』协议…」 | `client.py:807` |
| 6 | 「域名解析失败…」 | `client.py:812`、README:366-367 |
| 7 | 401（路径对、只差鉴权） | README:366-367 |
| 8 | 更新面板逐条死因四通道 | README:96-101、手册 Q4 |
| 9 | 「保存失败：磁盘回读与内容不一致…」 | `app/ui/bridge.py:2649` |
| 10 | 崩溃/断电后再开（断点续跑） | 手册 Q9、`app/crash.py` |
| 11 | 审校 REJECT 三轮不收敛→待人工 | README:585-586、手册 §5.3 |
| 12 | 共写档点「开始」被拦 | `bridge.py:1292-1294 vs 1392-1394` |
| 13 | 首启动无网等待 | README:120-122 |

B 组三件套（logs 滚动 2MB×5 / crashes dump / 报障包两档脱敏）独立节；C 组=w1_ux 22 行摩擦表过筛，「指路型」进页、「产品 bug」标注不拿文档糊弄。验收：≥10 条、每条文案可 `grep` 到 `app/`、报障包出口每条末尾。**T-0 前必须**（判据 C 第三要件；w5_update DOC 行的「更新条目」在 U-A 落地后追加）。同批：`docs/README.md` 索引页（三类读者导航 + 79 份工程文档收折叠区 + §0.4 声明页脚）。

### 2.5 时点标注总表

**T-0 前必须**：P-p1~p6、promo README、文案包、8 分钟片（软性，最迟 T+7）、README 节 1-7/11/13、EN 数字、check_docs 五项、排障页 v1、docs/README.md 索引、hero 去重、social preview 确认、徽章+topics、主仓 skill 管线 T1-T4/T8。
**可 T+7**：README 节 8（证据链区块）、节 10 长文下沉、手册 v2、内嵌帮助（随包 HTML+F1）、首屏 GIF、Pages 目录页、bump 自动回填、deslop 第二批扩容（T6）、must 扩展（T7）、竖版切片、小红书卡、即刻图文。

---

## §3 渠道执行清单（谁执行：**全部所有者亲自**，R6 铁律）

> 裁决两处报告冲突：① V2EX 只发一次——首帖放 **T-0**（w4_growth §4.2「30 天内勿重复发帖」红线压过 §5.1 预热清单里的 V2EX 项；预热期 V2EX 仅回帖养号）；② 8 分钟演示片 T-0 前力争、最迟 T+7（§4.2 与 §5.1 折中）。

### 3.1 linux.do（流派母社区；发源帖实证 webnovel-writer README:365 → 帖 1397944）

- **T-14 回源帖**：以作者身份在 1397944 等帖内回帖——内容=《把去 AI 味做成确定性 lint》方法论 + 3 组改前/改后真实对照 + skill 仓链接（分享>推销，先给方法再给工具）。
- **T-0 独立发帖（北京 15-17 点）**：经验分享长帖「我用 4 个月把提示词流水线做成双击即用的桌面应用」+ 架构图 + 成本账本截图 + 54.6s 品牌片；帖内互链 GitHub/知乎。
- 红线：L 站反感硬广与营销腔；新号先 genuine 参与 1-2 周（养号从 T-28 起）。
- 验收：回帖/发帖存活未被删；首周帖内回复 ≥5 条且有技术问；skill 对照被引用。
- **T+14~ 双周更**：每篇证据链内容在原帖跟评（L 站算法吃回帖，保持活性）。

### 3.2 V2EX（/go/share 分享创造）

- **T-0 一帖**：标题打「工程」不打「小说」——「千笔一文：把『写到 300 章设定不崩』做成确定性流水线（开源）」；正文=①钩子（成本+去味）→①证据（工程叙事+台账截图）→③收尾（作者在环）；附 GitHub+视频。
- 红线：网文轻视链→用「长篇创作/工程」措辞；同一项目 30 天内不重复发帖；每条技术回复 24h 内自答（周内持续）。
- 验收：帖进 /go/share 首页；周内回复 ≥10 且无删帖。

### 3.3 知乎

- **T-10 起每周 1 答**：锚定高流量问题（「AI 写小说工具哪个好」「长篇小说 AI 一致性」）；回答末尾自然带 repo，不做首答导流；首个回答可提前到 T-7。
- **T-0 专栏长文**：《我们把「写到 300 章不崩」做成了一条流水线》（复用 README 工程叙事 + 台账截图 + 可复现命令）。
- 红线：折叠机制严格→真实干货比；**检测器类问题只讲机制不讲百分比**。
- 验收：专栏文不被折叠；月内回答累计赞同 ≥20；文内命令有人照跑并反馈。

### 3.4 B 站

- **T-0**：54.6s 品牌片上传（简介区放时间轴章节 + repo 链接 + 「工具实测」定位）。
- **T+7 前**：8 分钟演示长片（w4_growth §5.3 九幕脚本；SmartScreen 如实拍是诚实资产）+ 3 条竖版切片（各 30-45s：①拦住 AI 腔的瞬间 ②账本对账 ③长跑书架实拍），另拍不裁切、每条独立可懂。
- 红线：标题禁「AI 写小说日入过万」式词；评论区预期敌意，**只答技术不接骂战**；去 AI 工具盘点类视频下做「工具向」补充（非抢楼）。
- 验收：长片完成率 ≥30%；切片各有独立播放；评论区无失态截图。

### 3.5 GitHub 端（地基动作，T-7 前完成，多为所有者点选）

| 项 | 动作 | 时点 | 验收 |
|---|---|---|---|
| Social preview | Settings→General→Social preview 上传 `docs/social-preview.png`（API 无法验证，必须手动确认） | T-7 | 预览卡出图 |
| Topics | 补 `novel-writing` `fiction` `writing-tools`（skill 仓另挂 `claude-skills`） | T-7 | About 栏可见 |
| 徽章 | 补 Discussions + Release 下载两枚 | T-7 | README 渲染正常 |
| Discussions | 开 3 类目：公告（每次 release cross-post）/ 晒书 / 功能投票（声明不算 roadmap） | T-7 | 类目可见；0.21 发布令同步 cross-post |
| Trending | 不指望自然冲榜：五渠道同日集中引爆（增速窗口），发帖选北京 15:00-23:00，目标发布日 50-100★/天冲日榜尾部二次曝光 | T-0 | 发布周 ★≥60、下载 ≥200（对比 v0.19.9 单版 123 历史峰值） |
| issue SLA | README 已知边界旁加「Bug 报告 48 小时内必回应」（只承诺响应） | T-0 随 README | 行在 |
| 订阅三件套 | `/releases.atom` 链接 + latest.json 可选 `announce` 字段（复用 6 通道）+ Watch Releases 徽章 | T+7 可 | 离线用户也能收公告 |
| 增长台账 | 每周一 10 分钟记 ★/下载/issue+discussion 三数 | T+7 起每周 | docs/增长台账.md 连续 |

### 3.6 渠道红线速查（每帖发布前对表）

零检测率承诺（标准答复语固定）｜章数修辞不进标题｜成本数字带口径括号｜不互 star｜不贬低竞品（issue 号可引）｜只承诺 48h 响应不承诺修复｜L 站分享>推销｜B 站不接骂战｜所有物料发布前过 §0.2 对应绿档表。

**所有者亲自执行项清单（计数）**：① linux.do 回帖 ② linux.do 独立帖 ③ V2EX 帖 ④ 知乎锚定回答（每周）⑤ 知乎专栏文 ⑥ B 站品牌片上传 ⑦ B 站演示片+切片上传 ⑧ social preview 上传确认 ⑨ Discussions 类目配置 ⑩ qianbi-skills 建仓+首推（§1.6） ⑪ VirusTotal 提交 ⑫ 国产杀软三件套实测 ⑬ VM 矩阵 ⑭ 真机矩阵 ⑮ Release 发布令。**共 15 项**（其中 ⑪-⑭ 见 §4）。

---

## §4 0.21 发版日 Runbook（打 tag → 五渠道齐发）

### 4.0 环境事实（每条命令都按此写）

- git 全局代理 `127.0.0.1:7897` 常不在跑 → 推送一律 `git -c http.proxy= -c https.proxy= push origin main`；
- 提交含 workflow 文件时 → `env -u GITHUB_TOKEN -u GH_TOKEN git push`；
- GitHub API 直连可用（urllib + `ProxyHandler({})`，参照 `_scratch/gh_search.py`）；
- 版本唯一来源 `app/__init__.py __version__`； latest.json 改一字节都要重签。

### 4.1 T-7 ~ T-1 准备窗（机器可代办部分由施工批跑，账户动作所有者）

1. C09 已合入（B7 补测 / M-CI `scripts/check_manifest_consistency.py`+release-consistency job / M-SCH stats 回填 / U-C / U-2 修复）——本 runbook 依赖它们存在；未合入则 §4.3 步 8/9 降级为手工三通道核对并在发布说明如实注记。
2. `check_docs.py` 全绿（第 7 道闸就位）；README 13 节 T-0 前任务全部落地；EN 数字同步。
3. 文案包终稿（五渠道）+ §0.2 绿档表逐张过；skill 仓已发（T-14）且首周 ★ 核对。
4. VM 快照刷新为干净 Win11；国产杀软三件套环境备好；预留所有者 T-1 整段时段。

### 4.2 T-1 构建与真机日

5. 版本收口：`app/__init__.py` → 0.21.0；CHANGELOG 补条目（含「skill 包影响」复选框，T8）。
6. 全量闸门（=release_checklist §1）：`pytest tests/unit -q` 全绿（基线 1132+）；探针舰队离线子集逐支 rc=0 读 PROBE_DONE；`probe_prompt_baseline` **零漂移**；`probe_qml_compile`；六道发版闸门（probe_prompt_baseline / probe_qml_compile / `tools/audit_tokens.py` / `scripts/update_keys.py --check-repo` / probe_update_ui 46 项 / probe_conn_delete）；涉流水线改动 → ≥3 章真机小 e2e 产物留档。**禁止 `--skip-tests` / `--skip-probe`。**
7. `python scripts/build_release.py`：质量闸门后 stats 自动回填（unit_tests=collect-only 实数、probes=探针名单、collected_at）；notes **删内嵌测试数字**改人写散文；installed_size 回填；先写盘后 Ed25519 签名；`sign_manifest.py --verify latest.json` = VERIFY OK + 反向验证（篡改 version 一字节必须 FAIL）；CI 断言顶层 sha256==assets.setup.sha256（老客户端兼容双写）。onedir 体积记录进发版说明。
8. 杀软预检（所有者）：VT 上传查看检出；≥2 家检出 → 先复检 → 微软提交误报 → 等候选再发；360/火绒/腾讯实装实测。未配签名证书 → 流水线 `[SKIP]` 照常出包，**README/更新面板/Release 正文三处必须写明 SmartScreen 点击路径 + SHA256SUMS 核对法**。
9. VM 矩阵（§4 七项）+ 真机矩阵（§5b 八项：安装版空闲/脏稿/便携版无安装钮/旧进程覆盖装/断网离线导入/SmartScreen 实点/陈旧代理/未验签无按钮）逐项打勾。注：静默「0 向导点击」行属 U-A 之后版本（0.22+），本轮按现行向导口径验收。

### 4.3 T-0 发版日（上午机器链 → 下午五渠道）

10. `git status` 干净 → 提交已推送（`git -c http.proxy= -c https.proxy= push origin main`）。
11. 打 tag 并推：`git tag v0.21.0 && git -c http.proxy= -c https.proxy= push origin v0.21.0`（若仓内新增过 workflow 文件改用 `env -u GITHUB_TOKEN -u GH_TOKEN git push`）。
12. `gh release create v0.21.0 --title "v0.21.0 …" --notes-file RELEASE_NOTES.md` 上传 setup.exe / portable.zip / SHA256SUMS / THIRD-PARTY / PRIVACY / LICENSE；Release Notes 沿用 v0.20.0「数字墙」模板（ae5e4dd 已验证）+ SmartScreen 提示句。
13. latest.json 回填推 main（`env -u … git push` 若含 workflow 改动）；`curl -I https://<user>.github.io/<repo>/latest.json` = 200（仓库根 `.nojekyll` 在位）。
14. 三通道一致性（M-CI）：`python scripts/check_manifest_consistency.py`——raw vs Pages vs 本地逐字节一致=PASS；jsDelivr 一致=PASS / 旧版=PASS(WARN，≤12h 追平) / 新版或改写=FAIL；触发 GH Actions release-consistency job 留档。stats 双源核对：latest.json stats.unit_tests==collect-only、probes==`ls tests/probe_*.py | wc -l`。**验收发布生效只看 raw 与 Pages，别用 jsDelivr 判断**（缓存 s-maxage=43200）。
15. Discussions「公告」类目 cross-post 发布令；README 下载徽章自动更新。
16. **15:00-17:00（北京）五渠道齐发**：linux.do 独立帖 → V2EX 帖 → 知乎专栏文 → B 站 54.6s 品牌片 → GitHub Release/trending 窗口；全部互链；文案=②钩子→①证据→③收尾。
17. 晚间首波回评（24h SLA 开跑）；「检测器」问用标准答复语。

### 4.4 T+1 ~ T+7 收尾

18. jsDelivr 追平核对（发布次日）；增长台账首个周一记数；周内每条评论 24h 回；8 分钟演示片完成则补发 B 站（最迟 T+7）；awesome 两目录投递（T9 后半）；skill 包 issue 首扫。

### 4.5 release_checklist 34 个未勾框逐框处置

| 处置 | 框（编号按 §4.2-§4.4 步骤） | 数量 |
|---|---|---|
| **并入 runbook 机器流程**（施工批可执行） | §0 工作树(步10)；§1 探针舰队(步6)、prompt 零漂移(步6)、流水线 e2e(步6)、onedir 体积(步7)、setup sha256 复核(步7)、Pages curl(步13)、raw/Pages 复验(步14)、开机自动检查 probe(步6 探针)、上一版安装包留存(步12 Releases 永存核对) | 10 |
| **并入 runbook 所有者时段**（T-1~T-0） | §1「禁止 --skip-tests」声明(步6)；§3 VT(步8)、误报预案(步8)、国产三件套(步8)、无证书 SmartScreen 文案(步8)；§4 VM 七项(步9)；§5b 真机八项(步9) | 20 |
| **条件豁免 + 理由** | §1 probe_about_ui——0.21 未改关于页（内嵌帮助入口属 DOC-10/T+7 批），改了才跑；§3 代码签名——无证书走 `[SKIP]` 设计路径，证书就绪版本起执行 | 2 |
| **转长期纪律行**（不再勾选） | §1 凭据沙箱——「别拆 probe_guard 沙箱」是永久纪律，每次 pytest 隐含执行，写进 runbook 步 6 备注 | 1 |
| **转应急预案卡**（不占发版日） | §7 清单回指旧版——仅回滚时执行：改回 latest.json → **必须重签** `sign_manifest.py`（未签名回滚清单只显示不安装，缓存重验自愈）；卡片存 docs，随 §7 上一版包留存项年年核对 | 1 |

合计 10+20+2+1+1=34 ✓。0.21 发版后 32 框可在 checklist 打勾（2 框豁免理由随轮次如实注记，沿用 §0.20.0 收口轮的诚实说明格式）。

### 4.6 回滚预案（引用既有设计，零新增基建）

新安装包出问题：① Release 页旧版包永存可下；② updates/ 目录旧 setup 用户盘上就有（U-C 起保留当前+上一版）；③ 重跑同版安装器自愈损坏树（`[InstallDelete]`）；④ 清单回指旧版=重签自愈（4.5 应急卡）。排障页写「完全起不来」三条（卸载→装旧版直链 / updates 目录双击 / 同版重装修复）；边界句「程序可回滚，数据不回滚」进手册。

---

## 附录 A：T-14 → T+14 时间线骨架（与 plan A 批次衔接）

| 时点 | 发布线（本文） | 与施工批衔接（plan A） |
|---|---|---|
| T-28~T-15 | linux.do 养号 | Wave 0 并行 |
| **T-14** | **qianbi-skills 首发建仓（§1.6，所有者 15 项之一）**；skill 引流文成稿启动 | C28 验收点（npx skills add 可装） |
| T-10~T-7 | 知乎首个锚定回答；引流文定稿 | C03 文档止血 / C04 EN 同步同窗 |
| T-7~T-1 | promo 防腐 pass（§2.1）；README 重构 T-0 前节；check_docs+排障页+索引页；8 分钟片录制；GitHub 地基 5 项；主仓 skill 管线 T1-T4/T8 | C03/C13/C09/C28；T1-T4 为新增插队批（主仓，S-M，与 Wave 1 并行安全——只加新目录） |
| **T-0** | **0.21 发版 runbook（§4.3 步 10-17）+ 五渠道齐发** | C18 发版准备收口；六道闸+第 7 道文档口径闸 |
| T+1~T+7 | 24h 回评 SLA；jsDelivr 追平；8 分钟片补发；awesome 投递；增长台账首记 | — |
| T+7~T+14 | 竖版切片 ×3 / 即刻 / 小红书 / README 证据链区块 | C19-C22 静默安装+回滚批（Wave 2）可与放量并行 |
| T+14~T+90 | 证据链双周更（固定双周一 10:00；长跑台账/成本月报/用户进度） | T3 重跑数据（C45）出数后解禁章数修辞 |

## 附录 B：指标对账（w4_growth §6.3 目标，非预测）

30 天：★100-150（发布周 ≥60）、issue ≥5、Discussions ≥8、下载 ≥600；北极星=非作者提交 issue/discussion 占比 >50%；反目标=不做互 star。失守即渠道判断证伪信号。
