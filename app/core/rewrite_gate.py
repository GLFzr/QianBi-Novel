# -*- coding: utf-8 -*-
"""改写净增益闸（0.24.0 Q2-b）。

背景（docs/0.24.0_质量全量提升计划.md §一 P0-2 / ICLR 2310.01798）：
无外部信号的自我改写必然倾向变差。旧采纳判据只有「非空+长度」（二测已加长度
骤减守卫，但那是「不比原来差多少」而非「比原来好」）。本模块给一切改写相位
（trim/deslop/review_fix）一个零成本的**机器外部信号**：改写稿必须在本地指标
上不劣化、且保留在场的角色名——否则拒绝采纳，调用方回退原稿。

纯函数、零 LLM、零盘上副作用；stages._rewrite_phase 统一接线。
"""
import os
import re

from . import gates
from . import deslop_metrics

# ---- 常量（0.24.0 v1 标定；后续按盲评回归调参）----
MAX_RULE_GROWTH = 0        # 阻断数不得增加
MAX_TOTAL_GROWTH = 2       # 阻断+建议总量容差（改写可能换一种建议形态）
# 四元组复现率容差：该指标非 0-1 归一（重复饱和文本可 >1，夹具实测 3.85），用
# **相对**增长阈值——劣化超 10% 才拒（夹具 39↔40 次复读的 2% 波动不误杀，
# 真堆料的翻倍增长必拒）。
MAX_REPEAT_GROWTH_REL = 0.10
MIN_KEEP_RATIO = 0.5       # 长度下限（保留 50%；trim 目标裁量 ≤30%，安全）
MIN_KEEP_CHARS = 300

GATED_PHASES = ("trim", "deslop", "review_fix")


def _rule_counts(text: str, proj: str = None) -> tuple:
    blocking, advisory = gates.scan_deslop(text, proj=proj)
    return len(blocking), len(advisory)


def _repeat_ratio(text: str) -> float:
    blocking, advisory = gates.scan_deslop(text)
    m = deslop_metrics.compute_metrics(text, list(blocking) + list(advisory))
    try:
        return float((m.get("repetition") or {}).get("fourgram_repeat_ratio") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def tracked_names(proj: str) -> list:
    """角色名清单：追踪/角色状态.md 的 `## 角色名` 小节标题（记账真源，零猜测）。"""
    path = os.path.join(proj or "", "追踪", "角色状态.md")
    try:
        with open(path, encoding="utf-8") as f:
            return [h.strip() for h in re.findall(r"^##\s+(.+)$", f.read(), re.M)
                    if h.strip() and "角色" not in h]
    except OSError:
        return []


def gate_rewrite(before: str, after: str, *, names: tuple = (), proj: str = None) -> tuple:
    """改写净增益判定。返回 (ok, reasons)。

    判据（全零成本本地指标）：
    1. 长度下限：after ≥ max(300, before×50%)（毁稿式重写拦截，与既有守卫同哲学）；
    2. 阻断不增：after 阻断数 ≤ before 阻断数；
    3. 总量容差：after 阻断+建议 ≤ before 总量 + 2；
    4. 复现不劣化：fourgram_repeat_ratio(after) ≤ before + 0.02（防堆料）；
    5. 角色在场：before 中出场的角色名（tracked_names 提供时）在 after 仍在场——
       「信息项在场清单」的 v1 形态（账本名册即信息项；后续扩事实条目）。
    names 显式传入可旁路盘上读取（测试/调用方已持有清单时）。空清单=该项跳过
    （fail-open：没有账本的书不做名册断言）。
    """
    reasons = []
    b_block, b_adv = _rule_counts(before, proj)
    a_block, a_adv = _rule_counts(after, proj)
    if a_block > b_block + MAX_RULE_GROWTH:
        reasons.append(f"阻断数增加 {b_block}→{a_block}")
    if (a_block + a_adv) > (b_block + b_adv) + MAX_TOTAL_GROWTH:
        reasons.append(f"规则总量增加 {b_block + b_adv}→{a_block + a_adv}")
    # 长度下限：保留 ≥50%；绝对地板 300 只对长文（≥2×300）生效——短文（如共写
    # 草稿数百字）的增长型改写不该被绝对地板误杀（三测后回归发现：216→243 被
    # 拒，floor 公式错在 max 恒取 300）。
    floor = int(len(before) * MIN_KEEP_RATIO)
    if len(before) >= MIN_KEEP_CHARS * 2:
        floor = max(floor, MIN_KEEP_CHARS)
    if len(after) < floor:
        reasons.append(f"长度骤减 {len(before)}→{len(after)}（下限 {floor}）")
    rep_b, rep_a = _repeat_ratio(before), _repeat_ratio(after)
    if rep_a > rep_b * (1 + MAX_REPEAT_GROWTH_REL) + 0.01:
        reasons.append(f"四元组复现率劣化 {rep_b:.3f}→{rep_a:.3f}")
    pool = list(names) if names else tracked_names(proj)
    if pool:
        missing = [n for n in pool if n in before and n not in after]
        if missing:
            reasons.append("角色丢失：" + "、".join(missing[:3]))
    return (not reasons), reasons
