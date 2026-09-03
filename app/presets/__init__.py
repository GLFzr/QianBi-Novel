# -*- coding: utf-8 -*-
"""题材预设系统：主干 prompt 题材无关，题材差异经预设注入

- 内置预设：app/presets/*.json
- 用户预设：~/.qianbi_novel/presets/*.json（导入的预设放这里，重装不丢）
- 项目选用：pipeline_state.json 的 genre_preset 字段（随时可切，下一章生效）
"""
import hashlib
import json
import os
import re
import shutil

BUILTIN_DIR = os.path.dirname(os.path.abspath(__file__))

PRESET_FIELDS = [
    # (键, 中文说明)
    ("style_hint", "文风补充"),
    ("world_rules", "题材世界规则"),
    ("plot_conventions", "题材套路与节奏"),
    ("taboos", "题材禁忌"),
    ("deslop_extra", "题材专属去味黑名单"),
    ("review_extra", "题材审校补充"),
]

# 共写参考字段（grow_*）：仅供共写档阶段 Agent 参考、不得锁定死；不进 genre_block
GROW_FIELDS = [
    ("grow_core_template", "同类型核心设定的优秀设计参考"),
    ("grow_outline_template", "同类型大纲的体量划分/卷级/终局储备范式"),
    ("grow_worldbook_direction", "同类型世界书应覆盖的板块方向"),
    ("grow_unit_logic", "同类型小单元细纲逻辑（开-承-转-合模板）"),
    ("grow_regex_direction", "同类型适合固化为必须成立约束的规则方向"),
]

# ---- v2：分环节特化提示词（每个创作环节一个专属块，题材特化但不固定情节）----

STAGE_HINT_KEYS = [
    # (stage_key, 中文说明)
    ("core_setting", "核心设定环节特化"),
    ("outline", "大纲环节特化"),
    ("unit_outline", "细纲环节特化"),
    ("prose", "正文环节特化（文风锚）"),
    ("worldbook", "世界书环节特化"),
    ("review", "审校环节特化"),
]

# 各环节额外携带的 v1 共享字段（文风/世界规则等按相关性分配）
_STAGE_SHARED_FIELDS = {
    "core_setting": ["world_rules", "plot_conventions", "taboos"],
    "outline": ["world_rules", "plot_conventions", "taboos"],
    "unit_outline": ["world_rules", "plot_conventions", "taboos"],
    "prose": ["style_hint", "world_rules", "taboos"],
    "worldbook": ["world_rules"],
    "review": [],
}


def stage_hint(preset_id: str, stage: str) -> str:
    """v2 分环节特化提示词块（无预设/旧 JSON 返回空串，不报错）"""
    if not preset_id or stage not in dict(STAGE_HINT_KEYS):
        return ""
    p = load_preset(preset_id)
    hints = p.get("stage_hints") or {}
    val = (hints.get(stage) or "").strip()
    if not val:
        return ""
    label = dict(STAGE_HINT_KEYS).get(stage, stage)
    return f"【{label}（题材专属指导：约束框架与文风，不限定具体情节）】\n{val}"


def genre_block_for(preset_id: str, stage: str) -> str:
    """按环节组装题材预设块（v2）：环节特化 hint 打头 + 相关共享字段随后。

    v1 预设（无 stage_hints）退化为原 genre_block 全量注入（向后兼容）。
    """
    if not preset_id:
        return "（本书未启用题材预设，按通用网文规范写作）"
    hint = stage_hint(preset_id, stage)
    if not hint:
        return genre_block(preset_id)
    p = load_preset(preset_id)
    parts = [f"【题材预设：{p.get('name', preset_id)} · {dict(STAGE_HINT_KEYS).get(stage, stage)}】", hint]
    labels = dict(PRESET_FIELDS)
    for key in _STAGE_SHARED_FIELDS.get(stage, []):
        val = (p.get(key) or "").strip()
        if val:
            parts.append(f"### {labels.get(key, key)}\n{val}")
    return "\n\n".join(parts)


