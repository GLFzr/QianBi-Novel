# 规则依据与定标（qianbi-deslop，自动生成）

> 本文件由导出管线从上游 `app/deslop.py` 生成；本版引擎含 **45 条规则**。
> 引擎与阈值为上游逐字副本（scripts/_vendor/），规则注释自带语料基线数字
> 与误报学出处——规则明细以引擎源码为唯一真源，本文件只登记清单与方法论。

## 本版规则清单（45 条，源码出现序）

- `not-is-comparison`
- `reverse-not-is`
- `negation-parade`
- `voice-contrast`
- `flat-voice`
- `trailer-ending`
- `trailer-summary`
- `fate-summary`
- `em-dash`
- `daizhe-adverb`
- `cliche-word`
- `simile-marker-density`
- `prompting-colon`
- `dunhao-list-density`
- `telling-cognition`
- `metaphor-density`
- `micro-action-tic`
- `abstract-summary-tic`
- `reasoning-chain`
- `period-stutter`
- `long-paragraph`
- `quote-emphasis`
- `gaze-density`
- `brake-sentence`
- `brake-standalone-para`
- `one-line-para`
- `stamp-para`
- `mengdi-density`
- `negation-pair-tic`
- `stock-reaction-tic`
- `action-list-tic`
- `system-notice-formality-tic`
- `overcompressed-prose-tic`
- `low-connective-density-tic`
- `formulaic-parallelism`
- `cliche-density-tic`
- `forced-triad`
- `sentence-opening-run`
- `idealized-persona-simile`
- `adjacent-sentence-isomorph`
- `zero-subject-comment`
- `vague-rider`
- `closer-recap-tic`
- `sendoff-para`
- `recap-opening`

## 定标方法（上游口径）

- **真机语料对比**：每条密度型规则都用「人类作者语料 vs 多模型 AI 产出语料」
  的每千字密度对比定标。定标目标：人类文风零误报，AI 堆叠稳定触发。
- **双级设计**：单句式规则（形态即问题）为 blocking；密度型规则低密度是合法
  文风（advisory 或不报），超过 AI 特征密度才升级。校准纪律：有真人命中就不许
  升 blocking。
- **引号豁免**：对话引号内的文本默认豁免密度类规则——人物说话风格不属于叙述腔
  控制范围。
- **白名单**：书级白名单字面量（世界观术语/招式名）等长掩码后不参与任何规则，
  上游 `gates.load_deslop_whitelist` 产出；本 CLI 未带白名单输入，命中白名单
  类误报请人工裁量保留。

## 与上游的关系

- 本包引擎=上游逐字副本，规则行为与上游同版本完全一致；
- 上游 `python -m app.selftest` 与全量单测持续校准规则，本包随版本号同步；
- 上游 GUI 版另有契约化改写回环（改写后自动复扫+指标对比），本包步骤 4 复扫
  需手动执行。
