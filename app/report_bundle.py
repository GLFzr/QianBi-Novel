# -*- coding: utf-8 -*-
"""WP-28：一键报障包（对话记录 + 程序日志 + 版本 + 脱敏配置摘要 → 单个 zip）。

价值定位：远端 0 open issue、无使用遥测——报障包是收到外人反馈的唯一通路。
R14 对位：①包内所有文本过 secrets.redact_text + 家目录路径替换 <HOME>，
api_key 字段整段剔除；⑤体积护栏：日志只取尾部 max_log_bytes、对话只取最近
keep_dialogue 个分片（100 章长书不会一键导出几百 MB）。
"""
import json
import logging
import os
import zipfile
from datetime import datetime, timezone

logger = logging.getLogger("qianbi.report_bundle")


def _redact(text: str) -> str:
    from . import secrets
    text = secrets.redact_text(text or "")
    home = os.path.expanduser("~")
    if home and home in text:
        text = text.replace(home, "<HOME>")
    return text


def _config_summary(cfg: dict) -> dict:
    """配置摘要：只留诊断所需非敏感字段；Key/URL 凭据字段整段剔除"""
    slots = (cfg or {}).get("slots", {})
    conns = [{"name": c.get("name", ""), "provider": c.get("provider", ""),
              "model": c.get("model", "")}
             for c in (cfg or {}).get("connections", [])]
    return {
        "app_version": _app_version(),
        "slots": dict(slots),
        "connections": conns,          # 无 base_url/api_key/user_id
        "dialogue_log": dict((cfg or {}).get("dialogue_log", {}) or {}),
        "gates": {k: v for k, v in (cfg or {}).get("gates", {}).items()
                  if isinstance(v, (bool, int, float, str))},
    }


def _app_version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"


def _tail_bytes(path: str, limit: int) -> bytes:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size <= limit:
            return f.read()
        f.seek(size - limit)
        data = f.read()
    return ("…[截断，只保留尾部]\n").encode("utf-8") + data


def collect_sources(proj: str, cfg: dict, logs_dir: str,
                    keep_dialogue: int = 20, max_log_bytes: int = 2 * 1024 * 1024) -> list:
    """收集 (zip 内路径, bytes) 列表。对话=最近 keep_dialogue 个分片；日志=尾部截断"""
    out = []
    out.append(("版本.txt", _app_version().encode("utf-8")))
    summary = json.dumps(_config_summary(cfg), ensure_ascii=False, indent=2)
    out.append(("配置摘要.json", _redact(summary).encode("utf-8")))

    # 对话记录（书内 .dialogue/，最新 N 个分片）
    d = os.path.join(proj or "", ".dialogue")
    if os.path.isdir(d):
        dlg = sorted((os.path.getmtime(os.path.join(d, fn)), fn)
                     for fn in os.listdir(d) if fn.endswith(".jsonl"))
        for _mt, fn in dlg[-keep_dialogue:]:
            raw = open(os.path.join(d, fn), "rb").read()
            out.append((f"对话记录/{fn}", _redact(raw.decode("utf-8", "replace")).encode("utf-8")))

    # 程序日志（滚动分片，取尾部）
    if os.path.isdir(logs_dir):
        for fn in sorted(os.listdir(logs_dir)):
            p = os.path.join(logs_dir, fn)
            if os.path.isfile(p):
                out.append((f"日志/{fn}", _redact(
                    _tail_bytes(p, max_log_bytes).decode("utf-8", "replace")).encode("utf-8")))
    return out


def create_bundle(proj: str, out_dir: str, cfg: dict, logs_dir: str,
                  keep_dialogue: int = 20, max_log_bytes: int = 2 * 1024 * 1024) -> str:
    """生成单个 zip，返回路径。真实产物（包内清单）见落地注记与探针。"""
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = os.path.join(out_dir, f"报障包_{stamp}.zip")
    items = collect_sources(proj, cfg, logs_dir,
                            keep_dialogue=keep_dialogue, max_log_bytes=max_log_bytes)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in items:
            z.writestr(name, data)
    logger.info("报障包已生成：%s（%d 个文件）", path, len(items))
    return path
