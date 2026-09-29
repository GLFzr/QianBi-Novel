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
    # ---- C26 阶段级策略卡（w4_model_orch §3 方案 A）----
    # 除三槽层外还带 stage_params 阶段档，由 bridge.ModelPolicyController.applyStrategy
    # 写进项目题材预设（读取/消费管道早已接线：stage_slot/stage_params + stages 各调用点）。
    # 审校系相位（review 三票/根因/修复/清算/终审）读码里全部默认走 review 槽，
    # 所以「强审校」在槽位层把 review 槽钉 Pro 即全组生效；阶段层再把草稿组与
    # 大纲组相位钉死 Flash——日后用户把写作槽升 Pro，快草稿组合语义也不漂移。
    # A14：两卡钉的都是官方 Flash/Pro 行（apply_preset 已确保存在），零静默换型。
    "quality_mix": {
        "label": "强审校快草稿（审校槽 Pro，草稿/大纲钉 Flash）",
        "slots": {"writing": OFFICIAL_FLASH, "helper": OFFICIAL_FLASH, "review": OFFICIAL_PRO},
        "desc": "审校/根因/清算走官方 Pro，判分更稳；正文/扩写/压缩/去味与四个大纲相位在阶段层钉 Flash，日后升写作槽也不改快草稿。",
        "stage_params": {
            "prose": {"slot": OFFICIAL_FLASH}, "enrich": {"slot": OFFICIAL_FLASH},
            "trim": {"slot": OFFICIAL_FLASH}, "deslop": {"slot": OFFICIAL_FLASH},
            "core_setting": {"slot": OFFICIAL_FLASH}, "volume_outline": {"slot": OFFICIAL_FLASH},
            "worldbook": {"slot": OFFICIAL_FLASH}, "outline": {"slot": OFFICIAL_FLASH},
        },
    },
    "budget_run": {
        "label": "全快档挂机（全 Flash + 创作相位关思考）",
        "slots": {"writing": OFFICIAL_FLASH, "helper": OFFICIAL_FLASH, "review": OFFICIAL_FLASH},
        "desc": "三槽全 Flash；正文/核心设定/全书大纲/世界书关思考（追踪/摘要/去味等机械相位内置表本就关）——批量挂机最省最快。",
        "stage_params": {
            "prose": {"thinking": "disabled"}, "core_setting": {"thinking": "disabled"},
            "volume_outline": {"thinking": "disabled"}, "worldbook": {"thinking": "disabled"},
        },
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
    """槽位层策略卡（设置页既有「一键切换三槽」节）。

    阶段级卡（quality_mix/budget_run，带 stage_params）不在此列——它们需要
    项目题材预设落阶段档，由 ModelPolicyController.strategyOptions 单独出口；
    混进三槽列表会出现「点了没全生效」的半套语义。
    """
    return [{"id": pid, "label": spec["label"]}
            for pid, spec in PRESETS.items() if not spec.get("stage_params")]


def strategy_card_options() -> list:
    """阶段级策略卡视图（bridge.ModelPolicyController 消费）"""
    return [{"id": pid, "label": spec.get("label", pid), "desc": spec.get("desc", "")}
            for pid, spec in PRESETS.items() if spec.get("stage_params")]
