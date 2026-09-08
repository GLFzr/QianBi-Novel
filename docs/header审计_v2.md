# project_header 利用率审计（W0.6 · 成本优化战役 v2）

本文件由 `scripts/header_audit.py` 产出（幂等可复跑，不含时间戳；复跑：`cd G:\ai\酒馆\qianbi-novel && .venv/Scripts/python.exe scripts/header_audit.py`）。
对照对象：deepseek-harness 社区审计 #2064——tool schemas 占前缀 86%，其中一半根本用不到。本项目没有工具表，对应物是 **project_header 的设定全家桶**。本审计回答：头部六块各被谁真正消费，谁是无用块。

## 1. 口径与夹具

**数字口径**：
- 字符数 = Python `len()`（含空白与 markdown 标记的原始字符）；
- 估算 token = **中文字符数 × 0.6**（粗估口径，非中文字符与空白不计入；DeepSeek 实际分词与公式有 ±20% 量级偏差，正则/表格等 ASCII 密集块会低估，只用于块间量级比较，精确值以 usage.jsonl 实测为准）；
- 占比 = 块字符数 / 头部总字符数。

**夹具最小集**（先读代码确认）：`project_header` 的读取路径 = `设定/题材定位.md`（全文截 1500 + 约束三节各截 600）、`设定/正则.md`（整文件）、`设定/世界书.md`（仅 [常驻] 条目）、`pipeline_state.json` 的 `genre_preset`（题材预设源）。`state.load_state` 缺文件时返回 DEFAULT_STATE 不报错，`genre_preset` 取到空串 → 块01 缺席。因此：
- **夹具A**（最小集，三件设定文件，不建 state）：验证缺文件行为——块01 确实缺席，头部 1713 字符 / 估算 721 tok；
- **夹具B**（A + 单键 `pipeline_state.json`，仅 `genre_preset=cultivation`；真实项目必有该文件）：六块齐全，作为主测量口径，下表数字全部来自真实 `project_header()` 输出。

## 2. 头部逐块审计表（夹具B · cultivation 预设 · prose 档）

| 块 | 字符 | 估算token | 占比 | 独立消费方（非组装点·真实引用） | 判定 |
|---|---:|---:|---:|---|---|
| – | 头部横幅 | 36 | 17 | 1.4% | –（结构行，全员共享） |
| 01 | 912 | 442 | 34.9% | app/core/co_dialogue.py×1、app/core/stages.py×6、app/presets/__init__.py×1、app/selftest.py×1 | **全员共享（含重复注入）** |
| 02 | 230 | 92 | 8.8% | app/core/canon_audit.py×1、app/core/stages.py×6、app/project.py×1、app/ui/bridge.py×2 | **全员共享（含重复注入）** |
| 03 | 145 | 64 | 5.5% | app/core/canon_audit.py×2 | **专属相位** |
| 04 | 163 | 43 | 6.2% | app/core/canon_audit.py×1、app/core/co_dialogue.py×8、app/core/stages.py×5、app/importdoc.py×1 等8个文件 | **全员共享（含重复注入）** |
| 05 | 44 | 17 | 1.7% | （无） | **疑似低利用（含重复注入）** |
| 06 | 1084 | 488 | 41.5% | app/core/stages.py×1 | **专属相位（含重复注入）** |
| **合计** | **2614** | **1163** | 100% | 16 个模板常量经 `{project_header}` 整体注入（见 §3） | – |

**逐块审计说明**（判定标准：疑似低利用 = 独立消费方只有组装点自身，没有任何 prompt 模板或逻辑读取其内容；专属相位 = 独立消费方集中在单一相位；全员共享 = 跨相位多处独立消费。「含重复注入」= 头部之外还有调用点把同一来源内容再注入一遍）：

