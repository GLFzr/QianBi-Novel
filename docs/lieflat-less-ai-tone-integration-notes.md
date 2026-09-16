# lieflat-less-ai-tone 集成落地记录

> 方案来源：`docs/lieflat-less-ai-tone-integration-plan.md` v2（已经过对抗性评审定稿）
> 实施日期：2026-09-16
> 上游快照：commit `27d29232f10124db904ca9c0536d0b67cb3b2833`（2026-08-24T06:56:55Z）

## 0. 合规声明

- 上游 SKILL.md / LICENSE 以**原文**vendored 于 `app/vendor/lieflat-less-ai-tone/`，
  sha256 与上游 commit 记录在该目录 `VERSION.txt`。
- 上游 MIT License（Copyright (c) 2026 shiujan）。本项目 loader（`app/prompts/skill_rules.py`）
  对 SKILL.md 做裁剪/措辞适配，属 MIT 允许的衍生使用，**适配部分同样遵循 MIT**。
- **未**集成同系列 `lieflat-gongwen` / `lieflat-charts`（PolyForm Noncommercial 1.0.0，禁商用）。

## 1. 实施内容（按 Phase）

### Phase 0 供应商化与合规
- vendor 三件套 + THIRD-PARTY-LICENSES.md 条目 + `QianBi-Novel.spec` datas 镜像
  （照抄 presets 模式；loader 用 `os.path.dirname(os.path.abspath(__file__))`
  source-relative 解析，PyInstaller onedir 下与 presets 同样可读）。
- `config.py` 新增 `deslop` 节：`rules_source: "lieflat"(缺省)|"builtin"`、
  `rules_render: "lean"(缺省)|"full"`。老配置经 `load_config()` 深合并自动补键。
- **启动缓存**：`main.py` 启动时调用 `skill_rules.init_rules_cache(cfg)` 一次性读入
  并冻结；测试/探针走首次访问懒初始化。
  ⚠ **卷写作中途切换 `rules_source` / `rules_render` 或修改 vendor 文件 = 卷级冻结头
  字节变化 = 会话栈整卷作废重建（费用损失）。换源请开新卷（重启应用）。**

### Phase 1 改写面（并集 + 适配）
- 新 loader `app/prompts/skill_rules.py`：
  - 剥 YAML frontmatter → 按 `## ` 标题**前缀**切片（上游实际用全角括号
    `硬性边界（最高优先级）`，方案文档的半角写法是编写快照——以实际文件为准）；
  - 丢弃交互节 `## 用法`、`## 有风格参考时先读它`（单元测试锁死，方案 §5 验收）；
  - 删除规则 8 的整句 `可以在输出后提示作者此处材料稀薄，由作者决定是否补充。`
    （该句会被模型遵守拼进正文，`clean_llm_output` 拦不住）；
  - 硬性边界首段适配为："未命中上述任何规则、且不在本轮检出问题清单 / 口头禅
    黑名单 / 本书正则契约中的文字，逐字保留"（原白名单措辞与 findings/
    tic_blacklist/must_block 自相矛盾）；其余信息守恒等段落原文保留；
  - 负表（不作为改写理由）全量 + 改写规则 11 条全量保留在文本层 + 最终验收；
  - 两档渲染：full（带 ❌/✅ 示例）/ lean（只裁 `>` 示例块。**故意不做**按
    "触发标记/改法"前缀的行过滤——规则 1 翻案腔句式清单、规则 9 起手式词表的
    触发实体在正文叙述里，机械过滤会把规则裁没；示例块才是体积大头）；
  - 任一预期标题缺失 / 渲染产物含花括号（会炸 `.format`）/ vendor 文件读不到
    → **整体回退 builtin 并出声告警**（不半截拼接）。
- `writing.deslop_static_rules()` 返回**并集**（内置 10 条体裁层原则全保 ∪ skill
  新规则 ∪ 负表全量 ∪ 适配边界），并**同字节拼接进模板**：
  - `_set_active_template()` 同步 writing 模块**与 `app.prompts` 包两级属性**——
    `stages.py` / `co_dialogue.py` 都走包属性取模板，只改模块属性 splice 会静默失效
    （单测抓出后修复）；
  - `_ACTIVE_UNION` 追踪当前已拼并集，支持重初始化后的任意档位切换（lean↔full↔builtin）；
  - `_ORIGINAL_DESLOP_REWRITE_PROMPT` 快照保证 `builtin` 模式**逐字节**回退旧行为；
  - 标记切片（`DESLOP_RULES_MARKER`/`END_MARKER`）不动——`_rewrite_phase` 逐字剥除、
    卷级冻结头注入、"静态段同源同字节"契约完整保持；
  - `co_dialogue.py` / `stages.py` 两处 `.format()` 关键字参数集合（findings/prose/
    tic_blacklist/must_block/project_header/chapter_header）未动，无 KeyError 面。
