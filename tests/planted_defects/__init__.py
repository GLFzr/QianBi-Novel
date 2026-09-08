# -*- coding: utf-8 -*-
"""雷集 v2 框架（W0.5 / E3.1）：埋雷数据加载、六维覆盖报告与轮换政策校验

雷集文件：本目录下 defects.json（schema version=2）。
- 每颗雷落在 FINAL_REVIEW_PROMPT（app/prompts/review.py）六维之一的**明文硬规则**上；
- 每颗雷须双人独立核验"确实违反明文硬规则"后才算入集（verified_by，SWE-bench Verified 教训）；
- 每 2 轮实验轮换 30%（check_rotation，防审校模型记忆化）；
- 埋雷/去雷工具见 scripts/plant_defects.py；v1 四雷已迁移入库（legacy_v1=true）。

本模块只依赖标准库，禁止真实 LLM 调用（核验字段是人工流程的载体）。
"""
from __future__ import annotations

import json
import math
import os
import re

__all__ = [
    "DIMS", "MODES", "TEXT_MIN", "TEXT_MAX", "DefectSchemaError",
    "load_defects", "by_dim", "coverage_report", "check_rotation",
]

# 审校六维（与 FINAL_REVIEW_PROMPT 输出格式的六个小节一一对应）
DIMS = ["A_GOLDEN_OPEN", "B_PAYOFF", "C_FINGER", "D_PLOT", "E_CHARACTER", "F_HOOK"]
# 注入模式（与 scripts/plant_defects.py 的实现一一对应）
MODES = ["after_title", "before_end", "at_end", "replace_regex"]
# 注入正文的字数区间（写得像真正文）
TEXT_MIN, TEXT_MAX = 30, 120
# 轮换政策：每 2 轮实验轮换 30%
ROTATION_INTERVAL = 2
ROTATION_RATIO = 0.3

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "defects.json")


class DefectSchemaError(ValueError):
    """雷集文件 schema 校验失败。"""


def load_defects(path=None, validate=True):
    """读取雷集文件并做 schema 校验，返回原始 dict。

    校验项：version==2；rotation 段（policy/history）；雷数 ≥12；
    id 唯一且形如 A01；dim 合法且六维每维 ≥2；inject.mode 合法；
    replace_regex 的 anchor 必须是可编译正则；text 30-120 字；verified_by 为 list。
    校验失败抛 DefectSchemaError。
    """
    path = path or DEFAULT_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if validate:
        _validate(data)
    return data