- **01 题材预设**（912 字符 / 估算 442 tok，占比 34.9%）→ 全员共享（含重复注入）。组装点唯一（shared_prefix 按 prose 档注入）；独立消费方 stages._genre_block 按相位（core_setting/outline/worldbook/unit_outline）再注入各自特化档——其余四相位头部档与相位档并存（两份题材文本），正文相位只靠头部这份。
- **02 核心设定节选**（230 字符 / 估算 92 tok，占比 8.8%）→ 全员共享（含重复注入）。头部只装 题材定位.md 前 1500 字符；独立读方多：stages 卷纲重读前 4000 字符、enrich 重读前 1500 字符、project.worldbook_anchors 读角色表做锚点、canon_audit 读授权自创清单——内容被多处按需重读，头部副本有普适依据。
- **03 约束条款（金手指/红线/授权自创）**（145 字符 / 估算 64 tok，占比 5.5%）→ 专属相位。唯一独立消费方 canon_audit：清算两 prompt（AUDIT/AUDIT_REVIEW）各自独立注入constraints_block，并单独解析「授权自创清单」做专名豁免；planning.py 是这三节的产出侧（生成指令）不是消费侧；其余相位纯搭车。移出头部前须确认审校/正文对红线的隐性依赖（设计意图：红线随时在场）→ 交 gate 裁决。
- **04 正则契约全文**（163 字符 / 估算 43 tok，占比 6.2%）→ 全员共享（含重复注入）。独立消费方最多的一块：mustscan.scan_proj 本地硬校验、stages 各相位 regex_block/must_block 再注入、co_dialogue 六处、importdoc、canon_digest。头部灌的是 设定/正则.md 整文件（含 should 与注释），与标题「must 全文」名实不符——保留也应过滤。与逐章 regex_block 构成双份注入。
- **05 世界书·常驻条目**（44 字符 / 估算 17 tok，占比 1.7%）→ 疑似低利用（含重复注入）。constant_entries 在全仓只有一个调用方——组装点 shared_prefix 自身；按判定标准（消费方只有组装点自身）属疑似低利用。且 wb.assemble 逐章装配（prose/细纲/终审的 worldbook_block）时同批常驻条目按 P_CONSTANT 最高档**再次进入**——头部这份与逐章块重复；仅当逐章 2000 字预算把常驻条目挤掉时头部版才兜底。移出候选之首。
- **06 全局写作纪律**（1084 字符 / 估算 488 tok，占比 41.5%）→ 专属相位（含重复注入）。唯一独立消费方 = 正文模板的 {style_discipline} 槽（stages.py 组 kwargs 注入 PROSE_WRITING_PROMPT）——正文相位本就双份；纪律条目 4-15 全是正文工艺，大纲/审校/摘要等相位无独立消费证据，属搭车。移出头部对正文零损失（模板槽已自带），其余相位瘦头。

## 3. 消费方扫描明细

扫描范围：`app/` 下全部 51 个 .py（app/prompts/ 7 个 + app/core/ 16 个 + 根模块/UI/基建其余），逐行正则命中；引用行排除定义/转出口/注释与组装点自身。整体注入方（模板含 `{project_header}` 占位符，任何块都随头部进这些调用）：

- `app/core/canon_audit.py :: AUDIT_PROMPT`
- `app/core/canon_audit.py :: AUDIT_REVIEW_PROMPT`
- `app/prompts/co_writing.py :: CO_DIALOGUE_PROMPT`
- `app/prompts/co_writing.py :: CO_SUMMARIZE_PROMPT`
- `app/prompts/memory.py :: TRACKING_UPDATE_PROMPT`
- `app/prompts/memory.py :: CHAPTER_SUMMARY_PROMPT`
- `app/prompts/memory.py :: GLOBAL_SUMMARY_PROMPT`
- `app/prompts/planning.py :: CORE_SETTING_PROMPT`
- `app/prompts/planning.py :: VOLUME_OUTLINE_PROMPT`
- `app/prompts/planning.py :: CHAPTER_OUTLINE_PROMPT`
- `app/prompts/review.py :: REVIEW_FIX_PROMPT`
- `app/prompts/review.py :: FINAL_REVIEW_PROMPT`
- `app/prompts/writing.py :: PROSE_WRITING_PROMPT`
- `app/prompts/writing.py :: ENRICH_PROMPT`
- `app/prompts/writing.py :: TRIM_PROMPT`
- `app/prompts/writing.py :: DESLOP_REWRITE_PROMPT`
- `app/core/stages.py`：18 处 `project_header(...)` 调用点（核心设定/卷纲/细纲批/正文/扩写/压缩/去味/终审/审校票/作者复审/追踪/摘要等相位组装）；另有 chapter_session/co_dialogue/ui bridge 直接拼 system

### 01 题材预设

