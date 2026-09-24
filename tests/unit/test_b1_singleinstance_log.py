# -*- coding: utf-8 -*-
"""B-1：单实例锁降级的可见性护栏。

listen 失败时行为保持降级多开（可用性优先，不变），但必须留一行含
「可能有另一实例在跑」的 warning——真机双实例写花 config.json / pipeline_state.json
的事故需要日志可循，静默降级 = 事故后无迹可查。
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import singleinstance  # noqa: E402


def test_listen_failure_degrades_with_warning(monkeypatch, caplog):
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    # 打桩网络面：既有实例连不上、listen 失败——只验证降级放行 + 日志留痕
    monkeypatch.setattr(QLocalSocket, "connectToServer", lambda self, name: None)
    monkeypatch.setattr(QLocalSocket, "waitForConnected", lambda self, ms: False)
    monkeypatch.setattr(QLocalServer, "listen", lambda self, name: False)
    monkeypatch.setattr(QLocalServer, "errorString", lambda self: "权限不足")
    with caplog.at_level(logging.WARNING, logger="qianbi.singleinstance"):
        si = singleinstance.SingleInstance()
        assert si.acquire() is True, "listen 失败应降级放行（返回 True），不得误判已有实例"
        assert not si.already_running
    hits = [r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING and "可能有另一实例在跑" in r.getMessage()]
    assert hits, "listen 失败未留下含「可能有另一实例在跑」的 warning（静默降级回归）"
    assert any("权限不足" in h for h in hits), "warning 未带 errorString 现场，无从排查"