- `DESLOP_PINNED_PROMPT`（定点修复）**豁免**全套规则注入，仅追加负表 lean 压缩版
  一行（轻量设计不摧毁）。

### Phase 2 检测面与生成端联动（一次决策，四处同一提交）
- `deslop.py` `CLICHE_PATTERNS[0]`（仿佛|犹如|宛若|如同）移出一级禁用词表 →
  独立 `CLICHE_SIMILE`，降为密度阈值型 advisory（`simile-marker-density`，
  阈值 `max(4, 2/千字)`）。旧逐词 blocking 与生成端"每千字 ≥1 具象比喻"下限
  自相矛盾是历史病根（复扫烧尽→章章待修）。
- `writing.py` 生成端红线放宽：标记词不禁（明喻配额统一管理），禁陈词化文言腔堆叠；
  明喻配额**上下限均保留**（决策记录：上限是标记词解禁后比喻总量的唯一闸门，
  下限与上游"人类比喻 2.4 倍"结论同向）；`SELECTION_REWRITE_PROMPT` 第 4 条解除"仿佛"。
- 新增两条 advisory（都按千字阈值，仿 em-dash 先例；**上线前先过测试资产**）：
  - `prompting-colon` 提示性冒号（窄表：核心是/关键在于/一句话总结…；对话内豁免；
    阈值 `max(2, 1/千字)`）——corpus_pd 人类语料 1.84 万字实测 **0 命中**；
  - `dunhao-list-density` 顿号罗列（分句内 ≥2 顿号即罗列句；对话内豁免；阈值
    `max(4, 2/千字)`）——corpus_pd 人类基线实测 1.14/千字（上游 1.78），零误报；
  - **明确不做**（方案 §4 Phase 2.4）：序数词小标题正则（recall≈0）、拟人化喻体/
    相邻句同款/段首零回指的正则化（只存在于改写规则文本层，由 LLM 执行，复扫
    gate 保持纯正则确定性）、审校维 F 不动。

### Phase 3 测试与文档
- `tests/unit/test_skill_rules.py`（11 例）：切片/frontmatter/规则 8 删除/标题缺失
  回退/vendor 缺失回退/花括号回退/两档渲染差异 + **并集静态段 golden 快照**
  （`tests/snapshots/lieflat_union_lean.txt`，切片/剥除契约失配即红）+
  **规则族清单快照**（`tests/snapshots/deslop_rule_families.txt`，规则表漂移即红）。
- `tests/unit/test_skill_dualmode_regression.py`：双开关样章装配回归（3 章样稿 ×
  builtin/full/lean：装配无 KeyError、静态段同源、检出面两档逐条一致、
  lieflat 档 skill 规则确实进 prompt 而 builtin 档不泄漏）+ token 成本估算。
- `tests/unit/test_skill_advisory_rules.py`：新规则误报/召回门禁 + 降级决策锁死。

## 2. Token 成本对比（估算口径）

| 渲染档 | 静态段字符数 | 相对内置增量 | 估算增量 token（×0.6，DeepSeek 中文上界） |
|---|---|---|---|
| builtin（内置 10 条） | 352 | — | — |
| lieflat + lean（缺省） | +8,108 | ≈ +4,900 token/改写轮 | 可接受（整章改写 prompt 原本 6-8k） |
| lieflat + full | +10,365 | ≈ +6,200 token/改写轮 | 明显更贵 → **默认档定为 lean** |

估算口径：DeepSeek 中文 ≈0.6 token/字上界，非计费实测；`instruction_in_head`
开启时静态段进卷级冻结头，整卷只付一次（轮次剥除复用），实际摊销远低于上表。

## 3. 豁免清单及理由（方案 Phase 3.5）

| 豁免项 | 理由 |
|---|---|
| ChapterRepairWorker / REVIEW_FIX_PROMPT | 其"只替换命中句式本身"是规则源无关的元规则 |
| 审校维 F（review.py 结构指纹） | 自有语料验证过的计数规则，不稀释 |
| presets `deslop_extra` 通道 | 题材黑名单独立通道（`{tic_blacklist}` 槽），与规则源正交，继续有效 |
| DESLOP_PINNED_PROMPT 全套注入 | 定点修复的轻量设计；只带负表 lean 压缩行 |