- 消费探针 `genre_block_for\(|genre_block\(` → 真实引用：app/core/co_dialogue.py×1、app/core/stages.py×6、app/presets/__init__.py×1、app/selftest.py×1
  - `app/core/co_dialogue.py:511` [core逻辑] `genre_block=genre_presets.genre_block(state.get("genre_preset", "")),`
  - `app/core/stages.py:116` [core逻辑] `return genre_presets.genre_block_for(pid, stage)`
  - `app/core/stages.py:121` [core逻辑] `return genre_presets.genre_block(pid)`
  - `app/core/stages.py:557` [core逻辑] `genre_block=_genre_block(ctx.proj, "core_setting"),`
  - `app/core/stages.py:592` [core逻辑] `genre_block=_genre_block(ctx.proj, "outline"),`
  - `app/core/stages.py:626` [core逻辑] `genre_block=_genre_block(proj, "worldbook"),`
  - `app/core/stages.py:746` [core逻辑] `genre_block=_genre_block(ctx.proj, "unit_outline"),`
  - `app/presets/__init__.py:80` [基建] `return genre_block(preset_id)`
- 重复注入探针 `genre_block\s*=|_genre_block\(` → app/core/co_dialogue.py×1、app/core/stages.py×4
  - `app/core/co_dialogue.py:511` [core逻辑] `genre_block=genre_presets.genre_block(state.get("genre_preset", "")),`
  - `app/core/stages.py:557` [core逻辑] `genre_block=_genre_block(ctx.proj, "core_setting"),`
  - `app/core/stages.py:592` [core逻辑] `genre_block=_genre_block(ctx.proj, "outline"),`
  - `app/core/stages.py:626` [core逻辑] `genre_block=_genre_block(proj, "worldbook"),`
  - `app/core/stages.py:746` [core逻辑] `genre_block=_genre_block(ctx.proj, "unit_outline"),`
- 概念探针 `题材预设|genre_block|genre_preset` → 139 处命中 / 14 个文件（含泛指与产出侧，仅作背景）

### 02 核心设定节选

- 消费探针 `read_file\([^\n]*题材定位` → 真实引用：app/core/canon_audit.py×1、app/core/stages.py×6、app/project.py×1、app/ui/bridge.py×2
  - `app/core/canon_audit.py:264` [core逻辑] `core = project.read_file(os.path.join(proj, "设定", "题材定位.md"))`
  - `app/core/stages.py:274` [core逻辑] `core = project.read_file(os.path.join(proj, "设定", "题材定位.md"))`
  - `app/core/stages.py:578` [core逻辑] `core_setting = project.read_file(os.path.join(ctx.proj, "设定", "题材定位.md"))`
  - `app/core/stages.py:616` [core逻辑] `core_setting = project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:2500]`
  - `app/core/stages.py:670` [core逻辑] `core_setting = project.read_file(os.path.join(ctx.proj, "设定", "题材定位.md"))`
  - `app/core/stages.py:920` [core逻辑] `core_setting = (project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1500]`
  - `app/core/stages.py:940` [core逻辑] `core_setting = (project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1500]`
  - `app/project.py:404` [app根模块] `core = read_file(os.path.join(proj, "设定", "题材定位.md"))`
- 重复注入探针 `core_setting\s*=|core_text\s*=` → app/core/stages.py×9、app/ui/bridge.py×3
  - `app/core/stages.py:578` [core逻辑] `core_setting = project.read_file(os.path.join(ctx.proj, "设定", "题材定位.md"))`
  - `app/core/stages.py:582` [core逻辑] `core_setting = core_setting[:4000]`
  - `app/core/stages.py:589` [core逻辑] `core_setting=core_setting,`
  - `app/core/stages.py:616` [core逻辑] `core_setting = project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:2500]`
  - `app/core/stages.py:624` [core逻辑] `core_setting=core_setting or "（未提供）",`
  - `app/core/stages.py:670` [core逻辑] `core_setting = project.read_file(os.path.join(ctx.proj, "设定", "题材定位.md"))`
- 概念探针 `核心设定|题材定位` → 124 处命中 / 20 个文件（含泛指与产出侧，仅作背景）

### 03 约束条款（金手指/红线/授权自创）

- 消费探针 `constraints_block\(` → 真实引用：app/core/canon_audit.py×2
  - `app/core/canon_audit.py:211` [core逻辑] `constraints_block=constraints_block(proj))`
  - `app/core/canon_audit.py:378` [core逻辑] `constraints_block=constraints_block(proj),`
- 概念探针 `金手指约束|全局红线|授权自创|constraints_block` → 19 处命中 / 3 个文件（含泛指与产出侧，仅作背景）

### 04 正则契约全文

