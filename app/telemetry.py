# -*- coding: utf-8 -*-
"""遥测（opt-in，默认关）：本地文件落点，不上传

- 仅两类事件：应用启动/章节完成计数 + 崩溃摘要（均经 secrets.redact_text 脱敏）
- 落点 ~/.qianbi_novel/telemetry/pending.jsonl；服务端上传为远期可选，当前纯本地
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