def _validate(data):
    if not isinstance(data, dict):
        raise DefectSchemaError("雷集根节点必须是 dict")
    if data.get("version") != 2:
        raise DefectSchemaError("version 必须为 2，实际：%r" % data.get("version"))
    rot = data.get("rotation")
    if not isinstance(rot, dict) or not isinstance(rot.get("policy"), str) \
            or not isinstance(rot.get("history"), list):
        raise DefectSchemaError("rotation 段缺失或格式错误（需 policy:str + history:list）")
    defects = data.get("defects")
    if not isinstance(defects, list) or len(defects) < 12:
        raise DefectSchemaError("defects 必须 ≥12 颗，实际：%r" % (len(defects) if isinstance(defects, list) else defects))
    seen = set()
    for d in defects:
        did = d.get("id")
        if not isinstance(did, str) or not re.fullmatch(r"[A-F]\d{2}", did):
            raise DefectSchemaError("雷 id 非法（需形如 A01）：%r" % (did,))
        if did in seen:
            raise DefectSchemaError("雷 id 重复：%s" % did)
        seen.add(did)
        if d.get("dim") not in DIMS:
            raise DefectSchemaError("雷 %s 的 dim 非法：%r" % (did, d.get("dim")))
        for key in ("rule_ref", "desc"):
            if not isinstance(d.get(key), str) or not d[key].strip():
                raise DefectSchemaError("雷 %s 缺少必填字段：%s" % (did, key))
        inj = d.get("inject")
        if not isinstance(inj, dict):
            raise DefectSchemaError("雷 %s 缺少 inject 段" % did)
        mode = inj.get("mode")
        if mode not in MODES:
            raise DefectSchemaError("雷 %s 的 inject.mode 非法：%r" % (did, mode))
        anchor = inj.get("anchor")
        if not isinstance(anchor, str) or not anchor.strip():
            raise DefectSchemaError("雷 %s 缺少 anchor" % did)
        if mode == "replace_regex":
            try:
                re.compile(anchor)
            except re.error as e:
                raise DefectSchemaError("雷 %s 的 anchor 不是合法正则：%s" % (did, e))
        text = inj.get("text")
        if not isinstance(text, str) or not (TEXT_MIN <= len(text) <= TEXT_MAX):
            raise DefectSchemaError("雷 %s 的 text 长度须 %d-%d 字，实际：%d"
                                    % (did, TEXT_MIN, TEXT_MAX, len(text) if isinstance(text, str) else -1))
        if not isinstance(inj.get("strip_hint"), str) or not inj["strip_hint"].strip():
            raise DefectSchemaError("雷 %s 缺少 strip_hint" % did)
        if not isinstance(d.get("verified_by"), list):
            raise DefectSchemaError("雷 %s 的 verified_by 须为 list（双人核验记录）" % did)
    # 六维覆盖：每维 ≥2
    report = coverage_report(data)
    if report["missing"]:
        raise DefectSchemaError("六维覆盖不足（每维 ≥2），缺口：%s"
                                % ", ".join("%s=%d" % (k, v) for k, v in report["missing"].items()))


def by_dim(data=None, dim=None):
    """按维度分组返回 {dim: [defect, ...]}；给定 dim 时只返回该维列表。

    data 缺省时自动 load_defects()。
    """
    data = data if data is not None else load_defects()
    groups = {k: [] for k in DIMS}
    for d in data.get("defects", []):
        if d.get("dim") in groups:
            groups[d["dim"]].append(d)
    if dim is not None:
        if dim not in DIMS:
            raise DefectSchemaError("未知维度：%r" % (dim,))
        return groups[dim]
    return groups


def coverage_report(data=None):
    """六维分布报告：总数、每维计数、缺口（某维 <2 记入 missing）、legacy 数、核验进度。"""
    data = data if data is not None else load_defects()
    groups = by_dim(data)
    per_dim = {k: len(v) for k, v in groups.items()}
    defects = data.get("defects", [])
    return {
        "total": len(defects),
        "per_dim": per_dim,
        "missing": {k: v for k, v in per_dim.items() if v < 2},
        "legacy_v1": sum(1 for d in defects if d.get("legacy_v1")),
        "verified": sum(1 for d in defects if d.get("verified_by")),
    }


def check_rotation(active_ids, rounds=2, ratio=ROTATION_RATIO):
    """轮换政策校验（policy：每 2 轮实验轮换 30%），返回应轮换的 id 提示列表。

    - rounds：已完成实验轮数；每逢 ROTATION_INTERVAL（2）的整数倍触发一次轮换建议；
    - 数量 = ceil(ratio × len(active_ids))；
    - 选择确定性（可重放）：legacy_v1 优先（最老先用），其余按 id 升序；
    - 未触发返回 []。active_ids 含未知 id 时抛 DefectSchemaError（防手滑）。
    """
    known = {d["id"] for d in load_defects()["defects"]}
    unknown = sorted(set(active_ids) - known)
    if unknown:
        raise DefectSchemaError("active_ids 含雷集外 id：%s" % ", ".join(unknown))
    if rounds < ROTATION_INTERVAL or rounds % ROTATION_INTERVAL != 0:
        return []
    all_defects = sorted(load_defects()["defects"], key=lambda d: (not d.get("legacy_v1"), d["id"]))
    pool = [d["id"] for d in all_defects if d["id"] in set(active_ids)]
    n = math.ceil(ratio * len(pool))
    return pool[:n]
