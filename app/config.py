# -*- coding: utf-8 -*-
"""千笔一文 Novel 应用配置：连接档案（酒馆式）+ 任务槽位路由 + 质量闸门策略

存于用户目录 ~/.qianbi_novel/config.json；自动迁移旧版（.oh_story_desktop）配置。
"""
import json
import logging

from . import secrets
import os
import shutil
import uuid

CONFIG_DIR = os.environ.get("QIANBI_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".qianbi_novel")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
_LEGACY_DIR = os.path.join(os.path.expanduser("~"), ".oh_story_desktop")

# ---- 任务槽位 ----
SLOT_WRITING = "writing"   # 核心设定/大纲/草稿/去味改写/扩写
SLOT_HELPER = "helper"     # 细纲/章节摘要/全局摘要/追踪更新/检索关键词
SLOT_REVIEW = "review"     # 一致性审校
SLOT_ORDER = [SLOT_WRITING, SLOT_HELPER, SLOT_REVIEW]
SLOT_LABELS = {SLOT_WRITING: "写作槽", SLOT_HELPER: "辅助槽", SLOT_REVIEW: "审校槽"}

# ---- 质量闸门策略 ----
GATE_STRICT = "strict"              # 自动修复 1 次仍失败 → 暂停等人
GATE_MARK_CONTINUE = "mark_continue"  # 修复失败 → 标待修继续写（默认）

DEFAULT_CONNECTIONS = [
    {"id": "ds-v4-pro", "name": "DeepSeek V4 Pro", "provider": "deepseek",
     "base_url": "https://api.deepseek.com", "api_key": "", "model": "deepseek-v4-pro",
     "temperature": 0.7, "max_tokens": 32768, "timeout": 300},
    {"id": "ds-v4-flash", "name": "DeepSeek V4 Flash", "provider": "deepseek",
     "base_url": "https://api.deepseek.com", "api_key": "", "model": "deepseek-v4-flash",
     "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "ocgo-flash", "name": "OpenCode Go · V4 Flash", "provider": "opencodego",
     "base_url": "https://opencode.ai/zen/go/v1", "api_key": "", "model": "deepseek-v4-flash",
     "temperature": 0.7, "max_tokens": 65536, "timeout": 600,
     "thinking": "enabled", "reasoning_effort": "max"},
]

DEFAULT_CONFIG = {
    "connections": DEFAULT_CONNECTIONS,
    "slots": {SLOT_WRITING: "ds-v4-pro", SLOT_HELPER: "ds-v4-flash", SLOT_REVIEW: "ds-v4-flash"},
    "gates": {"strategy": GATE_MARK_CONTINUE, "deslop_max_rounds": 2, "word_tolerance": 0.1,
              "word_enrich_rounds": 2,   # 字数不足的自动扩写轮数（真机缺陷④：原单轮偏宽松）
              "review_enabled": True, "review_max_rounds": 1,
              "review_temperature": 0.2,   # 审校判定低温（单次覆盖，不改连接档案）
              "review_votes": 3,           # 首扫多轮投票数（平票从严，阻塞需 ≥2 票）
              "review_votes_recheck": 1},  # 修复环复扫投票数（控成本）
    "llm": {"max_retries": 2, "backoff_base": 2.0},
    "writing": {"chapter_word_target": 3000, "default_genre": "", "default_platform": "番茄",
                "run_mode": "auto",             # auto=全自动 / step=逐步确认 / border=边界确认 / cw=共写
                "step_confirm": False,          # 兼容旧开关（逐步确认=step 模式启用且全硬停）
                "regex_semantics": "logic",     # 正则语义：logic=逻辑约束规则集（默认）/ regex=字面正则样本
                "readback_on_save": True,       # 读改揣摩：保存有变时触发 1 次（复用 review 槽）
                "readback_min_diff": 200,       # 最小改动量阈值（低于不触发；0=每次都触发）
                "gate_hard": ["G2", "G5L", "G8", "G9"],   # G8 审校门入硬停（plan_step_gates_v1 §2 默认）
                "gate_soft": ["G1", "G3", "G4", "G6", "G7"]},
    "last_project": "",
    "recent_projects": [],
    "general": {"onboarded": False},          # 首启向导（T3.5）
    "telemetry": {"enabled": False},           # 遥测 opt-in（D6：默认关，本地落点）
    "updates": {"manifest_url": "https://raw.githubusercontent.com/GLFzr/QianBi-Novel/main/latest.json",
                # 开机自连 GitHub 属于对外请求，与「数据不出本机」的默认承诺冲突，
                # 所以默认只做手动检查；要开机自动查在「关于」里显式打开。
                "auto_check": False,
                # 自己的镜像/CDN 上那份清单（GitHub 连不上时的第二条路），填了排最前
                "custom_url": "",
                "interval_hours": 24.0,           # 自动检查限流：一天最多问一次
                "proxy_mode": "system",           # system 读注册表 | env 环境变量 | none 直连 | custom
                "proxy_url": "",
                # last_* 是运行时状态（不是用户设置）；清单正文另存 updates/manifest.json，
                # 因为那是可重验的原始载荷，塞进 config 会被当成配置来回改写。
                "last_channel": "",
                "last_check_ts": 0.0},
}


def _migrate_legacy_dir():
    """旧版应用配置目录迁移（.oh_story_desktop → .qianbi_novel）"""
    legacy_file = os.path.join(_LEGACY_DIR, "config.json")
    if os.path.exists(legacy_file) and not os.path.exists(CONFIG_FILE):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            shutil.copy2(legacy_file, CONFIG_FILE)
        except OSError:
            pass


def _migrate_legacy_format(cfg: dict) -> dict:
    """旧格式（单个 llm 配置）→ 连接档案 + 槽位"""
    if "connections" in cfg:
        return cfg
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k in ("writing", "last_project", "recent_projects"):
        if k in cfg:
            merged[k] = cfg[k]
    legacy = cfg.get("llm", {})
    if legacy.get("base_url") or legacy.get("api_key"):
        conn = {
            "id": "legacy",
            "name": legacy.get("model", "旧配置"),
            "provider": "custom",
            "base_url": legacy.get("base_url", ""),
            "api_key": legacy.get("api_key", ""),
            "model": legacy.get("model", ""),
            "temperature": legacy.get("temperature", 0.7),
            "max_tokens": legacy.get("max_tokens", 8192),
            "timeout": legacy.get("timeout", 300),
        }
        merged["connections"] = [conn] + [c for c in DEFAULT_CONNECTIONS]
        merged["slots"] = {SLOT_WRITING: "legacy", SLOT_HELPER: "legacy", SLOT_REVIEW: "legacy"}
    return merged


def _migrate_builtin_connections(cfg: dict) -> dict:
    """内置连接（ds-v4-pro/ds-v4-flash）参数升级：max_tokens 随版本调大

    只升级仍持有旧默认值(8192)的内置连接，不覆盖用户自定义的修改。
    """
    by_id = {c["id"]: c for c in DEFAULT_CONNECTIONS}
    for conn in cfg.get("connections", []):
        builtin = by_id.get(conn.get("id"))
        if not builtin:
            continue
        if conn.get("max_tokens") == 8192 and builtin["max_tokens"] > 8192:
            conn["max_tokens"] = builtin["max_tokens"]
    return cfg


def _migrate_updates(cfg: dict) -> dict:
    """旧键 updates.check_on_start → auto_check

    旧键在 v0.15 里从没被任何调用点读到（自动检查根本没接线），磁盘上那个 True
    是出厂默认而不是用户选择，原样搬到新键上等于升级后偷偷开机联网。
    """
    u = cfg.get("updates")
    if isinstance(u, dict) and "check_on_start" in u:
        u.pop("check_on_start")
        u.setdefault("auto_check", False)
    return cfg


def load_config() -> dict:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    _migrate_legacy_dir()
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg = _migrate_legacy_format(cfg)
        # 补齐缺失键
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        for k, v in cfg.items():
            if isinstance(v, dict) and k in merged and isinstance(merged[k], dict) and k != "connections":
                merged[k].update(v)
            else:
                merged[k] = v
        if not merged.get("connections"):
            merged["connections"] = json.loads(json.dumps(DEFAULT_CONNECTIONS))
        # 槽位指向失效连接的修复
        ids = {c["id"] for c in merged["connections"]}
        for slot in SLOT_ORDER:
            if merged["slots"].get(slot) not in ids:
                merged["slots"][slot] = merged["connections"][0]["id"]
        _migrate_builtin_connections(merged)
        _migrate_updates(merged)
        # 补全新内置连接模板（如 ocgo-flash，无 key，用户在界面填写）
        for c in DEFAULT_CONNECTIONS:
            if c["id"] not in ids:
                merged["connections"].append(json.loads(json.dumps(c)))
        merged = secrets.hydrate(merged)
        return merged
    except Exception as e:  # noqa: BLE001
        # 读不懂/读不到 ≠ 没有配置：先把用户那份另存，再回落默认值。
        # 直接返回默认值会让下一次 save_config 覆盖掉连接档案与槽位绑定。
        _quarantine_config()
        logging.getLogger("qianbi.config").warning(
            "config.json 解析失败（%s），已另存为 config.json.broken-* 并使用默认配置", e)
        return json.loads(json.dumps(DEFAULT_CONFIG))


def _quarantine_config():
    """把无法解析的 config.json 另存一份，保住用户设置的可恢复性"""
    import time
    bak = "%s.broken-%s" % (CONFIG_FILE, time.strftime("%Y%m%d%H%M%S"))
    try:
        os.replace(CONFIG_FILE, bak)
        return bak
    except OSError:
        return ""   # 文件被占用等情况：不抛，交给调用方回落默认值


def save_config(cfg: dict):
    # T3.3 关键修复：在深拷贝上脱水——传入对象是 bridge 持有的运行时配置，
    # 原地清空会导致后续 LLM 调用拿到空 key（真机 401 事故根因）
    import copy
    disk = secrets.dehydrate(copy.deepcopy(cfg))
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(disk, f, ensure_ascii=False, indent=2)


def find_connection(cfg: dict, conn_id: str) -> dict:
    for c in cfg.get("connections", []):
        if c.get("id") == conn_id:
            return c
    return {}


def slot_connection(cfg: dict, slot: str) -> dict:
    """取某槽位当前绑定的连接；未绑定时回退写作槽，再回退第一条"""
    conn = find_connection(cfg, cfg.get("slots", {}).get(slot, ""))
    if not conn:
        conn = find_connection(cfg, cfg.get("slots", {}).get(SLOT_WRITING, ""))
    if not conn and cfg.get("connections"):
        conn = cfg["connections"][0]
    return conn


def new_connection_id() -> str:
    return uuid.uuid4().hex[:8]


def push_recent_project(cfg: dict, path: str):
    """规范化路径后写入最近项目（防混合斜杠/重复条目）"""
    norm = os.path.normpath(path or "")
    if not norm:
        return
    recent = [os.path.normpath(p) for p in cfg.get("recent_projects", []) if p]
    if norm in recent:
        recent.remove(norm)
    recent.insert(0, norm)
    cfg["recent_projects"] = recent[:10]
    cfg["last_project"] = norm