def grow_block(preset_id: str, field: str) -> str:
    """共写档阶段 Agent 参考块（方案 §2）：grow_* 仅参考不锁定

    - 无预设 / 缺字段 / 旧 JSON → 占位「该预设未提供此参考」，不报错
    - 不进 genre_block：只由共写档经本函数读取
    """
    if not preset_id:
        return "（通用流程无题材预设：按通用网文规范给出参考即可）"
    p = load_preset(preset_id)
    if not p:
        return "（该预设未提供此参考）"
    val = (p.get(field) or "").strip()
    if not val:
        return "（该预设未提供此参考）"
    label = dict(GROW_FIELDS).get(field, field)
    return f"【同类型参考：{label}（仅供参考、不得锁定死）】\n{val}"


def user_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "presets")
    os.makedirs(d, exist_ok=True)
    return d


def _load_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_src"] = path
        data["_builtin"] = path.startswith(BUILTIN_DIR)
        return data
    except (OSError, ValueError):
        return None


def list_presets() -> list:
    """[{id,name,description,builtin}]：通用占位 + 内置 + 用户导入"""
    result = [{"id": "", "name": "通用（不使用题材预设）",
               "description": "主干提示词独立服务所有题材，无题材专项约束", "builtin": True}]
    seen = set()
    for d in (BUILTIN_DIR, user_dir()):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(d, fn)
            data = _load_file(p)
            if not data or data.get("id") in seen:
                continue
            # v0.13：v1 文件自动迁移到 v2（确保 list 拿到的元数据是 v2）
            data = _migrate_v1_to_v2(data)
            seen.add(data.get("id"))
            result.append({
                "id": data.get("id", ""),
                "name": data.get("name", fn),
                "description": data.get("description", ""),
                "builtin": data["_builtin"],
            })
    return result


def _migrate_v1_to_v2(data: dict) -> dict:
    """v1 → v2 自动迁移：把 v1 共享字段塞入 stage_hints['prose'] fallback。

    - 不修改原始 JSON（内存层）
    - 添加 _v2_migrated 标记，供调用方 toast 告知用户
    """
    if data.get("version", 1) >= 2:
        return data
    style = (data.get("style_hint") or "").strip()
    if style and "stage_hints" not in data:
        data = dict(data)
        data["stage_hints"] = {"prose": style}
        data["_v2_migrated"] = True
    data["version"] = 2
    return data


def load_preset(preset_id: str) -> dict:
    for d in (user_dir(), BUILTIN_DIR):  # 用户导入的同名覆盖内置
        p = os.path.join(d, f"{preset_id}.json")
        if os.path.isfile(p):
            data = _load_file(p)
            if data:
                return _migrate_v1_to_v2(data)
    return {}


# 已有专属近端槽的字段不再进题材块：deslop_extra 由 stages._tic_blacklist 落到
# 「去 AI 味红线 / 专属口头禅黑名单」一节——那一节同时存在于写作/扩写/压缩/去味四张
# 模板上，题材块却只在前两张；与其在中段多占一份预算，不如只走生效面更大的槽。
_GENRE_BLOCK_DEDICATED = {"deslop_extra"}


def genre_block(preset_id: str) -> str:
    """把预设合成为注入主干 prompt 的「题材预设」块（空预设返回占位）"""
    if not preset_id:
        return "（本书未启用题材预设，按通用网文规范写作）"
    p = load_preset(preset_id)
    if not p:
        return "（本书未启用题材预设，按通用网文规范写作）"
    parts = [f"【题材预设：{p.get('name', preset_id)}】"]
    for key, label in PRESET_FIELDS:
        if key in _GENRE_BLOCK_DEDICATED:
            continue
        val = (p.get(key) or "").strip()
        if val:
            parts.append(f"### {label}\n{val}")
    return "\n\n".join(parts)


def deslop_extra(preset_id: str) -> str:
    p = load_preset(preset_id) if preset_id else {}
    return (p.get("deslop_extra") or "").strip()


def author_note(preset_id: str) -> str:
    """作者按（SillyTavern Author's Note 语义）：短提醒，只注入正文 prompt 近端。

    刻意不进 PRESET_FIELDS/genre_block —— 题材块落在 prompt 中段会被长上下文稀释，
    作者按的价值恰在贴着生成点；重复注入等于浪费额度。
    """
    p = load_preset(preset_id) if preset_id else {}
    return (p.get("author_note") or "").strip()


# ---- 阶段参数档（预设＝组装层：不只拼文本，还管每阶段用什么档、什么采样）----

