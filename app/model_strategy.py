# -*- coding: utf-8 -*-
"""模型策略（方案 B）：角色→档位→连接 的两级解析 + 出厂预设

背景（验证实测）：百炼 flash-0731 审校票 5-8 分钟、追踪更新两次 600s 超时、
每章一次空流返回；DeepSeek 官方 flash 草稿 79 秒/章、零超时。作者拍板：
**全量切 DeepSeek 官方**。本模块提供：
  ensure_official_connections —— 官方 flash/pro 连接行确保存在（Key 复用同账号行）
  apply_preset               —— 一键把三槽指向官方全家桶 / 严格审校（review 升 pro）
  preset_options             —— 设置页的预设清单

Key 来源策略：官方连接共用同一把 DeepSeek Key——优先从现有官方行（ds-v4-pro）
取已水合的 api_key，其次从凭据管理器按已知 id 取；都没有则保留空（用户填一次
官方 Key 到任意行即可全家生效）。
"""
from . import secrets as secrets_mod

OFFICIAL_FLASH = "ds-official-flash"
OFFICIAL_PRO = "ds-official-pro"

PRESETS = {
    "official_all": {
        "label": "官方全家桶（DeepSeek 官方 flash ×3 槽，推荐）",
        "slots": {"writing": OFFICIAL_FLASH, "helper": OFFICIAL_FLASH, "review": OFFICIAL_FLASH},
    },
    "strict_review": {
        "label": "严格审校（写作/辅助 flash，审校 pro）",
        "slots": {"writing": OFFICIAL_FLASH, "helper": OFFICIAL_FLASH, "review": OFFICIAL_PRO},
    },
}

# 已知存过官方 Key 的连接 id（按序探测）
_KEY_DONORS = ("ds-v4-pro", OFFICIAL_PRO, OFFICIAL_FLASH, "legacy")


def _official_row(cfg: dict, conn_id: str, model: str, name: str) -> dict:
    return {"id": conn_id, "name": name, "provider": "deepseek",
            "base_url": "https://api.deepseek.com", "api_key": "",
            "model": model, "temperature": 0.7,
            "max_tokens": 32768, "timeout": 300}


def _official_key(cfg: dict) -> str:
    """官方 Key：已水合行 → 凭据管理器（按已知 donor id 顺序）"""
    for c in cfg.get("connections", []):
        cid = str(c.get("id", ""))
        if cid in _KEY_DONORS and c.get("api_key"):
            return c["api_key"]
    for cid in _KEY_DONORS:
        k = secrets_mod.get_secret(cid)
        if k:
            return k
    return ""


def ensure_official_connections(cfg: dict) -> dict:
    """官方 flash/pro 两行连接确保存在且带 Key（幂等；就地修改并返回 cfg）"""
    key = _official_key(cfg)
    rows = {c.get("id"): c for c in cfg.setdefault("connections", [])}
    specs = {OFFICIAL_FLASH: ("deepseek-v4-flash", "DeepSeek 官方 V4 Flash"),
             OFFICIAL_PRO: ("deepseek-v4-pro", "DeepSeek 官方 V4 Pro")}
    for conn_id, (model, name) in specs.items():
        row = rows.get(conn_id)
        if row is None:
            row = _official_row(cfg, conn_id, model, name)
            cfg["connections"].append(row)
            rows[conn_id] = row
        if key and not row.get("api_key"):
            row["api_key"] = key
    return cfg


def apply_preset(cfg: dict, preset_id: str) -> dict:
    """应用模型策略预设：确保官方连接存在 + 三槽重绑。返回应用后的槽位映射。

    preset_id 不在 PRESETS 里时原样返回（custom = 用户手动绑定，不动）。
    """
    spec = PRESETS.get(preset_id)
    if not spec:
        return cfg
    ensure_official_connections(cfg)
    cfg.setdefault("slots", {}).update(spec["slots"])
    return cfg


def preset_options() -> list:
    return [{"id": pid, "label": spec["label"]} for pid, spec in PRESETS.items()]
