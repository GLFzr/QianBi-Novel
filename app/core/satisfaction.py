# -*- coding: utf-8 -*-
"""B1 爽点引擎（0.20.0 L5-B1，质量线唯一 P0；台账 §6.2）

33 章实测无一次完整「压抑→反转→结算」闭环：既有 `- 爽点：` 字段只是一句承诺
（payoff_findings 只能抓推迟语式），没有可逐拍追责的结构化字段。本模块给细纲
加「本章爽点节拍」三拍字段（压抑对象/反转触发/结算兑现），并把它作为必须兑现
的写作指令注入正文轮——生成侧立约、写作侧履约、L0 侧确定性对账（l0_checks.

开关：`writing.satisfaction_engine`（缺省 False，变量隔离纪律）——关闭时本模块
全部产出为空串，装配字节与 0.19.x 逐字节一致；节拍行不存在时 l0_checks 的节拍
检查恒空（证据在场才检查，不读配置）。

设计边界（登记册 B1 原文）：
- 允许「本章无节拍」显式空档——低压章不每章强塞，但空档必须写明，不许缺失本行；
- 「无节拍」不得连续超过 2 章、每 3-5 章至少 1 次完整三拍闭环（连排规则进指令）；
- 判据：盲评 D2（爽点闭环）由 +0.02 → ≥ +0.5。
"""
from __future__ import annotations

import re

# 节拍字段行（细纲内的唯一事实源；解析与检查共用本正则）
_BEAT_LINE_RE = re.compile(r"^-\s*本章爽点节拍[：:]\s*(.+)$", re.M)

# 显式空档标记（与 l0_checks.payoff_findings 的「无显性爽点」同纪律：不评不判）
_NO_BEAT_MARKERS = ("无节拍", "无爽点节拍", "本章无")

# 三拍结构标记（节拍行缺段 = 结构不完整，供 L0 出「核对」级证据）
_BEAT_SEGMENTS = ("压抑", "反转", "结算")

# 压抑拍与反转拍的边界标记之外的第四拍不许有（防模型把结算写成空头支票）——
# 只查三拍齐全，不约束写法。

_OUTLINE_DIRECTIVE = """

## 本章爽点节拍字段（爽点引擎·每章必须填写，缺行即不合格）
在每章细纲的「- 爽点：」行之后**必须**新增一行，格式三选一：
- 本章爽点节拍：压抑（谁/什么被压制，压力可指认）→ 反转（触发事件与主角动作）→ 结算（兑现与收益，当场落袋）
- 本章爽点节拍：本章无节拍（理由：……）——低压/铺垫章的显式空档
- 承接章（上一章已立压抑拍）：本章爽点节拍：压抑（延续上章）→ 反转（……）→ 结算（……）
纪律：三拍必须落在**本章**可演出的场景上（不许写"下一章才结算"）；「本章无节拍」
连续不得超过 2 章；本批细纲每 3-5 章至少 1 章是完整三拍闭环（结算收益当场到手：
灵石/地位/信息/伤敌，不能白忙）。"""


def _engine_on(cfg: dict) -> bool:
    return bool(((cfg or {}).get("writing", {}) or {}).get("satisfaction_engine", False))


def outline_directive(cfg: dict) -> str:
    """细纲模板尾部的节拍字段指令块；引擎关闭返回空串（装配字节不变）。"""
    return _OUTLINE_DIRECTIVE if _engine_on(cfg) else ""


def beat_of_outline(outline: str) -> str:
    """细纲「本章爽点节拍」行原文（单一事实源；无行返回空串）。"""
    m = _BEAT_LINE_RE.search(outline or "")
    return m.group(1).strip() if m else ""


def beat_declared(beat: str) -> bool:
    """该章是否声明了真实节拍（False = 无行 / 显式空档——两者都不评不判）。"""
    beat = (beat or "").strip()
    if not beat:
        return False
    return not any(m in beat for m in _NO_BEAT_MARKERS[:2]) and not beat.startswith("本章无")


_PROSE_BLOCK_TMPL = """

## 本章爽点节拍（细纲契约：三拍必须逐拍演成场景，不得推迟或一笔带过）
- 细纲节拍：{beat}
执行纪律：压抑拍先给可指认的压力铺垫；反转拍本章当场触发（主角有动作，不是等来的）；
结算拍收益当场落袋并写出在场反应——禁止「算了吧/改日再算」式推迟（L0 预检按推迟
语式确定性抓，检出即进审校裁决）。"""


def prose_beat_block(outline: str) -> str:
    """正文 PROSE 轮的节拍兑现指令块。

    仅当本章细纲声明了真实节拍时非空——「本章无节拍」章与引擎关闭时返回空串
    （空档章不强塞，装配字节与引擎关闭逐字节一致）。
    """
    beat = beat_of_outline(outline)
    if not beat_declared(beat):
        return ""
    return _PROSE_BLOCK_TMPL.format(beat=beat[:300])