# 相位键必须与 app/core/stages.py 的 PHASE_* 字面量一致（单测锁死，改名即破坏兼容）
STAGE_PARAM_PHASES = [
    ("core_setting", "核心设定"),
    ("volume_outline", "全书大纲"),
    ("worldbook", "世界书"),
    ("outline", "细纲"),
    ("prose", "正文"),
    ("enrich", "扩写"),
    ("trim", "压缩"),
    ("deslop", "去 AI 味"),
    ("review", "审校"),
    ("root_cause", "根因分析"),
    ("review_fix", "审校修复"),
]

# (键, 中文说明, 下限, 上限, 取整)；slot 只用于选客户端，不进 HTTP 请求体
STAGE_PARAM_FIELDS = [
    ("slot", "连接槽", None, None, False),
    ("temperature", "温度", 0.0, 2.0, False),
    ("top_p", "核采样", 0.0, 1.0, False),
    ("presence_penalty", "存在惩罚", -2.0, 2.0, False),
    ("frequency_penalty", "频率惩罚", -2.0, 2.0, False),
    ("max_tokens", "输出上限", 1, 1000000, True),
]


def _coerce_param(key: str, val, lo, hi, as_int: bool):
    """单个参数取值校验：非数 / 越界 / 空串一律丢弃

    丢弃而不是钳位 —— 钳位会把「用户写错了」伪装成「故意设成边界值」。
    数值接受字符串写法（"0.9"）：预设 JSON 以手写为主，但这种写法不会被静默吞掉。
    审校温度另有一道锁（app/llm/client.TEMP_LOCKED_PHASES），这里不重复判。
    """
    if key == "slot":
        s = str(val or "").strip()
        return s[:40] if s else None
    if isinstance(val, str):
        try:
            val = float(val.strip())
        except ValueError:
            return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    v = float(val)
    if not (lo <= v <= hi):
        return None
    return int(v) if as_int else v


def stage_params(preset_id: str) -> dict:
    """预设的 {phase: {参数: 值}}（未知相位/未知键/脏值丢弃，旧 JSON 无此键返回 {}）"""
    p = load_preset(preset_id) if preset_id else {}
    raw = p.get("stage_params")
    if not isinstance(raw, dict):
        return {}
    phases = dict(STAGE_PARAM_PHASES)
    out = {}
    for phase, vals in raw.items():
        if phase not in phases or not isinstance(vals, dict):
            continue
        ov = {}
        for key, _label, lo, hi, as_int in STAGE_PARAM_FIELDS:
            if key not in vals:
                continue
            v = _coerce_param(key, vals[key], lo, hi, as_int)
            if v is not None:
                ov[key] = v
        if ov:
            out[phase] = ov
    return out


def stage_slot(preset_id: str, phase: str) -> str:
    """本阶段指定的连接槽；未配置返回空串（调用方沿用默认槽）"""
    return str((stage_params(preset_id).get(phase) or {}).get("slot") or "")


# 全书采样基线可写的参数：slot 只在相位档有意义（选槽按阶段），基线不分相位
_SAMPLING_KEYS = {k: (lo, hi, as_int) for k, _l, lo, hi, as_int in STAGE_PARAM_FIELDS
                  if k != "slot"}
# 参数名与网关方言同源，允许预设按连接习惯固化 thinking/effort（清空＝不写这个键）
_SAMPLING_EXTRA = (("thinking", "思考模式", ("disabled", "enabled")),
                   ("reasoning_effort", "思考强度", ("low", "high", "max")))
SAMPLING_LABELS = {k: lab for k, lab, _lo, _hi, _int in STAGE_PARAM_FIELDS if k != "slot"}
SAMPLING_LABELS.update({k: lab for k, lab, _allowed in _SAMPLING_EXTRA})


def sampling(preset_id: str) -> dict:
    """预设的全书采样基线（SillyTavern preset 的 sampling 段）→ 客户端 payload_defaults

    与 stage_params 同一套「脏值即丢」校验；相位档压在它之上，显式实参压过两者。
    """
    p = load_preset(preset_id) if preset_id else {}
    raw = p.get("sampling")
    if not isinstance(raw, dict):
        return {}
    allowed_extra = {k: allowed for k, _lab, allowed in _SAMPLING_EXTRA}
    out = {}
    for key, val in raw.items():
        if key in _SAMPLING_KEYS:
            lo, hi, as_int = _SAMPLING_KEYS[key]
            v = _coerce_param(key, val, lo, hi, as_int)
        elif key in allowed_extra:
            s = str(val or "").strip().lower()
            v = s if s in allowed_extra[key] else None
        else:
            v = None
        if v is not None:
            out[key] = v
    return out


