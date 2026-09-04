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

# 出厂预设只预置「提供方」：名称、provider、base_url（v0.18.2 起）。
# 不预置模型——模型名是各家变最快的参数，预置进去的症状是过期即误导；建议候选在
# 表单选服务商时给下拉（providers.py 的 models），「拉取」到的实时列表优先。
# id 保持稳定（槽位绑定与参数升级都按 id 认），尽管个别 id 里带着旧模型名的影子。
DEFAULT_CONNECTIONS = [
    {"id": "ds-v4-pro", "name": "DeepSeek 官方", "provider": "deepseek",
     "base_url": "https://api.deepseek.com", "api_key": "", "model": "",
     "temperature": 0.7, "max_tokens": 32768, "timeout": 300},
    {"id": "bl-qwen-max", "name": "阿里云百炼", "provider": "bailian",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "zp-glm-5", "name": "智谱 BigModel", "provider": "zhipu",
     "base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "kimi-k3", "name": "Kimi（Moonshot）", "provider": "kimi",
     "base_url": "https://api.moonshot.cn/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 32768, "timeout": 300},
    {"id": "ark-doubao", "name": "火山引擎方舟", "provider": "ark",
     "base_url": "https://ark.cn-beijing.volces.com/api/v3", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "hy-turbos", "name": "腾讯混元", "provider": "hunyuan",
     "base_url": "https://api.hunyuan.cloud.tencent.com/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "mm-m3", "name": "MiniMax", "provider": "minimax",
     "base_url": "https://api.minimaxi.com/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "sf-dsv4-pro", "name": "硅基流动", "provider": "siliconflow",
     "base_url": "https://api.siliconflow.cn/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 32768, "timeout": 300},
    {"id": "or-claude", "name": "OpenRouter（聚合）", "provider": "openrouter",
     "base_url": "https://openrouter.ai/api/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "gm-25-pro", "name": "Google Gemini", "provider": "gemini",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "xai-grok", "name": "xAI Grok", "provider": "xai",
     "base_url": "https://api.x.ai/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 16384, "timeout": 300},
    {"id": "groq-oss", "name": "Groq", "provider": "groq",
     "base_url": "https://api.groq.com/openai/v1", "api_key": "",
     "model": "", "temperature": 0.7, "max_tokens": 8192, "timeout": 300},
]

DEFAULT_CONFIG = {
    "connections": DEFAULT_CONNECTIONS,
    # 三槽出厂都指向 DeepSeek 官方那条：内置提示词按 V4 系调校。但预设不再带模型——
    # 新用户要先把这行的 Key 填上、模型选好（表单有候选下拉，或「拉取」实时列表），
    # 全流程才跑得通；想压成本自己再加轻量模型或改指向（连接列表可以复制行）。
    "slots": {SLOT_WRITING: "ds-v4-pro", SLOT_HELPER: "ds-v4-pro", SLOT_REVIEW: "ds-v4-pro"},
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
                # v0.18 起默认开：不自动查，「有新版时出现图标、点一下就能更新」这条链就名不副实。
                # 边界写清楚——只下载一份 1KB 的公开版本清单，不上传任何东西，且在更新面板可关。
                # 多条通道全挂时也只是等满 25s 的后台线程，不碰界面。
                "auto_check": True,
                "auto_check_chosen": False,     # 用户在界面上显式表过态；迁移逻辑只认这个标记
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
    """内置预设的参数升级：max_tokens 随版本调大

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


# 退役的出厂预设行：留着就是设置里一排误导人的卡（v0.18.1 下架的两家 provider 已从
# PROVIDERS 移除；v0.18.2 把 12 家预设改成只预置提供方，带模型名的旧行整批退役）。
# 身份字段必须与当年出厂那行逐字相等才认——比对逻辑见 _retire_builtin_connections。
RETIRED_BUILTINS = {
    # ---- v0.18.1 下架：provider 已不在 PROVIDERS 里 ----
    "ds-v4-flash": {"name": "DeepSeek V4 Flash", "provider": "deepseek",
                    "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
    "ocgo-flash": {"name": "OpenCode Go · V4 Flash", "provider": "opencodego",
                   "base_url": "https://opencode.ai/zen/go/v1", "model": "deepseek-v4-flash"},
}
# ---- v0.18.2 退役：同一 id 换成不带模型的出厂行（v0.18.1 的 12 家原样记录）----
RETIRED_BUILTINS.update({
    "ds-v4-pro": {"name": "DeepSeek V4 Pro", "provider": "deepseek",
                  "base_url": "https://api.deepseek.com", "model": "deepseek-v4-pro"},
    "bl-qwen-max": {"name": "阿里云百炼 · Qwen3.8 Max", "provider": "bailian",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "qwen3.8-max"},
    "zp-glm-5": {"name": "智谱 · GLM-5", "provider": "zhipu",
                 "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-5"},
    "kimi-k3": {"name": "Kimi · K3", "provider": "kimi",
                "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k3"},
    "ark-doubao": {"name": "火山方舟 · Doubao Seed 2.1 Pro", "provider": "ark",
                   "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                   "model": "doubao-seed-2-1-pro-260628"},
    "hy-turbos": {"name": "腾讯混元 · Turbos", "provider": "hunyuan",
                  "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
                  "model": "hunyuan-turbos-latest"},
    "mm-m3": {"name": "MiniMax · M3", "provider": "minimax",
              "base_url": "https://api.minimaxi.com/v1", "model": "MiniMax-M3"},
    "sf-dsv4-pro": {"name": "硅基流动 · DeepSeek V4 Pro", "provider": "siliconflow",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "model": "deepseek-ai/DeepSeek-V4-Pro"},
    "or-claude": {"name": "OpenRouter · Claude Sonnet 4.5", "provider": "openrouter",
                  "base_url": "https://openrouter.ai/api/v1",
                  "model": "anthropic/claude-sonnet-4.5"},
    "gm-25-pro": {"name": "Google Gemini 2.5 Pro", "provider": "gemini",
                  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                  "model": "gemini-2.5-pro"},
    "xai-grok": {"name": "xAI · Grok", "provider": "xai",
                 "base_url": "https://api.x.ai/v1", "model": "grok-4.6"},
    "groq-oss": {"name": "Groq · GPT-OSS 20B", "provider": "groq",
                 "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-20b"},
})
# load_config 几乎每个界面动作都会被调一次，凭据管理器读一次不算便宜：
# 记住哪些退役行确实带着 Key，本进程内不再重读（只读缓存，不缓存「没有」以外的结论）。
_RETIRED_WITH_KEY = set()


def _retire_builtin_connections(cfg: dict) -> dict:
    """删掉**从没被改过、也没在用、也没存过 Key** 的退役预设行

    三个条件缺一就不删，因为每一种都对应一次真实的用户劳动：
      · 改过身份字段（换过模型名/地址/名字）→ 那已经是他的连接了，不是我们的预设；
      · 有槽位指着它 → 删了等于悄悄换掉「用哪个模型写我的书」；
      · 凭据管理器里有它的 Key → 连接删了 Key 就成了孤儿，比留一张卡更糟。
    max_tokens/temperature/timeout 不参与比对：上面那条升级会正当地把 8192 抬到出厂值。

    **这里绝不写也绝不删凭据**：本函数每次 load_config 都会跑，探针与单测也在跑它，
    只读凭据存储才安全。要搬 Key 得由用户在界面上动手（或删除逻辑自己负责收尾）。
    """
    conns = cfg.get("connections")
    if not isinstance(conns, list):
        return cfg
    used = set((cfg.get("slots") or {}).values())
    kept, dropped = [], []
    for c in conns:
        spec = RETIRED_BUILTINS.get(c.get("id")) if isinstance(c, dict) else None
        if not spec or c.get("id") in used:
            kept.append(c)
            continue
        if any(str(c.get(k) or "") != v for k, v in spec.items()):
            kept.append(c)          # 被改过：这不是我们发出去的那一行预设了
            continue
        if c["id"] in _RETIRED_WITH_KEY or secrets.get_secret(c["id"]):
            _RETIRED_WITH_KEY.add(c["id"])
            kept.append(c)      # 存过 Key：宁可留一张卡，也不留一个没人认领的孤儿凭据
            continue
        dropped.append(c["id"])
    if dropped:
        cfg["connections"] = kept
        logging.getLogger("qianbi.config").info("已移除退役的出厂预设连接：%s", ", ".join(dropped))
    return cfg


def _migrate_updates(cfg: dict) -> dict:
    """v0.15 死键清理 + v0.18 默认翻转

    `check_on_start` 在 v0.15 从没被任何调用点读到（自动检查根本没接线），那份 True
    不是用户的选择，搬到新键上等于升级后偷偷开机联网——直接丢弃。

    翻转默认值有个真问题：首次运行时应用会把整份 DEFAULT 落盘，于是老用户磁盘上的
    `auto_check: false` 分不清是「他关掉的」还是「抄来的出厂默认」。只有界面上真的
    拨过开关才会写 `auto_check_chosen`，所以拿它当唯一凭据：没表过态的按新默认走，
    不做静默改写。UI 那条「已为你默认开启」的告知也读这个标记，用户一旦亲自拨过
    开关就自然消失，不需要再多存一个「提示已过」的键。
    """
    u = cfg.get("updates")
    if not isinstance(u, dict):
        return cfg
    u.pop("check_on_start", None)
    if not u.get("auto_check_chosen") and u.get("auto_check") is False:
        u["auto_check"] = True
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
        _migrate_builtin_connections(merged)
        _retire_builtin_connections(merged)
        _migrate_updates(merged)
        # 补全新内置连接模板（v0.18.1 起十余家预设；退役腾出的 id 在这里补上新的出厂行，
        # 所以 ids 必须在退役之后才算——提前算会把换血后的 id 当成已存在）
        ids = {c["id"] for c in merged["connections"]}
        for c in DEFAULT_CONNECTIONS:
            if c["id"] not in ids:
                merged["connections"].append(json.loads(json.dumps(c)))
        # 槽位指向失效连接的修复：放在连接集合定形之后，别把槽位指到刚被退役的行上
        ids = {c["id"] for c in merged["connections"]}
        for slot in SLOT_ORDER:
            if merged["slots"].get(slot) not in ids:
                merged["slots"][slot] = merged["connections"][0]["id"]
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