## 4. 上游跟踪机制

- 上游无 tag/release，规则仍在修正。**每季度**复查一次上游 main：
  1. `curl` 取新 commit hash，diff SKILL.md；
  2. 重新 vendor（原文件覆盖 + 更新 `VERSION.txt`）；
  3. 跑 `pytest tests/unit/test_skill_rules.py` ——golden 快照会立刻暴露切片/措辞
     变化（golden 缺失即 fail，不再自动写入）；人工确认差异后跑
     `python tests/bless_snapshots.py` 重新生成并入库（WP-15①/R11：测试永不
     自动调用 bless）；
  4. 走 PR，不改 `config.py` 缺省值（用户无感）。

## 5. 双开关样章回归的 LLM 侧说明（环境不判）

方案 §5 验收第 3 条"lieflat 模式复扫通过率 ≥ builtin 基线"需要真实 LLM 改写：
离线已完成装配/契约/检出一致性部分（`test_skill_dualmode_regression`）；
复扫通过率与"待修"章数对比需配置真 Key 跑 3-5 章样稿（两次全链路），留待真机窗口。

## 6. 归因更正与缺省态声明（WP-15⑤⑦，2026-09-17 补）

### 6.1 prompt 基线漂移归因更正（更正 80b7c8c 提交信息）

`80b7c8c` 刷新基线时对 7 点漂移写的归因里，6 点准确，1 点不实：

- 原文：「deslop/writing #42：DESLOP_REWRITE_PROMPT 改写原则段**并入 lieflat
  并集**（Phase 1 核心改动，字符数 4045→4002 系模板切片源切换）」
- 事实：#42 装配点在 Phase 1/3 的并集架构下**逐字未变**（静态段走卷级冻结头，
  不在轮次装配点计字符串内）。4045→4002（−43）的真实成因是 **Phase 2 的一级
  禁用词放松**——DESLOP_REWRITE_PROMPT「改写原则」第 4 条删去「仿佛」相关措辞
  （与 CLICHE_SIMILE 降级、SELECTION 第 4 条解除"仿佛"同批联动）。并集有
  8,108 字，若真并入装配点方向应为正向大增，"−43 归因于并入并集"在数量级和
  方向上都不成立。

另（R2 类自评更正）：`13796c5`/`a01d308` 提交信息自称「prompt 基线零漂移」，
而漂移实际发生在 `0f12215`（Phase 2）——那两个提交内"零漂移"表述是**当时未跑
基线**下的乐观措辞，不是实测结论。完整逐条归因见 80b7c8c（其 #42 一条按本节
更正）与本节。

### 6.2 生产行为变更登记（N-38）

| 项 | 内容 |
|---|---|
| 变更 | 检测面：一级禁用词「仿佛/犹如/宛若/如同」由逐词 blocking 降为密度型 advisory（simile-marker-density，阈值 max(4, 2/千字)），并新增 prompting-colon / dunhao-list-density 两条 advisory |
| 影响面 | deslop 检出计数 #42：4045→4002（−43，全部来自比喻标记降级）；章「待修」判定随之可能减少（advisory 不进阻断集） |
| 是否默认生效 | **是**——本地扫描器无条件运行，不收 instruction_in_head 控制；正文/选区改写模板的红线措辞同步放宽（随模板默认生效） |
| 反向面 | lieflat 并集注入 prompt **默认不生效**（见 6.3）——默认态下检测面已变而改写指令未变，二者口径差由检测降级本身保证不冲突（比喻不再判死） |

### 6.3 instruction_in_head 缺省态（显式声明，不许隐式）

`writing.instruction_in_head` **不在 `DEFAULT_CONFIG`**，读取点
`stages.py:1556` 的缺省值为 `False` ⇒ **全新安装与未显式开启的存量用户：
lieflat 并集从不进入任何 prompt**（`stages.py:1922-1923`、
`volume_session.py:704/728` 三处注入点都收它控制）。本集成在缺省安装下的全部
实际生效面 = 6.2 表所列检测面/模板措辞变更；并集注入属于**显式 opt-in** 的
实验特性。开启方式：config.json → `writing.instruction_in_head: true`
（注意：开启会改变卷级冻结头字节，写作中途开启需开新卷）。