def review_extra(preset_id: str) -> str:
    p = load_preset(preset_id) if preset_id else {}
    return (p.get("review_extra") or "").strip()


def import_preset(path: str) -> dict:
    """导入预设文件（json）到用户目录；返回 {ok, msg, id}"""
    data = _load_file(path)
    if not data:
        return {"ok": False, "msg": "不是有效的预设文件（需要 JSON）"}
    pid = re.sub(r"[^a-zA-Z0-9_\-]", "", data.get("id") or "")[:40]
    if not pid:
        pid = "imported_" + str(int(__import__("time").time()) % 100000)
        data["id"] = pid
    if not data.get("name"):
        data["name"] = pid
    data.pop("_src", None)
    data.pop("_builtin", None)
    out = os.path.join(user_dir(), f"{pid}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "msg": f"预设「{data['name']}」已导入", "id": pid}


def export_preset(preset_id: str, out_path: str) -> bool:
    p = load_preset(preset_id)
    if not p:
        return False
    p.pop("_src", None)
    p.pop("_builtin", None)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    return True


# ---- P3：章级生成快照（P2）→ 可复用的组装层模板 ----

_SNAP_STAGE_KEYS = {k for k, _lab, _lo, _hi, _int in STAGE_PARAM_FIELDS}

# 固化时由快照重新决定的字段；其余（题材文本块）原样带走，_ 前缀是加载器打的路径标记
_TEMPLATE_SKIP_KEYS = {"id", "name", "version", "description", "sampling", "stage_params"}


def save_preset(data: dict) -> str:
    """写入用户预设仓（与 import_preset 同落点同格式，加载链原样复用）"""
    if not str(data.get("id") or "").strip():
        raise ValueError("预设缺 id，无法落盘")
    out = os.path.join(user_dir(), f"{data['id']}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out


def snapshot_template_id(book_title: str, num: int) -> str:
    """同一书同一章恒得同一 id：重复固化只覆盖同一模板，不在用户目录里堆垃圾"""
    h = hashlib.sha1(f"{book_title}#{int(num)}".encode("utf-8")).hexdigest()[:8]
    return f"snap_{h}"


def preset_from_snapshot(snap: dict, book_title: str, source: dict = None) -> dict:
    """快照 → v2 预设字典（冻结这一章的完整配方）

    一个项目只挂一个题材预设，所以模板必须连来源预设的题材文本块一起带走——
    只留参数会让用户一选它就丢文风。参数则反过来取「每次调用真实下发的采样」
    而非预设声明值：网关已拒收的键不会被写回来，换本书也不会重复踩同一次降级。
    脏键交给 stage_params()/sampling() 的校验剥掉，这里不另建第二套钳位规则。
    """
    snap = snap or {}
    num = int(snap.get("num") or 0)
    per_phase = {}
    for c in snap.get("calls") or []:
        phase = c.get("phase") or ""
        if not phase or phase in per_phase:   # 多票/重试取首次，后续调用只在失败时才发生
            continue
        vals = {k: v for k, v in (c.get("sampling") or {}).items() if k in _SNAP_STAGE_KEYS}
        slot = str(c.get("slot") or "").strip()
        if slot:
            vals["slot"] = slot
        if vals:
            per_phase[phase] = vals
    out = {k: v for k, v in (source or {}).items()
           if k not in _TEMPLATE_SKIP_KEYS and not k.startswith("_")}
    out.update({
        "id": snapshot_template_id(book_title, num),
        "name": f"《{book_title}》第{num}章配方",
        "version": 2,
        "description": "由《%s》第 %d 章生成快照（%s）固化；来源预设：%s。"
                       "题材文本块沿用来源预设，采样与相位档取该章实际下发值。"
                       % (book_title, num, snap.get("ts", ""),
                          (source or {}).get("name") or "通用（无预设）"),
        "sampling": dict(snap.get("sampling") or {}),
        "stage_params": per_phase,
    })
    return out


def validate_sample() -> None:
    for it in list_presets():
        if it["id"]:
            load_preset(it["id"])
