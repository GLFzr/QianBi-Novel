# 集成方案:lieflat-less-ai-tone(去 AI 味 skill)并入 qianbi-novel

> 版本:v2(已经过对抗性评审修正)
> 日期:2026-09-16
> 适用仓库:`G:\ai\酒馆\qianbi-novel`(开发主线)
> 上游:https://github.com/larashero3-dotcom/lieflat-less-ai-tone

---

## 0. 一句话目标

把上游 skill 的**规则内核**(11 条白名单改写规则 + 硬约束 + "不作为改写理由"负表)以**并集**方式并入现有去 AI 味链路(检测→改写→复扫→审校),同时**对齐检测面与生成端**的三处既有矛盾。**不替换**现有流水线骨架,不动网文特化规则层。

## 1. 授权与合规(必须先做,不可省略)

- 上游为**标准 MIT 协议**,LICENSE 首行 `Copyright (c) 2026 shiujan`,允许复制、修改、闭源商用集成。唯一义务:**保留版权声明与 MIT 许可文本**。
- 本方案对 SKILL.md 做**衍生适配**(裁剪交互节、改写边界措辞),MIT 明确允许;需在文档中注明"基于 MIT 衍生适配"。
- **禁止**顺带集成同系列的 `lieflat-gongwen` / `lieflat-charts`——那是 PolyForm Noncommercial 1.0.0(禁商用)。
- 上游仓库**无 tag、无 release**,规则仍在修正。必须固定到具体 commit hash 并记录。

## 2. 现状架构(实现前必读)

> 下述行号基于 2026-09 的 0.20.0-dev 快照,可能漂移;实现时**以符号名定位为准**,行号仅作导航。

### 2.1 去 AI 味链路(保留,不重构)

| 环节 | 位置 | 说明 |
|---|---|---|
| 本地正则检测 | `app/deslop.py`(`scan_text()` L114-325) | 约 25 个规则族,分 `blocking`(阻断)/`advisory`(建议)两级 |
| 门禁分组 | `app/core/gates.py` `scan_deslop()` L67-72 | findings 分为 (blocking, advisory);`resolve_failed` L75-88 |
| 整章改写 | `app/prompts/writing.py` `DESLOP_REWRITE_PROMPT` **L172-202** | 内联 10 条改写原则(L184-194);注入 `{findings}`、`{must_block}`、`{tic_blacklist}` |
| 静态规则段抽取 | `writing.py` `deslop_static_rules()` **L212-216** | 用标记切片:`DESLOP_RULES_MARKER="## 改写原则"` / `DESLOP_RULES_END_MARKER="## 本书正则契约"`(L208-209) |
| 定点修复 | `writing.py` `DESLOP_PINNED_PROMPT` L223-240 | ≤2 处命中时走轻量定点路径,缺省关 |
| 复扫环 | `app/core/stages.py` L1889-1978 | 改写后 `gates.scan_deslop()` 复扫,上限 `gates.deslop_max_rounds=2`(`config.py` L82),耗尽按 `gates.strategy` 裁决 |
| 改写相位与剥规则段 | `stages.py` `_rewrite_phase()` L733-812 | **逐字匹配剥除**静态规则段(L809-812:`if strip_static in turn_text`),剥不干净会告警并保留全文 |
| 定点重写 | `stages.py` `_deslop_pinned_rewrite()` L867-931 | |
| 共写档手动入口 | `app/core/co_dialogue.py` L587-658(`_run_deslop()` L625-658) | `.format()` 用**显式关键字参数**(L638)——模板改占位符必须同步改,否则 KeyError |
| 卷级冻结头 | `app/core/volume_session.py` L704 / L728 | `instruction_in_head` 开启时静态规则段进卷级 system;**首条 system 与当前前缀不一致时整栈作废重建**(L511-564) |
| 审校维 F | `app/prompts/review.py` L173-174 | 三个结构指纹计数(视线词族/刹车句/单句短段),自有语料验证过,**本方案不动** |
| 生成端红线 | `writing.py` `PROSE_WRITING_PROMPT` **L51-67** | L56:禁"仿佛/犹如/宛若"等文言腔;L61:明喻配额 ≤5/章(上限)+ 每千字 ≥1 处具象新鲜比喻(下限) |
| 局部改写 | `writing.py` `SELECTION_REWRITE_PROMPT` **L266** | 第 4 条硬编码禁"不是A而是B""仿佛""他知道"等模板腔 |
| Agent 对话入口 | `app/agent_tools.py` L188(`cw_deslop`)| 复用 CwProseCheckWorker,改 co_dialogue 即自动覆盖,无需额外工作 |
| 修复环 | `app/ui/bridge.py` ChapterRepairWorker L222 起 + `review.py` `REVIEW_FIX_PROMPT` | 其第 7 条"只替换命中句式本身"是规则源无关的元规则,**豁免不改** |
| 题材黑名单 | `app/presets/__init__.py`(BUILTIN_DIR L14;`deslop_extra` 字段)| 经 `stages._tic_blacklist()`(L216-240)走 `{tic_blacklist}` 槽,独立通道,保留 |

