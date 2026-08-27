# -*- coding: utf-8 -*-
"""题材预设系统：主干 prompt 题材无关，题材差异经预设注入

- 内置预设：app/presets/*.json
- 用户预设：~/.qianbi_novel/presets/*.json（导入的预设放这里，重装不丢）
- 项目选用：pipeline_state.json 的 genre_preset 字段（随时可切，下一章生效）
"""
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


def genre_block(preset_id: str) -> str:
    """把预设合成为注入主干 prompt 的「题材预设」块（空预设返回占位）"""
    if not preset_id:
        return "（本书未启用题材预设，按通用网文规范写作）"
    p = load_preset(preset_id)
    if not p:
        return "（本书未启用题材预设，按通用网文规范写作）"
    parts = [f"【题材预设：{p.get('name', preset_id)}】"]
    for key, label in PRESET_FIELDS:
        val = (p.get(key) or "").strip()
        if val:
            parts.append(f"### {label}\n{val}")
    return "\n\n".join(parts)


def deslop_extra(preset_id: str) -> str:
    p = load_preset(preset_id) if preset_id else {}
    return (p.get("deslop_extra") or "").strip()


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


def validate_sample() -> None:
    for it in list_presets():
        if it["id"]:
            load_preset(it["id"])
