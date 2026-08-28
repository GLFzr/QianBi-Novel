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
    sig_stream_stage = Signal(str)      # 流式阶段切换（草稿/去味/审校…），UI 清空流式区并显示标签
    sig_stream_reasoning = Signal(str)  # 思维链增量（默认隐藏，用户主动查看）
    sig_chapter_done = Signal(dict)     # 章节记录
    sig_queue = Signal()                # 队列数据变化，通知 UI 刷新
    sig_finished = Signal(str)          # done / stopped
    sig_failed = Signal(str)
    sig_auto_paused = Signal(str)       # 闸门自动暂停（strict 策略），带原因
    sig_gate = Signal(str, int, str)    # 步骤决策门：gate_key, chapter, summary

    def __init__(self, proj: str, cfg: dict, parent=None):
        super().__init__(parent)
        self.proj = proj
        self.cfg = cfg
        self.router = ModelRouter(cfg)
        self._pause = threading.Event()
        self._resume_evt = threading.Event()   # 暂停唤醒事件（T3.3：去 0.15s 轮询）
        self._stop = False
        # 步骤决策门（Step Gates）：每一决策点等待人确认 → 继续/带想法继续/回退重做
        self._gate_evt = threading.Event()     # 门等待事件（置位=人已决策）
        self._gate_idea = ""                   # 人提交的想法（注入下一步/重跑步骤）
        self._gate_return = False              # True=回退重做请求
        self._gate_return_target = ""          # 回退目标门键（默认上一步=当前门）
        self._gate_pending = ""                # 当前等待中的门键
        # 章间传递的"门想法"（G9 的想法可注入下一章；G2 的想法注入细纲）
        self._gate_carry_idea = ""
        # 失败现场（stages 在每次 LLM 调用前写入）
        self.last_prompt = ""
        # 最近一次 6 维审校的原始输出（反馈环根因解析专用；与 last_prompt 的输入语义区分）
        self.review_raw = ""
        self._log_tail = []             # 最近日志（环形）
        self._cur_stage = ""
        self._cur_num = 0
        self._cur_step = ""

    # ---------- 外部控制 ----------

    def pause(self):
        self._pause.set()
        self._resume_evt.clear()

    def resume(self):
        self._pause.clear()
        self._resume_evt.set()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    def stop(self):
        self._stop = True
        self._pause.clear()
        # 唤醒所有直等中的阻塞点（T3.3）：暂停等待/门等待立即退出并走停止分支
        self._resume_evt.set()
        self._gate_evt.set()

    def auto_pause(self, reason: str):
        """质量闸门自动暂停（strict 策略）：置暂停位 + 通知 UI，等人处理后续跑"""
        self._pause.set()
        self.log("warn", f"闸门暂停：{reason}（处理后可点「继续」）")
        self.sig_auto_paused.emit(reason)

    # ---------- 步骤决策门（Step Gates）----------

    def gate_enabled(self, key: str) -> bool:
        """按运行模式判断门是否启用：auto=全关 / step=全开 / border=按硬软清单"""
        mode = self.cfg.get("writing", {}).get("run_mode", "auto")
        if mode == "auto":
            return False
        if mode == "step":
            return True
        writing = self.cfg.get("writing", {})
        return key in writing.get("gate_hard", []) or key in writing.get("gate_soft", [])

    def gate(self, key: str, summary: str = "", chapter: int = 0) -> str:
        """停在决策门等人确认。返回人提交的想法（空=直接继续）。
        回退重做在解锁前由 _apply_rollback 处理，本方法不返回"""
        if not self.gate_enabled(key):
            return ""
        state = st.load_state(self.proj)
        state["gate_status"] = {"gate": key, "chapter": chapter,
                                "summary": summary[:200], "ts": time.time()}
        st.save_state(self.proj, state)
        self._gate_evt.clear()
        self._gate_idea = ""
        self._gate_return = False
        self._gate_pending = key
        self.log("info", f"决策门 {key}（第{chapter}章）等待你的决定：{summary[:60]}")
        self.sig_gate.emit(key, chapter, summary)
        # 直等决策（T3.3）：stop() 会置位 _gate_evt 立即唤醒；1s 超时仅兜底
        while not self._gate_evt.wait(1.0):
            if self._stop:
                raise PipelineStopped()
        if self._stop:
            raise PipelineStopped()
        self._gate_pending = ""
        idea = self._gate_idea
        self._gate_idea = ""
        ret = self._gate_return
        self._gate_return = False
        if ret:
            self._apply_rollback(key, chapter)
            # 回退后：携带的想法留给重跑步骤注入；并让主循环重跑缺失产物
            self._gate_carry_idea = idea or self._gate_carry_idea
            return None  # 调用方据此知晓发生了回退
        return idea

    def resolve_gate(self, action: str, idea: str) -> bool:
        """UI 线程调用：next / return 决策，返回是否成功送达"""
        if not self._gate_pending:
            return False
        self._gate_idea = (idea or "").strip()
        self._gate_return = (action == "return")
        self._gate_evt.set()
        return True

    def consume_gate_idea(self) -> str:
        """取走章间携带的想法（G9→下一章 / 回退后→重跑注入）"""
        idea = self._gate_carry_idea
        self._gate_carry_idea = ""
        return idea

    def _apply_rollback(self, key: str, chapter: int):
        """回退动作：把目标产物归档后删除 → 主循环按「缺失即重跑」自动重做"""
        import shutil
        import datetime
        ts = datetime.datetime.now().strftime("%m%d_%H%M%S")
        if not self.proj:
            return
        roll = os.path.join(self.proj, "pipeline_debug", "rollback", f"{key}_ch{chapter}_{ts}")
        try:
            if key == "G2":  # 回退重拟全书大纲（连带清空细纲，避免旧细纲对账过期）
                os.makedirs(roll, exist_ok=True)
                targets = [os.path.join(self.proj, "大纲", "大纲.md")]
                outlines_dir = os.path.join(self.proj, "大纲")
                for n, p in project.list_outlines(self.proj):
                    targets.append(p)
                for t in targets:
                    if os.path.exists(t):
                        shutil.copy2(t, os.path.join(roll, os.path.basename(t)))
                        os.remove(t)
                # 大纲回退后把细纲已删除，需同步清空状态中的相关计划提示
                self.log("warn", "G2 回退：全书大纲与全部细纲已归档并清除，将重新生成")
            elif key == "G9":  # 回退重写本章：归档章节文件，版本历史保留（v1 仍在）
                # M4 锁守卫：locked 章直接拒绝（「该章已锁定，请先在共写档显式解锁」）
                if project.is_chapter_locked(self.proj, chapter):
                    self.log("warn", f"G9 回退拒绝：第 {chapter} 章已终稿锁定，请先在共写档显式解锁")
                    return
                os.makedirs(roll, exist_ok=True)
                for n, name, path in project.list_chapters(self.proj):
                    if n == chapter:
                        shutil.copy2(path, os.path.join(roll, os.path.basename(path)))
                        os.remove(path)
                        self.log("warn", f"G9 回退：第 {chapter} 章已归档并清除（版本历史保留），将重写本章")
                        break
            elif key in ("G4", "G6", "G7", "G8"):
                # 内侧门（T4.1）：回退由章节微循环内部处理（重新组装/保留原稿），此处不动物料
                self.log("info", f"门 {key} 回退：由章节微循环内部处理（重新组装/保留原稿语义）")
            else:
                self.log("warn", f"门 {key} 暂不支持回退，已按继续处理")
        except Exception as e:  # noqa: BLE001
            self.log("error", f"回退动作失败（{e}），已按继续处理")
            self._gate_return = False

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

    def stream_stage(self, label: str):
        """流式阶段切换 → UI（清空流式区 + 显示阶段标签）"""
        self.sig_stream_stage.emit(label)

    def stream_reasoning(self, text: str):
        """思维链增量 → UI（默认不展示，用户主动打开才看）"""
        self.sig_stream_reasoning.emit(text)

    def checkpoint(self):
        if self._stop:
            raise PipelineStopped()
        while self._pause.is_set():
            # 直等唤醒（T3.3）：resume()/stop() 置位 _resume_evt；1s 超时兜底
            self._resume_evt.wait(1.0)
            if self._stop:
                raise PipelineStopped()
        if self._stop:   # stop() 唤醒时 _pause 已被清，出循环后再查一次
            raise PipelineStopped()

    # ---------- 主流程 ----------

    def run(self):
        try:
            project.ensure_tracking_files(self.proj)
            state = st.load_state(self.proj)
            # 恢复上次回退时持久化的用户想法（G2 回退后重启仍携带）
            if state.get("carry_idea"):
                self._gate_carry_idea = state.pop("carry_idea", "")
                st.save_state(self.proj, state)

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
                # 决策门 G2：大纲完成 → 人确认/提想法/回退重拟
                self.checkpoint()
                g2_idea = self.gate("G2", "全书大纲已生成。下一步：规划总章数并进入章节细纲。",
                                    chapter=0)
                if g2_idea is None:
                    # 回退：大纲与细纲已归档清除，重新走「缺失即重跑」
                    state = st.load_state(self.proj)
                    state["total_chapters"] = 0
                    if self._gate_carry_idea:
                        state["carry_idea"] = self._gate_carry_idea  # 重启后注入细纲
                    st.save_state(self.proj, state)
                    return  # 结束本次运行，等待用户再次点「开始」重跑（细纲层将带想法）
                if g2_idea:
                    self._gate_carry_idea = g2_idea  # 注入首批细纲
            else:
                # 大纲已存在（续跑）：若上次回退留下想法，带进细纲
                pass

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
                # 取走用户提交的创作想法（标记已应用，注入草稿 prompt）
                ideas = st.take_ideas(state, num)
                if ideas:
                    st.save_state(self.proj, state)
                    self.log("info", f"第 {num} 章应用用户想法 {len(ideas)} 条：{ideas[0][:60]}")
                # 决策门 G5L：草稿开始前（软门：无产物可回退，想法直接并入指导）
                g5_idea = self.gate("G5L", f"第 {num} 章上下文就绪，即将开写草稿（目标 {chapter_words} 字）",
                                    chapter=num)
                if g5_idea is None:
                    g5_idea = ""  # 软门回退按继续处理
                carry = self.consume_gate_idea()
                if carry:
                    guidance = (guidance + "\n" + carry) if guidance else carry
                if g5_idea:
                    guidance = (guidance + "\n" + g5_idea) if guidance else g5_idea
                record = stages.chapter_microcycle(self, num, guidance=guidance, ideas=ideas)
                self.sig_chapter_done.emit(record)

                state = st.load_state(self.proj)
                state["stage"] = st.STAGE_PROSE
                state["current_chapter"] = num
                st.append_history(self.proj, state, record)
                self.sig_queue.emit()
                # 决策门 G9：本章定稿完成 → 确认进下一章 / 带想法 / 回退重写本章
                self.checkpoint()
                g9_idea = self.gate("G9", f"第 {num} 章已定稿（{record.get('words', 0)} 字" +
                                    f"· 审校{record.get('review_blocking', 0)}处阻塞）",
                                    chapter=num)
                if g9_idea is not None and g9_idea:
                    self._gate_carry_idea = g9_idea  # 注入下一章
                if g9_idea is None:
                    continue  # 回退已删本章文件，循环以相同 num 重跑
                num += 1

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