### 2.2 关键检测规则(本方案的靶点)

- `app/deslop.py` `CLICHE_PATTERNS[0]`(**L59**):`仿佛|犹如|宛若|如同` **逐词命中即 blocking**("一级禁用词",命中逻辑 L180-185)。
- `METAPHOR_MARKERS`(**L74**):`好像|像是|仿佛|宛如|如同|像`,喂给 `metaphor-density`(**L196-200**,本来就是 advisory,阈值 ≥max(7, 3/千字))。
- `em-dash` 规则的**千字密度阈值**实现(L161-171)是新增密度型规则的最佳先例。

### 2.3 现状已存在的内部矛盾(本方案要修的"病")

生成端 `PROSE_WRITING_PROMPT` 要求每千字 ≥1 处比喻 → 写手常用"仿佛" → 检测端 `CLICHE_PATTERNS[0]` 逐词判 blocking → 复扫 2 轮烧尽 → 章章"待修"。**这是现状 bug,不只是集成障碍。**

## 3. 上游 SKILL.md 结构(实现 loader 的依据)

全文约 28KB。YAML frontmatter 仅 name+description(易剥)。章节标题**稳定**,可程序化定位:

| 标题 | 处置 |
|---|---|
| `## 硬性边界(最高优先级)` | **取用**,但措辞必须适配(见 §4.2) |
| `## 不改的情况` | 取用 |
| `## 不作为改写理由` | **全量取用**(负表:比喻、设问、被动句、名词化等实测不构成 AI 指纹——本集成最高价值项) |
| `## 改写规则(按优先级排序)` | **选段取用**:11 条中取网文适用子集(段首零回指评论、相邻句结构同款、拟人化喻体、禁用起手式等);论述文指纹条目(顿号罗列、提示性冒号、序数词小标题、数据概括)保留在文本层但预期召回低。**规则 8 内含"可以在输出后提示作者此处材料稀薄"——必须删除该句**,否则会被模型遵守,把提示语拼进章节正文(`clean_llm_output` 只剥代码围栏,拦不住) |
| `## 最终验收` | 取用 |
| `## 用法` | **丢弃**(交互式 agent 指令) |
| `## 有风格参考时先读它` | **丢弃**(本管线无法提供风格参考文档) |

11 条规则清单(供核对):翻案腔("不是A而是B")、顿号罗列过密、相邻句结构同款、破折号滥用、提示性冒号、序数词当小标题、拟人化喻体、概括表述覆盖已有数据、禁用起手式("说白了")、翻译腔(仅 5 种结构)、段首零回指评论。

## 4. 实施方案(分四个 Phase)

### Phase 0|供应商化与合规

1. 新建目录 `app/vendor/lieflat-less-ai-tone/`,放入:
   - `SKILL.md`(**原文**,不作任何修改——它只作存档与 loader 输入源)
   - `LICENSE`(上游 MIT 全文)
   - `VERSION.txt`:记录上游 commit hash、上游最后提交时间、vendor 日期、vendored 人
