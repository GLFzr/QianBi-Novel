# -*- coding: utf-8 -*-
"""盲评防偏差三件套（0.20.3 B10，LitBench 协议卫生）——纯函数，Wave D 盲评消费

研究判准（T3 报告 §LitBench / Top20-T3）：
1. **位置置换**：朴素配对评估强烈偏向前置稿（位置偏差实证）——A/B 呈现顺序必须
   按随机种子置换（取均值或成对抵消）；
2. **长度配平**：朴素 RM 强烈偏长文本（长度偏差实证）——两稿长度差 ≥25% 必须在
   judge prompt 里显式配平提示（评分不得以长度为据）；
3. **先叙情节后判决**：判词先讨论情节再给判决，判决正确性 +14.8%——盲评 judge
   prompt 强制先复述两稿情节再下判定（与审校主审校 B10 纪律同源，见 review.py
   硬纪律第 8 条）。

本模块只交付 **prompt 构造器**（Wave D 盲评 A/B 用）；聚合/加权/引文验真在
scripts/blind_pack.py（既有仪器），两处不互相 import（prompt 侧/聚合侧解耦）。
`plot_restatement`/`===情节重述===` 命名与 review.py 输出协议同族，便于复用解析。
挂点 TODO（Wave D）：scripts/blind_pack.py 打包器可选用本构造器生成 judge 票
（本卡不接线）。
"""
import random

# 长度配平阈（LitBench 配对清洗口径：长度差 <25% 或直方图配平）
LENGTH_IMBALANCE_RATIO = 0.25

# 盲评呈现标签（对 judge 匿名：不许出现 A/B/变体名/模型名）
_BLIND_LABELS = ("稿一", "稿二")


def permute_positions(seed: int, n: int = 2) -> list:
    """位置置换：seed 决定 n 稿呈现顺序（同种子同序，确定可复现）。

    返回排列表，如 [1, 0] 表示原第 2 稿先呈现。Wave D 取均值/成对抵消时，
    对同一样本换 seed 重抽即可（种子由调用方从样本 id 派生保证可复现）。
    """
    if n < 2:
        return list(range(max(n, 0)))
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order


def length_imbalance(len_a: float, len_b: float) -> bool:
    """两稿长度差是否 ≥ LENGTH_IMBALANCE_RATIO（配平失败=长度偏差风险在案）。

    口径：相对**较短稿**的差（|a-b|/min）——防长度偏差取保守侧，同样的绝对差
    在短稿组合下更容易被判失衡，宁可多提示不可漏提示。
    """
    a, b = max(float(len_a or 0), 0.0), max(float(len_b or 0), 0.0)
    if a <= 0 or b <= 0:
        return True            # 缺长度信息一律按未配平处理（提示必须给）
    return abs(a - b) / min(a, b) >= LENGTH_IMBALANCE_RATIO


def length_balance_hint(len_a: float = None, len_b: float = None) -> str:
    """长度配平提示行：judge prompt 防长度偏差的显式纪律。"""
    base = "长度配平纪律：两稿篇幅长短不是质量信号，评分与判定**不得以长度为据**——短稿写完了就是写完了，长稿注水照样扣分。"
    if len_a is None or len_b is None:
        return base + "（本次未提供字数，请格外警惕凭篇幅厚薄下判断）"
    flag = "已配平" if not length_imbalance(len_a, len_b) else "**未配平（长度差≥25%），更须警惕长度偏好**"
    return f"{base}（本次两稿字数 {int(len_a)}/{int(len_b)} 字，{flag}）"


def narrative_first_block() -> str:
    """先叙情节要求块：与审校主审校 B10 纪律同源的判词纪律（+14.8% 判准）。"""
    return ("先叙情节后判决（判准纪律）：给出任何判定之前，先用你自己的话分别复述"
            "两稿的情节（每稿 ≤100 字：谁→做了什么→转折→收在哪个动作上），再对照"
            "复述出的情节下判定——判词先讨论情节再判决，判决正确性显著更高"
            "（评估研究 +14.8%）；禁止跳过复述直接打分，禁止复述照抄原文。")


def build_blind_eval_prompt(prose_a: str, prose_b: str, *, seed: int,
                            dim_block: str = "", extra_rules: str = "",
                            len_a: float = None, len_b: float = None):
    """盲评 A/B judge prompt 构造器（位置置换 + 长度配平 + 先叙情节三件套）。

    返回 (prompt, order)：
    - order = permute_positions(seed, 2)：order[0] 是**先呈现的输入下标**
      （0=prose_a，1=prose_b）——调用方据 order 把「稿一/稿二」映射回真实变体，
      judge 只见 稿一/稿二，变体身份/模型名/来源永不进 prompt；
    - dim_block：可选评分维度块（如 blind_pack.DIMS 说明），缺省只出胜负判定；
    - extra_rules：追加规则（如题材判据）；len_a/len_b 提供时提示行带字数与配平状态。
    """
    order = permute_positions(seed, 2)
    proses = [prose_a or "", prose_b or ""]
    parts = [
        "你是网文盲评裁判。下面两稿正文来自同一题目的不同写法，你的任务：判哪稿更好。",
        "## 防偏差纪律（三件套，逐条遵守）",
        "1. " + narrative_first_block(),
        "2. " + length_balance_hint(len_a, len_b),
        "3. 位置盲评：两稿以「稿一/稿二」随机顺序呈现，呈现顺序与质量无关，不要因先读/后读产生偏好；你的输出里只允许出现「稿一/稿二」，禁止猜测或提及稿件来源、变体名、模型名。",
    ]
    if extra_rules:
        parts.append("## 追加判据\n" + extra_rules)
    for label, idx in zip(_BLIND_LABELS, order):
        parts.append(f"## {label}\n{proses[idx]}")
    out = ["## 输出格式（严格遵守）", "===情节重述===（两稿各一段，先叙后判）",
           "===判定=== [稿一胜|稿二胜|平局] + 一句依据（依据必须落在具体情节上，禁「感觉」「文笔更好」式空评）"]
    if dim_block:
        out.append("===评分===\n" + dim_block)
    parts.append("\n".join(out))
    return "\n\n".join(parts), order
