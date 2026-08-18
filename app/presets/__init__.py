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
            seen.add(data.get("id"))
            result.append({
                "id": data.get("id", ""),
                "name": data.get("name", fn),
                "description": data.get("description", ""),
                "builtin": data["_builtin"],
            })
    return result


def load_preset(preset_id: str) -> dict:
    for d in (user_dir(), BUILTIN_DIR):  # 用户导入的同名覆盖内置
        p = os.path.join(d, f"{preset_id}.json")
        if os.path.isfile(p):
            data = _load_file(p)
            if data:
                return data
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
