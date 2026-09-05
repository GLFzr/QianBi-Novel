# -*- coding: utf-8 -*-
"""遥测与公测数据包（opt-in，默认关）

- 仅两类事件：应用启动/章节完成计数 + 崩溃摘要（均经 secrets.redact_text 脱敏）
- 落点 ~/.qianbi_novel/telemetry/pending.jsonl；不上传，用户可一键导出公测数据包
- 公测版（v0.18.4 起）：导出内容含缓存命中率/成本流水/章节完成统计，
  **不含任何书稿内容、API Key、提示词正文**——导出前先看导出说明
- 用户可在「关于」对话框一键开关（config.telemetry.enabled）
"""
import datetime
import json
import logging
import os

from . import secrets

logger = logging.getLogger("qianbi.telemetry")

DIR = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "telemetry")
FILE = os.path.join(DIR, "pending.jsonl")
MAX_LINES = 2000


def enabled(cfg: dict) -> bool:
    return bool((cfg.get("telemetry") or {}).get("enabled", False))


def set_enabled(cfg: dict, on: bool) -> dict:
    cfg.setdefault("telemetry", {})["enabled"] = bool(on)
    return cfg


def record(cfg: dict, event: str, **props):
    """记录一条事件（未启用时零开销直接返回）"""
    if not enabled(cfg):
        return
    try:
        os.makedirs(DIR, exist_ok=True)
        entry = {"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "event": event,
                 "version": props.pop("version", "")}
        entry.update({k: secrets.redact_text(str(v))[:300] for k, v in props.items()})
        # 简单容量上限：超限截断旧事件
        if os.path.exists(FILE):
            with open(FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) >= MAX_LINES:
                lines = lines[-MAX_LINES // 2:]
                with open(FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines)
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.debug("遥测落点失败（忽略）: %s", e)


def export_beta_pack(cfg: dict) -> str:
    """导出公测数据包（jsonl 合集 → 单文件）：公测版提交流程的唯一通道。

    内容 = 三类**元数据**：
      ① usage.jsonl（token 用量/缓存命中/相位/耗时/模型——成本与命中率分析的原料）
      ② telemetry/pending.jsonl（启动/章节完成/崩溃事件）
      ③ 追踪层质量摘要（各项目设定清算的 violations 计数与 beat_check，不含正文）
    明确不含：书稿正文、提示词正文、API Key（dehydrate 后的指纹也不含）、连接配置。
    返回导出文件路径；异常抛给调用方提示。
    """
    import glob
    base = os.path.expanduser("~")
    pack = {"kind": "qianbi-beta-pack", "version": 1, "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "usage": [], "events": [], "quality": []}
    u = os.path.join(base, ".qianbi_novel", "usage", "usage.jsonl")
    if os.path.exists(u):
        with open(u, encoding="utf-8") as f:
            pack["usage"] = [json.loads(x) for x in f if x.strip()]
    if os.path.exists(FILE):
        with open(FILE, encoding="utf-8") as f:
            pack["events"] = [json.loads(x) for x in f if x.strip()]
    # 质量摘要：只取计数与缺失拍，不取 quote 原句（防书稿内容泄漏）
    for qf in sorted(glob.glob(os.path.join(base, "Documents", "千笔一文", "**", "追踪", "设定清算_*.json"), recursive=True))             + sorted(glob.glob(os.path.join(base, ".qianbi_novel", "**", "追踪", "设定清算_*.json"), recursive=True)):
        try:
            with open(qf, encoding="utf-8") as f:
                d = json.load(f)
            pack["quality"].append({"file": os.path.basename(qf),
                                    "violations": len(d.get("violations") or []),
                                    "hard": sum(1 for v in d.get("violations") or [] if v.get("severity") == "硬伤"),
                                    "adoptions": len(d.get("adoptions") or []),
                                    "beat_check": d.get("beat_check") or {},
                                    "failed": d.get("failed", False)})
        except Exception:  # noqa: BLE001
            continue
    out_dir = DIR
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "beta_pack_%s.json" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False)
    return out
