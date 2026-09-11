# -*- coding: utf-8 -*-
"""演示伪流式回放引擎（0.20.0 演示引导）

把真实测试产物按时间线回放，驱动与真实流水线**完全相同**的 bridge 渲染路径：
_on_stream_stage / _on_stream_chunk / _on_step / _on_log / _console_log /
_on_chapter_done。不 import 任何 LLM 模块——结构上保证演示发不出真实请求。

时间线 = [(delay_ms, callable), ...]，单 QTimer 顺序推进；stop() 随时可掐。
"""
import os

from PySide6.QtCore import QObject, QTimer


class DemoReplayer(QObject):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self._timeline = []
        self._idx = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt_CoarseTimer())
        self._timer.timeout.connect(self._tick)
        self._on_done = None
        self._running = False

    # ---- 生命周期 ----

    def play(self, timeline: list, on_done=None):
        """timeline: [(delay_ms, callable), ...]——delay 为该操作前的等待"""
        self.stop()
        self._timeline = timeline
        self._idx = 0
        self._on_done = on_done
        self._running = True
        self._timer.start(10)

    def stop(self):
        self._timer.stop()
        self._running = False
        self._timeline = []
        self._idx = 0

    @property
    def running(self) -> bool:
        return self._running

    def _tick(self):
        if not self._running:
            return
        if self._idx >= len(self._timeline):
            self._timer.stop()
            self._running = False
            cb, self._on_done = self._on_done, None
            if cb:
                cb()
            return
        delay, fn = self._timeline[self._idx]
        self._idx += 1
        if delay > 0:
            self._timer.stop()
            self._timer.start(delay)
        try:
            fn()
        except Exception:  # noqa: BLE001  # 演示回放的单点失败绝不炸主进程
            self.stop()
            cb, self._on_done = self._on_done, None
            if cb:
                cb()

    # ---- 时间线构件（bridge 直通真实渲染路径）----

    def op_log(self, msg: str, level: str = "info"):
        return (0, lambda m=msg, lv=level: self.bridge._on_log(lv, m))

    def op_console(self, msg: str, kind: str = "agent"):
        return (0, lambda m=msg, k=kind: self.bridge._console_log(k, m))

    def op_call(self, fn):
        return (0, fn)

    def op_wait(self, ms: int):
        return (ms, lambda: None)

    def op_stage(self, label: str):
        """编辑器流式阶段切换（清空流式区、打阶段标签）"""
        return (0, lambda l=label: self.bridge._on_stream_stage(l))

    def op_step(self, step_key: str, num: int = 1):
        return (0, lambda k=step_key, n=num: self.bridge._on_step(n, k))

    def op_stream(self, text: str, chars: int, ms: int):
        """把 text 拆成 chunks 依次喂进流式区"""
        ops = []
        for i in range(0, len(text), chars):
            piece = text[i:i + chars]
            ops.append((ms, lambda p=piece: self.bridge._on_stream_chunk(p)))
        return ops

    def op_stream_reasoning(self, text: str):
        return (0, lambda t=text: self.bridge._on_stream_reasoning(t))


def Qt_CoarseTimer():
    from PySide6.QtCore import Qt
    return Qt.TimerType.CoarseTimer


def book_rel(pack_base: str, rel: str) -> str:
    return os.path.join(pack_base, "book", rel)
