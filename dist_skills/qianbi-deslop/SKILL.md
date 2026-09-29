---
name: qianbi-deslop
description: 中文网文去 AI 味 lint 与白名单式改写。确定性脚本扫描章节里的 AI 写作痕迹（毒句式、禁用词、密度型 AI 腔、结构层指纹，本版 45 条规则），给出行号与修法方向，再按白名单纪律改写。当用户提到去AI味、AI味重、AI腔、机翻感、降 AI 痕迹、润色网文章节、检查 AI slop、让文字更像人写的时候使用。仅适用于中文虚构叙事；不讨论不承诺任何 AIGC 检测器分数，不做非虚构文风改写。
license: MIT
compatibility: 需要 Python 3.8+（仅标准库）；脚本在本 skill 目录 scripts/ 下运行，适用于任何支持 Agent Skills 的客户端。
metadata:
  author: qianbi
  version: 0.22.0
  source: https://github.com/GLFzr/qianbi-novel
---
# 网文去 AI 味：确定性 lint + 白名单改写

目标**只是读感**：把「一眼 AI」的文本改成可读、可信的中文叙事。本 skill 不承诺、
不讨论、不尝试优化任何第三方 AIGC 检测器的分数；不注水、不故意制造错字。

本版引擎 **45 条规则**（与上游 qianbi-novel 0.22.0 逐字一致），随包自检金标见
`tests/`。

## 流程（五步，按序执行，不得跳步）

1. **扫描**：对目标章节运行
   `python <skill目录>/scripts/deslop_check.py 章节文件.txt`
   得到 lint 报告（规则 ID / 级别 / 行号 / 修法方向）。`--json` 可得机器可读
   结果；退出码 1 表示存在 blocking。`--rules` 列出本版全部规则。
2. **定档**：按报告定本轮 AI 味等级——只有 advisory → 轻度；有 1-3 类
   blocking → 中度；blocking 覆盖 4 类以上或多段结构指纹（one-line-para /
   stamp-para）→ 重度。
3. **改写**（白名单纪律，逐条硬约束）：
   - 只处理报告列出的规则命中；清单外、且不在检出问题里的文字**逐字保留**；
   - 只改「怎么说」，不改「说什么」：不得增删情节、人物、信息与因果关系；
   - 删除比例上限：轻度 ≤15%，中度 ≤25%，重度 ≤35%（按字数计，含同义改写
     压缩量）；
   - blocking 必修；advisory 逐条裁量，拿不准就保留原文；
   - 同一处命中只改一次，不得为消规则而把句子改出新的模板腔。
4. **复扫**：改完复跑步骤 1，blocking 必须为 0；advisory 数量不得高于改前。
5. **反指纹终查**：检查替换写法是否在全文复用（同一替换写法反复出现，本身会
   成为新指纹）。有复用就换写法，再复扫一次。

## 改写方向速查（高频命中的通用修法）

| 规则 | 修法方向 |
|---|---|
| not-is-comparison / reverse-not-is | 删掉翻转结构，直接写 B；或拆成动作与后果 |
| negation-parade | 否定排比至多留一项，其余改成白描或动作 |
| voice-contrast / flat-voice | 删音量/声线声明，直接写台词内容与可听见的声音特征 |
| trailer-ending / trailer-summary / fate-summary | 用具体物件、动作或未解决的问题收束；抽象总结落回角色当下 |
| cliche-word（一丝/一抹/眼中闪过…） | 换成该角色特有的动作、物件或环境反应 |
| em-dash（密度型） | 高于 6/千字时改句号、逗号断句；低密度属合法文风，不动 |
| gaze-density（盯着/看向/目光成片） | 注意力外化成动作与物件（指节抵着桌沿、茶凉了没喝） |
| brake-sentence / brake-standalone-para | 「没有×」全章至多保留 2 处，其余改成动作或对白呈现 |
| one-line-para / stamp-para | 关联动作并成复合段；单词定性段还原成可拍摄的细节，全章至多 1 处 |
| 其余密度/结构型规则 | 见 `references/rule-basis.md` 与引擎源码注释（自带语料基线与修法） |

## 边界与纪律

- 本脚本只报告，不改写；一切修改由你在步骤 3 亲手做出。
- 引号内的对话默认豁免密度类规则；对话本身有问题时按语义改，不套模板。
- 宁缺勿滥：无法确证的疑点保持 advisory，不得升级为「必须改」。
- 改写产出的段落要朗读顺口；lint 是底线，不是目标。

## 环境与故障

- 脚本纯 Python 标准库，3.8+ 可跑；Windows 控制台乱码时先 `chcp 65001` 或重定向
  到文件查看。
- 引擎为上游逐字副本：`scripts/_vendor/` 下 `qianbi_vendor/deslop.py`；
  规则与阈值明细以引擎源码注释为唯一真源。
- 上游：https://github.com/GLFzr/qianbi-novel（GUI 版含全量规则、契约化改写回环与改写前后指标对比）。

本包由 qianbi-novel 导出管线自动生成（scripts/build_skills.py），引擎与码表为上游逐字副本；请勿手改产物——上游更新后重跑导出管线并用 --check 对账。
