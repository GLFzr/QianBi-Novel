# -*- coding: utf-8 -*-
"""单实例锁：QLocalServer/QLocalSocket（跨平台 Qt 方案）

- 二次启动：connect 到既有实例的本地套接字 → 发送 "raise" → 退出
- 首个实例：listen，收到 "raise" 时回调 on_raise（把主窗口提到前台）
- 防多开写坏 config.json / pipeline_state.json（真机双实例写花配置事故）
"""
import logging

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger("qianbi.singleinstance")

LOCK_NAME = "QianBiNovel.lock"


class SingleInstance(QObject):
    def __init__(self, on_raise=None, parent=None):
        super().__init__(parent)
        self._on_raise = on_raise
        self._server = None
        self.already_running = False

    def acquire(self) -> bool:
        """尝试成为唯一实例。返回 False 表示已有实例在跑（本进程应退出）"""
        sock = QLocalSocket(self)
        sock.connectToServer(LOCK_NAME)
        if sock.waitForConnected(500):
            sock.write(b"raise\n")
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
            self.already_running = True
            return False
        # 残留锁清理（崩溃后 QLocalServer 名称可能残留）
        QLocalServer.removeServer(LOCK_NAME)
        self._server = QLocalServer(self)
        if not self._server.listen(LOCK_NAME):
            logger.warning("单实例锁 listen 失败（%s），降级允许多开", self._server.errorString())
        self._server.newConnection.connect(self._on_new_connection)
        return True

    def _on_new_connection(self):
        sock = self._server.nextPendingConnection()
        if sock:
            sock.readyRead.connect(lambda: self._read(sock))

    def _read(self, sock):
        data = bytes(sock.readAll()).decode("utf-8", "ignore")
        if "raise" in data and self._on_raise:
            try:
                self._on_raise()
            except Exception as e:  # noqa: BLE001
                logger.warning("唤起主窗口失败: %s", e)
        sock.disconnectFromServer()
