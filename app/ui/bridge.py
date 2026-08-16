# -*- coding: utf-8 -*-
"""QML 桥接层：向界面暴露流水线状态、章节队列、日志流与全部命令"""
import logging
import os
import re

from PySide6.QtCore import (QObject, QAbstractListModel, Qt, QModelIndex,
                            Property, Signal, Slot, QThread, QTimer)

from .. import config as cfg_mod
from .. import project, deslop, prompts
from ..core import state as st, versions
from ..core.orchestrator import Orchestrator
from ..llm import LLMClient, LLMError, ModelRouter
from ..llm import clean_llm_output
from ..llm.providers import PROVIDERS, PROVIDER_ORDER

logger = logging.getLogger("qianbi.ui")


# ---------- 局部改写工作线程（选中文本 + 用户想法）----------

class SelectionRewriteWorker(QThread):
    """独立线程跑局部改写：流式回传增量，不阻塞 UI，不碰流水线"""
    sig_chunk = Signal(str)
    sig_reasoning = Signal(str)
    sig_done = Signal(str)
    sig_error = Signal(str)

    def __init__(self, cfg: dict, before: str, selected: str, after: str,
                 idea: str, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.before = before
        self.selected = selected
        self.after = after
        self.idea = idea
        self.router = ModelRouter(cfg)

    def run(self):
        try:
            prompt = prompts.SELECTION_REWRITE_PROMPT.format(
                user_idea=self.idea or "（无具体想法，请按你的判断润色这段）",
                selected=self.selected,
                before_context=self.before or "（选中段落在章节开头）",
                after_context=self.after or "（选中段落在章节末尾）",
            )
            client = self.router.client(cfg_mod.SLOT_WRITING)
            text = clean_llm_output(client.chat_stream(
                prompt, on_chunk=self.sig_chunk.emit,
                on_reasoning=self.sig_reasoning.emit))
            if not text.strip():
                self.sig_error.emit("模型返回为空，请重试")
            else:
                self.sig_done.emit(text)
        except Exception as e:  # noqa: BLE001
            self.sig_error.emit(str(e))


# ---------- 列表模型 ----------

class ChapterListModel(QAbstractListModel):
    NumRole = Qt.UserRole + 1
    TitleRole = Qt.UserRole + 2
    StateRole = Qt.UserRole + 3
    WordsRole = Qt.UserRole + 4
    NoteRole = Qt.UserRole + 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def roleNames(self):
        return {self.NumRole: b"num", self.TitleRole: b"title",
                self.StateRole: b"state", self.WordsRole: b"words",
                self.NoteRole: b"note"}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role == self.NumRole:
            return item.get("num", 0)
        if role == self.TitleRole:
            return item.get("title", "")
        if role == self.StateRole:
            return item.get("state", "queued")
        if role == self.WordsRole:
            return item.get("words", 0)
        if role == self.NoteRole:
            return item.get("note", "")
        return None

    def set_items(self, items: list):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def update_item(self, num: int, patch: dict):
        for i, it in enumerate(self._items):
            if it.get("num") == num:
                it.update(patch)
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                return


class LogListModel(QAbstractListModel):
    TimeRole = Qt.UserRole + 1
    LevelRole = Qt.UserRole + 2
    TextRole = Qt.UserRole + 3
    MAX_ROWS = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def roleNames(self):
        return {self.TimeRole: b"time", self.LevelRole: b"level", self.TextRole: b"text"}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role == self.TimeRole:
            return item.get("time", "")
        if role == self.LevelRole:
            return item.get("level", "info")
        if role == self.TextRole:
            return item.get("text", "")
        return None

    def append(self, level: str, text: str):
        import datetime
        if len(self._items) >= self.MAX_ROWS:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._items.pop(0)
            self.endRemoveRows()
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append({"time": datetime.datetime.now().strftime("%H:%M:%S"),
                            "level": level, "text": text})
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self._items = []
        self.endResetModel()


class ConnectionListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    ProviderRole = Qt.UserRole + 3
    ModelRole = Qt.UserRole + 4
    BaseUrlRole = Qt.UserRole + 5
    ApiKeyRole = Qt.UserRole + 6
    TemperatureRole = Qt.UserRole + 7
    MaxTokensRole = Qt.UserRole + 8
    TimeoutRole = Qt.UserRole + 9
    SlotsRole = Qt.UserRole + 10   # 该连接绑定的槽位标签，如 "写作槽"

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge

    def rowCount(self, parent=QModelIndex()):
        return len(self._bridge.cfg.get("connections", []))

    def roleNames(self):
        return {self.IdRole: b"cid", self.NameRole: b"name", self.ProviderRole: b"provider",
                self.ModelRole: b"model", self.BaseUrlRole: b"baseUrl", self.ApiKeyRole: b"apiKey",
                self.TemperatureRole: b"temperature", self.MaxTokensRole: b"maxTokens",
                self.TimeoutRole: b"timeout", self.SlotsRole: b"slots"}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        conns = self._bridge.cfg.get("connections", [])
        if not (0 <= index.row() < len(conns)):
            return None
        c = conns[index.row()]
        if role == self.IdRole:
            return c.get("id", "")
        if role == self.NameRole:
            return c.get("name", "")
        if role == self.ProviderRole:
            return c.get("provider", "custom")
        if role == self.ModelRole:
            return c.get("model", "")
        if role == self.BaseUrlRole:
            return c.get("base_url", "")
        if role == self.ApiKeyRole:
            return c.get("api_key", "")
        if role == self.TemperatureRole:
            return c.get("temperature", 0.7)
        if role == self.MaxTokensRole:
            return c.get("max_tokens", 8192)
        if role == self.TimeoutRole:
            return c.get("timeout", 300)
        if role == self.SlotsRole:
            bound = [cfg_mod.SLOT_LABELS[s] for s in cfg_mod.SLOT_ORDER
                     if self._bridge.cfg.get("slots", {}).get(s) == c.get("id")]
            return " · ".join(bound)
        return None

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()


class _NetWorker(QThread):
    """连接测试 / 拉模型 后台小任务"""
    test_done = Signal(str, bool, str)          # conn_id, ok, msg
    models_done = Signal(str, list)             # conn_id, models

    def __init__(self, mode: str, conn: dict, parent=None):
        super().__init__(parent)
        self.mode, self.conn = mode, conn

    def run(self):
        client = LLMClient.from_connection(self.conn)
        cid = self.conn.get("id", "")
        try:
            if self.mode == "test":
                msg = client.test_connection()
                self.test_done.emit(cid, True, msg)
            else:
                self.models_done.emit(cid, client.list_models())
        except LLMError as e:
            if self.mode == "test":
                self.test_done.emit(cid, False, str(e))
            else:
                self.models_done.emit(cid, [])


class _IdeaWorker(QThread):
    """选题展开（灵感 → 3 个选题方向）：用辅助槽，后台执行"""
    done = Signal(bool, str)                    # ok, result_or_error

    def __init__(self, cfg: dict, idea: str, parent=None):
        super().__init__(parent)
        self.cfg, self.idea = cfg, idea

    def run(self):
        from .. import prompts
        from ..llm import ModelRouter, clean_llm_output
        try:
            router = ModelRouter(self.cfg)
            prompt = prompts.IDEA_EXPAND_PROMPT.format(user_input=self.idea)
            result = clean_llm_output(router.client(cfg_mod.SLOT_HELPER).chat(prompt))
            self.done.emit(bool(result), result or "模型返回为空")
        except Exception as e:
            self.done.emit(False, str(e))


# ---------- 主桥 ----------

class Bridge(QObject):
    # 属性变更信号
    bookTitleChanged = Signal()
    bookMetaChanged = Signal()
    stageKeyChanged = Signal()
    progressChanged = Signal()
    runningChanged = Signal()
    pausedChanged = Signal()
    currentChapterChanged = Signal()
    currentStepChanged = Signal()
    tokensChanged = Signal()
    slotsTextChanged = Signal()
    hasProjectChanged = Signal()
    chapterTextChanged = Signal()
    chapterFindingsChanged = Signal()
    lastRecordChanged = Signal()
    liveDraftChanged = Signal()
    streamingChanged = Signal()
    streamStageChanged = Signal()
    reasoningChanged = Signal()
    selectionDraftChanged = Signal()
    selectionReasoningChanged = Signal()
    selectionStateChanged = Signal()
    ideaCountChanged = Signal()
    editorDirtyChanged = Signal()
    recoverableDraftChanged = Signal()
    # 事件信号
    projectOpened = Signal()
    toast = Signal(str, str)                    # level, msg
    connTestResult = Signal(str, bool, str)     # cid, ok, msg
    modelsFetched = Signal(str, list)           # cid, models
    ideaExpanded = Signal(bool, str)            # ok, result_or_error

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = cfg_mod.load_config()
        self.proj = None
        self.orch = None
        self._workers = []
        self._running = False
        self._paused = False
        self._book_title = ""
        self._book_meta = ""
        self._stage_key = st.STAGE_INIT
        self._progress_text = ""
        self._progress_value = 0.0
        self._cur_num = 0
        self._cur_title = ""
        self._cur_step = ""
        self._chapter_text = ""
        self._chapter_path = ""
        self._chapter_findings = []
        self._last_record = {}
        self._live_draft = ""
        self._streaming = False
        self._stream_stage_label = ""
        self._reasoning_text = ""
        # 局部改写状态（选中文本 + 想法 → AI 只改选中段）
        self._sel_draft = ""
        self._sel_reasoning = ""
        self._sel_worker = None
        self._sel_result = ""
        # 保存驱动版本状态：工作副本 dirty 跟踪 + 草稿暂存（不产生版本）
        self._editor_dirty = False
        self._working_text = ""
        self._last_edit_action = ""            # 最近一次编辑动作来源（局部改写/手动）
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(5000)    # 5s 防抖：只防丢稿，不算版本
        self._draft_timer.timeout.connect(self._flush_draft)
        self.chapterModel = ChapterListModel(self)
        self.logModel = LogListModel(self)
        self.connectionModel = ConnectionListModel(self)
        # 上次项目自动打开
        last = self.cfg.get("last_project", "")
        if last and project.is_project(last):
            self._open_project(last, silent=True)

    # ============ 属性 ============

    def _get_book_title(self): return self._book_title
    def _get_book_meta(self): return self._book_meta
    def _get_stage_key(self): return self._stage_key
    def _get_progress_text(self): return self._progress_text
    def _get_progress_value(self): return self._progress_value

    def _get_progress_percent_text(self):
        """进度百分比文本：无总字数目标（无限续写）时显示『续写中』而非误导的 0%"""
        if not self.proj:
            return ""
        state = st.load_state(self.proj)
        total = state.get("total_chapters", 0) or project.planned_chapters(
            self.proj, self.cfg.get("writing", {}).get("chapter_word_target", 3000))
        if not total:
            return "续写中"
        done = len(project.list_chapters(self.proj))
        return f"{int(done / total * 100)}%"
    def _get_running(self): return self._running
    def _get_paused(self): return self._paused
    def _get_cur_num(self): return self._cur_num
    def _get_cur_title(self): return self._cur_title
    def _get_cur_step(self): return self._cur_step
    def _get_has_project(self): return bool(self.proj)
    def _get_chapter_text(self): return self._chapter_text
    def _get_chapter_path(self): return self._chapter_path
    def _get_chapter_findings(self): return self._chapter_findings
    def _get_live_draft(self): return self._live_draft
    def _get_streaming(self): return self._streaming
    def _get_stream_stage(self): return self._stream_stage_label
    def _get_reasoning(self): return self._reasoning_text
    def _get_sel_draft(self): return self._sel_draft
    def _get_sel_reasoning(self): return self._sel_reasoning
    def _get_sel_rewriting(self): return self._sel_worker is not None and self._sel_worker.isRunning()
    def _get_pending_ideas(self):
        if not self.proj:
            return 0
        state = st.load_state(self.proj)
        return len(state.get("pending_ideas") or [])

    def _get_editor_dirty(self): return self._editor_dirty

    def _get_has_recoverable_draft(self):
        return bool(self.proj and versions.newest_draft(self.proj))

    def _get_tokens(self):
        if self.orch:
            return self.orch.router.total_tokens()
        return 0

    def _get_cost_text(self):
        if not self.orch:
            return "¥0.00"
        return f"¥{self.orch.router.estimate_cost():.2f}"

    def _get_slot_text(self):
        def fmt(slot):
            conn = cfg_mod.slot_connection(self.cfg, slot)
            return conn.get("model", "未配置") if conn else "未配置"
        return f"写作 {fmt(cfg_mod.SLOT_WRITING)} · 辅助 {fmt(cfg_mod.SLOT_HELPER)}"

    bookTitle = Property(str, _get_book_title, notify=bookTitleChanged)
    bookMeta = Property(str, _get_book_meta, notify=bookMetaChanged)
    stageKey = Property(str, _get_stage_key, notify=stageKeyChanged)
    progressText = Property(str, _get_progress_text, notify=progressChanged)
    progressValue = Property(float, _get_progress_value, notify=progressChanged)
    progressPercentText = Property(str, _get_progress_percent_text, notify=progressChanged)
    isRunning = Property(bool, _get_running, notify=runningChanged)
    isPaused = Property(bool, _get_paused, notify=pausedChanged)
    currentChapterNum = Property(int, _get_cur_num, notify=currentChapterChanged)
    currentChapterTitle = Property(str, _get_cur_title, notify=currentChapterChanged)
    currentStepKey = Property(str, _get_cur_step, notify=currentStepChanged)
    hasProject = Property(bool, _get_has_project, notify=hasProjectChanged)
    totalTokens = Property(int, _get_tokens, notify=tokensChanged)
    estCost = Property(str, _get_cost_text, notify=tokensChanged)
    slotsText = Property(str, _get_slot_text, notify=slotsTextChanged)
    chapterText = Property(str, _get_chapter_text, notify=chapterTextChanged)
    chapterPath = Property(str, _get_chapter_path, notify=chapterTextChanged)
    chapterFindings = Property("QVariantList", _get_chapter_findings, notify=chapterFindingsChanged)
    lastRecord = Property("QVariantMap", lambda self: self._last_record, notify=lastRecordChanged)
    liveDraftText = Property(str, _get_live_draft, notify=liveDraftChanged)
    isStreaming = Property(bool, _get_streaming, notify=streamingChanged)
    streamStageLabel = Property(str, _get_stream_stage, notify=streamStageChanged)
    reasoningText = Property(str, _get_reasoning, notify=reasoningChanged)
    selectionDraftText = Property(str, _get_sel_draft, notify=selectionDraftChanged)
    selectionReasoningText = Property(str, _get_sel_reasoning, notify=selectionReasoningChanged)
    isRewritingSelection = Property(bool, _get_sel_rewriting, notify=selectionStateChanged)
    pendingIdeas = Property(int, _get_pending_ideas, notify=ideaCountChanged)
    editorDirty = Property(bool, _get_editor_dirty, notify=editorDirtyChanged)
    hasRecoverableDraft = Property(bool, _get_has_recoverable_draft,
                                   notify=recoverableDraftChanged)
    providerOptions = Property("QVariantList", lambda self: [
        {"key": k, "label": PROVIDERS[k]["label"], "baseUrl": PROVIDERS[k]["base_url"],
         "hint": PROVIDERS[k]["hint"], "models": PROVIDERS[k]["models"]}
        for k in PROVIDER_ORDER], constant=True)
    slotLabels = Property("QVariantMap", lambda self: dict(cfg_mod.SLOT_LABELS), constant=True)
    chapterModelProp = Property(QObject, lambda self: self.chapterModel, constant=True)
    logModelProp = Property(QObject, lambda self: self.logModel, constant=True)
    connectionModelProp = Property(QObject, lambda self: self.connectionModel, constant=True)

    # ============ 项目管理 ============

    @Slot(str, str, str, str, int, str, result=bool)
    def newProject(self, location, name, genre, platform, totalWan, idea):
        location, name = location.strip(), name.strip()
        if not location or not name:
            self.toast.emit("warn", "请填写保存位置与书名")
            return False
        try:
            path = project.create_project(location, name)
        except FileExistsError:
            self.toast.emit("warn", "目录已存在同名项目")
            return False
        project.write_idea_info(path, genre.strip(), platform.strip() or "番茄",
                                idea.strip(), int(totalWan or 0))
        self._open_project(path)
        self.toast.emit("ok", f"项目《{name}》已创建，点击「开始」启动流水线")
        return True

    @Slot(str)
    def openProject(self, path):
        if not path:
            return
        if path.startswith("file://"):
            from PySide6.QtCore import QUrl
            path = QUrl(path).toLocalFile()
        if not project.is_project(path):
            self.toast.emit("warn", "该目录不是写作项目（缺少 设定/大纲/正文/追踪）")
            return
        self._open_project(path)

    def _open_project(self, path: str, silent: bool = False):
        self.proj = path
        cfg_mod.push_recent_project(self.cfg, path)
        cfg_mod.save_config(self.cfg)
        project.ensure_tracking_files(path)
        self._book_title = os.path.basename(path)
        info = project.read_idea_info(path)
        meta_parts = [p for p in [info["genre"], info["platform"],
                                  f"目标 {info['total_words_wan']} 万字" if info["total_words_wan"] else ""] if p]
        self._book_meta = " · ".join(meta_parts)
        # 恢复最近一次定稿记录（质量格/快捷按钮的数据源）
        _state = st.load_state(path)
        _hist = _state.get("history") or []
        if _hist:
            self._last_record = dict(sorted(_hist, key=lambda h: h.get("num", 0))[-1])
        else:
            self._last_record = {}
        self._refresh_progress()
        self.refreshQueue()
        self.lastRecordChanged.emit()
        self.bookTitleChanged.emit()
        self.bookMetaChanged.emit()
        self.hasProjectChanged.emit()
        # 打开项目即加载最新一章到中央编辑器（写作软件直觉：打开就有内容可读）
        chapters = project.list_chapters(path)
        if chapters:
            self._cur_num = chapters[-1][0]
            self._chapter_path = chapters[-1][2]
            self._chapter_text = project.read_file(chapters[-1][2])
            self._chapter_findings = []
            self.chapterTextChanged.emit()
            self.chapterFindingsChanged.emit()
        self._reset_editor_state()
        # 草稿恢复检测（崩溃/意外退出后留下的未保存草稿）
        self.recoverableDraftChanged.emit()
        if not silent:
            self.projectOpened.emit()

    def _reset_editor_state(self):
        """工作副本状态复位：编辑器内容 == 磁盘基准，无未保存修改"""
        self._editor_dirty = False
        self._working_text = ""
        self._last_edit_action = ""
        self._draft_timer.stop()
        self.editorDirtyChanged.emit()

    def _flush_draft(self):
        """5s 防抖草稿暂存（只防丢稿，绝不产生版本）"""
        if (self.proj and self._cur_num and self._working_text
                and self._editor_dirty):
            versions.save_draft(self.proj, self._cur_num, self._working_text)

    # ============ 流水线控制 ============

    @Slot()
    def startPipeline(self):
        logger.info("[dbg] startPipeline invoked, proj=%s running=%s", self.proj, self._running)
        if not self.proj:
            self.toast.emit("warn", "请先打开或新建项目")
            return
        if self._running:
            return
        # api key 检查
        missing = []
        for slot in cfg_mod.SLOT_ORDER:
            conn = cfg_mod.slot_connection(self.cfg, slot)
            if not conn:
                missing.append(cfg_mod.SLOT_LABELS[slot])
                continue
            url = conn.get("base_url", "")
            if not conn.get("api_key") and "localhost" not in url and "127.0.0.1" not in url:
                missing.append(f"{cfg_mod.SLOT_LABELS[slot]}（{conn.get('name', '')} 未填 API Key）")
        if missing:
            self.toast.emit("warn", "请先在「连接与模型」配置：" + "、".join(missing))
            return
        self.orch = Orchestrator(self.proj, self.cfg, self)
        self.orch.sig_log.connect(self._on_log)
        self.orch.sig_stage.connect(self._on_stage)
        self.orch.sig_chapter_started.connect(self._on_chapter_started)
        self.orch.sig_step.connect(self._on_step)
        self.orch.sig_stream_chunk.connect(self._on_stream_chunk)
        self.orch.sig_stream_stage.connect(self._on_stream_stage)
        self.orch.sig_stream_reasoning.connect(self._on_stream_reasoning)
        self.orch.sig_chapter_done.connect(self._on_chapter_done)
        self.orch.sig_queue.connect(self.refreshQueue)
        self.orch.sig_finished.connect(self._on_finished)
        self.orch.sig_failed.connect(self._on_failed)
        self.orch.sig_auto_paused.connect(self._on_auto_paused)
        self._set_running(True)
        self._set_paused(False)
        self.logModel.append("info", "流水线启动")
        logger.info("流水线启动: %s", self.proj)
        self.orch.start()

    @Slot()
    def pausePipeline(self):
        if self.orch and self._running:
            self.orch.pause()
            self._set_paused(True)
            self.logModel.append("info", "已请求暂停（当前步骤完成后停）")

    @Slot()
    def resumePipeline(self):
        if self.orch and self._running:
            self.orch.resume()
            self._set_paused(False)
            self.logModel.append("info", "继续写作")

    @Slot()
    def stopPipeline(self):
        if self.orch and self._running:
            self.orch.stop()
            self.logModel.append("warn", "已请求停止…")

    @Slot(int)
    def rewriteChapter(self, num: int):
        """重写某章：删除正文文件后回到流水线（运行中不可操作）"""
        self._rewrite_chapter_common(num, "")

    @Slot(int, str)
    def rewriteChapterWithGuidance(self, num: int, guidance: str):
        """带用户指导重写：删除正文文件 + 登记指导语，续跑时注入正文 prompt"""
        self._rewrite_chapter_common(num, guidance)

    def _rewrite_chapter_common(self, num: int, guidance: str):
        if self._running or not self.proj:
            self.toast.emit("warn", "请先停止流水线再重写章节")
            return
        guidance = (guidance or "").strip()
        for n, name, path in project.list_chapters(self.proj):
            if n == num:
                try:
                    os.remove(path)
                except OSError as e:
                    self.toast.emit("warn", f"删除失败: {e}")
                    return
                break
        if guidance:
            state = st.load_state(self.proj)
            st.set_guidance(self.proj, state, num, guidance)
        self.refreshQueue()
        if guidance:
            self.toast.emit("ok", f"第 {num} 章正文已移除，已登记重写指导，点击「开始」从该章续跑")
        else:
            self.toast.emit("ok", f"第 {num} 章正文已移除，点击「开始」将从该章续跑")

    # ============ 局部改写（选中文本 + 想法，不动流水线）============

    @Slot(str, str, str, str)
    def rewriteSelection(self, before: str, selected: str, after: str, idea: str):
        """AI 只改写选中段落：流式预览 → QML 应用/放弃"""
        if not selected.strip():
            self.toast.emit("warn", "请先在编辑器中选中要改写的段落")
            return
        if self._sel_worker and self._sel_worker.isRunning():
            self.toast.emit("warn", "上一段改写还在进行中")
            return
        self._sel_draft = ""
        self._sel_reasoning = ""
        self._sel_result = ""
        self.selectionDraftChanged.emit()
        self.selectionReasoningChanged.emit()
        self.selectionStateChanged.emit()
        worker = SelectionRewriteWorker(self.cfg, before, selected, after, idea, self)
        worker.sig_chunk.connect(self._on_sel_chunk)
        worker.sig_reasoning.connect(self._on_sel_reasoning)
        worker.sig_done.connect(self._on_sel_done)
        worker.sig_error.connect(self._on_sel_error)
        self._sel_worker = worker
        worker.start()
        self.selectionStateChanged.emit()

    def _on_sel_chunk(self, text: str):
        self._sel_draft += text
        self.selectionDraftChanged.emit()

    def _on_sel_reasoning(self, text: str):
        self._sel_reasoning += text
        self.selectionReasoningChanged.emit()

    def _on_sel_done(self, text: str):
        self._sel_result = text
        self.selectionStateChanged.emit()
        self.toast.emit("ok", "改写完成，可「应用」或「放弃」")

    def _on_sel_error(self, msg: str):
        self.selectionStateChanged.emit()
        self.toast.emit("error", f"局部改写失败: {msg}")

    @Slot(result=str)
    def selectionResult(self) -> str:
        return self._sel_result

    @Slot()
    def cancelSelectionRewrite(self):
        if self._sel_worker and self._sel_worker.isRunning():
            self._sel_worker.requestInterruption()
        self._sel_worker = None
        self.selectionStateChanged.emit()

    # ============ 创作想法提交（人和 AI 一起创作）============

    @Slot(str)
    def submitIdea(self, text: str):
        """写作中随时提交创作想法：注入下一章草稿 prompt"""
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return
        state = st.load_state(self.proj)
        if st.add_idea(self.proj, state, text):
            self.ideaCountChanged.emit()
            self.toast.emit("ok", "想法已提交，将注入下一章创作")
        else:
            self.toast.emit("warn", "想法不能为空")

    # ============ 章节查看/编辑（保存驱动版本语义）============

    @Slot(int)
    def openChapter(self, num: int):
        """打开章节到编辑器（工作副本：加载磁盘内容，无未保存修改）
        注意：QML 端在调用前需先处理当前未保存修改（保存/放弃/取消）"""
        if not self.proj:
            return
        for n, name, path in project.list_chapters(self.proj):
            if n == num:
                self._chapter_path = path
                self._chapter_text = project.read_file(path)
                self._chapter_findings = []
                self.chapterTextChanged.emit()
                self.chapterFindingsChanged.emit()
                self._reset_editor_state()
                return
        self.toast.emit("warn", f"第 {num} 章正文不存在")

    @Slot(str)
    def markEditorDirty(self, text: str):
        """编辑器内容变化时由 QML 调用：比较磁盘基准，置未保存标记 + 启动防抖暂存"""
        dirty = text != self._chapter_text
        if dirty != self._editor_dirty:
            self._editor_dirty = dirty
            self.editorDirtyChanged.emit()
        if dirty:
            self._working_text = text
            self._draft_timer.start()
        else:
            self._working_text = ""
            self._draft_timer.stop()

    @Slot()
    def clearEditorDirty(self):
        """放弃未保存修改（QML 确认对话框「放弃」后调用）"""
        self._reset_editor_state()

    @Slot(str)
    def noteEditAction(self, source: str):
        """登记最近一次编辑动作来源（局部改写应用等），下次保存时作为版本来源标注"""
        self._last_edit_action = source or ""

    @Slot(str)
    def saveChapterText(self, text: str):
        """保存驱动版本的唯一提交动作：
        ① 磁盘旧内容归档为新版本（内容有变化才产生）
        ② 新内容写正文 ③ 工作副本变干净
        取消 / 切换章节 / 关闭 / 意外退出 都不会走到这里，因此不会产生版本"""
        if not self._chapter_path:
            return
        source = self._last_edit_action or versions.SOURCE_MANUAL
        old = project.read_file(self._chapter_path)
        v = versions.snapshot(self.proj, self._cur_num, old, source)
        project.write_file(self._chapter_path, text)
        self._chapter_text = text
        self._last_edit_action = ""
        self._working_text = ""
        self._draft_timer.stop()
        if self._editor_dirty:
            self._editor_dirty = False
            self.editorDirtyChanged.emit()
        if self.proj and self._cur_num:
            versions.discard_draft(self.proj, self._cur_num)
        self.toast.emit("ok", f"已保存（{project.count_chars(text)} 字）"
                         + (f" · 版本 v{v} 已归档" if v else " · 内容无变化，未产生新版本"))
        self.refreshQueue()

    # ============ 版本历史（保存驱动 · 查看/diff/回退）============

    @Slot(int, result="QVariantList")
    def versionsForChapter(self, num: int) -> list:
        if not self.proj:
            return []
        return versions.list_versions(self.proj, num)

    @Slot(int, int, result=str)
    def readVersion(self, num: int, v: int) -> str:
        if not self.proj:
            return ""
        return versions.read_version(self.proj, num, v)

    @Slot(int, result=str)
    def diskTextOf(self, num: int) -> str:
        """磁盘当前（已保存）内容，作为版本 diff 的参照"""
        if not self.proj:
            return ""
        for n, name, path in project.list_chapters(self.proj):
            if n == num:
                return project.read_file(path)
        return ""

    @Slot(int, int, int, result="QVariantList")
    def diffVersions(self, num: int, v1: int, v2: int) -> list:
        if not self.proj:
            return []
        return versions.diff_versions(self.proj, num, v1, v2)

    @Slot(int, int, result="QVariantList")
    def diffVersionWithDisk(self, num: int, v: int) -> list:
        """版本 v vs 磁盘当前内容（回退前预览）"""
        if not self.proj:
            return []
        return versions.diff_texts(versions.read_version(self.proj, num, v),
                                   self.diskTextOf(num))

    # ============ 草稿恢复（崩溃/意外退出后的未保存内容，仍算工作副本）============

    @Slot(result="QVariantMap")
    def recoverDraft(self) -> dict:
        """恢复最新未保存草稿到编辑器（工作副本，未保存；保存才成为版本）。
        返回 {num, text}；无草稿返回 {}。基准保持磁盘旧内容，dirty 置位。"""
        nd = versions.newest_draft(self.proj)
        if not nd:
            return {}
        num, content, mtime = nd
        for n, name, path in project.list_chapters(self.proj):
            if n == num:
                self._chapter_path = path
                break
        self._cur_num = num
        self._chapter_findings = []
        self._editor_dirty = True
        self._working_text = content
        self._draft_timer.stop()
        versions.discard_draft(self.proj, num)
        self.editorDirtyChanged.emit()
        self.chapterFindingsChanged.emit()
        self.toast.emit("ok", f"已恢复第 {num} 章未保存草稿（工作副本，点「保存」提交为新版本）")
        return {"num": num, "text": content}

    @Slot()
    def discardDrafts(self):
        """丢弃全部未保存草稿（用户确认后）"""
        if self.proj:
            versions.discard_all_drafts(self.proj)
        self.recoverableDraftChanged.emit()
        self.toast.emit("ok", "未保存草稿已丢弃")

    @Slot(str)
    def scanChapterText(self, text: str):
        if not text.strip():
            self._chapter_findings = []
        else:
            findings = deslop.scan_text(text)
            self._chapter_findings = [
                {"level": f.level, "message": f.message, "text": f.text or "",
                 "start": f.start, "end": f.end, "hint": f.fix_hint or ""}
                for f in findings
            ]
        self.chapterFindingsChanged.emit()

    @Slot(result=str)
    def readFileText(self) -> str:
        return self._chapter_text

    # ============ 连接与模型 ============

    @Slot(str, result="QVariantMap")
    def getConnection(self, cid: str) -> dict:
        return dict(cfg_mod.find_connection(self.cfg, cid))

    @Slot("QVariantMap")
    def saveConnection(self, conn: dict):
        conn = dict(conn)
        cid = conn.get("id") or cfg_mod.new_connection_id()
        conn["id"] = cid
        conns = self.cfg.setdefault("connections", [])
        for i, c in enumerate(conns):
            if c.get("id") == cid:
                conns[i] = conn
                break
        else:
            conns.append(conn)
        cfg_mod.save_config(self.cfg)
        self.connectionModel.refresh()
        self.slotsTextChanged.emit()
        self.toast.emit("ok", f"连接「{conn.get('name', '')}」已保存")

    @Slot(str)
    def deleteConnection(self, cid: str):
        conns = self.cfg.get("connections", [])
        if len(conns) <= 1:
            self.toast.emit("warn", "至少保留一条连接")
            return
        self.cfg["connections"] = [c for c in conns if c.get("id") != cid]
        for slot in cfg_mod.SLOT_ORDER:
            if self.cfg["slots"].get(slot) == cid:
                self.cfg["slots"][slot] = self.cfg["connections"][0]["id"]
        cfg_mod.save_config(self.cfg)
        self.connectionModel.refresh()
        self.slotsTextChanged.emit()

    @Slot(str, str)
    def setSlot(self, slot: str, cid: str):
        self.cfg.setdefault("slots", {})[slot] = cid
        cfg_mod.save_config(self.cfg)
        self.connectionModel.refresh()
        self.slotsTextChanged.emit()
        self.toast.emit("ok", f"{cfg_mod.SLOT_LABELS.get(slot, slot)} → {cfg_mod.find_connection(self.cfg, cid).get('name', '')}")

    @Slot("QVariantMap")
    def testConnectionDraft(self, conn: dict):
        """用表单当前内容直接测试（不要求先保存）"""
        conn = dict(conn)
        if not conn.get("id"):
            conn["id"] = "__draft__"
        w = _NetWorker("test", conn, self)
        w.test_done.connect(self.connTestResult)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    @Slot(str)
    def testConnection(self, cid: str):
        conn = cfg_mod.find_connection(self.cfg, cid)
        if not conn:
            return
        w = _NetWorker("test", conn, self)
        w.test_done.connect(self.connTestResult)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    @Slot(str)
    def fetchModels(self, cid: str):
        conn = cfg_mod.find_connection(self.cfg, cid)
        if not conn:
            return
        w = _NetWorker("models", conn, self)
        w.models_done.connect(self.modelsFetched)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    # ============ 队列与进度 ============

    @Slot()
    def refreshQueue(self):
        if not self.proj:
            self.chapterModel.set_items([])
            return
        state = st.load_state(self.proj)
        history = {h["num"]: h for h in state.get("history", [])}
        chapters = {n: (name, path) for n, name, path in project.list_chapters(self.proj)}
        outlines = {n for n, _ in project.list_outlines(self.proj)}
        nums = set(chapters) | set(outlines) | set(history)
        if self._cur_num:
            nums.add(self._cur_num)
        items = []
        for num in sorted(nums):
            title, state_str, words, note = "", "queued", 0, ""
            if num in chapters:
                m = re.match(r"第\d+章_?(.+)\.md", chapters[num][0])
                title = m.group(1) if m and m.group(1) else ""
                words = project.count_chars(project.read_file(chapters[num][1]))
            if num in history:
                h = history[num]
                title = h.get("title") or title
                words = h.get("words") or words
                state_str = "pass" if h.get("status") == "pass" else "needs_fix"
                if h.get("deslop_blocking"):
                    note = f"AI味 {h['deslop_blocking']} 阻断"
            if num == self._cur_num and self._running:
                state_str = "writing"
                note = st.STEP_LABELS.get(self._cur_step, "")
            elif state_str == "queued" and num in outlines:
                state_str = "outline_ready"
                note = "细纲就绪"
            items.append({"num": num, "title": title, "state": state_str,
                          "words": words, "note": note})
        self.chapterModel.set_items(items)
        self._refresh_progress()

    def _refresh_progress(self):
        if not self.proj:
            self._progress_text, self._progress_value = "", 0.0
        else:
            state = st.load_state(self.proj)
            total = state.get("total_chapters", 0) or project.planned_chapters(
                self.proj, self.cfg.get("writing", {}).get("chapter_word_target", 3000))
            done = len(project.list_chapters(self.proj))
            self._progress_text = f"{done} / {total} 章" if total else f"{done} 章"
            self._progress_value = (done / total) if total else 0.0
        self.progressChanged.emit()

    # ============ Orchestrator 事件 ============

    def _on_log(self, level: str, msg: str):
        self.logModel.append(level, msg)

    def _on_stage(self, key: str):
        self._stage_key = key
        self.stageKeyChanged.emit()

    def _on_chapter_started(self, num: int):
        self._cur_num = num
        self._cur_step = ""
        self._live_draft = ""
        self._streaming = True
        self.liveDraftChanged.emit()
        self.streamingChanged.emit()
        self.ideaCountChanged.emit()   # 想法可能已被流水线消费，刷新计数
        self.currentChapterChanged.emit()
        self.currentStepChanged.emit()
        self.refreshQueue()

    def _on_stream_chunk(self, text: str):
        self._live_draft += text
        self.liveDraftChanged.emit()

    def _on_stream_stage(self, label: str):
        """流式阶段切换：清空流式区 + 更新阶段标签（人和 AI 一起读）"""
        self._live_draft = ""
        self._stream_stage_label = label
        self._streaming = True
        self._reasoning_text = ""
        self.liveDraftChanged.emit()
        self.streamStageChanged.emit()
        self.reasoningChanged.emit()
        self.streamingChanged.emit()

    def _on_stream_reasoning(self, text: str):
        """思维链增量（默认隐藏，用户主动打开才看）"""
        self._reasoning_text += text
        self.reasoningChanged.emit()

    def _on_step(self, num: int, step_key: str):
        self._cur_step = step_key
        self.currentStepChanged.emit()
        self.chapterModel.update_item(num, {"note": st.STEP_LABELS.get(step_key, "")})

    def _on_chapter_done(self, record: dict):
        self._cur_title = record.get("title", "")
        self._last_record = record
        self._streaming = False
        self._stream_stage_label = ""
        self._reasoning_text = ""
        # 若当前编辑器正显示刚定稿的章：跟随磁盘新内容（工作副本干净，版本基准同步）
        if self._cur_num == record.get("num") and self.proj:
            for n, name, path in project.list_chapters(self.proj):
                if n == record.get("num"):
                    self._chapter_path = path
                    self._chapter_text = project.read_file(path)
                    self.chapterTextChanged.emit()
                    self._reset_editor_state()
                    break
        self.streamStageChanged.emit()
        self.reasoningChanged.emit()
        self.streamingChanged.emit()
        self.lastRecordChanged.emit()
        self.currentChapterChanged.emit()
        self.tokensChanged.emit()
        self._refresh_progress()

    def _on_finished(self, reason: str):
        self._set_running(False)
        self._set_paused(False)
        self._streaming = False
        self._stream_stage_label = ""
        self._reasoning_text = ""
        self.streamStageChanged.emit()
        self.reasoningChanged.emit()
        self.streamingChanged.emit()
        self._cur_num = 0
        self._cur_step = ""
        self.currentChapterChanged.emit()
        self.currentStepChanged.emit()
        self.refreshQueue()
        if reason == "done":
            self.toast.emit("ok", "全书完本")

    def _on_failed(self, msg: str):
        self._set_running(False)
        self._set_paused(False)
        self._streaming = False
        self._stream_stage_label = ""
        self.streamStageChanged.emit()
        self.streamingChanged.emit()
        self.logModel.append("error", msg)
        self.toast.emit("error", msg)
        logger.error("流水线失败: %s", msg)

    def _on_auto_paused(self, reason: str):
        """质量闸门自动暂停（strict）：置暂停态 + 提示用户处理"""
        self._set_paused(True)
        self.toast.emit("warn", f"闸门暂停：{reason}")

    def _set_running(self, v: bool):
        self._running = v
        self.runningChanged.emit()

    def _set_paused(self, v: bool):
        self._paused = v
        self.pausedChanged.emit()

    @Slot(str, str)
    def showToast(self, level: str, msg: str):
        """QML 端复用全局 Toast"""
        self.toast.emit(level, msg)

    @Slot(result="QVariantList")
    def recentProjects(self) -> list:
        result = []
        for p in self.cfg.get("recent_projects", []):
            if project.is_project(p):
                prog = project.project_progress(p)
                info = project.read_idea_info(p)
                result.append({
                    "path": p, "name": os.path.basename(p),
                    "genre": info["genre"], "platform": info["platform"],
                    "chapters": prog["chapters_written"], "words": prog["total_words"],
                })
        return result

    @Slot(result="QVariantList")
    def connectionOptions(self) -> list:
        """供槽位下拉使用：[{id, name, boundSlots}]"""
        result = []
        slots = self.cfg.get("slots", {})
        for c in self.cfg.get("connections", []):
            bound = [s for s in cfg_mod.SLOT_ORDER if slots.get(s) == c.get("id")]
            result.append({"id": c.get("id", ""), "name": c.get("name", ""), "boundSlots": bound})
        return result

    @Slot(str)
    def expandIdea(self, idea: str):
        """选题展开：一句话灵感 → 3 个选题方向（后台执行，结果经 ideaExpanded 信号返回）"""
        idea = (idea or "").strip()
        if not idea:
            self.toast.emit("warn", "先填写一句话灵感，再点「AI 展开」")
            return
        w = _IdeaWorker(self.cfg, idea, self)
        w.done.connect(self.ideaExpanded)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    @Slot(result="QVariantList")
    def projectFiles(self) -> list:
        """列出项目内可编辑的 md 文件（设定/大纲/追踪），供「项目文件」面板浏览"""
        if not self.proj:
            return []
        result = []
        for d in ["设定", "大纲", "追踪"]:
            base = os.path.join(self.proj, d)
            if not os.path.isdir(base):
                continue
            for name in sorted(os.listdir(base)):
                p = os.path.join(base, name)
                if os.path.isfile(p) and name.endswith(".md"):
                    rel = os.path.join(d, name).replace(os.sep, "/")
                    result.append({"rel": rel, "name": name, "dir": d,
                                   "size": os.path.getsize(p)})
        return result

    @Slot(str, result=str)
    def readProjectFile(self, rel: str) -> str:
        if not self.proj:
            return ""
        p = os.path.join(self.proj, rel)
        if not os.path.isfile(p):
            return ""
        return project.read_file(p)

    @Slot(str, str)
    def saveProjectFile(self, rel: str, text: str):
        if not self.proj:
            return
        p = os.path.join(self.proj, rel)
        if not os.path.isfile(p):
            self.toast.emit("warn", "文件不存在")
            return
        project.write_file(p, text)
        self.refreshQueue()
        self.toast.emit("ok", f"已保存 {rel}")

    @Slot(str, result=str)
    def exportProject(self, fmt: str) -> str:
        """导出全本：txt（平台上传标准）或 epub（阅读器标准）。返回导出路径"""
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return ""
        try:
            from .. import export as export_mod
            path = export_mod.export_project(self.proj, fmt)
            self.toast.emit("ok", f"已导出：{os.path.basename(path)}")
            return path
        except ValueError as e:
            self.toast.emit("warn", str(e))
            return ""
        except Exception as e:
            self.toast.emit("error", f"导出失败: {e}")
            return ""

    @Slot(result=str)
    def defaultBooksRoot(self) -> str:
        root = os.path.join(os.path.expanduser("~"), "Documents", "千笔一文")
        os.makedirs(root, exist_ok=True)
        return root