- 消费探针 `regex_rules\(|regex_block\(|scan_proj\(|canon_digest\(` → 真实引用：app/core/canon_audit.py×1、app/core/co_dialogue.py×8、app/core/stages.py×5、app/importdoc.py×1 等8个文件
  - `app/core/canon_audit.py:530` [core逻辑] `rules = project.regex_rules(proj)`
  - `app/core/co_dialogue.py:166` [core逻辑] `canon = project.canon_digest(proj, 800)`
  - `app/core/co_dialogue.py:172` [core逻辑] `canon = project.canon_digest(proj, 800)`
  - `app/core/co_dialogue.py:181` [core逻辑] `rg = project.regex_block(proj, "logic", 1200)`
  - `app/core/co_dialogue.py:189` [core逻辑] `rg = project.regex_block(proj, "logic", 1000)`
  - `app/core/co_dialogue.py:198` [core逻辑] `rg = project.regex_block(proj, "logic", 1000)`
  - `app/core/co_dialogue.py:430` [core逻辑] `regex_block=project.regex_block(self.proj, "logic", 1000),`
  - `app/core/co_dialogue.py:510` [core逻辑] `regex_block=project.regex_block(self.proj, "logic", 1200),`
- 重复注入探针 `regex_block\s*=|must_block\s*=` → app/core/co_dialogue.py×4、app/core/stages.py×6、app/ui/bridge.py×2
  - `app/core/co_dialogue.py:430` [core逻辑] `regex_block=project.regex_block(self.proj, "logic", 1000),`
  - `app/core/co_dialogue.py:510` [core逻辑] `regex_block=project.regex_block(self.proj, "logic", 1200),`
  - `app/core/co_dialogue.py:568` [core逻辑] `regex_block=project.regex_block(self.proj, "logic", 1200),`
  - `app/core/co_dialogue.py:638` [core逻辑] `must_block=stages_mod._must_block(self.proj, self.cfg),`
  - `app/core/stages.py:748` [core逻辑] `regex_block=rg_block_text,`
  - `app/core/stages.py:1009` [core逻辑] `must_block=_must_block(proj, ctx.cfg),`
- 概念探针 `正则契约|正则约束|正则规则|must 规则` → 32 处命中 / 14 个文件（含泛指与产出侧，仅作背景）

### 05 世界书·常驻条目

- 消费探针 `constant_entries\(` → 真实引用：（无）
- 重复注入探针 `worldbook_block\s*=|worldbook_text\(|wb\.assemble\(` → app/core/co_dialogue.py×7、app/core/stages.py×7、app/project.py×1、app/selftest.py×3
  - `app/core/co_dialogue.py:180` [core逻辑] `wb = project.worldbook_text(proj, 1500)`
  - `app/core/co_dialogue.py:188` [core逻辑] `wb = project.worldbook_text(proj, 1200)`
  - `app/core/co_dialogue.py:197` [core逻辑] `wb = project.worldbook_text(proj, 1200, num=num)`
  - `app/core/co_dialogue.py:429` [core逻辑] `worldbook_block=project.worldbook_text(self.proj, 1200, num=self.num),`
  - `app/core/co_dialogue.py:509` [core逻辑] `worldbook_block=project.worldbook_text(self.proj, 1500, num=self.batch[0]),`
  - `app/core/co_dialogue.py:566` [core逻辑] `worldbook_block=project.worldbook_text(self.proj, 1500,`
- 概念探针 `世界书|worldbook` → 273 处命中 / 19 个文件（含泛指与产出侧，仅作背景）

### 06 全局写作纪律

- 消费探针 `STYLE_DISCIPLINE` → 真实引用：app/core/stages.py×1
  - `app/core/stages.py:973` [core逻辑] `"style_discipline": prompts.STYLE_DISCIPLINE,`
- 重复注入探针 `[\"'{]style_discipline|style_discipline\s*=` → app/core/stages.py×1、app/prompts/writing.py×1
  - `app/core/stages.py:973` [core逻辑] `"style_discipline": prompts.STYLE_DISCIPLINE,`
  - `app/prompts/writing.py:39` [prompts模板] `{style_discipline}`
- 概念探针 `全局写作纪律|STYLE_DISCIPLINE|style_discipline` → 9 处命中 / 5 个文件（含泛指与产出侧，仅作背景）

## 4. 真实项目样本（projects/，只读实测）

| 项目 | 头部字符 | 估算token | 在场块（字符） | 缺席块 |
|---|---:|---:|---|---|
| projects/修仙测试/凡人问道 | 2630 | 1146 | 02=1510、06=1084 | 01、03、04、05 |
| projects/现代穿越修仙/代码修仙 | 2630 | 1091 | 02=1510、06=1084 | 01、03、04、05 |