2. `THIRD-PARTY-LICENSES.md` 增加条目:lieflat-less-ai-tone (c) 2026 shiujan, MIT License + 说明"含衍生适配,适配部分同样遵循 MIT"。关于页(如有第三方许可展示)同步。
3. `QianBi-Novel.spec` 的 `datas` 增加镜像条目(照抄 presets 的模式):`('app/vendor/lieflat-less-ai-tone', 'app/vendor/lieflat-less-ai-tone')`。运行时资源路径解析沿用现有 presets 的 `os.path.dirname(__file__)` + PyInstaller 兼容写法。
4. `config.py` 增加 `deslop.rules_source: "lieflat"(默认) | "builtin"`。loader 读不到 vendor 文件/解析失败时自动回退 `builtin` 并出声告警(参考项目现有告警风格)。
5. **vendor 文件内容在应用启动时一次性读入缓存**。原因:`volume_session` 在卷级 system 头字节变化时会整栈作废重建(L511-564),运行中文件被改动 = 会话栈全废(费用损失)。文档中写明:"卷写作中途切换 rules_source 或修改 vendor 文件,需开新卷"。

### Phase 1|改写面:并集 + 适配(核心)

1. 新建 loader `app/prompts/skill_rules.py`:
   - 读启动缓存中的 SKILL.md → 剥 frontmatter → 按上表标题切片 → 丢弃两个交互节 → 删除规则 8 的"提示作者"句 → 输出"适配渲染版"规则文本。
   - **任一预期标题缺失 → 整体回退 `builtin` 并告警**(不半截拼接)。
   - 提供两档渲染:`full`(带 ❌/✅ 示例)与 `lean`(只保触发标记+改法,裁示例)。默认 `lean`,理由见 Phase 3 成本验收。
2. `writing.py` 的 `deslop_static_rules()` 改为返回**并集**文本(开关开且 loader 成功时):
   - **内置 10 条原则中 skill 未覆盖项全部保留**(它们是网文体裁层:预告腔、声线、微表情、章末钩子、字数纪律等);
   - 追加 skill 贡献的新规则项(段首零回指、相邻句结构同款、拟人化喻体、禁用起手式、翻译腔子集等文本层表述);
   - 追加**负表全量**("以下情况禁止作为改写理由:比喻、设问、被动句……");
   - **边界段适配措辞**为:"未命中上述规则、且不在本轮检出问题清单 / 口头禅黑名单 / 本书正则契约中的文字,逐字保留"。不改这句,prompt 自相矛盾(一边说"清单外别动",一边 findings 里全是清单外问题)。
   - 标记切片机制(`DESLOP_RULES_MARKER`/`END_MARKER`)保持不变——`_rewrite_phase` 的逐字剥除(L809-812)与卷级头注入依赖"静态段同源同字节",这是既有契约,**不得破坏**。
3. `DESLOP_REWRITE_PROMPT` 模板不需要改为占位符:保持"模板内联内置规则 + `deslop_static_rules()` 从标记切片"的现有机制即可(切片源换成并集文本)。**注意 `co_dialogue.py` L638 与 `stages.py` L1941 两处 `.format()` 的关键字参数集合不变**,避免 KeyError。
4. `DESLOP_PINNED_PROMPT`(定点修复)**豁免**:保持精简纪律,最多追加负表的 lean 压缩版。全套 11 条塞进定点路径会摧毁其轻量设计。
5. 卷级冻结头(volume_session)自动继承,无需单独改动,但需按 Phase 0 第 5 条做启动缓存。

### Phase 2|检测面与生成端联动对齐(一次决策,三处联动)

1. **`deslop.py` `CLICHE_PATTERNS[0]`(`仿佛|犹如|宛若|如同`)从逐词 blocking 降级为密度阈值型 advisory**(仿 `em-dash` L161-171 的千字阈值先例)。理由:上游 283 万字语料证明人类比喻频率是 AI 的 2.4 倍,逐词阻断与负表直接冲突,且与生成端比喻下限自相矛盾(§2.3)。
2. **同一决策点联动修改**(必须一次改完,否则互相打架):
   - `writing.py` L56 生成端"禁仿佛/犹如/宛若文言腔":放宽为"禁陈词化文言腔堆叠"(保留对**陈词**的约束,解除对**比喻标记词本身**的禁令);
   - `writing.py` L61 明喻配额:**保留下限**(与上游结论同向),上限 ≤5/章酌情放宽或保留,由同一决策记录确认;
   - `writing.py` L266 `SELECTION_REWRITE_PROMPT` 第 4 条中的"仿佛":随第 1 条同步解除;
   - `metaphor-density`(L196-200)维持 advisory 不动(自有语料的 advisory 阈值与上游数据不真正冲突)。
