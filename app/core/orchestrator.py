# -*- coding: utf-8 -*-
"""主写 AI 调度器：QThread 中运行总流水线，事件经 Qt 信号推到 UI

- 断点续跑：从 pipeline_state.json 与项目文件推断进度，缺什么补什么
- 暂停：当前 LLM 调用返回后停（checkpoint 语义）
- 停止：尽快在安全点退出
- 失败现场：异常时把最后 prompt / 日志尾部 dump 到项目 pipeline_debug/
"""
import logging
import os
import threading
import time

from PySide6.QtCore import QThread, Signal

from .. import project
from .. import diagnostics
from ..llm import ModelRouter
from . import stages, state as st
from .stages import StageError, PipelineStopped

logger = logging.getLogger("qianbi.core")

OUTLINE_BATCH = 2  # 细纲每批生成章数（max 思考下 5 章批会被推理吃光输出预算，2 章批实测稳定）

LOG_TAIL_MAX = 50  # 日志环形缓冲条数（失败 dump 用）


class Orchestrator(QThread):
    sig_log = Signal(str, str)          # level, msg
    sig_stage = Signal(str)             # 当前总阶段 key
    sig_chapter_started = Signal(int)
    sig_step = Signal(int, str)         # 章号, 微循环步骤 key
    sig_stream_chunk = Signal(str)      # LLM 流式输出增量（写作工作台实时显示）
    sig_chapter_done = Signal(dict)     # 章节记录
    sig_queue = Signal()                # 队列数据变化，通知 UI 刷新
    sig_finished = Signal(str)          # done / stopped
    sig_failed = Signal(str)
    sig_auto_paused = Signal(str)       # 闸门自动暂停（strict 策略），带原因

    def __init__(self, proj: str, cfg: dict, parent=None):
        super().__init__(parent)
        self.proj = proj
        self.cfg = cfg
        self.router = ModelRouter(cfg)
        self._pause = threading.Event()
        self._stop = False
        # 失败现场（stages 在每次 LLM 调用前写入）
        self.last_prompt = ""
        self._log_tail = []             # 最近日志（环形）
        self._cur_stage = ""
        self._cur_num = 0
        self._cur_step = ""

    # ---------- 外部控制 ----------

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    def stop(self):
        self._stop = True
        self._pause.clear()

    def auto_pause(self, reason: str):
        """质量闸门自动暂停（strict 策略）：置暂停位 + 通知 UI，等人处理后续跑"""
        self._pause.set()
        self.log("warn", f"闸门暂停：{reason}（处理后可点「继续」）")
        self.sig_auto_paused.emit(reason)

    # ---------- stage ctx 接口 ----------

    def log(self, level: str, msg: str):
        self.sig_log.emit(level, msg)
        self._log_tail.append(f"[{level}] {msg}")
        if len(self._log_tail) > LOG_TAIL_MAX:
            del self._log_tail[: len(self._log_tail) - LOG_TAIL_MAX]
        (logger.info if level == "ok" else
         logger.warning if level == "warn" else
         logger.error if level == "error" else logger.info)(msg)

    def step(self, num: int, step_key: str):
        self._cur_num = num
        self._cur_step = step_key
        self.sig_step.emit(num, step_key)

    def stream_chunk(self, text: str):
        """LLM 流式增量 → UI（写作工作台实时显示）"""
        self.sig_stream_chunk.emit(text)

    def checkpoint(self):
        if self._stop:
            raise PipelineStopped()
        while self._pause.is_set():
            if self._stop:
                raise PipelineStopped()
            time.sleep(0.15)

    # ---------- 主流程 ----------

    def run(self):
        try:
            project.ensure_tracking_files(self.proj)
            state = st.load_state(self.proj)

            # 阶段① 核心设定（缺失才生成）
            if not os.path.exists(os.path.join(self.proj, "设定", "题材定位.md")):
                state["stage"] = st.STAGE_SETTING
                st.save_state(self.proj, state)
                self._cur_stage = st.STAGE_SETTING
                self.sig_stage.emit(st.STAGE_SETTING)
                stages.stage_core_setting(self)
                self.sig_queue.emit()
                state["stage"] = st.STAGE_OUTLINE
                st.save_state(self.proj, state)

            # 阶段② 全书大纲（缺失才生成）
            if not os.path.exists(os.path.join(self.proj, "大纲", "大纲.md")):
                self._cur_stage = st.STAGE_OUTLINE
                self.sig_stage.emit(st.STAGE_OUTLINE)
                stages.stage_volume_outline(self)
                self.sig_queue.emit()

            # 计划总章数
            chapter_words = self.cfg.get("writing", {}).get("chapter_word_target", 3000)
            total = state.get("total_chapters", 0) or project.planned_chapters(self.proj, chapter_words)
            if total and state.get("total_chapters") != total:
                state["total_chapters"] = total
                st.save_state(self.proj, state)

            # 阶段③④ 正文循环（细纲按需自动补）
            num = project.next_chapter_num(self.proj)
            while total == 0 or num <= total:
                self.checkpoint()
                if not os.path.exists(project.get_outline_path(self.proj, num)):
                    self._cur_stage = st.STAGE_CH_OUTLINE
                    self.sig_stage.emit(st.STAGE_CH_OUTLINE)
                    stages.stage_chapter_outlines(self, num, num + OUTLINE_BATCH - 1)
                    self.sig_queue.emit()
                    if not os.path.exists(project.get_outline_path(self.proj, num)):
                        self.log("warn", f"第 {num} 章细纲仍缺失，流水线停在此处")
                        break

                self._cur_stage = st.STAGE_PROSE
                self.sig_stage.emit(st.STAGE_PROSE)
                self.sig_chapter_started.emit(num)
                # 取走用户为该章登记的重写指导（消费即删，写入正文 prompt）
                state = st.load_state(self.proj)
                guidance = st.take_guidance(state, num)
                if guidance:
                    st.save_state(self.proj, state)
                    self.log("info", f"第 {num} 章应用用户重写指导：{guidance[:80]}")
                record = stages.chapter_microcycle(self, num, guidance=guidance)
                self.sig_chapter_done.emit(record)

                state = st.load_state(self.proj)
                state["stage"] = st.STAGE_PROSE
                state["current_chapter"] = num
                st.append_history(self.proj, state, record)
                self.sig_queue.emit()
                num += 1
            else:
                pass

            if total and num > total:
                state = st.load_state(self.proj)
                state["stage"] = st.STAGE_DONE
                st.save_state(self.proj, state)
                self.sig_stage.emit(st.STAGE_DONE)
                self.log("ok", f"全书 {total} 章完本")
                self.sig_finished.emit("done")
            else:
                self.sig_finished.emit("stopped")
        except PipelineStopped:
            self.log("info", "流水线已停止，进度已保存，可随时续跑")
            self.sig_finished.emit("stopped")
        except StageError as e:
            self._dump_failure(e)
            self.sig_failed.emit(str(e))
        except Exception as e:
            self._dump_failure(e)
            self.sig_failed.emit(f"流水线异常: {e}")

    def _dump_failure(self, error: BaseException):
        """失败现场落盘：阶段/章号/最后 prompt/日志尾部"""
        path = diagnostics.dump_failure(
            self.proj, self._cur_stage, self._cur_num,
            self.last_prompt, error, list(self._log_tail), self._cur_step)
        self.log("error", f"失败现场已保存: {path}" if path else "失败现场写入失败")
