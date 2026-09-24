# -*- coding: utf-8 -*-
"""WP-27：Agent/用户对话全量落盘（本地 JSONL，不上网，默认开）。

R14 五条的对位：
- ①脱敏：prompt/reply/error 落盘前一律过 secrets.redact_text；API Key 不入档
  （client 层只把「连接标签」给本模块，不给 Key）
- ②位置在界面可发现：设置面板「对话记录」开关 + 「打开对话记录目录」按钮；
  目录为书内 `.dialogue/`，与 `.annotations` 同族，随项目备份 zip 走
- ③可关闭：config `dialogue_log.enabled`（默认 True——用户指派默认开）
- ④PRIVACY.md 与设置面板同步说明（存在/在哪/装什么/不上网/如何关）
- ⑤滚动上限：单分片 >max_bytes 开新分片；目录内最多 keep_files 个分片，超限
  删最旧——总量硬上界 = max_bytes × keep_files

写入语义：每次 HTTP 请求一条 JSONL（重试/降级/abort 各算一条）——「记录条数 ==
实际发出请求数」由测试钉死（R13 数量一致性）。记录器自身故障绝不打断流水线：
只 log warning 并丢弃该条。
"""
import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

logger = logging.getLogger("qianbi.dialogue_log")

_LOCK = threading.Lock()
_STATE = {
    "proj": "",          # 当前书（.dialogue/ 挂在书内；空=不记录）
    "enabled": True,     # R14③：可关闭（默认开=用户指派）
    "max_bytes": 5 * 1024 * 1024,
    "keep_files": 40,
}
_LOCAL = threading.local()   # 章号上下文（orchestrator/共写 worker 设置）


def configure(proj: str, enabled: bool = True, keep_files: int = 40) -> None:
    """bridge.openProject / 设置变更时调用：绑定当前书与开关"""
    _STATE["proj"] = proj or ""
    _STATE["enabled"] = bool(enabled)
    _STATE["keep_files"] = max(1, int(keep_files or 40))


def set_enabled(enabled: bool) -> None:
    _STATE["enabled"] = bool(enabled)


def enabled() -> bool:
    return bool(_STATE["enabled"] and _STATE["proj"])


def set_chapter(num: int) -> None:
    """章号上下文：orchestrator 章循环 / 共写 worker.run 里设置"""
    _LOCAL.chapter = int(num or 0)


def dialogue_dir(proj: str = "") -> str:
    return os.path.join(proj or _STATE["proj"], ".dialogue")


def stats() -> dict:
    """界面可发现性：目录、分片数、总字节（设置面板展示用）"""
    d = dialogue_dir()
    files, total = [], 0
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".jsonl"):
                p = os.path.join(d, fn)
                files.append(fn)
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
    return {"dir": d, "files": len(files), "bytes": total,
            "enabled": _STATE["enabled"], "proj": _STATE["proj"]}


def _redact(text: str) -> str:
    from . import secrets
    try:
        return secrets.redact_text(text or "")
    except Exception:  # noqa: BLE001
        return "<redact-failed>"


def _system_ref(system: str) -> dict:
    """R14/体积权衡：system 前缀（章会话下数 KB 且逐调用重复）只存
    头部 4000 字 + sha256，完整原文可从卷会话/快照复原"""
    if not system:
        return {"system_head": "", "system_sha256": ""}
    return {"system_head": _redact(system[:4000]),
            "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest()}


def record_chat(client=None, phase: str = "", outcome: str = "",
                prompt: str = "", system: str = "", reply: str = "",
                usage: dict = None, latency: float = 0.0, error: str = "",
                attempt: int = 1, degraded: bool = False,
                stream: bool = False, note: str = "") -> None:
    """client 层每次 HTTP 请求结束调用一条。任何异常都不外抛。"""
    if not enabled():
        return
    try:
        entry = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "chapter": getattr(_LOCAL, "chapter", 0) or 0,
            "phase": phase or "",
            "slot": getattr(client, "slot", "") or "",
            "model": getattr(client, "model", "") or "",
            "outcome": outcome,          # ok / ok_empty / http_<code> / timeout / network / stream_error / error
            "attempt": int(attempt),
            "degraded": bool(degraded),  # 思考/参数降级是否发生
            "stream": bool(stream),
            "latency_s": round(float(latency or 0.0), 2),
            "usage": dict(usage or {}),
            "prompt": _redact(prompt or ""),
            **_system_ref(system),
            "reply": _redact(reply or ""),
            "error": _redact(error or ""),
            "note": note or "",
        }
        _append(entry)
    except Exception as e:  # noqa: BLE001
        logger.warning("对话记录写入失败（不影响生成）：%s", e)


def _append(entry: dict) -> None:
    d = dialogue_dir()
    os.makedirs(d, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    with _LOCK:
        path, seq = os.path.join(d, f"对话_{day}.jsonl"), 1
        while os.path.exists(path) and os.path.getsize(path) >= _STATE["max_bytes"]:
            seq += 1
            path = os.path.join(d, f"对话_{day}_{seq}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _prune(d)


def _prune(d: str) -> None:
    """R14⑤：分片数超上限删最旧（总量硬上界 = max_bytes × keep_files）。
    最旧 = 分片序号最小：对话_YYYYMMDD.jsonl 是当天第 1 片，_N 后缀是第 N 片——
    不按字节大小挑：小分片往往是刚开的新片，按大小删会把最新的先删掉。"""
    def _seq(fn: str) -> tuple:
        m = re.fullmatch(r"对话_(\d{8})(?:_(\d+))?\.jsonl", fn)
        # 认不出的命名排最后（不碰来路不明的文件），本模块分片都走上面分支
        return (m.group(1), int(m.group(2) or 1)) if m else ("99991231", 0)

    files = sorted((fn for fn in os.listdir(d) if fn.endswith(".jsonl")), key=_seq)
    while len(files) > _STATE["keep_files"]:
        oldest = files.pop(0)
        try:
            os.remove(os.path.join(d, oldest))
        except OSError:
            pass