3. **新增两条 advisory 正则**(都按千字密度阈值,仿 em-dash 先例):
   - 提示性冒号(触发词表:"核心是/关键在于/一句话总结"等窄表);
   - 顿号罗列密度(按上游原触发标记:分句内 ≥2 顿号且 ≥3 并列项)。
   - **上线前先跑测试资产**(见 Phase 3 第 3 条):`tests/corpus_pd` 人类语料(萧红《呼兰河传》、鲁迅《野草》)测**误报**,`tests/planted_defects` 测**召回**。误报不达标就不上线,宁缺毋滥。
4. **明确不做**:
   - 序数词小标题正则——网文正文中不存在该形态,recall≈0,做了是死代码;
   - 拟人化喻体 / 相邻句结构同款 / 段首零回指的正则化——不可靠,只存在于 Phase 1 的改写规则文本层,由 LLM 执行,复扫 gate 保持纯正则确定性验收;
   - 审校维 F(review.py)——不动。

### Phase 3|测试、成本与文档

1. **单测**(放 `tests/`,沿用现有风格):
   - loader:正常切片 / 标题缺失回退 / frontmatter 剥离 / 规则 8 句子删除;
   - 渲染产物**快照测试**:锁住"并集静态段"全文,防止上游 re-vendor 或内置规则改动时切片/剥除契约悄悄失配;
   - `deslop.py` 规则族清单快照(防止规则表无意识漂移)。
2. **回归**:取 3-5 章样稿,`rules_source: builtin` vs `lieflat` 双开关跑 deslop 全链路,对比:findings 数、复扫通过率、改写轮次、"待修"章数。验收线:lieflat 模式下复扫通过率**不得低于** builtin 基线。
3. **Token 成本实测**:对比两档渲染(full/lean)在整章改写 prompt 上的增量 token;若 full 档单章增量不可接受,默认档定为 lean 并写入配置说明。
4. **文档**:`docs/` 下本文档的落地记录 + CHANGELOG 条目 + 上游跟踪机制(该仓库年轻且规则仍在修正,建议**每季度**复查上游,重新 vendor 走 PR 并更新 VERSION.txt 与快照)。
5. 文档中写明豁免清单及理由:ChapterRepairWorker / REVIEW_FIX_PROMPT(元规则,规则源无关)、审校维 F(自有语料验证,不稀释)、presets `deslop_extra` 频道(独立通道,继续有效)。

## 5. 验收标准(整体)

- [ ] `app/vendor/lieflat-less-ai-tone/` 齐备(SKILL.md 原文 + LICENSE + VERSION.txt 含 commit hash);THIRD-PARTY-LICENSES.md 与关于页有 MIT 声明;PyInstaller 打包后应用内可读到 vendor 文件。
- [ ] `rules_source: lieflat` 时,整章去味改写 prompt 含:内置体裁层规则 ∪ skill 新规则 ∪ 负表 ∪ 适配后边界;`_rewrite_phase` 剥除与卷级冻结头工作正常(无双重规则、无剥除告警、无 KeyError)。
- [ ] 双开关样章回归:lieflat 模式复扫通过率 ≥ builtin 基线,"待修"章数不增加。
- [ ] `CLICHE_PATTERNS[0]` 降级 + 生成端两处 + SELECTION 一处联动完成;新正则通过 corpus_pd 误报测试与 planted_defects 召回测试后才启用。
- [ ] 交互节内容(`## 用法`/`## 有风格参考时先读它`/"提示作者"句)经 loader 后不存在于任何注入 prompt 中(用断言测试锁死)。
- [ ] 全部现有测试通过;新增单测通过。

## 6. 风险与对策备忘

| 风险 | 对策 |
|---|---|
| 上游 re-vendor 后标题结构变化导致切片失败 | 标题缺失即回退 builtin + 告警;快照测试提前发现 |
| 白名单边界与 findings/tic_blacklist/must_block 冲突 | 边界措辞已适配(§4.2);断言测试锁死交互节移除 |
| 改写器被负表"松绑"后过度保守、该改不改 | 并集中保留内置 10 条的强制性;双开关回归看复扫通过率 |
| 卷中途切规则源 → 会话栈作废 | 启动缓存 + 文档声明 |
| Token 成本膨胀 | lean 渲染默认档 + instruction_in_head 冻结复用 |
| 上游规则仍在修正 | 固定 commit hash,季度复查,快照测试护栏 |