读法：以表中「缺席块」列为准。两本现有真实书均未进入世界书/正则阶段（无 `设定/正则.md`、`设定/世界书.md` → 块04/05 缺席），state 也没有 `genre_preset`（块01 缺席），且题材定位.md 未含「金手指约束条款」三节（块03 缺席——planning 模板要求生成该三节，这两本早期书没有）→ 真实头部 ≈ 横幅 + 核心设定节选 + 全局写作纪律，两本书的设定全文都顶到 1500 字截断上限。推论：**块03 的约束注入对存量书是空的**（头部与 canon_audit 同源，两边一起空）；共写档（`CW_STAGE_WORLDBOOK`）落盘正则/世界书后块04/05 才上场，届时正则文件的体量决定块04 占比（「H 主力」之说只对有正则的书成立）。

## 5. 发现与建议（交 gate 裁决，本包不改 app/）

**F1 疑似低利用块清单**：
- **块05 世界书·常驻条目**：`wb.constant_entries` 全仓唯一调用方是组装点自身（判定标准直接命中）；且逐章 `worldbook_block`（wb.assemble 的 P_CONSTANT 档）把同批条目**再注入一遍**——头部版只在逐章 2000 字预算挤掉常驻条目时兜底。移出方向二选一：① 头部移出、`wb.assemble` 对常驻条目保底（语义不变，头部瘦 17 tok）；② 保留头部、assemble 排除 constant 防双份（省的是逐章 hit 价）。
- **块06 全局写作纪律（次级候选，专属相位）**：唯一独立消费方是正文模板的 `{style_discipline}` 槽——正文相位双份，其余相位纯搭车。移出头部：正文总输入不变（模板槽已自带），其余每笔省 488 tok（hit 价）；需 gate 确认审校相位是否依赖纪律条目 6/11/13 的跨章条款。
- **块03 约束条款（专属相位，谨慎）**：唯一独立消费方是清算 canon_audit（两 prompt 独立注入 + 授权自创豁免解析）；但设计意图是红线随时在场。建议保留头部，或仅随创作类相位注入。

**F2 正文相位三重重复注入**：正文一笔 prompt 里同时有 头部块04（正则整文件）+ `{regex_block}`、头部块05（常驻条目）+ `{worldbook_block}`、头部块06 + `{style_discipline}`。哪怕块不移出，去重也能省（hit 价口径）。

**F3 块04 名实不符**：标题写「must 全文 · 违反即硬伤」，实现是 `read_file(REGEX_PATH)` 整文件——`level：should` 规则与 `#` 注释行一并注入并被冠以 must 之名。若 gate 决定保留，至少按 must 级过滤后再入头部（本夹具口径下块04=163 字符，其中 should 条约占 1/3）。

**F4 头部指纹不含 genre_preset**：`_fingerprint` 只看三个设定文件的 mtime，块01 的数据源 `pipeline_state.json` 不在其中——进程内切预设不会失效已缓存头部（「下一章生效」实际依赖跨进程重启）。仅记录；另注意 `_header_cached` 是进程内 LRU，同一 (proj, 指纹) 二次调用逐字节一致，符合设计。

**F5 移出节省的口径**（token 口径，不折现；价目见 `docs/成本优化深度调研报告_v2.md` §缓存计价横评，DeepSeek hit=miss×1/31）：
- 每笔**暖命中**调用省：块 tok × hit 价（= miss 价 / 31）；
- 每次**冷启动**（进程首笔 / TTL 过期 / 前缀变更后首笔）省：块 tok × miss 价；
- context rot：头部每瘦 1k tok，注意力噪声与首笔延迟同降（不可量化，只记方向）。

**F6 · N3 红线（改动前缀的一次性代价）**：前缀按位置逐字节匹配——任何块移出/过滤都会让**下一跑首笔全 miss**（整个头部按 miss 价重算一次，约等于全头部 tok × miss 价；夹具B 全头部 1163 tok，真实书以实测为准），之后重新暖起。因此：所有前缀变更（移出块05/06、块04 过滤 should）**合并为一次变更**上线，不要分多次折腾前缀；变更时机选挂机队列起点。

**F7 与 harness #2064 的对照结论**：我们没有 86% 那样的单一巨块——头部六块里没有「一半根本用不到」的体量；最接近的对应物是**块05 的重复注入**（用不到的「第二份常驻条目」）与块04 的 should/注释杂质。结构性结论：本项目的缓存大头治理应继续走 O7（缓存卫生）与 O1/O2（输出/思考侧），头部只做上述小修。

