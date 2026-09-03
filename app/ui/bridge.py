# -*- coding: utf-8 -*-
"""QML 桥接层：向界面暴露流水线状态、章节队列、日志流与全部命令"""
import datetime
import difflib
import json
import threading
import logging
import os
import re

from PySide6.QtCore import (QObject, QAbstractListModel, Qt, QModelIndex,
                            Property, Signal, Slot, QThread, QTimer)

from .. import config as cfg_mod
from .. import mustscan, project, deslop, prompts
from ..core import gates, state as st, versions
from ..core.orchestrator import Orchestrator
from ..core.co_writing import CoWriting
from ..core import co_dialogue
from ..llm import LLMClient, LLMError, ModelRouter
from ..llm import clean_llm_output
from ..llm.providers import PROVIDERS, PROVIDER_ORDER

logger = logging.getLogger("qianbi.ui")


# ---------- 局部改写工作线程（选中文本 + 用户想法）----------

class SelectionRewriteWorker(QThread):
    """独立线程跑局部改写：流式回传增量，不阻塞 UI，不碰流水线

    mode: only=仅选中段 | neighbor=带前后各一段 | full=带全章 | setting=全章+核心设定
    """
    sig_chunk = Signal(str)
    sig_reasoning = Signal(str)
    sig_done = Signal(str)
    sig_error = Signal(str)

    def __init__(self, cfg: dict, before: str, selected: str, after: str,
                 idea: str, mode: str = "neighbor", proj: str = "", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.before = before
        self.selected = selected
        self.after = after
        self.idea = idea
        self.mode = mode or "neighbor"
        self.proj = proj or ""
        self.router = ModelRouter(cfg)

    def run(self):
        try:
            core = ""
            if self.mode == "setting" and self.proj:
                from .. import project as _pj
                core = _pj.read_file(os.path.join(self.proj, "设定", "题材定位.md"))[:1500]
            core_block = (prompts.SELECTION_CORE_SETTING_BLOCK.format(core_setting=core)
                          if core else "")
            from ..core import stages as stages_mod
            must_block = (stages_mod._must_block(self.proj, self.cfg) if self.proj
                          else "（未打开书籍，暂无正则契约）")
            prompt = prompts.SELECTION_REWRITE_PROMPT.format(
                user_idea=self.idea or "（无具体想法，请按你的判断润色这段）",
                selected=self.selected,
                before_context=self.before or "（选中段落在章节开头）",
                after_context=self.after or "（选中段落在章节末尾）",
                core_setting=core,
                core_setting_block=core_block,
                must_block=must_block,
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


# ---------- 定向修复助手（v3：最小差异 + 同一性验收）----------

def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def format_fix_targets(targets: list) -> str:
    """修复目标 → REVIEW_FIX_PROMPT 注入的问题清单（含原文引证/命中原文/修法）"""
    lines = []
    for i, t in enumerate(targets, 1):
        if t.get("kind") == "deslop":
            lines.append(f"[问题{i}] 去AI味规则 {t.get('dim', '')}")
            lines.append(f"说明: {t.get('text', '')}")
            if t.get("quote"):
                lines.append(f"命中原文: 「{t['quote']}」（只改这一句）")
            if t.get("hint"):
                lines.append(f"修法: {t['hint']}")
        else:
            dim = t.get("dim") or ""
            lines.append(f"[问题{i}]" + (f" 维度{dim}" if dim else ""))
            lines.append(f"说明: {t.get('text', '')}")
            if t.get("quote"):
                lines.append(f"原文引证: 「{t['quote']}」（只改包含此引文的位置）")
    return "\n".join(lines) or "（无问题）"


def flagged_para_indices(prose: str, targets: list) -> set:
    """包含任一问题引证/命中原文的段号（按换行分段，0 基）"""
    norm_paras = [_norm_text(p) for p in prose.split("\n")]
    flagged = set()
    for t in targets:
        q = _norm_text(t.get("quote") or "")
        if not q:
            continue
        for i, np_ in enumerate(norm_paras):
            if q in np_:
                flagged.add(i)
    return flagged


def enforce_minimal_diff(prose: str, rewritten: str, flagged: set):
    """段级对齐后机械还原：未涉及任何问题的原文段落被模型改动/增删的一律还原。

    Returns (enforced_text, restored_count)。
    """
    old = prose.split("\n")
    new = rewritten.split("\n")
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    out = []
    restored = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(old[i1:i2])
        elif tag == "replace":
            oc, nc = old[i1:i2], new[j1:j2]
            chunk_flagged = any(i in flagged for i in range(i1, i2))
            for k in range(max(len(oc), len(nc))):
                if k < len(oc):
                    oi = i1 + k
                    if oi in flagged:
                        out.append(nc[k] if k < len(nc) else oc[k])
                    else:
                        if k >= len(nc) or nc[k] != oc[k]:
                            restored += 1
                        out.append(oc[k])
                elif chunk_flagged:
                    out.append(nc[k])
                else:
                    restored += 1   # 无问题区域的插入段 → 丢弃
        elif tag == "insert":
            if (i1 - 1) in flagged or i1 in flagged:
                out.extend(new[j1:j2])
            else:
                restored += j2 - j1
        elif tag == "delete":
            for oi in range(i1, i2):
                out.append(old[oi])
                if oi not in flagged:
                    restored += 1
    return "\n".join(out), restored


def issue_similarity(a: str, b: str) -> float:
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def target_resolved(t: dict, new_text: str, new_blocking_texts: list) -> bool:
    """同一性判定：原问题「已解决」= 引文不再存在 且 复扫没有报出相似问题"""
    similar = any(issue_similarity(t.get("text", ""), nb) >= 0.55
                  for nb in new_blocking_texts)
    q = _norm_text(t.get("quote") or "")
    if q:
        return q not in _norm_text(new_text) and not similar
    return not similar


def recover_quote_from_text(text: str, prose: str) -> str:
    """从问题文本里恢复可定位的原文引证（登记时 quote 丢失的兜底）。

    优先取【原文引证：...】整段及其内部引号片段，其次取文本内引号片段；
    只返回确实存在于正文的片段。
    """
    prose_norm = _norm_text(prose)
    candidates = []
    m = re.search(r"【原文引证[：:]\s*(.+?)\s*】", text or "", re.S)
    if m:
        q = m.group(1).strip().strip('"“”')
        candidates.append(q)
        candidates.extend(re.findall(r"[“\"]([^”\"]{4,80})[”\"]", q))
    candidates.extend(re.findall(r"[“\"]([^”\"]{4,80})[”\"]", text or ""))
    for q in candidates:
        q = q.strip()
        if q and _norm_text(q) and _norm_text(q) in prose_norm:
            return q
    return ""


def split_unstructured_findings(text: str) -> list:
    """把「[未结构化评审]」式的整条阻塞文本按 - [阻塞]/- [建议] 拆成独立问题。"""
    if not re.search(r"- ?[【\[]?(?:阻塞|建议)[】\]]?", text or ""):
        return [text]
    segs = re.split(r"- ?[【\[]?(?:阻塞|建议)[】\]]?", text)
    out = []
    for s in segs:
        s = re.sub(r"^\s*[【\[]?未结构化评审[】\]]?\s*\S*\s*===ITEMS===\s*", "", s).strip()
        if s:
            out.append(s)
    return out or [text]


# ---------- 待修章节一键修复工作线程（依据已登记审校问题定向修复，不碰流水线）----------

class ChapterRepairWorker(QThread):
    """逐章修复待修章节：聚合登记阻塞问题 + 本地 deslop 阻断命中 → 快照「修复前备份」→
    REVIEW_FIX_PROMPT 按引证定向修改 → 段级最小差异还原 → 同一性验收（原问题消除才采纳）。"""
    sig_log = Signal(str)
    sig_chapter_done = Signal(int, bool, str)   # num, ok, detail
    sig_all_done = Signal(int, int)             # ok_count, fail_count

    def __init__(self, cfg: dict, proj: str, nums: list, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.nums = list(nums)
        from ..core import stages as stages_mod
        # 与流水线同一预设参数档：否则「一键修复」和自动跑出来的稿子采样口径不一致
        self.router = ModelRouter(cfg, **stages_mod.preset_param_layers(proj))

    def run(self):
        ok = fail = 0
        for num in self.nums:
            try:
                success, detail = self._repair_one(num)
            except Exception as e:  # noqa: BLE001
                success, detail = False, f"异常: {e}"
            if success:
                ok += 1
            else:
                fail += 1
            self.sig_chapter_done.emit(num, success, detail)
        self.sig_all_done.emit(ok, fail)

    def _build_fix_targets(self, num: int, prose: str) -> list:
        """聚合定向修复目标：登记 6 维 fail 项（带原文引证）+ v1 blocking 兜底 + 本地 deslop 阻断命中。

        每条 {kind: review|deslop, dim, text, quote, hint}；quote 用于定位段落与同一性验收。
        """
        state = st.load_state(self.proj)
        rf = st.load_review_findings(state, num)
        targets = []
        seen = set()

        def _add(kind, dim, text, quote, hint=""):
            text = str(text or "").strip()
            if not text:
                return
            nt, nq = _norm_text(text), _norm_text(quote)
            if (nt and nt in seen) or (nq and nq in seen):
                return
            if nt:
                seen.add(nt)
            if nq:
                seen.add(nq)
            targets.append({"kind": kind, "dim": dim or "", "text": text,
                            "quote": str(quote or "").strip(), "hint": hint or ""})

        for it in (rf.get("items") or []):
            if isinstance(it, dict) and it.get("level") == "fail" and it.get("text") \
                    and not str(it["text"]).startswith("[字数]") \
                    and it.get("quote_verified") is not False:
                _add("review", it.get("dim", ""), it["text"], it.get("quote", ""))
        for b in (rf.get("blocking") or []):
            for part in split_unstructured_findings(str(b or "")):
                # [字数] 项修复 prompt 扩不了字数，进目标只会死循环（#37 教训）→ 不进修复目标
                if not part.startswith("[字数]"):
                    _add("review", "", part, "")
        for f in deslop.scan_text(prose):
            if f.level == "blocking":
                _add("deslop", f.rule, f.message, f.text, f.fix_hint)
        # 引证恢复：登记时 quote 丢失（解析降级/旧数据）→ 从问题文本里找回正文中真实存在的引文
        for t in targets:
            if t["kind"] == "review" and not t["quote"]:
                t["quote"] = recover_quote_from_text(t["text"], prose)
        # 过期引证过滤：登记问题的引文已不在正文（多为人工已修）→ 该目标作废，
        # 全部作废时走新鲜复审而不是白白调一次修复模型
        prose_norm = _norm_text(prose)
        targets = [t for t in targets
                   if t["kind"] != "review" or not t["quote"]
                   or _norm_text(t["quote"]) in prose_norm]
        return targets

    def _review_v2(self, num: int, prose: str) -> dict:
        """新鲜 6 维复审（多轮投票，组装与 stages._chapter_review 同源）"""
        from ..core import gates as gates_mod, stages as stages_mod
        # 字数预检（本地，零 LLM）：短章直接 REJECT
        wc_items, wc_blocking, wc_verdict = gates_mod.word_count_precheck(
            self.proj, num, prose, self.cfg)
        if wc_verdict:
            return {"verdict": wc_verdict, "items": wc_items,
                    "blocking": wc_blocking, "advisory": [],
                    "summary": {"pass": 0, "marginal": 0, "fail": len(wc_items)}}

        class _Ctx:   # review_with_votes 需要的最小 ctx 面
            pass
        ctx = _Ctx()
        ctx.proj = self.proj
        ctx.cfg = self.cfg
        ctx.router = self.router
        ctx.last_prompt = ""
        ctx.review_raw = ""
        ctx.stream_chunk = lambda t: None
        ctx.log = lambda level, msg: self.sig_log.emit(msg)
        votes = max(1, int(self.cfg.get("gates", {}).get("review_votes", 3)))
        return stages_mod.review_with_votes(ctx, num, prose, votes)

    def _repair_one(self, num: int) -> tuple:
        path = None
        for n, _name, p in project.list_chapters(self.proj):
            if n == num:
                path = p
                break
        if not path:
            return False, "未找到正文文件"
        prose = project.read_file(path)
        if not prose.strip():
            return False, "正文为空"
        targets = self._build_fix_targets(num, prose)
        if not targets:
            self.sig_log.emit(f"第 {num} 章无登记阻塞问题，先跑一轮新鲜复审…")
            v2 = self._review_v2(num, prose)
            if v2["verdict"]:
                st.save_review_findings(self.proj, st.load_state(self.proj), num,
                                        v2["verdict"], v2["items"], v2["blocking"], v2["advisory"])
            targets = self._build_fix_targets(num, prose)
            if not targets:
                if v2["verdict"] in ("REJECT", "REJECT-HARD"):
                    reason = "; ".join(str(b) for b in v2["blocking"]) or "存在阻塞问题"
                    return False, f"复审 {v2['verdict']}（无可定向修复项）：{reason}"
                st.update_history_status(self.proj, st.load_state(self.proj), num, "pass")
                self._reset_attempts(num)
                return True, "复审通过，无阻塞问题"
        self.sig_log.emit(f"第 {num} 章按 {len(targets)} 处问题定向修复（带引证定位，最小改动）…")
        versions.snapshot(self.proj, num, prose, "修复前备份")
        fix_prompt = prompts.REVIEW_FIX_PROMPT.format(
            chapter_num=num, findings=format_fix_targets(targets), prose=prose,
            outline_brief=(project.read_file(project.get_outline_path(self.proj, num))[:600]
                           or "（无本章细纲）"),
            core_setting_brief=(project.read_file(os.path.join(self.proj, "设定", "题材定位.md"))[:1200]
                                or "（未提供）"))
        rewritten = clean_llm_output(
            self.router.client(cfg_mod.SLOT_REVIEW).chat_stream(fix_prompt))
        # 修复稿健全性守卫（与 stages.py 修复环同款：拒绝修订计划/空文本/长度骤减）
        looks_like_plan = rewritten.lstrip().startswith("===")
        too_short = len(rewritten.strip()) < max(300, int(len(prose) * 0.5))
        if not rewritten.strip() or looks_like_plan or too_short:
            reason = "空" if not rewritten.strip() else "修订计划" if looks_like_plan else "长度骤减"
            self._bump_attempts(num)
            return False, f"模型返回非正文（{reason}），原稿保留"
        # 最小差异强制：未涉及任何问题的段落被模型顺手改动的一律还原；
        # 若所有问题都无法定位到段落（无引证），降级为不强制还原，仅靠同一性验收把关
        flagged = flagged_para_indices(prose, targets)
        if flagged:
            enforced, restored = enforce_minimal_diff(prose, rewritten, flagged)
            if restored:
                self.sig_log.emit(f"第 {num} 章：已回滚 {restored} 处非问题区域的顺手改动")
        else:
            enforced, restored = rewritten, 0
            self.sig_log.emit(f"第 {num} 章：问题无可定位引证，本轮放宽最小差异约束")
        if _norm_text(enforced) == _norm_text(prose):
            marked = self._bump_attempts(num)
            suffix = "，连续 3 轮未收敛已转人工" if marked else ""
            return False, f"修复无效：模型未改动任何问题段落{suffix}，原稿保留"
        # 同一性验收：原问题确实消除且不复发才采纳（不再只看数量减少）
        v2 = self._review_v2(num, enforced)
        new_blocking = list(v2["blocking"])
        for f in deslop.scan_text(enforced):
            if f.level == "blocking" and f.text not in new_blocking:
                new_blocking.append(f.text)
        resolved = [t for t in targets if target_resolved(t, enforced, new_blocking)]
        if not new_blocking:
            project.write_file(path, enforced)
            state = st.load_state(self.proj)
            if v2["verdict"]:
                st.save_review_findings(self.proj, state, num, v2["verdict"],
                                        v2["items"], new_blocking, v2["advisory"])
            st.update_history_status(self.proj, st.load_state(self.proj), num, "pass")
            self._reset_attempts(num)
            extra = f"，回滚 {restored} 处无关改写" if restored else ""
            return True, f"已修复 {len(targets)} 处问题，复审通过{extra}"
        if not resolved:
            marked = self._bump_attempts(num)
            suffix = "，连续 3 轮未收敛已转人工" if marked else ""
            return False, f"原问题未被修复（{len(new_blocking)} 处仍在）{suffix}，原稿保留"
        if len(new_blocking) >= len(targets):
            marked = self._bump_attempts(num)
            suffix = "，连续 3 轮未收敛已转人工" if marked else ""
            return False, (f"修复无净改善（{len(targets)}→{len(new_blocking)}，已解决 {len(resolved)} "
                           f"但出现新问题）{suffix}，原稿保留")
        project.write_file(path, enforced)
        state = st.load_state(self.proj)
        if v2["verdict"]:
            st.save_review_findings(self.proj, state, num, v2["verdict"],
                                    v2["items"], new_blocking, v2["advisory"])
        st.update_history_status(self.proj, st.load_state(self.proj), num, "needs_fix")
        return True, f"阻塞 {len(targets)}→{len(new_blocking)}（已解决 {len(resolved)}，可再修一轮）"

    def _bump_attempts(self, num: int) -> bool:
        """累计修复轮次；≥3 轮未收敛标 chapter_need_human。返回本轮是否已升级。"""
        state = st.load_state(self.proj)
        att = state.setdefault("repair_attempts", {})
        rec = att.get(str(num)) or {"count": 0}
        rec["count"] = int(rec.get("count", 0)) + 1
        att[str(num)] = rec
        st.save_state(self.proj, state)
        if rec["count"] >= 3:
            st.mark_chapter_need_human(self.proj, st.load_state(self.proj), num)
            return True
        return False

    def _reset_attempts(self, num: int):
        state = st.load_state(self.proj)
        att = state.get("repair_attempts") or {}
        if str(num) in att:
            att.pop(str(num), None)
            state["repair_attempts"] = att
            st.save_state(self.proj, state)


def collect_needs_fix(state: dict) -> list:
    """聚合待修章节：history 状态非 pass，或登记的 review_findings 仍有阻塞。

    返回 [{num, title, words, status, verdict, blocking, advisory, needHuman, ts}]（按章号升序）
    """
    entries = {}
    for h in state.get("history", []):
        if not isinstance(h, dict) or h.get("status") == "pass":
            continue
        num = h.get("num", 0)
        entries[num] = {"num": num, "title": h.get("title", ""), "words": h.get("words", 0),
                        "status": h.get("status", "needs_fix"), "verdict": "",
                        "blocking": 0, "advisory": 0, "needHuman": False, "ts": h.get("ts", "")}
    for key, rf in (state.get("review_findings") or {}).items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(rf, dict):
            continue
        blocking = [b for b in (rf.get("blocking") or []) if str(b).strip()]
        if not blocking:
            blocking = [i.get("text", "") for i in (rf.get("items") or [])
                        if isinstance(i, dict) and i.get("level") == "fail" and i.get("text")]
        if not blocking:
            continue
        e = entries.get(num) or {"num": num, "title": "", "words": 0, "status": "needs_fix",
                                 "verdict": "", "blocking": 0, "advisory": 0,
                                 "needHuman": False, "ts": ""}
        e["verdict"] = rf.get("verdict", "")
        e["blocking"] = len(blocking)
        e["advisory"] = len(rf.get("advisory") or [])
        e["ts"] = rf.get("ts", "") or e["ts"]
        entries[num] = e
    nhh = state.get("chapter_need_human") or {}
    for num in entries:
        if str(num) in nhh:
            entries[num]["needHuman"] = True
    return sorted(entries.values(), key=lambda e: e["num"])


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


class _BlurbWorker(QThread):
    """发布物料生成（题材定位 + 全书大纲 → 标签 + 简介）：用辅助槽，后台执行"""
    done = Signal(bool, str)                    # ok, result_or_error

    def __init__(self, cfg: dict, proj: str, parent=None):
        super().__init__(parent)
        self.cfg, self.proj = cfg, proj

    def run(self):
        from .. import prompts
        from ..llm import ModelRouter, clean_llm_output
        try:
            info = project.read_idea_info(self.proj)
            core = (project.read_file(os.path.join(self.proj, "设定", "题材定位.md")) or "")[:2000] or "（未提供）"
            outline = (project.read_file(os.path.join(self.proj, "大纲", "大纲.md")) or "")[:4000] or "（未提供）"
            prompt = prompts.BLURB_AND_TAGS_PROMPT.format(
                book_name=os.path.basename(self.proj),
                genre=info.get("genre") or "（不限）",
                platform=info.get("platform") or "番茄",
                core_setting=core,
                volume_outline=outline,
            )
            result = clean_llm_output(ModelRouter(self.cfg).client(cfg_mod.SLOT_HELPER).chat(prompt))
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
    stoppingChanged = Signal()
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
    # v2 新增：6 维审校 issues + 主题切换
    reviewIssuesChanged = Signal()
    themeChanged = Signal()
    # 待修章节汇总 + 一键修复
    needsFixChanged = Signal()
    needsFixReady = Signal()        # 流水线结束且存在待修章：QML 弹汇总对话框询问作者
    genConfigReady = Signal(int)    # 队列行「查看生成配置」：QML 弹本章 P2 快照对话框（带章号）
    repairChanged = Signal()
    # 共写档（co-write）状态
    cwModeChanged = Signal()
    cwStageChanged = Signal()
    cwBusyChanged = Signal()
    cwMessagesChanged = Signal()
    cwStreamingChanged = Signal()
    cwLockedChanged = Signal()
    cwReportChanged = Signal()
    cwProsePolished = Signal(str)   # M6：手动去AI味完成，改写文本进编辑器工作副本（不落盘）
    # 事件信号
    projectOpened = Signal()
    toast = Signal(str, str)                    # level, msg
    connTestResult = Signal(str, bool, str)     # cid, ok, msg
    modelsFetched = Signal(str, list)           # cid, models
    ideaExpanded = Signal(bool, str)            # ok, result_or_error
    blurbGenerated = Signal(bool, str)          # ok, result_or_error（发布物料：标签+简介）
    lockBlocked = Signal(int, str, int, int, str)  # 锁定被闸门拦截：num, reason, actual, target, kind
    # kind: "word"=字数未达标（有 actual/target）| "contract"=正则 must 契约违规（无字数概念）
    gateAsked = Signal(str, int, str)           # 步骤决策门：key, chapter, summary
    gateClosed = Signal()                       # 门已失效（停止/失败/完成时清决策条，真机缺陷②）
    consoleChanged = Signal()                   # T4.3：Console 思考链/对话区/展开态更新
    mainWindowReady = Signal()                  # 主窗口就绪（单实例唤起时序）
    updateFound = Signal(str, str, str)         # 检查更新：version, notes, url
    generalChanged = Signal()                   # 向导/遥测等通用设置变更
    usageChanged = Signal()                     # token 用量统计刷新（插件）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = cfg_mod.load_config()
        self.proj = None
        self.orch = None
        self._workers = []
        self._running = False
        self._paused = False
        self._stopping = False
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
        # 待修章节一键修复状态
        self._repair_worker = None
        self._repair_status = ""
        # ReviewIssueDialog 正在显示的章号（resolveReviewIssue 回执不再错位到 current_chapter）
        self._review_issue_num = 0
        # 保存驱动版本状态：工作副本 dirty 跟踪 + 草稿暂存（不产生版本）
        self._editor_dirty = False
        self._working_text = ""
        self._last_edit_action = ""            # 最近一次编辑动作来源（局部改写/手动）
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(5000)    # 5s 防抖：只防丢稿，不算版本
        self._draft_timer.timeout.connect(self._flush_draft)
        # 共写档状态（CoWriting 状态机 + 一次性 worker）
        self._cw = None
        self._cw_view = ""                     # 对话区查看的阶段（回看历史用，机器阶段不动）
        self._cw_busy = False
        self._cw_confirming = False            # 确定按钮重入锁（#3）
        self._cw_cancelled = False             # 用户取消在途请求（#8）
        self._cw_busy_seconds = 0
        self._cw_reply = ""                    # 本轮 agent 流式回复缓冲
        self._cw_worker = None
        self._cw_sum_worker = None
        self._backflow_worker = None           # 剧情反哺 worker（helper 槽，后台串行）
        self._backflow_queue = []              # 补跑队列（章号，先进先出）
        self._cw_busy_timer = QTimer(self)
        self._cw_busy_timer.setInterval(1000)
        self._cw_busy_timer.timeout.connect(self._on_cw_busy_tick)
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
    def _get_stopping(self): return self._stopping
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
        return len(st.pending_idea_texts(state))

    def _get_editor_dirty(self): return self._editor_dirty

    def _get_has_recoverable_draft(self):
        return bool(self.proj and versions.newest_draft(self.proj))

    def _get_tokens(self):
        from .. import usage as _usage
        t = _usage.summary().get("today", {})
        return int(t.get("in", 0)) + int(t.get("out", 0))

    def _get_cost_text(self):
        from .. import usage as _usage
        return f"¥{_usage.summary().get('today', {}).get('cost', 0.0):.2f}"

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
    isStopping = Property(bool, _get_stopping, notify=stoppingChanged)
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
    # ---- 共写档属性（M1）----
    cwMode = Property(str, lambda self: self._get_cw_mode(), notify=cwModeChanged)
    cwStageKey = Property(str, lambda self: self._get_cw_stage_key(), notify=cwStageChanged)
    cwStageLabel = Property(str, lambda self: self._get_cw_stage_label(), notify=cwStageChanged)
    cwAgent = Property(str, lambda self: self._get_cw_agent(), notify=cwStageChanged)
    cwViewStage = Property(str, lambda self: self._get_cw_view(), notify=cwStageChanged)
    cwBusy = Property(bool, lambda self: self._cw_busy, notify=cwBusyChanged)
    cwMessages = Property("QVariantList", lambda self: self._get_cw_messages(), notify=cwMessagesChanged)
    cwStreamingText = Property(str, lambda self: self._cw_reply, notify=cwStreamingChanged)
    cwSummary = Property("QVariantMap", lambda self: self._get_cw_summary(), notify=cwStageChanged)
    cwStageCards = Property("QVariantList", lambda self: self._get_cw_stage_cards(), notify=cwStageChanged)
    cwUnitInfo = Property("QVariantMap", lambda self: self._get_cw_unit(), notify=cwStageChanged)
    cwUnitHasOutlines = Property(bool, lambda self: self._get_cw_unit_has_outlines(), notify=cwStageChanged)
    chapterLocked = Property(bool, lambda self: self._get_chapter_locked(), notify=cwLockedChanged)
    readbackEnabled = Property(bool, lambda self: bool(self.cfg.get("writing", {}).get("readback_on_save", True)),
                               notify=cwLockedChanged)
    readbackMinDiff = Property(int, lambda self: int(self.cfg.get("writing", {}).get("readback_min_diff", 200)),
                               notify=cwLockedChanged)
    cwReportText = Property(str, lambda self: self._get_cw_report_text(), notify=cwReportChanged)
    cwReportTs = Property(str, lambda self: self._get_cw_report_ts(), notify=cwReportChanged)
    cwReportConsumed = Property(bool, lambda self: self._get_cw_report_consumed(), notify=cwReportChanged)
    cwBusySeconds = Property(int, lambda self: self._cw_busy_seconds, notify=cwBusyChanged)
    cwPreset = Property(str, lambda self: self._get_cw_preset(), notify=cwStageChanged)
    cwReachedStages = Property("QVariantList", lambda self: self._get_cw_reached_stages(), notify=cwStageChanged)
    chapterModelProp = Property(QObject, lambda self: self.chapterModel, constant=True)
    logModelProp = Property(QObject, lambda self: self.logModel, constant=True)
    connectionModelProp = Property(QObject, lambda self: self.connectionModel, constant=True)

    # ============ 项目管理 ============

    @Slot(str, str, str, str, int, str, str, result=bool)
    def newProject(self, location, name, genre, platform, totalWan, idea, presetId=""):
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
        preset_name = ""
        if presetId:
            from .. import presets as genre_presets
            state = st.load_state(path)
            state["genre_preset"] = presetId
            st.save_state(path, state)
            preset_name = genre_presets.load_preset(presetId).get("name") or presetId
        self._open_project(path)
        self.toast.emit("ok", f"项目《{name}》已创建"
                        + (f"（题材预设「{preset_name}」）" if preset_name else "")
                        + "，点击「开始」启动流水线")
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
        # 共写档状态机（按项目粘性档位初始化；回看视图=机器阶段）
        self._cw = CoWriting(path)
        self._cw_view = self._get_cw_stage_key()
        self.cwModeChanged.emit()
        self.cwStageChanged.emit()
        self.cwMessagesChanged.emit()
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
        # 每日自动备份（设置开启后，一天最多一次）
        self._maybe_auto_backup()
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
        if self._get_cw_mode() == "cw":
            self.toast.emit("warn", "当前为共写档：先完成共写阶段或切换回自动档再启动流水线")
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
        self.orch.sig_thinking.connect(self._on_thinking)
        self.orch.sig_chapter_done.connect(self._on_chapter_done)
        self.orch.sig_queue.connect(self.refreshQueue)
        self.orch.sig_finished.connect(self._on_finished)
        self.orch.sig_failed.connect(self._on_failed)
        self.orch.sig_auto_paused.connect(self._on_auto_paused)
        self.orch.sig_gate.connect(self._on_gate)
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
            self.logModel.append("info", "暂停已受理：本次 LLM 调用跑完后停在当前步骤边界（不是立刻掐断）")

    @Slot()
    def resumePipeline(self):
        if self.orch and self._running:
            self.orch.resume()
            self._set_paused(False)
            self.logModel.append("info", "继续写作")

    @Slot()
    def stopPipeline(self):
        if not (self.orch and self._running):
            return
        if self._get_stopping():
            self.logModel.append("info", "已在停止中：等当前这步收尾，勿重复点")
            return
        self._stopping = True
        self.stoppingChanged.emit()   # 按钮转「正在停止…」并禁用，避免「点了没反应」的体感
        self.orch.stop()
        self.logModel.append("warn", "停止已受理：正在生成的这一次调用会在下一 token 处中断")

    # ============ 步骤决策门（Step Gates）============

    GATE_META = [
        {"key": "G1", "label": "G1 设定完成", "desc": "核心设定生成后确认，可回退重拟设定", "wired": False},
        {"key": "G2", "label": "G2 大纲完成", "desc": "全书大纲生成后确认，可回退重拟大纲（连带清空细纲）", "wired": True},
        {"key": "G3", "label": "G3 细纲批完成", "desc": "每批细纲（2章）生成后确认", "wired": False},
        {"key": "G4", "label": "G4 素材组装后", "desc": "草稿开写前确认投入材料，可带想法或回退重组装", "wired": True},
        {"key": "G5L", "label": "G5 草稿开始前", "desc": "第N章开写前确认，可带想法（软门：无产物可回退）", "wired": True},
        {"key": "G6", "label": "G6 扫描完成", "desc": "AI 味扫描结果确认，可带想法或回退保留原稿跳过去味", "wired": True},
        {"key": "G7", "label": "G7 去味完成", "desc": "去味改写前后对比确认，回退=还原去味前原稿", "wired": True},
        {"key": "G8", "label": "G8 审校完成", "desc": "审校结论确认，回退=还原审校前原稿（G9 仍把关）", "wired": True},
        {"key": "G9", "label": "G9 定稿完成", "desc": "每章定稿后确认，可回退重写本章（版本历史保留）", "wired": True},
    ]

    @Slot(result="QVariantList")
    def gateMetaList(self) -> list:
        return [dict(m) for m in self.GATE_META]

    @Slot(result=str)
    def runMode(self) -> str:
        # 项目级档位粘性优先：共写档状态 cw.mode == 'cw' 时即显示共写
        if self.proj:
            state = st.load_state(self.proj)
            if st.ensure_cw(state).get("mode") == "cw":
                return "cw"
        # config 的 'cw' 只在项目已迁移时有效；未迁移时按 auto 显示（防脱同步，#1）
        m = str(self.cfg.get("writing", {}).get("run_mode", "auto"))
        return "auto" if m == "cw" else m

    @Slot(str)
    def setRunMode(self, mode: str):
        m = mode if mode in ("auto", "step", "border", "cw") else "auto"
        self.cfg.setdefault("writing", {})["run_mode"] = m
        self.cfg["writing"]["step_confirm"] = (m == "step")
        cfg_mod.save_config(self.cfg)
        # cw ↔ 自动档为受控切换（仅阶段空闲可切）：同步项目级粘性
        if m == "cw":
            self.setCwMode(True)
        elif self._get_cw_mode() == "cw":
            self.setCwMode(False)
        names = {"auto": "全自动", "step": "逐步确认", "border": "边界确认", "cw": "共写"}
        self.toast.emit("ok", f"运行模式已切换为「{names[m]}」")

    @Slot(str, result=bool)
    def gateEnabled(self, key: str) -> bool:
        w = self.cfg.get("writing", {})
        if self.cfg.get("writing", {}).get("run_mode", "auto") == "step":
            return True
        return key in w.get("gate_hard", []) or key in w.get("gate_soft", [])

    @Slot(str, bool)
    def setGateEnabled(self, key: str, on: bool):
        w = self.cfg.setdefault("writing", {})
        hard_keys = {"G1", "G2", "G3", "G5L", "G8", "G9"}
        hard = set(w.get("gate_hard", []))
        soft = set(w.get("gate_soft", []))
        if on:
            (hard if key in hard_keys else soft).add(key)
        else:
            hard.discard(key)
            soft.discard(key)
        w["gate_hard"] = sorted(hard)
        w["gate_soft"] = sorted(soft)
        cfg_mod.save_config(self.cfg)

    def _on_gate(self, key: str, chapter: int, summary: str):
        self.gateAsked.emit(key, chapter, summary)
        self.logModel.append("info", f"⏸ 决策门 {key}（第{chapter}章）：{summary}")
        self._console_log("gate", f"⏸ 决策门 {key}（第{chapter}章）：{summary}", num=chapter)

    @Slot(str, str)
    def resolveStepGate(self, action: str, idea: str):
        """决策条调用：action = next / return；idea 为可选的用户想法"""
        if self.orch and self._running and not self.orch.resolve_gate(action or "next", idea or ""):
            self.toast.emit("warn", "当前没有等待中的决策门")
            return
        level = "info" if action != "return" else "warn"
        suffix = f"，并附想法：{idea[:60]}" if (idea or "").strip() else ""
        act = "回退重做" if action == "return" else "继续"
        self.logModel.append(level, f"决策门已{act}{suffix}")
        # T4.3 M2：门决策镜像到 Console 对话区
        if action == "return":
            self._console_log("agent", f"↩ 已回退重做{(f'，想法：{idea[:60]}' if (idea or '').strip() else '')}")
        else:
            self._console_log("user" if (idea or "").strip() else "agent",
                              f"▶ 继续{(f'（想法：{idea[:60]}）' if (idea or '').strip() else '')}")

    # ========== Token 用量统计（插件）==========

    @Slot(result="QVariantMap")
    def usageSummary(self) -> dict:
        """聚合视图：今日/本月/全部 的 tokens、调用数、成本、按模型分组"""
        from .. import usage as _usage
        return _usage.summary(cfg_mod.load_config())

    @Slot()
    def refreshUsage(self):
        self.usageChanged.emit()
        self.tokensChanged.emit()

    # ========== 商业级运行时（封装计划 T3.x/T4.x）==========

    @Property(str, constant=True)
    def appVersion(self) -> str:
        from .. import __version__
        return __version__

    # ---- 首启向导（T3.5）----
    @Property(bool, notify=generalChanged)
    def onboarded(self) -> bool:
        if not self.proj:
            return bool(cfg_mod.load_config().get("general", {}).get("onboarded", False))
        return bool(cfg_mod.load_config().get("general", {}).get("onboarded", False))

    @Slot()
    def setOnboarded(self):
        cfg = cfg_mod.load_config()
        cfg.setdefault("general", {})["onboarded"] = True
        cfg_mod.save_config(cfg)
        self.generalChanged.emit()

    # ---- 遥测开关（T4.3，默认关）----
    @Property(bool, notify=generalChanged)
    def telemetryEnabled(self) -> bool:
        return bool((cfg_mod.load_config().get("telemetry") or {}).get("enabled", False))

    @Slot(bool)
    def setTelemetryEnabled(self, on: bool):
        cfg = cfg_mod.load_config()
        from .. import telemetry
        cfg = telemetry.set_enabled(cfg, bool(on))
        cfg_mod.save_config(cfg)
        self.generalChanged.emit()
        self.toast.emit("ok", "遥测已" + ("开启（数据仅保存在本地）" if on else "关闭"))

    # ---- 检查更新（T3.4，GitHub Releases 主通道）----
    @Slot(bool)
    def checkForUpdates(self, manual: bool):
        cfg = cfg_mod.load_config()
        u = cfg.get("updates") or {}
        if not manual and not u.get("check_on_start", True):
            return
        from .. import __version__
        url = u.get("manifest_url", "")

        def work():
            from .. import update_check
            m = update_check.check(url, __version__)
            if m:
                self.updateFound.emit(str(m.get("version", "")),
                                      str(m.get("notes", "")),
                                      str(m.get("url", "")))
            elif manual:
                self.toast.emit("ok", f"已是最新版本 v{__version__}")
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def openPath(self, path: str):
        """打开目录/文件（资源管理器或默认程序）"""
        try:
            os.startfile(path)
        except Exception as e:  # noqa: BLE001
            self.toast.emit("warn", f"无法打开: {e}")

    @Slot()
    def openLogDir(self):
        self.openPath(os.path.join(os.path.expanduser("~"), ".qianbi_novel", "logs"))

    @Slot()
    def openDataDir(self):
        self.openPath(os.path.join(os.path.expanduser("~"), ".qianbi_novel"))

    @Slot(str, str)
    def emitCrash(self, summary: str, path: str):
        """全局崩溃对话框（main.py CrashReporter 排队到主线程调用）"""
        try:
            from PySide6.QtWidgets import QMessageBox
            from PySide6.QtGui import QGuiApplication
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("千笔一文 Novel — 遇到问题")
            msg.setText("应用遇到未捕获的错误。现场已保存（含脱敏处理），已保存的稿件不受影响。")
            msg.setDetailedText(f"{summary}\n\n现场文件：{path}")
            b_logs = msg.addButton("打开日志目录", QMessageBox.ActionRole)
            b_copy = msg.addButton("复制详情", QMessageBox.ActionRole)
            msg.addButton("关闭", QMessageBox.RejectRole)
            msg.exec()
            if msg.clickedButton() is b_logs:
                self.openLogDir()
            elif msg.clickedButton() is b_copy:
                QGuiApplication.clipboard().setText(f"{summary}\n{path}")
        except Exception as e:  # noqa: BLE001
            logger.error("崩溃对话框失败: %s", e)

    # ========== Agent Console（T4.3 M1+M2：思考链留存 + 对话区落盘）==========
    # 设计依据 plan_agent_console_v3 §1.3；M3（阅读器收窄/门合并）另行排期。
    _console_thinking = None      # {(slot, stage, num): [chunk]} 实例级惰性初始化
    _console_dialogue = None      # [{ts, kind, slot, stage, num, text}]
    _console_expanded = False
    _console_rev = 0

    def _console_ensure(self):
        if self._console_thinking is None:
            self._console_thinking = {}
        if self._console_dialogue is None:
            self._console_dialogue = []

    def _on_thinking(self, slot: str, stage: str, num: int, text: str):
        """思维链增量 → 按 槽位×阶段×章 分组留存（随结束不清空，M1 痛点）"""
        self._console_ensure()
        key = (slot, stage, int(num))
        buf = self._console_thinking.setdefault(key, [])
        buf.append(text)
        if len(buf) > 800:                     # 单组环形上限，防长跑内存膨胀
            del buf[: len(buf) - 800]
        self._console_rev += 1
        self.consoleChanged.emit()

    def _console_log(self, kind: str, text: str, slot: str = "", stage: str = "", num: int = 0):
        """Console 对话区条目：内存 + pipeline_debug/console/ 会话落盘（M2）"""
        self._console_ensure()
        import datetime
        entry = {"ts": datetime.datetime.now().strftime("%m-%d %H:%M:%S"),
                 "kind": kind, "slot": slot, "stage": stage, "num": int(num),
                 "text": text}
        self._console_dialogue.append(entry)
        if len(self._console_dialogue) > 500:
            del self._console_dialogue[: len(self._console_dialogue) - 500]
        self._console_rev += 1
        self.consoleChanged.emit()
        if self.proj:
            try:
                d = os.path.join(self.proj, "pipeline_debug", "console")
                os.makedirs(d, exist_ok=True)
                path = os.path.join(d, f"session-{datetime.datetime.now():%Y%m%d}.jsonl")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:  # noqa: BLE001
                pass   # 落盘失败不影响主流程

    @Property("QVariantList", notify=consoleChanged)
    def consoleThinkingGroups(self) -> list:
        """思考链分组（M1）：[{key, slot, stage, num, text}]，当前章在前"""
        self._console_ensure()
        cur = self._cur_num
        groups = []
        for (slot, stage, num), chunks in self._console_thinking.items():
            groups.append({"key": f"{slot}|{stage}|{num}", "slot": slot, "stage": stage,
                           "num": num, "text": "".join(chunks)[-6000:],
                           "is_current": num == cur})
        groups.sort(key=lambda g: (not g["is_current"], -g["num"]))
        return groups[:40]

    @Property("QVariantList", notify=consoleChanged)
    def consoleDialogue(self) -> list:
        self._console_ensure()
        return list(self._console_dialogue[-200:])

    @Property(bool, notify=consoleChanged)
    def consoleExpanded(self) -> bool:
        return self._console_expanded

    @Slot(bool)
    def setConsoleExpanded(self, on: bool):
        if self._console_expanded != bool(on):
            self._console_expanded = bool(on)
            self.consoleChanged.emit()

    @Slot(str)
    def consoleSubmit(self, text: str):
        """Console 输入框（M3 门合并前的对话通道雏形）：
        门等待中 → 作为「带想法继续」送入当前门；否则沉淀为「下一章」想法"""
        text = (text or "").strip()
        if not text:
            return
        self._console_ensure()
        if self.orch and self._running and self.orch.resolve_gate("next", text):
            self._console_log("user", text)
            self._console_log("agent", "已作为「带想法继续」送入当前决策门")
            return
        if self.proj and not self._running:
            self.toast.emit("warn", "流水线未运行，想法已保存为「下一章」")
        elif not self.proj:
            self._console_log("agent", "当前未打开项目，内容未保存")
            return
        state = st.load_state(self.proj)
        if st.add_idea(self.proj, state, text, "next"):
            self._console_log("user", text)
            self._console_log("agent", "已沉淀为「下一章」想法（笔记面板可管理）")
            self.ideaCountChanged.emit()

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
                # 整章重写安全网：旧正文先归档为版本（重写前快照），放弃重写时可在版本历史回退
                old = project.read_file(path)
                if old.strip():
                    versions.snapshot(self.proj, num, old, "重写前备份")
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

    @Slot(str, str, str, str, str)
    def rewriteSelection(self, before: str, selected: str, after: str, idea: str, mode: str = "neighbor"):
        """AI 只改写选中段落：流式预览 → QML 应用/放弃
        mode: only=仅选中段 neighbor=带前后各一段 full=带全章 setting=全章+核心设定"""
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
        worker = SelectionRewriteWorker(self.cfg, before, selected, after, idea,
                                        mode=mode, proj=self.proj or "", parent=self)
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
        self.refreshUsage()
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
        """写作中随时提交创作想法（默认注入下一章草稿 prompt）"""
        self.submitIdeaScoped(text, "next")

    @Slot(str, str)
    def submitIdeaScoped(self, text: str, scope: str):
        """scope: next=下一章 | 通用=通用想法 | 数字=指定第N章"""
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return
        text = (text or "").strip()
        if not text:
            self.toast.emit("warn", "想法不能为空")
            return
        state = st.load_state(self.proj)
        if st.add_idea(self.proj, state, text, scope or "next"):
            self.ideaCountChanged.emit()
            label = {"next": "下一章", "通用": "通用想法"}.get(scope, f"第 {scope} 章")
            self.toast.emit("ok", f"想法已记录，将注入{label}的创作")

    # ============ 章节查看/编辑（保存驱动版本语义）============

    @Slot(int)
    def openChapter(self, num: int):
        """打开章节到编辑器（工作副本：加载磁盘内容，无未保存修改）
        正文不存在时合成空打开（路径=无标题预期文件名），供补写缺失章节
        注意：QML 端在调用前需先处理当前未保存修改（保存/放弃/取消）"""
        if not self.proj:
            return
        for n, name, path in project.list_chapters(self.proj):
            if n == num:
                self._cur_num = num
                self._chapter_path = path
                self._chapter_text = project.read_file(path)
                self._chapter_findings = []
                self.chapterTextChanged.emit()
                self.chapterFindingsChanged.emit()
                self.currentChapterChanged.emit()
                self._reset_editor_state()
                if st.is_review_stale(self.proj, st.load_state(self.proj), num):
                    self.toast.emit("warn", f"第 {num} 章审校结论已过期（正文在结论后被修改过），建议重新查验")
                return
        self._cur_num = num
        self._chapter_path = project.get_chapter_path(self.proj, num)
        self._chapter_text = ""
        self._chapter_findings = []
        self.chapterTextChanged.emit()
        self.chapterFindingsChanged.emit()
        self.currentChapterChanged.emit()
        self._reset_editor_state()
        self.toast.emit("info", f"第 {num} 章尚未写成——可直接书写，或在共写档让写作 Agent 按上下文补写")

    def _canonical_chapter_path(self, num: int, fallback: str) -> str:
        """该章号已有正文文件时返回其真实路径（防止无标题文件名造成同章双文件）"""
        if self.proj and num:
            for n, _name, path in project.list_chapters(self.proj):
                if n == num:
                    return path
        return fallback

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
        取消 / 切换章节 / 关闭 / 意外退出 都不会走到这里，因此不会产生版本
        共写档：locked 章拒绝保存；保存有变且读改节流通过 → 触发读改揣摩（review 槽）"""
        if not self._chapter_path:
            return
        if project.is_chapter_locked(self.proj, self._cur_num):
            self.toast.emit("warn", "该章已终稿锁定，请先在共写档显式解锁")
            return
        if self._cur_num and not os.path.isfile(self._chapter_path):
            self._chapter_path = self._canonical_chapter_path(self._cur_num, self._chapter_path)
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
        # 读改揣摩（M4）：共写档 + 内容有变 + 开关开 + 改动量达阈值 → review 槽读一遍
        if (self._get_cw_mode() == "cw" and self._cur_num
                and old != text and self._get_cw_stage_key() == st.STAGE_CW_PROSE):
            self._maybe_readback(old, text)

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
        self._chapter_path = project.get_chapter_path(self.proj, num)
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
                if num not in chapters:      # 正文文件缺失才用历史快照兜底（防止快照冻结旧字数）
                    words = h.get("words") or words
                state_str = "pass" if h.get("status") == "pass" else "needs_fix"
                if h.get("deslop_blocking"):
                    note = f"AI味 {h['deslop_blocking']} 阻断"
                if state_str == "needs_fix":
                    rf = (state.get("review_findings") or {}).get(str(num)) or {}
                    rb = [b for b in (rf.get("blocking") or []) if str(b).strip()]
                    if rb:
                        note = (note + " · " if note else "") + f"审校 {len(rb)} 处"
            if num in chapters and st.is_review_stale(self.proj, state, num):
                state_str = "stale"
                note = (note + " · " if note else "") + "结论已过期·待复审"
            if num == self._cur_num and self._running:
                state_str = "writing"
                note = st.STEP_LABELS.get(self._cur_step, "")
            elif num in chapters and num not in history and state_str != "stale":
                state_str = "untracked"
                note = "正文存在·未入流水线"
            elif state_str == "queued" and num in outlines:
                state_str = "outline_ready"
                note = "细纲就绪"
            elif (state_str == "queued" and num == self._cur_num
                  and num not in chapters and num not in outlines and num not in history):
                state_str = "untracked"
                note = "未写"
            items.append({"num": num, "title": title, "state": state_str,
                          "words": words, "note": note})
        self.chapterModel.set_items(items)
        self._refresh_progress()
        self.needsFixChanged.emit()

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
        self._console_log("agent", f"—— 第 {num} 章开始 ——", num=num)
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
        self.refreshUsage()
        self._refresh_progress()
        # 逐步确认模式：每章定稿后暂停（新版由决策门 G9 承担；此处仅兼容旧配置：auto 模式+step_confirm）
        if (self._running and self.orch
                and self.cfg.get("writing", {}).get("run_mode", "auto") == "auto"
                and self.cfg.get("writing", {}).get("step_confirm")):
            self.orch.pause()
            self._set_paused(True)
            self.logModel.append("info", f"第 {record.get('num')} 章已定稿（逐步确认模式）：阅读确认后点「继续」")

    def _on_finished(self, reason: str):
        self._set_running(False)
        self._set_paused(False)
        self._stopping = False
        self.stoppingChanged.emit()
        self._streaming = False
        self._stream_stage_label = ""
        self._reasoning_text = ""
        self.streamStageChanged.emit()
        self.reasoningChanged.emit()
        self.streamingChanged.emit()
        self.gateClosed.emit()   # 真机缺陷②：停止/完本后清掉残留决策条
        self._cur_num = 0
        self._cur_step = ""
        self.currentChapterChanged.emit()
        self.currentStepChanged.emit()
        self.refreshQueue()
        if reason == "done":
            self.toast.emit("ok", "全书完本")
        # 检查出问题 → 汇总待修并询问作者是否一键修复（跑完即触发）
        nf = self._needs_fix_entries()
        if nf:
            self.toast.emit("warn", f"流水线结束：{len(nf)} 章待修，已汇总到「待修」入口")
            self.needsFixReady.emit()

    def _on_failed(self, msg: str):
        self._set_running(False)
        self._set_paused(False)
        self._stopping = False
        self.stoppingChanged.emit()
        self._streaming = False
        self._stream_stage_label = ""
        self.streamStageChanged.emit()
        self.streamingChanged.emit()
        self.gateClosed.emit()   # 真机缺陷②：失败后同样清决策条
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

    # ---- 发布物料：标签 + 简介（据大纲/设定生成）----

    @Slot(result=str)
    def blurbText(self) -> str:
        """已保存的发布物料内容（设定/简介与标签.md），未生成返回空串"""
        if not self.proj:
            return ""
        return project.read_file(os.path.join(self.proj, "设定", "简介与标签.md"))

    @Slot()
    def generateBlurb(self):
        """据题材定位 + 全书大纲 后台生成标签与简介；结果经 blurbGenerated 返回并自动保存"""
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return
        if not os.path.exists(os.path.join(self.proj, "大纲", "大纲.md")):
            self.toast.emit("warn", "还没有全书大纲，先生成大纲再生成发布物料")
            return
        self.toast.emit("info", "正在生成发布标签与简介（辅助槽，约 30-60 秒）…")
        w = _BlurbWorker(self.cfg, self.proj, self)
        w.done.connect(self._on_blurb_done)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _on_blurb_done(self, ok: bool, text: str):
        self.blurbGenerated.emit(ok, text)
        if ok:
            project.write_file(os.path.join(self.proj, "设定", "简介与标签.md"), text)
            self.toast.emit("ok", "发布物料已生成并保存 → 设定/简介与标签.md")
        else:
            self.toast.emit("error", f"发布物料生成失败: {text}")

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
            chapters = len(project.list_chapters(self.proj))
            words = sum(project.count_chars(project.read_file(p))
                        for _n, _m, p in project.list_chapters(self.proj))
            size_kb = os.path.getsize(path) / 1024
            self.toast.emit("ok", f"已导出 {os.path.basename(path)}：{chapters} 章 · "
                                  f"{words} 字 · {size_kb:.0f} KB")
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

    # ============ 阅读器体系（M2 · 读者视角）============

    READER_DEFAULTS = {
        "theme": "night", "fontScale": 1.0, "lineHeight": 1.8,
        "serif": True, "paged": False,
    }

    @Slot(result="QVariantMap")
    def readerPrefs(self) -> dict:
        prefs = dict(self.READER_DEFAULTS)
        prefs.update(self.cfg.get("reader", {}))
        return prefs

    @Slot(str, "QVariant")
    def setReaderPref(self, key: str, value):
        self.cfg.setdefault("reader", {})[key] = value
        cfg_mod.save_config(self.cfg)

    # ---- 每章阅读数据（标注 / 书签 / 位置）：正文/.annotations/第X章.json ----

    def _read_store(self, proj: str, num: int) -> dict:
        path = os.path.join(proj, "正文", ".annotations", f"第{num}章.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("annotations", [])
                data.setdefault("bookmarks", [])
                data.setdefault("position", 0.0)
                return data
        except (OSError, ValueError):
            pass
        return {"annotations": [], "bookmarks": [], "position": 0.0}

    def _write_store(self, proj: str, num: int, data: dict):
        d = os.path.join(proj, "正文", ".annotations")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"第{num}章.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    @Slot(int, result="QVariantMap")
    def readStore(self, num: int) -> dict:
        if not self.proj:
            return {"annotations": [], "bookmarks": [], "position": 0.0}
        return self._read_store(self.proj, num)

    @Slot(int, str, str, str, float)
    def addAnnotation(self, num: int, kind: str, quote: str, note: str, pos: float):
        """kind: highlight_yellow / highlight_green / highlight_red / comment（同引文同类型去重）"""
        if not self.proj:
            return
        data = self._read_store(self.proj, num)
        quote = quote[:120]
        for ann in data["annotations"]:
            if ann.get("kind") == kind and ann.get("quote") == quote:
                self.toast.emit("info", "该内容已有相同标注")
                return
        data["annotations"].append({
            "kind": kind, "quote": quote, "note": (note or "").strip(),
            "pos": float(pos), "ts": datetime.datetime.now().strftime("%m-%d %H:%M"),
        })
        self._write_store(self.proj, num, data)
        self.toast.emit("ok", "批注已保存" if note else "已高亮标注")

    @Slot(int, int)
    def removeAnnotation(self, num: int, idx: int):
        if not self.proj:
            return
        data = self._read_store(self.proj, num)
        if 0 <= idx < len(data["annotations"]):
            data["annotations"].pop(idx)
            self._write_store(self.proj, num, data)

    @Slot(int, str)
    def addReaderIdea(self, num: int, text: str):
        """阅读灵感标记 → 自动进创作笔记（关联章节），注入后续创作"""
        if not self.proj:
            return
        text = (text or "").strip()
        if not text:
            self.toast.emit("warn", "灵感内容不能为空")
            return
        state = st.load_state(self.proj)
        if st.add_idea(self.proj, state, f"[第{num}章·阅读灵感] {text}", "next"):
            self.ideaCountChanged.emit()
            self.toast.emit("ok", "灵感已记入创作笔记，将注入后续章节")

    @Slot(int, float, str)
    def addBookmark(self, num: int, pos: float, label: str):
        if not self.proj:
            return
        data = self._read_store(self.proj, num)
        data["bookmarks"].append({
            "pos": float(pos), "label": (label or "").strip() or f"第{num}章书签",
            "ts": datetime.datetime.now().strftime("%m-%d %H:%M"),
        })
        self._write_store(self.proj, num, data)
        self.toast.emit("ok", "已加书签（标注面板可查看跳转）")

    @Slot(int, int)
    def removeBookmark(self, num: int, idx: int):
        if not self.proj:
            return
        data = self._read_store(self.proj, num)
        if 0 <= idx < len(data["bookmarks"]):
            data["bookmarks"].pop(idx)
            self._write_store(self.proj, num, data)

    @Slot(int, float)
    def saveReadPosition(self, num: int, pos: float):
        if self.proj:
            data = self._read_store(self.proj, num)
            data["position"] = float(max(0.0, min(1.0, pos)))
            self._write_store(self.proj, num, data)

    @Slot(result="QVariantList")
    def readerChapterList(self) -> list:
        """阅读目录：[{num, title, words}]（有正文的章节）"""
        if not self.proj:
            return []
        result = []
        for n, name, path in project.list_chapters(self.proj):
            m = re.match(r"第\d+章_?(.+)\.md", name)
            result.append({"num": n, "title": m.group(1) if m and m.group(1) else f"第{n}章",
                           "words": project.count_chars(project.read_file(path))})
        return result

    @Slot(int, result="QVariantMap")
    def readerChapter(self, num: int) -> dict:
        """阅读章节：优先磁盘已保存内容；无正文但编辑器正写此章时给工作副本/流式内容"""
        text = self.diskTextOf(num)
        if not text and num == self._cur_num and self._working_text:
            text = self._working_text
        return {"num": num, "text": text,
                "isDraft": bool(num == self._cur_num and self._editor_dirty),
                "isLive": bool(num == self._cur_num and self._streaming)}

    # ============ 创作驾驶舱（M3 · 阶段卡片）============

    @Slot(result="QVariantList")
    def stageCards(self) -> list:
        """阶段卡片：设定/大纲/细纲/正文——状态 + 产物文件 + 完成度"""
        if not self.proj:
            return []
        state = st.load_state(self.proj)
        chapters = project.list_chapters(self.proj)
        outlines = project.list_outlines(self.proj)
        setting_ok = os.path.isfile(os.path.join(self.proj, "设定", "题材定位.md"))
        outline_ok = os.path.isfile(os.path.join(self.proj, "大纲", "大纲.md"))
        total = state.get("total_chapters", 0) or len(chapters)
        stage = state.get("stage", st.STAGE_INIT)
        cur = self._cur_num if self._running else 0

        def st_of(done, active_key, active):
            if active:
                return "active"
            if done:
                return "done"
            return "pending" if stage != st.STAGE_DONE else "pending"

        return [
            {"key": "setting", "label": "核心设定", "icon": "✦",
             "status": st_of(setting_ok, st.STAGE_SETTING, self._running and stage == st.STAGE_SETTING),
             "detail": "设定/题材定位.md",
             "done": setting_ok, "file": "设定/题材定位.md" if setting_ok else ""},
            {"key": "outline", "label": "全书大纲", "icon": "❖",
             "status": st_of(outline_ok, st.STAGE_OUTLINE, self._running and stage == st.STAGE_OUTLINE),
             "detail": "大纲/大纲.md",
             "done": outline_ok, "file": "大纲/大纲.md" if outline_ok else ""},
            {"key": "ch_outline", "label": "章节细纲", "icon": "☰",
             "status": st_of(bool(outlines), st.STAGE_CH_OUTLINE, self._running and stage == st.STAGE_CH_OUTLINE),
             "detail": f"{len(outlines)} 章细纲",
             "done": bool(outlines), "count": len(outlines), "file": ""},
            {"key": "prose", "label": "正文写作", "icon": "✍",
             "status": "active" if cur else st_of(bool(chapters), st.STAGE_PROSE, False),
             "detail": f"{len(chapters)} 章 / 共 {total or '∞'} 章",
             "done": bool(chapters), "count": len(chapters), "file": ""},
        ]

    @Slot(str, str)
    def regenerateStage(self, key: str, guidance: str):
        """阶段重生成：删除阶段产物 → 点「开始」从该阶段续跑（guidance 可选注入）"""
        if self._running or not self.proj:
            self.toast.emit("warn", "请先停止流水线再重生成阶段")
            return
        guidance = (guidance or "").strip()
        try:
            if key == "setting":
                os.remove(os.path.join(self.proj, "设定", "题材定位.md"))
            elif key == "outline":
                os.remove(os.path.join(self.proj, "大纲", "大纲.md"))
                # 大纲重生成连带细纲失效（细纲依赖大纲）
                for n, path in project.list_outlines(self.proj):
                    os.remove(path)
            elif key == "ch_outline":
                nxt = project.next_chapter_num(self.proj)
                removed = 0
                for n, path in project.list_outlines(self.proj):
                    # M4 锁守卫：locked 章的细纲视为已定契约，不删除
                    if n >= nxt and not project.is_chapter_locked(self.proj, n):
                        os.remove(path)
                        removed += 1
                if removed == 0:
                    self.toast.emit("warn", "没有可重生成的细纲（后续章细纲为空）")
                    return
                self.toast.emit("ok", f"已移除 {removed} 章未写正文的细纲，点「开始」重新生成")
                return
            else:
                self.toast.emit("warn", "正文阶段请用章节面板的「重写」")
                return
        except OSError as e:
            self.toast.emit("warn", f"删除失败: {e}")
            return
        if guidance and key in ("setting", "outline"):
            # 阶段指导：暂存到 state，stage 执行时拼进 prompt（通过 pending_guidance 通道太章级化，直接写文件旁注）
            p = os.path.join(self.proj, "追踪", "阶段指导.md")
            project.write_file(p, f"# {key} 阶段重生成指导\n\n{guidance}\n")
        self.refreshQueue()
        label = {"setting": "核心设定", "outline": "全书大纲（含细纲）", "ch_outline": "细纲"}[key]
        self.toast.emit("ok", f"{label}产物已移除，点「开始」从该阶段重新生成")

    # ============ 共写档（co-write · M1：六阶段状态机 + 对话区 + 确定/打回/回看）============

    def _get_cw_mode(self) -> str:
        if not self.proj:
            return "auto"
        return st.ensure_cw(st.load_state(self.proj)).get("mode", "auto")

    def _get_cw_stage_key(self) -> str:
        if not self.proj:
            return st.STAGE_CW_PROJECT
        return st.ensure_cw(st.load_state(self.proj)).get("stage", st.STAGE_CW_PROJECT)

    def _get_cw_stage_label(self) -> str:
        return st.CW_STAGE_LABELS.get(self._get_cw_stage_key(), "")

    def _get_cw_agent(self) -> str:
        if not self._cw:
            return ""
        return self._cw.current_agent(self._cw.load())

    def _get_cw_view(self) -> str:
        return self._cw_view or self._get_cw_stage_key()

    def _get_cw_messages(self) -> list:
        if not self._cw:
            return []
        return self._cw.transcript(self._cw.load(), self._get_cw_view())

    def _get_cw_summary(self) -> dict:
        if not self._cw:
            return {"key": st.STAGE_CW_PROJECT, "label": "", "index": 0,
                    "products": [], "rollbackable": False, "canReopen": False, "reopening": False}
        return self._cw.stage_summary(self._cw.load())

    def _get_cw_stage_cards(self) -> list:
        if not self._cw:
            return []
        state = self._cw.load()
        cw = st.ensure_cw(state)
        idx = self._cw.stage_index(cw.get("stage", st.STAGE_CW_PROJECT))
        cards = []
        for i, key in enumerate(st.CW_STAGE_ORDER):
            status = "done" if i < idx else ("active" if i == idx else "pending")
            detail = " · ".join(st.CW_STAGE_PRODUCTS.get(key, []))
            if key == st.STAGE_CW_PROSE:
                detail = f"{len(project.list_chapters(self.proj))} 章正文"
            cards.append({"key": key, "label": st.CW_STAGE_LABELS.get(key, key),
                          "status": status, "detail": detail})
        return cards

    def _get_cw_unit(self) -> dict:
        if not self._cw:
            return {"start": 0, "target_end": 0, "topic": ""}
        return self._cw.unit(self._cw.load())

    def _get_cw_unit_has_outlines(self) -> bool:
        return bool(self.proj and project.list_outlines(self.proj))

    def _get_chapter_locked(self) -> bool:
        if not self.proj:
            return False
        return project.is_chapter_locked(self.proj, self._cur_num)

    def _get_cw_report_text(self) -> str:
        if not self._cw:
            return ""
        return str(st.ensure_cw(self._cw.load()).get("report", {}).get("text", ""))

    def _get_cw_report_ts(self) -> str:
        if not self._cw:
            return ""
        return str(st.ensure_cw(self._cw.load()).get("report", {}).get("ts", ""))

    def _get_cw_report_consumed(self) -> bool:
        if not self._cw:
            return False
        return bool(st.ensure_cw(self._cw.load()).get("report", {}).get("consumed", False))

    def _get_cw_preset(self) -> str:
        if not self._cw:
            return ""
        return str(st.ensure_cw(self._cw.load()).get("preset", ""))

    def _get_cw_reached_stages(self) -> list:
        """已到达的阶段（含当前）：供「打回」目标选择（排除创建项目，#5）"""
        if not self._cw:
            return []
        state = self._cw.load()
        idx = self._cw.stage_index(self._get_cw_stage_key())
        return [{"key": k, "label": st.CW_STAGE_LABELS.get(k, k)}
                for i, k in enumerate(st.CW_STAGE_ORDER)
                if i <= idx and k != st.STAGE_CW_PROJECT]

    def _cw_save_state(self, state: dict):
        st.save_state(self.proj, state)

    def _cw_refresh(self):
        self.cwModeChanged.emit()
        self.cwStageChanged.emit()
        self.cwMessagesChanged.emit()
        self.cwStreamingChanged.emit()

    def _cw_open_product(self, stage: str):
        """阶段切换：编辑器载入对应产物文件（cw_prose=当前打开章，回退最新一章）"""
        if stage == st.STAGE_CW_PROSE:
            chapters = project.list_chapters(self.proj)
            pick = None
            if self._cur_num:
                for n, _name, p in chapters:
                    if n == self._cur_num:
                        pick = (n, p)
                        break
            if pick is None and chapters:
                pick = (chapters[-1][0], chapters[-1][2])
            if pick:
                self._cur_num = pick[0]
                self._chapter_path = pick[1]
                self._chapter_text = project.read_file(pick[1])
            else:
                self._chapter_path = ""
                self._chapter_text = ""
        else:
            rels = st.CW_STAGE_PRODUCTS.get(stage, [])
            if rels:
                p = os.path.join(self.proj, rels[0])
                self._chapter_path = p if os.path.isfile(p) else ""
                self._chapter_text = project.read_file(p)
            else:
                self._chapter_path = ""
                self._chapter_text = ""
        self._chapter_findings = []
        self._reset_editor_state()
        self.chapterTextChanged.emit()
        self.chapterFindingsChanged.emit()
        self.currentChapterChanged.emit()
        self.cwLockedChanged.emit()

    # ---- 档位切换（受控：仅阶段空闲）----

    @Slot(bool)
    def setCwMode(self, on: bool):
        if self._running:
            self.toast.emit("warn", "流水线运行中不能切换档位，请先停止")
            return
        if not self.proj or not self._cw:
            return
        state = self._cw.load()
        self._cw.migrate_mode(state, bool(on))
        self._cw_save_state(state)
        self._cw_view = self._get_cw_stage_key()
        self._cw_open_product(self._get_cw_stage_key())
        self._cw_refresh()
        self.refreshQueue()
        if on:
            self.toast.emit("ok", "已切换到共写档：六阶段人机共写，每阶段讨论后点「确定」定稿")
        else:
            self.toast.emit("ok", "已切换回自动档（共写产物原样保留）")

    @Slot(str)
    def selectCwStage(self, key: str):
        """回看导航：只能回到已到达的阶段（机器阶段不动），编辑器载入对应产物"""
        if not self._cw or key not in st.CW_STAGE_ORDER:
            return
        state = self._cw.load()
        if self._cw.stage_index(key) > self._cw.stage_index(self._get_cw_stage_key()):
            self.toast.emit("warn", "该阶段还没到，先把当前阶段确定")
            return
        self._cw_view = key
        self._cw_open_product(key)
        self._cw_refresh()

    # ---- 对话（每轮输入 → 一次性 DialogueWorker）----

    @Slot(str)
    def submitCwMessage(self, text: str):
        if not self.proj or not self._cw:
            self.toast.emit("warn", "请先打开项目")
            return
        if self._get_cw_mode() != "cw":
            self.toast.emit("warn", "当前不在共写档，先切换到共写")
            return
        if self._cw_busy:
            self.toast.emit("warn", "AI 正在回复中…")
            return
        text = (text or "").strip()
        if not text:
            self.toast.emit("warn", "输入不能为空")
            return
        stage = self._get_cw_stage_key()
        if self._cw_view != stage:
            self.toast.emit("warn", "正在回看历史阶段，点当前阶段卡片回到讨论")
            return
        if stage == st.STAGE_CW_PROJECT:
            self.toast.emit("warn", "创建项目阶段请填写左侧选题表单后点「确定」")
            return
        state = self._cw.load()
        co_dialogue.transcript_append(state, stage, "user", text)
        self._cw_save_state(state)
        focus = self._cur_num if stage == st.STAGE_CW_PROSE else 0
        self._spawn_cw_dialogue(text, stage, focus)

    def _spawn_cw_dialogue(self, text: str, stage: str, focus_chapter: int = 0):
        """起一次性 DialogueWorker（QML 输入入口与主 Agent 派单共用）"""
        self._cw_reply = ""
        self._set_cw_busy(True)
        worker = co_dialogue.DialogueWorker(self.cfg, self.proj, stage, text, parent=self,
                                            focus_chapter=focus_chapter)
        worker.chunk.connect(self._on_cw_chunk)
        worker.done.connect(self._on_cw_done)
        worker.error.connect(self._on_cw_error)
        worker.finished.connect(lambda w=worker: self._release_cw_worker(w))
        self._cw_worker = worker
        worker.start()
        self.cwMessagesChanged.emit()

    def _release_cw_worker(self, w):
        if self._cw_worker is w:
            self._cw_worker = None
        if self._cw_sum_worker is w:
            self._cw_sum_worker = None
        running = ((self._cw_worker and self._cw_worker.isRunning())
                   or (self._cw_sum_worker and self._cw_sum_worker.isRunning()))
        if not running:
            self._set_cw_busy(False)

    def _set_cw_busy(self, v: bool):
        if v != self._cw_busy:
            self._cw_busy = v
            self._cw_busy_seconds = 0
            if v:
                self._cw_busy_timer.start()
            else:
                self._cw_busy_timer.stop()
            self.cwBusyChanged.emit()

    def _on_cw_busy_tick(self):
        """busy 计时（#8：让用户看到等待时长）"""
        self._cw_busy_seconds += 1
        self.cwBusyChanged.emit()

    @Slot()
    def cancelCwWorker(self):
        """取消在途共写请求（#8：中断尽力而为，结果丢弃）"""
        if not self._cw_busy:
            return
        self._cw_cancelled = True
        for w in (self._cw_worker, self._cw_sum_worker):
            if w and w.isRunning():
                w.requestInterruption()
        self._set_cw_busy(False)
        self.toast.emit("warn", "已请求取消（当前请求可能无法立即中断，结果将被丢弃）")

    def _on_cw_chunk(self, text: str):
        self._cw_reply += text
        self.cwStreamingChanged.emit()

    def _on_cw_done(self, text: str):
        self.refreshUsage()
        if self._cw_cancelled:
            self._cw_cancelled = False
            self._cw_reply = ""
            self.cwStreamingChanged.emit()
            return
        stage = self._get_cw_stage_key()
        state = self._cw.load()
        co_dialogue.transcript_append(state, stage, "agent", text)
        self._cw_save_state(state)
        self._cw_reply = ""
        self.cwMessagesChanged.emit()
        self.cwStreamingChanged.emit()

    def _on_cw_error(self, msg: str):
        self._cw_reply = ""
        self.cwStreamingChanged.emit()
        self.toast.emit("error", f"对话失败: {msg}")

    # ---- 确定（总结定稿）/ 打回 / 回看世界书 ----

    @Slot()
    def confirmCwStage(self):
        """✓ 确定（#3/#4 修复：重入锁 + 空转写拦截）"""
        if not self.proj or not self._cw:
            return
        if self._get_cw_mode() != "cw":
            return
        if self._cw_busy or self._cw_confirming:
            self.toast.emit("warn", "上一个操作还没完成，稍后再点「确定」")
            return
        self._cw_confirming = True
        try:
            stage = self._get_cw_stage_key()
            if self._cw_view != stage:
                self.toast.emit("warn", "正在回看历史阶段，回到当前阶段再确定")
                return
            if stage == st.STAGE_CW_PROJECT:
                self._confirm_cw_project()
                return
            if stage == st.STAGE_CW_PROSE:
                if not self._cur_num:
                    self.toast.emit("warn", "请先打开要确定的章节")
                    return
                _own = ""
                for _n, _name, _p in project.list_chapters(self.proj):
                    if _n == self._cur_num:
                        _own = project.read_file(_p)
                        break
                if not _own.strip():
                    self.toast.emit("warn", f"第 {self._cur_num} 章尚未写成——先完成正文再点「确定」")
                    return
                state = self._cw.load()
                supervised = st.ensure_cw(state).get("supervised", {})
                if supervised.get(str(self._cur_num)):
                    # 主 Agent 已比对过本章：确认即锁定
                    self.confirmChapterLocked()
                    return
                # 触发点①：每章定稿前先跑主 Agent 衔接比对（报告进报告区），再点确定即锁定
                if self._cw_busy:
                    self.toast.emit("warn", "AI 正在工作中…")
                    return
                self._start_cw_supervisor()
                return
            # 需要总结定稿的阶段：空转写拦截（#4）
            state = self._cw.load()
            if not co_dialogue.transcript_text(state, stage).strip():
                self.toast.emit("warn", "对话区还没有讨论内容——先和 Agent 聊几句再点「确定」")
                return
            self._set_cw_busy(True)
            worker = co_dialogue.SummarizeWorker(self.cfg, self.proj, stage, parent=self)
            worker.done.connect(self._on_cw_sum_done)
            worker.error.connect(self._on_cw_error)
            worker.finished.connect(lambda w=worker: self._release_cw_worker(w))
            self._cw_sum_worker = worker
            worker.start()
        finally:
            self._cw_confirming = False

    # ---- M3：单元细纲（单元范围/主题 + 滚动批次 + 确定细纲校验）----

    @Slot(int, int, str)
    def setCwUnitRange(self, start: int, targetEnd: int, topic: str):
        """登记单元范围/主题（±10 章约束在批次生成时校验）"""
        if not self.proj or not self._cw:
            return
        state = self._cw.load()
        self._cw.set_unit(state, int(start or 0), int(targetEnd or 0), topic or "")
        self._cw_save_state(state)
        self.cwStageChanged.emit()
        hint = ""
        if int(targetEnd or 0) and int(start or 0) > int(targetEnd or 0):
            hint = "（起始章大于目标完结章，请检查）"
        self.toast.emit("ok", f"单元已登记：第 {start} 章 ~ 第 {targetEnd} 章{hint}，点「确定」生成单元总纲")

    @Slot()
    def validateCwOutlines(self):
        """确定细纲：Agent 重读校验本批细纲衔接；无阻塞 → 自动进入正文写作"""
        if not self.proj or not self._cw:
            return
        if self._cw_busy:
            self.toast.emit("warn", "AI 正在工作中，稍后再校验")
            return
        stage = self._get_cw_stage_key()
        if stage != st.STAGE_CW_UNIT or self._cw_view != stage:
            self.toast.emit("warn", "请先回到单元细纲阶段")
            return
        nums = [n for n, _p in project.list_outlines(self.proj)]
        if not nums:
            self.toast.emit("warn", "还没有细纲可校验，先点「确定」生成单元总纲与细纲")
            return
        state = self._cw.load()
        unit = self._cw.unit(state)
        self._set_cw_busy(True)
        worker = co_dialogue.ReviewOutlinesWorker(self.cfg, self.proj, nums, unit, parent=self)
        worker.done.connect(self._on_cw_validate_done)
        worker.error.connect(self._on_cw_error)
        worker.finished.connect(lambda w=worker: self._release_cw_worker(w))
        self._cw_sum_worker = worker
        worker.start()
        self.toast.emit("info", "细纲校验中（重读衔接/世界书/正则/单元范围）…")

    def _on_cw_validate_done(self, text: str):
        from ..core.stages import parse_review_findings
        blocking, advisory = parse_review_findings(text)
        self.refreshUsage()
        state = self._cw.load()
        if blocking:
            msg = ("🔍 细纲校验发现 %d 处阻塞：\n%s\n请修改细纲（可直接编辑或对话区提出）后再次点「确定细纲」。"
                   % (len(blocking), "\n".join(f"- {b}" for b in blocking)))
            co_dialogue.transcript_append(state, st.STAGE_CW_UNIT, "agent", msg)
            self._cw_save_state(state)
            self.cwMessagesChanged.emit()
            self.toast.emit("warn", f"细纲校验未通过：{len(blocking)} 处阻塞")
            return
        co_dialogue.transcript_append(
            state, st.STAGE_CW_UNIT, "agent",
            "✅ 细纲校验通过：衔接、世界书/正则契约与单元范围均无阻塞"
            + (f"；{len(advisory)} 条建议（见上）" if advisory else "") + "。进入正文写作。")
        nxt = self._cw.advance(state)
        self._cw_save_state(state)
        self._cw_view = self._get_cw_stage_key()
        self._cw_open_product(nxt)
        self.cwMessagesChanged.emit()
        self._cw_refresh()
        self.refreshQueue()
        self.toast.emit("ok", "细纲校验通过，进入「正文写作」")

    def _start_cw_outline_batch(self, state: dict):
        """确定单元后：滚动生成下一批 5 章细纲（helper 槽，≈200 字/章）"""
        batch = self._cw.next_outline_batch(state)
        if not batch:
            self.toast.emit("info", "本单元细纲已全部生成，可直接修改或点「确定细纲」校验")
            return
        unit = self._cw.unit(state)
        self._set_cw_busy(True)
        worker = co_dialogue.OutlineBatchWorker(self.cfg, self.proj, batch, unit, parent=self)
        worker.done.connect(self._on_cw_batch_done)
        worker.error.connect(self._on_cw_error)
        worker.finished.connect(lambda w=worker: self._release_cw_worker(w))
        self._cw_worker = worker
        worker.start()

    def _on_cw_batch_done(self, outlines: list):
        self.refreshUsage()
        if self._cw_cancelled:
            self._cw_cancelled = False
            return
        state = self._cw.load()
        nums = [o[0] for o in outlines]
        co_dialogue.transcript_append(
            state, st.STAGE_CW_UNIT, "agent",
            f"✅ 本批细纲已生成：第 {nums[0]}-{nums[-1]} 章（{len(nums)} 章，≈200 字/章）。"
            "可直接在编辑器修改细纲，或对话区提出由我改；确认后点「确定细纲」校验衔接。")
        self._cw_save_state(state)
        self.cwMessagesChanged.emit()
        self.refreshQueue()
        self.toast.emit("ok", f"细纲已生成：第 {nums[0]}-{nums[-1]} 章")
        self._cw_open_product(self._get_cw_stage_key())

    # ---- M4：章节确定锁定（两级提交：保存=临时草稿 / 章节确定=终稿锁定）----

    @Slot()
    def confirmChapterLocked(self):
        """✓ 章节内容确定 = 终稿锁定：内容不再改动，编辑器只读

        两道确定性闸门，都不静默放行，都允许作者显式强过并留痕：
        ① 字数闸门：低于目标下限 → lockBlocked(kind="word")；
        ② 正则 must 契约：本地可判的规则被违反 → lockBlocked(kind="contract")。
        用户点强锁走 forceConfirmChapterLocked。契约不凌驾于作者——
        但绕过它必须留下署名记录，而不是悄悄发生。
        """
        if not self.proj or not self._cur_num:
            self.toast.emit("warn", "请先打开要锁定的章节")
            return
        if project.is_chapter_locked(self.proj, self._cur_num):
            self.toast.emit("info", "该章已终稿锁定")
            return
        prose = self._chapter_text or project.read_file(self._chapter_path or "")
        _items, blocking, verdict = gates.word_count_precheck(
            self.proj, self._cur_num, prose, self.cfg)
        if verdict:
            default = int(self.cfg.get("writing", {}).get("chapter_word_target", 3000))
            target = gates.chapter_word_target(self.proj, self._cur_num, default)
            self.lockBlocked.emit(self._cur_num, blocking[0],
                                  project.count_chars(prose), target, "word")
            return
        _c_items, c_blocking, c_verdict = mustscan.contract_precheck(
            self.proj, self._cur_num, prose)
        if c_verdict:
            self.lockBlocked.emit(self._cur_num, c_blocking[0], 0, 0, "contract")
            return
        self._do_lock_chapter(forced=False)

    @Slot()
    def forceConfirmChapterLocked(self):
        """强制锁定（用户在确认框选择「仍要锁定」）：未通过的闸门全部留审计痕

        绕过的那一条必须写进记录——否则强锁这个出口恰好藏掉了闸门要暴露的东西。
        """
        if not self.proj or not self._cur_num:
            return
        if project.is_chapter_locked(self.proj, self._cur_num):
            return
        prose = self._chapter_text or project.read_file(self._chapter_path or "")
        reasons = []
        _items, blocking, _v = gates.word_count_precheck(
            self.proj, self._cur_num, prose, self.cfg)
        reasons += list(blocking or [])
        _ci, c_blocking, _cv = mustscan.contract_precheck(self.proj, self._cur_num, prose)
        reasons += list(c_blocking or [])
        try:
            st.record_forced_lock(self.proj, st.load_state(self.proj), self._cur_num,
                                  "；".join(reasons) if reasons else "手动强锁")
        except Exception:
            pass
        self._do_lock_chapter(forced=True)

    def _do_lock_chapter(self, forced: bool = False):
        project.set_chapter_locked(self.proj, self._cur_num, True)
        self.cwLockedChanged.emit()
        self.refreshQueue()
        tag = "（强制锁定：字数未达标，已留审计痕）" if forced else ""
        self.toast.emit("ok", f"第 {self._cur_num} 章已确定（终稿锁定）{tag}：内容不再改动；"
                              "解锁后可继续编辑（终稿仍留版本历史）")
        self._maybe_backflow(self._cur_num)

    # ---- 剧情反哺：定稿正文里的新实体/新规则/伏笔变动 → 回写世界书/伏笔表 ----

    def _maybe_backflow(self, num: int, force: bool = False):
        """触发点：锁定/审校通过/补跑。新鲜度去重：正文没再改过就不重跑"""
        if not self.proj or not num:
            return
        if self._backflow_worker is not None:
            if force:
                self._backflow_queue.append(int(num))
            return
        if not force:
            try:
                if st.backflow_is_fresh(self.proj, self._cw.load(), int(num)):
                    return
            except Exception:
                pass
        self._start_backflow(int(num))

    def _start_backflow(self, num: int):
        prose = ""
        for n, _name, p in project.list_chapters(self.proj):
            if n == num:
                prose = project.read_file(p)
                break
        if not prose.strip():
            self.toast.emit("warn", f"第 {num} 章没有正文，反哺跳过")
            self._drain_backflow_queue()
            return
        worker = co_dialogue.MemoryBackflowWorker(self.cfg, self.proj, num, prose, parent=self)
        worker.done.connect(self._on_backflow_done)
        worker.error.connect(self._on_backflow_error)
        worker.finished.connect(lambda w=worker: self._release_backflow_worker(w))
        self._backflow_worker = worker
        worker.start()
        self.toast.emit("info", f"第 {num} 章剧情反哺提取中（新设定回写世界书）…")

    def _release_backflow_worker(self, w):
        if self._backflow_worker is w:
            self._backflow_worker = None

    def _on_backflow_done(self, num: int, report: str):
        self.refreshUsage()
        first_line = report.splitlines()[0] if report else f"反哺 第{num}章 完成"
        if "偏离点" in report:
            self.toast.emit("warn", f"{first_line}——存在偏离点，详见问题登记")
            try:
                state = self._cw.load()
                devs = [ln[2:].strip() for ln in report.splitlines() if ln.startswith("- ")]
                if devs:
                    items = [{"dim": "D_PLOT", "level": "marginal",
                              "text": f"[反哺偏离] {d}", "quote": "",
                              "root_layer": "ROOT_PROSE", "line": ""} for d in devs]
                    st.save_review_findings(self.proj, state, num, "ADVISORY",
                                            items, [], [it["text"] for it in items])
                    self.needsFixChanged.emit()
            except Exception:
                pass
        else:
            self.toast.emit("ok", first_line)
        self._drain_backflow_queue()

    def _on_backflow_error(self, num: int, msg: str):
        self.toast.emit("error", f"第 {num} 章反哺失败：{msg}（可稍后补跑）")
        self._drain_backflow_queue()

    def _drain_backflow_queue(self):
        while self._backflow_queue:
            nxt = self._backflow_queue.pop(0)
            if st.backflow_is_fresh(self.proj, self._cw.load(), nxt):
                continue
            self._start_backflow(nxt)
            return

    @Slot(str)
    def runBackfill(self, numsCsv: str):
        """手动补跑反哺：章号逗号分隔（如 "4,5"），跳过已新鲜登记的章"""
        if not self.proj:
            return
        nums = []
        for part in str(numsCsv or "").replace("，", ",").split(","):
            part = part.strip()
            if part.isdigit():
                nums.append(int(part))
        if not nums:
            self.toast.emit("warn", "补跑需要章号（逗号分隔），如 4,5")
            return
        have = {n for n, _name, _p in project.list_chapters(self.proj)}
        todo, missing = [], []
        state = self._cw.load()
        for n in nums:
            if n not in have:
                missing.append(n)
            elif not st.backflow_is_fresh(self.proj, state, n):
                todo.append(n)
        if missing:
            self.toast.emit("warn", "这些章没有正文文件：" + "、".join(map(str, missing)))
        if not todo:
            self.toast.emit("info", "所选章节均已反哺且正文未再改动，无需补跑")
            return
        self._backflow_queue.extend(n for n in todo if n not in self._backflow_queue)
        if self._backflow_worker is None:
            self._drain_backflow_queue()
        self.toast.emit("info", f"反哺补跑已排队：{len(todo)} 章（后台串行）")

    @Slot()
    def unlockChapter(self):
        """显式解锁：唯一放行通道"""
        if not self.proj or not self._cur_num:
            return
        if project.attempt_unlock(self.proj, self._cur_num):
            self.cwLockedChanged.emit()
            self.refreshQueue()
            self.toast.emit("ok", f"第 {self._cur_num} 章已解锁（原终稿仍在版本历史）")
        else:
            self.toast.emit("info", "该章未锁定")

    @Slot()
    def readbackChapter(self):
        """手动「读一遍」：通读当前章改动，揣摩意图（无视改动量阈值）"""
        if not self.proj or not self._cur_num or not self._chapter_path:
            return
        if self._cw_busy:
            self.toast.emit("warn", "AI 正在工作中…")
            return
        self._start_readback(project.read_file(self._chapter_path), self._chapter_text)

    def _maybe_readback(self, old: str, new: str):
        """保存有变 → 读改节流检查（readback_on_save 默认开 + readback_min_diff 阈值）"""
        w = self.cfg.get("writing", {})
        if not w.get("readback_on_save", True) or self._cw_busy:
            return
        diff_len = sum(len(d.get("text", "")) for d in versions.diff_texts(old, new)
                        if d.get("op") in ("del", "add"))
        min_diff = int(w.get("readback_min_diff", 200) or 0)
        if min_diff and diff_len < min_diff:
            return
        self._start_readback(old, new)

    def _start_readback(self, old: str, new: str):
        self._set_cw_busy(True)
        worker = co_dialogue.ReadbackWorker(self.cfg, self.proj, self._cur_num, old, new, parent=self)
        worker.done.connect(self._on_cw_readback_done)
        worker.error.connect(self._on_cw_error)
        worker.finished.connect(lambda w=worker: self._release_cw_worker(w))
        self._cw_worker = worker
        worker.start()

    def _on_cw_readback_done(self, text: str):
        self.refreshUsage()
        state = self._cw.load()
        co_dialogue.transcript_append(state, st.STAGE_CW_PROSE, "agent", "（读改揣摩）" + text)
        self._cw_save_state(state)
        self.cwMessagesChanged.emit()
        self.toast.emit("ok", "读改揣摩完成（已进对话区）")

    # ---- 读改节流设置（设置面板）----

    @Slot(bool)
    def setReadbackOnSave(self, on: bool):
        self.cfg.setdefault("writing", {})["readback_on_save"] = bool(on)
        cfg_mod.save_config(self.cfg)
        self.cwLockedChanged.emit()
        self.toast.emit("ok", on and "读改揣摩已开启（保存有变且达阈值时触发）" or "读改揣摩已关闭（可手动「读一遍」）")

    @Slot(int)
    def setReadbackMinDiff(self, v: int):
        self.cfg.setdefault("writing", {})["readback_min_diff"] = max(0, int(v))
        cfg_mod.save_config(self.cfg)
        self.cwLockedChanged.emit()
        self.toast.emit("ok", f"读改最小改动量阈值 = {max(0, int(v))} 字（低于不触发；0=每次都触发）")

    # ---- M5：主 Agent（Supervisor）——定稿前衔接比对 + 世界书变更影响提示 ----

    def _start_cw_supervisor(self):
        self._set_cw_busy(True)
        # 工作副本优先：定稿时编辑器未保存内容（_working_text）才是「待定稿」，
        # _chapter_text 是磁盘基准，只传它会在未保存时拿旧稿
        editor_text = self._working_text or self._chapter_text if self._cur_num > 0 else ""
        worker = co_dialogue.SupervisorWorker(self.cfg, self.proj, self._cur_num, parent=self,
                                              chapter_text=editor_text)
        worker.done.connect(self._on_cw_supervisor_done)
        worker.error.connect(self._on_cw_error)
        worker.finished.connect(lambda w=worker: self._release_cw_worker(w))
        self._cw_worker = worker
        worker.start()
        self.toast.emit("info", f"主 Agent 正在做第 {self._cur_num} 章定稿前衔接比对（review 槽）…")

    def _on_cw_supervisor_done(self, text: str):
        import datetime as _dt
        self.refreshUsage()
        num = self._cur_num
        state = self._cw.load()
        cw = st.ensure_cw(state)
        cw.setdefault("supervised", {})[str(num)] = _dt.datetime.now().strftime("%m-%d %H:%M")
        cw["report"] = {"ts": _dt.datetime.now().strftime("%m-%d %H:%M"),
                        "num": num, "text": text}
        if self._cw_cancelled:
            # 已取消：报告照常落盘，但不触发自动派活
            self._cw_cancelled = False
            self._cw_save_state(state)
            self.cwReportChanged.emit()
            return
        needs_fix, directive = co_dialogue.parse_supervisor_report(text)
        auto_fix = cw.setdefault("auto_fix", {})
        used = int(auto_fix.get(str(num), 0))
        # 全自动流转：需调整 + 有改写指令 + 本章自动轮次未超上限（1 次/章，防互改死循环）
        if needs_fix and directive and used < 1:
            auto_fix[str(num)] = used + 1
            self._cw_save_state(state)
            self.cwReportChanged.emit()
            self.toast.emit("info", f"主 Agent 判定第 {num} 章需调整，已自动派写作 Agent 改写")
            QTimer.singleShot(0, lambda n=num, d=directive, ts=cw["report"]["ts"]:
                              self._dispatch_cw_rewrite(n, d, report_ts=ts))
            return
        self._cw_save_state(state)
        self.cwReportChanged.emit()
        if needs_fix:
            reason = "改写指令缺失" if not directive else "已达自动轮次上限（1 次/章）"
            self.toast.emit("warn", f"主 Agent 判定第 {num} 章需调整（{reason}）——报告区可手动派给写作 Agent")
            return
        self.toast.emit("ok", f"主 Agent 衔接比对完成（第 {num} 章，见报告区）"
                              "——确认无问题再点「确定」锁定")

    def _dispatch_cw_rewrite(self, num: int, directive: str, report_ts: str = "",
                             _retry: int = 0):
        """派写作 Agent 按指令改写（对话区可见；产物仍走原「采纳/保存」人工落点）

        幂等守卫：首次进入（_retry==0）即认领报告（consumed 落盘）——自动链与手动
        按钮谁先进入谁消费，重试窗口内的第二次进入见 consumed 即放弃，杜绝重复派单。
        """
        if _retry == 0:
            if not self._cw:
                return
            state = self._cw.load()
            cw = st.ensure_cw(state)
            report = cw.get("report") or {}
            if report.get("consumed"):
                self.toast.emit("info", f"第 {num} 章的报告已派发过，不重复派单")
                return
            if report_ts and report.get("ts") != report_ts:
                self.toast.emit("warn", f"报告已被新一轮比对覆盖，派单取消（第 {num} 章）")
                return
            report["consumed"] = True
            cw["report"] = report
            self._cw_save_state(state)
            self.cwReportChanged.emit()
        if self._cw_worker is not None:
            # supervisor finished 尚未释放 worker：短延迟重试（最多 ~2s）
            if _retry < 20:
                QTimer.singleShot(100, lambda: self._dispatch_cw_rewrite(
                    num, directive, report_ts=report_ts, _retry=_retry + 1))
            else:
                self.toast.emit("warn", f"自动派单失败：worker 未释放（第 {num} 章），请在报告区手动派")
            return
        if self._get_cw_mode() != "cw" or self._get_cw_stage_key() != st.STAGE_CW_PROSE:
            self.toast.emit("warn", f"自动派单跳过：当前不在共写正文阶段（第 {num} 章）")
            return
        text = f"（主 Agent 派单）请按以下指令改写第 {num} 章：{directive}"
        state = self._cw.load()
        co_dialogue.transcript_append(state, st.STAGE_CW_PROSE, "user", text)
        self._cw_save_state(state)
        self._spawn_cw_dialogue(text, st.STAGE_CW_PROSE, focus_chapter=num)

    @Slot()
    def dispatchCwReport(self):
        """报告区手动派活（不受自动轮次限制）：按最新报告的【改写指令】派写作 Agent

        与自动链共用 _dispatch_cw_rewrite 的认领守卫：已消费的报告不再重派。
        """
        if not self._cw:
            return
        if self._cw_busy:
            self.toast.emit("warn", "AI 正在工作中，稍后再派")
            return
        state = self._cw.load()
        report = st.ensure_cw(state).get("report") or {}
        num = int(report.get("num") or 0)
        _needs_fix, directive = co_dialogue.parse_supervisor_report(report.get("text", ""))
        if num <= 0 or not directive:
            self.toast.emit("warn", "没有可派单的报告/改写指令")
            return
        self._dispatch_cw_rewrite(num, directive, report_ts=str(report.get("ts", "")))

    def _cw_worldbook_changed_notice(self, state: dict) -> bool:
        """触发点②：世界书变更后影响提示（不发 LLM）；locked 章建议显式解锁后重核"""
        locked = [n for n, _name, _p in project.list_chapters(self.proj)
                  if project.is_chapter_locked(self.proj, n)]
        cw = st.ensure_cw(state)
        if locked:
            names = "、".join(f"第 {n} 章" for n in locked[:3])
            cw["report"] = {"ts": "世界书变更", "num": 0,
                            "text": f"⚠️ 世界书/正则已修订写回。已锁定章节不会自动修改：影响 {names}，"
                                    "建议显式解锁后重核衔接（解锁前终稿仍留版本历史）。"}
        else:
            cw["report"] = {"ts": "世界书变更", "num": 0,
                            "text": "ℹ️ 世界书/正则已修订写回；未锁定章节将按新契约续写。"}
        return bool(locked)

    @Slot()
    def clearCwReport(self):
        if not self._cw:
            return
        state = self._cw.load()
        st.ensure_cw(state)["report"] = {}
        self._cw_save_state(state)
        self.cwReportChanged.emit()

    # ---- M6：共写档手动查验（去AI味 / 审校；结果不落盘）----

    @Slot()
    def deslopCwProse(self):
        """共写正文手动去AI味：扫描 + 改写进编辑器工作副本（保存才落盘）"""
        self._start_cw_prose_check("deslop")

    @Slot()
    def reviewCwProse(self):
        """共写正文手动六维审校：结果登记 review_findings，复用问题对话框/待修汇总"""
        self._start_cw_prose_check("review")

    def _start_cw_prose_check(self, mode: str):
        if not self.proj or not self._cw:
            return
        if self._get_cw_mode() != "cw" or self._get_cw_stage_key() != st.STAGE_CW_PROSE:
            self.toast.emit("warn", "手动查验只在共写正文阶段可用")
            return
        if self._cw_busy:
            self.toast.emit("warn", "AI 正在工作中，稍后再试")
            return
        if self._cur_num <= 0:
            self.toast.emit("warn", "请先打开要查验的章节")
            return
        text = self._working_text or self._chapter_text
        if not text.strip():
            self.toast.emit("warn", f"第 {self._cur_num} 章没有正文可查验")
            return
        num = self._cur_num
        self._cw_reply = ""
        self._set_cw_busy(True)
        worker = co_dialogue.CwProseCheckWorker(self.cfg, self.proj, num, text,
                                                mode=mode, parent=self)
        worker.chunk.connect(self._on_cw_chunk)
        if mode == "deslop":
            worker.done.connect(lambda _t, n=num: self._on_cw_deslop_done(n))
        else:
            worker.done.connect(lambda t, n=num: self._on_cw_review_done(t, n))
        worker.error.connect(self._on_cw_error)
        worker.finished.connect(lambda w=worker: self._release_cw_worker(w))
        self._cw_worker = worker
        worker.start()
        label = "去AI味改写" if mode == "deslop" else "六维审校"
        self.toast.emit("info", f"正在对第 {num} 章做{label}…")

    def _on_cw_deslop_done(self, num: int):
        self.refreshUsage()
        if self._cw_cancelled:
            self._cw_cancelled = False
            self._cw_reply = ""
            self.cwStreamingChanged.emit()
            return
        w = self._cw_worker
        self._cw_reply = ""
        self.cwStreamingChanged.emit()
        if w is None or not w.result_text.strip():
            return
        if not w.changed:
            self.toast.emit("ok", f"第 {num} 章扫描干净，无 AI 味问题")
            return
        if self._cur_num != num:
            self.toast.emit("warn", f"第 {num} 章去味完成，但你已切章——结果已丢弃，请回该章重跑")
            return
        b0, a0 = w.before_counts
        b1, a1 = w.after_counts
        self.cwProsePolished.emit(w.result_text)
        if b1:
            self.toast.emit("warn", f"去味完成：阻断 {b0}→{b1} / 建议 {a0}→{a1}（复扫仍有阻断，可再点一次）")
        else:
            self.toast.emit("ok", f"去味完成：阻断 {b0}→0 / 建议 {a0}→{a1}——已进编辑器，点「保存」才落盘")

    def _on_cw_review_done(self, text: str, num: int):
        self.refreshUsage()
        if self._cw_cancelled:
            self._cw_cancelled = False
            self._cw_reply = ""
            self.cwStreamingChanged.emit()
            return
        from ..core import stages as stages_mod
        self._cw_reply = ""
        self.cwStreamingChanged.emit()
        if not text.strip():
            return
        # 引证验真：假引证条目降级（编造引证不得进待修登记；盘上正文为空则跳过验真）
        prose = project.read_file(project.get_chapter_path(self.proj, num))
        v2 = stages_mod.parse_final_review_v2(text)
        if prose.strip():
            v2 = stages_mod.verify_review_quotes(prose, v2)
        if not v2["verdict"]:   # v1 兜底解析（与 ChapterRepairWorker._review_v2 同款）
            fb, fa = stages_mod.parse_review_findings(text)
            v2["blocking"] = v2["blocking"] or fb
            v2["advisory"] = v2["advisory"] or fa
        state = self._cw.load()
        # save_review_findings 内部已 save_state 落盘，无需二次写入
        st.save_review_findings(self.proj, state, num, v2["verdict"] or "REJECT",
                                v2["items"], v2["blocking"], v2["advisory"])
        self.needsFixChanged.emit()
        if str(v2["verdict"]).startswith("PASS") and not v2["blocking"]:
            self._maybe_backflow(num)
        if not v2["blocking"] and not v2["items"]:
            self.toast.emit("ok", f"第 {num} 章审校通过，无登记问题")
            return
        self.toast.emit("warn", f"第 {num} 章审校完成：阻断 {len(v2['blocking'])} / 建议 {len(v2['advisory'])}（详见问题对话框）")
        self.showReviewIssues(num)

    def _confirm_cw_project(self):
        state = self._cw.load()
        info = project.read_idea_info(self.proj)
        if not info["idea"]:
            self.toast.emit("warn", "选题信息为空：请先在左侧填写灵感，或打开书架重新立项")
            return
        # 创建项目 = 选预设/自定义主题 + 写选题信息（表单已写则原样保留）
        project.write_idea_info(self.proj, info["genre"], info["platform"],
                                info["idea"], info["total_words_wan"])
        cw = st.ensure_cw(state)
        if cw.get("preset"):
            state["genre_preset"] = cw["preset"]
        self._cw.advance(state)
        self._cw_save_state(state)
        self._cw_view = self._get_cw_stage_key()
        self._cw_open_product(st.STAGE_CW_CORE)
        self._cw_refresh()
        self.toast.emit("ok", "项目创建完成，进入「核心设定」：与设定 Agent 讨论后点确定")

    @Slot(str, str, str, int)
    def saveCwIdeaInfo(self, genre: str, platform: str, idea: str, totalWan: int):
        """共写档创建项目表单：写选题信息（确定前的可编辑阶段）"""
        if not self.proj:
            return
        project.write_idea_info(self.proj, (genre or "").strip(),
                                (platform or "").strip() or "番茄",
                                (idea or "").strip(), int(totalWan or 0))
        self._book_meta = " · ".join(p for p in [(genre or "").strip(),
                                                 (platform or "").strip() or "番茄"] if p)
        self.bookMetaChanged.emit()
        self.toast.emit("ok", "选题信息已保存，点「确定」进入核心设定")

    @Slot(str)
    def setCwPreset(self, preset_id: str):
        """共写档选题表单：选用题材预设（写入 state['cw']['preset'] 与 genre_preset）"""
        if not self.proj or not self._cw:
            return
        state = self._cw.load()
        st.ensure_cw(state)["preset"] = preset_id or ""
        if preset_id:
            state["genre_preset"] = preset_id
        self._cw_save_state(state)
        self.cwStageChanged.emit()   # 刷新预设 chips 选中态
        from .. import presets as genre_presets
        name = genre_presets.load_preset(preset_id).get("name", "通用") if preset_id else "通用（无预设）"
        self.toast.emit("ok", f"共写档选用预设「{name}」（仅作参考，不锁定）")

    def _on_cw_sum_done(self, text: str):
        self.refreshUsage()
        if self._cw_cancelled:
            self._cw_cancelled = False
            return
        stage = self._get_cw_stage_key()
        state = self._cw.load()
        product, handoff = co_dialogue.build_handoff(stage, text)
        if not product.strip():
            self.toast.emit("error", "总结产物为空，请在对话区继续讨论后重试")
            return
        # 落盘该阶段产物（世界书/正则按小节拆分）
        self._write_cw_products(stage, product)
        # 交接块存 state（唯一属主 = build_handoff）
        co_dialogue.store_handoff(state, stage, handoff)
        if not handoff:
            self.toast.emit("warn", "模型未输出「→ 下阶段交接」小节，下一阶段上下文将不完整")
        # 回看回边：写回世界书/正则后返回原阶段；cw_unit 确定后滚动生成细纲；否则前进
        if st.ensure_cw(state).get("reopening"):
            ret = self._cw.confirm_reopen_return(state)
            self.toast.emit("ok", "世界书/正则已写回，返回「%s」阶段" % st.CW_STAGE_LABELS.get(ret, ret))
            if self._cw_worldbook_changed_notice(state):
                self.toast.emit("warn", "世界书已变更：已锁定章节不会自动修改，建议解锁重核（见报告区）")
        elif stage == st.STAGE_CW_UNIT:
            self.toast.emit("ok", "「单元细纲」已确定定稿，正在滚动生成下一批 5 章细纲…")
        else:
            nxt = self._cw.advance(state)
            self.toast.emit("ok", "「%s」已确定定稿，进入「%s」"
                            % (st.CW_STAGE_LABELS.get(stage, stage), st.CW_STAGE_LABELS.get(nxt, nxt)))
        self._cw_save_state(state)
        self._cw_view = self._get_cw_stage_key()
        self._cw_open_product(self._get_cw_stage_key())
        self._cw_refresh()
        self.cwReportChanged.emit()
        self.refreshQueue()
        if stage == st.STAGE_CW_UNIT and not st.ensure_cw(state).get("reopening"):
            self._start_cw_outline_batch(state)

    def _write_cw_products(self, stage: str, product: str):
        """按阶段落盘产物：core→题材定位 / outline→大纲 / worldbook→世界书+正则 / unit→单元总纲"""
        if stage == st.STAGE_CW_WORLDBOOK:
            # 世界书全文 + 正则段拆分（「## 正则」小节独立成 设定/正则.md）
            wb, regex_part = project.split_worldbook_product(product)
            project.write_file(os.path.join(self.proj, "设定", "世界书.md"), wb)
            project.write_file(os.path.join(self.proj, "设定", "正则.md"),
                               regex_part or "## 正则（逻辑约束规则集）\n（确定时未拆分出独立正则段，见世界书）")
            return
        for rel in st.CW_STAGE_PRODUCTS.get(stage, []):
            project.write_file(os.path.join(self.proj, rel), product)

    @Slot()
    def rollbackCwStage(self):
        if not self.proj or not self._cw:
            return
        if self._cw_busy:
            self.toast.emit("warn", "AI 正在回复中，稍后再打回")
            return
        stage = self._get_cw_stage_key()
        if self._cw_view != stage:
            self.toast.emit("warn", "回到当前阶段再打回")
            return
        self._rollback_to(stage)

    @Slot(str)
    def rollbackCwStageTo(self, key: str):
        """打回到指定已到达阶段（#5：支持跨阶段打回）"""
        if not self.proj or not self._cw:
            return
        if self._cw_busy:
            self.toast.emit("warn", "AI 正在回复中，稍后再打回")
            return
        reached = {r["key"] for r in self._get_cw_reached_stages()}
        if key not in reached:
            self.toast.emit("warn", "该阶段不可打回")
            return
        self._rollback_to(key)

    def _rollback_to(self, stage: str):
        state = self._cw.load()
        result = self._cw.rollback(state, stage)
        self._cw_save_state(state)
        self._cw_view = stage
        self._cw_open_product(stage)
        self._cw_refresh()
        self.refreshQueue()
        n = len(result.get("archived", []))
        self.toast.emit("warn", f"「{st.CW_STAGE_LABELS.get(stage, stage)}」已打回，"
                        + (f"级联失效并归档 {n} 个下游产物" if n else "本阶段产物将重议"))

    @Slot()
    def reopenCwWorldbook(self):
        """回看世界书（软切）：cw_unit / cw_prose 阶段入口，不级联删除"""
        if not self.proj or not self._cw:
            return
        state = self._cw.load()
        if not self._cw.can_reopen(state):
            self.toast.emit("warn", "当前阶段不能回看世界书")
            return
        self._cw.reopen(state)
        self._cw_save_state(state)
        self._cw_view = self._get_cw_stage_key()
        self._cw_open_product(st.STAGE_CW_WORLDBOOK)
        self._cw_refresh()
        self.toast.emit("ok", "已回看世界书（软切，下游产物保留）：修订后点「确定」写回并返回原阶段")

    @Slot(str)
    def saveCwProduct(self, text: str):
        """共写档产物保存（编辑器直接改产物后保存修改：不走版本快照）"""
        if not self._chapter_path or not self.proj:
            return
        if self._cur_num and project.is_chapter_locked(self.proj, self._cur_num):
            self.toast.emit("warn", "该章已终稿锁定，请先显式解锁")
            return
        if self._cur_num and not os.path.isfile(self._chapter_path):
            self._chapter_path = self._canonical_chapter_path(self._cur_num, self._chapter_path)
        project.write_file(self._chapter_path, text or self._chapter_text)
        self._chapter_text = text or self._chapter_text
        self._reset_editor_state()
        self.toast.emit("ok", f"已保存 {os.path.basename(self._chapter_path)}")
        self.refreshQueue()

    # ============ 创作笔记（M3 · 想法 CRUD + 全局写作偏好）============

    @Slot(result="QVariantList")
    def ideasList(self) -> list:
        if not self.proj:
            return []
        state = st.load_state(self.proj)
        return list(reversed(st.norm_ideas(state)))   # 新的在前

    @Slot(str)
    def removeIdea(self, idea_id: str):
        if not self.proj:
            return
        state = st.load_state(self.proj)
        ideas = st.norm_ideas(state)
        state["pending_ideas"] = [it for it in ideas if it.get("id") != idea_id]
        st.save_state(self.proj, state)
        self.ideaCountChanged.emit()

    @Slot(str, str, str)
    def updateIdea(self, idea_id: str, text: str, scope: str):
        if not self.proj:
            return
        state = st.load_state(self.proj)
        for it in st.norm_ideas(state):
            if it.get("id") == idea_id:
                if (text or "").strip():
                    it["text"] = text.strip()
                it["scope"] = scope or it.get("scope", "next")
                it["status"] = "pending"
                break
        st.save_state(self.proj, state)
        self.ideaCountChanged.emit()
        self.toast.emit("ok", "想法已更新")

    @Slot(str)
    def markIdeaApplied(self, idea_id: str):
        if not self.proj:
            return
        state = st.load_state(self.proj)
        for it in st.norm_ideas(state):
            if it.get("id") == idea_id:
                it["status"] = "applied"
                break
        st.save_state(self.proj, state)
        self.ideaCountChanged.emit()

    @Slot(result="QVariantMap")
    def writingPrefs(self) -> dict:
        w = self.cfg.get("writing", {})
        return {"stylePref": w.get("style_pref", ""), "taboos": w.get("taboos", ""),
                "pacePref": w.get("pace_pref", ""),
                "stepConfirm": bool(w.get("step_confirm"))}

    @Slot(str, str, str)
    def saveGlobalPrefs(self, style: str, taboos: str, pace: str):
        """全局写作偏好：独立保存，注入所有章节正文 prompt（作者不改代码调全书文风）"""
        w = self.cfg.setdefault("writing", {})
        w["style_pref"] = (style or "").strip()
        w["taboos"] = (taboos or "").strip()
        w["pace_pref"] = (pace or "").strip()
        cfg_mod.save_config(self.cfg)
        self.toast.emit("ok", "全局写作偏好已保存，将从下一章开始注入")

    @Slot(result="QVariantList")
    def qualityTrend(self) -> list:
        """质量历史趋势：近 20 章 [{num, words, blocking, advisory, status}]"""
        if not self.proj:
            return []
        state = st.load_state(self.proj)
        hist = sorted(state.get("history", []), key=lambda h: h.get("num", 0))[-20:]
        return [{"num": h.get("num", 0), "words": h.get("words", 0),
                 "blocking": (h.get("deslop_blocking", 0) or 0) + (h.get("review_blocking", 0) or 0),
                 "advisory": h.get("deslop_advisory", 0) or 0,
                 "status": h.get("status", "")} for h in hist]

    # ============ 数据与项目管理体系（M4）============

    def _zip_backup(self) -> str:
        import zipfile
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(os.path.dirname(self.proj.rstrip("/\\")),
                           f"{os.path.basename(self.proj)}_backup_{ts}.zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(self.proj):
                for fn in files:
                    p = os.path.join(root, fn)
                    zf.write(p, os.path.relpath(p, self.proj))
        return out

    @Slot(result=str)
    def backupProject(self) -> str:
        """一键项目 zip 备份 → 项目同级目录（含设定/大纲/正文/追踪/版本/状态）"""
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return ""
        try:
            out = self._zip_backup()
            self.cfg.setdefault("backup", {})["last"] = datetime.date.today().isoformat()
            cfg_mod.save_config(self.cfg)
            self.toast.emit("ok", f"项目已备份：{os.path.basename(out)}（{os.path.getsize(out) // 1024} KB）")
            return out
        except Exception as e:  # noqa: BLE001
            self.toast.emit("error", f"备份失败: {e}")
            return ""

    def _maybe_auto_backup(self):
        """每日自动备份（设置开启后，打开项目时检查，一天最多一次）"""
        b = self.cfg.get("backup", {})
        if not b.get("auto"):
            return
        if b.get("last") == datetime.date.today().isoformat():
            return
        try:
            out = self._zip_backup()
            b["last"] = datetime.date.today().isoformat()
            cfg_mod.save_config(self.cfg)
            self.logModel.append("ok", f"每日自动备份完成：{os.path.basename(out)}")
        except Exception as e:  # noqa: BLE001
            self.logModel.append("warn", f"自动备份失败: {e}")

    @Slot(bool)
    def setAutoBackup(self, on: bool):
        self.cfg.setdefault("backup", {})["auto"] = bool(on)
        cfg_mod.save_config(self.cfg)
        self.toast.emit("ok", on and "已开启每日自动备份（打开项目时执行）" or "已关闭自动备份")

    @Slot(result=bool)
    def autoBackupEnabled(self) -> bool:
        return bool(self.cfg.get("backup", {}).get("auto"))

    @Slot(result="QVariantMap")
    def statsSummary(self) -> dict:
        """统计面板：章节数/全书字数/平均/今日增量/本周增量/累计 token/成本"""
        if not self.proj:
            return {}
        chapters = project.list_chapters(self.proj)
        words = 0
        for _n, _name, path in chapters:
            words += project.count_chars(project.read_file(path))
        # 增量：按 history 时间戳聚合当日/当周定稿字数
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())
        today_words = week_words = 0
        for h in st.load_state(self.proj).get("history", []):
            ts = h.get("ts", "")
            try:
                d = datetime.datetime.strptime(ts[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            w = h.get("words", 0) or 0
            if d == today:
                today_words += w
            if d >= week_start:
                week_words += w
        return {
            "chapters": len(chapters), "words": words,
            "avgWords": words // len(chapters) if chapters else 0,
            "todayWords": today_words, "weekWords": week_words,
            "tokens": self._get_tokens(), "cost": self._get_cost_text(),
        }

    @Slot(bool)
    def setStepConfirm(self, on: bool):
        """运行模式切换：逐步确认（每章定稿后暂停等人确认）/ 自动续写"""
        self.cfg.setdefault("writing", {})["step_confirm"] = bool(on)
        cfg_mod.save_config(self.cfg)
        self.toast.emit("ok", on and "已切换为逐步确认：每章定稿后暂停等你确认"
                        or "已切换为自动续写")

    @Slot(result=bool)
    def stepConfirmEnabled(self) -> bool:
        return bool(self.cfg.get("writing", {}).get("step_confirm"))


    # ============ 题材预设（主干题材无关，题材差异走预设层）============

    @Slot(result="QVariantList")
    def genrePresets(self) -> list:
        from .. import presets as genre_presets
        return genre_presets.list_presets()

    @Slot(result=str)
    def projectPreset(self) -> str:
        if not self.proj:
            return ""
        return st.load_state(self.proj).get("genre_preset", "")

    @Slot(str)
    def setProjectPreset(self, preset_id: str):
        """切换题材预设：随时可切，下一章生成生效（正文/细纲/审校三处注入）"""
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return
        from .. import presets as genre_presets
        state = st.load_state(self.proj)
        state["genre_preset"] = preset_id or ""
        st.save_state(self.proj, state)
        name = genre_presets.load_preset(preset_id).get("name", "通用") if preset_id else "通用（无预设）"
        self.toast.emit("ok", f"题材预设已切换为「{name}」，下一章生效")

    @Slot(str, result="QVariantMap")
    def importGenrePreset(self, path: str) -> dict:
        """导入预设文件（json）到用户预设目录"""
        from .. import presets as genre_presets
        if path.startswith("file:///"):
            from PySide6.QtCore import QUrl
            path = QUrl(path).toLocalFile()
        result = genre_presets.import_preset(path)
        self.toast.emit("ok" if result["ok"] else "warn", result["msg"])
        return result

    # ---- v2 题材预设库增强（plan v2 模块 A）----

    @Slot(result="QVariantList")
    def presetList(self) -> list:
        """v2 预设列表（含 v2 stage_hints 标记，供独立面板用）"""
        from .. import presets as genre_presets
        result = []
        for p in genre_presets.list_presets():
            data = genre_presets.load_preset(p["id"]) if p["id"] else {}
            result.append({
                "id": p["id"],
                "name": p["name"],
                "description": p.get("description", ""),
                "builtin": p.get("builtin", False),
                "version": data.get("version", 1),
                "genre": data.get("genre", ""),
                "has_stage_hints": bool(data.get("stage_hints")),
                "stages_with_hints": [
                    k for k, v in (data.get("stage_hints") or {}).items() if v
                ],
            })
        return result

    @Slot(str, result="QVariantMap")
    def presetDetails(self, preset_id: str) -> dict:
        """v2 预设详情：含 6 阶段 hint + v1 共享字段（独立面板预览用）"""
        from .. import presets as genre_presets
        if not preset_id:
            return {"id": "", "name": "通用（无预设）", "fields": {},
                    "stage_hints": {}, "stage_params": {}, "sampling": {}}
        p = genre_presets.load_preset(preset_id)
        if not p:
            return {"id": preset_id, "name": "(未找到)", "fields": {},
                    "stage_hints": {}, "stage_params": {}, "sampling": {}}
        # v1 共享字段
        fields = {}
        for key, label in genre_presets.PRESET_FIELDS:
            val = (p.get(key) or "").strip()
            if val:
                fields[key] = {"label": label, "value": val}
        note = genre_presets.author_note(preset_id)
        if note:
            fields["author_note"] = {"label": "作者按（正文 prompt 近端注入）", "value": note}
        # v2 stage hints
        hints = p.get("stage_hints") or {}
        stage_hints = {}
        for stage_key, stage_label in genre_presets.STAGE_HINT_KEYS:
            val = (hints.get(stage_key) or "").strip()
            if val:
                stage_hints[stage_key] = {"label": stage_label, "value": val}
        return {
            "id": preset_id,
            "name": p.get("name", preset_id),
            "description": p.get("description", ""),
            "version": p.get("version", 1),
            "genre": p.get("genre", ""),
            "fields": fields,
            "stage_hints": stage_hints,
            "stage_params": self._stage_param_view(preset_id),
            "sampling": self._sampling_view(preset_id),
        }

    @staticmethod
    def _sampling_view(preset_id: str) -> dict:
        """全书采样基线展示视图：不分相位的那层打底覆盖（阶段档压它，显式实参压两者）"""
        from .. import presets as genre_presets
        base = genre_presets.sampling(preset_id)
        return {k: {"label": genre_presets.SAMPLING_LABELS.get(k, k), "value": v}
                for k, v in base.items()}

    @staticmethod
    def _stage_param_view(preset_id: str) -> dict:
        """阶段参数档展示视图（已过白名单校验；脏值在读取层就被丢弃，这里只排版）"""
        from .. import presets as genre_presets
        labels = dict(genre_presets.STAGE_PARAM_PHASES)
        fields = {k: lab for k, lab, _lo, _hi, _int in genre_presets.STAGE_PARAM_FIELDS}
        view = {}
        for phase, vals in genre_presets.stage_params(preset_id).items():
            parts = [f"{fields.get(k, k)}={v}" for k, v in vals.items()]
            view[phase] = {"label": labels.get(phase, phase), "value": " · ".join(parts)}
        return view

    @Slot(str, str, result=bool)
    def exportPreset(self, preset_id: str, out_path: str) -> bool:
        """v2 导出预设到指定路径（无 UI 按钮时用 TUI 命令面板）"""
        from .. import presets as genre_presets
        if out_path.startswith("file:///"):
            from PySide6.QtCore import QUrl
            out_path = QUrl(out_path).toLocalFile()
        ok = genre_presets.export_preset(preset_id, out_path)
        if ok:
            self.toast.emit("ok", f"预设「{preset_id}」已导出到 {out_path}")
        else:
            self.toast.emit("warn", f"预设「{preset_id}」导出失败：未找到")
        return ok

    @Slot(result=str)
    def currentTheme(self) -> str:
        """当前主题名（qianbi_night / qianbi_parchment / qianbi_plain）"""
        return self.cfg.get("ui_theme", "qianbi_night")

    @Slot(str)
    def setTheme(self, theme: str):
        """切换主题（实时写入 cfg 并发信号给 QML 重新加载 Theme.qml 单例）"""
        valid = ("qianbi_night", "qianbi_parchment", "qianbi_plain")
        if theme not in valid:
            self.toast.emit("warn", f"未知主题：{theme}")
            return
        if self.cfg.get("ui_theme") == theme:
            return
        self.cfg["ui_theme"] = theme
        from app import config as cfg_mod
        cfg_mod.save_config(self.cfg)
        self.themeChanged.emit()
        cn = {"qianbi_night": "夜间", "qianbi_parchment": "羊皮纸", "qianbi_plain": "纯白"}[theme]
        self.toast.emit("ok", f"主题已切换为「{cn}」")

    # ---- 章级生成配置快照（P2）：队列行右键「查看生成配置」----

    @Slot(int, result="QVariantMap")
    def chapterGenConfig(self, num: int) -> dict:
        """这一章生成时吃了什么：世界书激活清单、参数档、每次调用真实下发的采样

        排版留在这里而不是 QML：快照结构由流水线写，展示口径变了只改一处。
        改造前跑出来的老章节没有快照 → found=False，面板按「未登记」提示。
        """
        num = int(num or 0)
        empty = {"found": False, "num": num, "sections": []}
        if not self.proj or not num:
            return empty
        snap = project.get_chapter_gen_config(self.proj, num)
        if not snap:
            return empty
        from .. import presets as genre_presets
        labels = {k: lab for k, lab, _lo, _hi, _int in genre_presets.STAGE_PARAM_FIELDS}
        labels.update(genre_presets.SAMPLING_LABELS)
        phases = dict(genre_presets.STAGE_PARAM_PHASES)
        order = list(labels)        # 标签表按预设字段顺序构造，键序即展示顺序

        def fmt(vals):
            """按预设字段声明顺序排版（连接槽→温度→核采样→…），字母序会把温度丢到中间"""
            d = vals or {}
            return " · ".join(f"{labels.get(k, k)}={d[k]}" for k in order if d.get(k) not in (None, ""))

        pid = snap.get("preset") or ""
        p_name = (genre_presets.load_preset(pid).get("name") or pid) if pid else "通用（无预设）"
        head = [f"预设：{p_name}", f"生成时间：{snap.get('ts', '')}"]
        layers = [f"全书采样基线：{t}" for t in [fmt(snap.get("sampling"))] if t]
        for phase, vals in (snap.get("stage_params") or {}).items():
            t = fmt(vals)
            if t:
                layers.append(f"{phases.get(phase, phase)}档：{t}")
        head += layers or ["参数档：无覆盖，全部沿用连接档案默认值"]
        sections = [{"title": f"第 {num} 章生成配置", "lines": head}]

        for phase, meta in (snap.get("worldbook") or {}).items():
            acts = meta.get("activated") or []
            lines = [f"{a.get('name', '')}｜{a.get('why', '')}" for a in acts]
            dropped = [d for d in (meta.get("dropped") or []) if d]
            if dropped:
                lines.append("未入预算：" + "、".join(dropped))
            sections.append({
                "title": "%s世界书 · 激活 %d 条 / 预算 %s 字" % (
                    phases.get(phase, phase), len(acts), meta.get("budget", 0)),
                "lines": lines or ["（本节装配无条目命中，或走了整文件快速路径）"]})

        calls = snap.get("calls") or []
        lines = []
        for c in calls:
            bits = [phases.get(c.get("phase", ""), c.get("phase", "未知相位")) or "未知相位",
                    c.get("slot") or "默认槽", c.get("model") or "?",
                    fmt(c.get("sampling")) or "档案默认"]
            if c.get("degraded"):
                bits.append("网关拒收已降级")
            bits.append("prompt " + str(c.get("prompt_hash", ""))[:8])
            lines.append(" · ".join(bits))
        if lines:
            sections.append({"title": f"调用记录（{len(calls)} 次）", "lines": lines})
        return {"found": True, "num": num, "sections": sections}

    @Slot(int)
    def showGenConfig(self, num: int):
        """队列行右键入口：章号随信号交给 QML 对话框，桥不持有对话框状态"""
        self.genConfigReady.emit(int(num or 0))

    @Slot(int, result="QVariantMap")
    def saveChapterPresetTemplate(self, num: int) -> dict:
        """「固化为模板」：这一章实际生效的组装参数 → 可复用预设（飞轮的写回端）

        模板 id 由「书名+章号」决定，重新生成后再固化只更新同一个模板文件，
        点赞过的章节不会被一堆近似重复的预设淹没。
        """
        from .. import presets as genre_presets
        num = int(num or 0)
        if not self.proj or not num:
            return {"ok": False, "msg": "请先打开项目并选择章节"}
        snap = project.get_chapter_gen_config(self.proj, num)
        if not snap:
            return {"ok": False, "msg": f"第 {num} 章没有生成配置快照，无法固化"}
        data = genre_presets.preset_from_snapshot(
            snap, self._book_title or os.path.basename(self.proj),
            genre_presets.load_preset(snap.get("preset") or ""))
        existed = os.path.isfile(os.path.join(genre_presets.user_dir(),
                                              data["id"] + ".json"))
        genre_presets.save_preset(data)
        msg = f"已{'更新' if existed else '创建'}模板「{data['name']}」" + \
              ("" if existed else "，可在「新建项目 → 题材预设」里选用")
        self.toast.emit("ok", msg)
        return {"ok": True, "msg": msg, "id": data["id"], "updated": existed}

    # ---- v2 6 维审校 issues（plan v2 模块 B）----

    @Slot(result="QVariantList")
    def reviewIssues(self) -> list:
        """当前章最近一次 6 维审校的 issues（UI ReviewIssueDialog 渲染用）"""
        if not self.proj:
            return []
        s = st.load_state(self.proj)
        rf = s.get("review_findings") or {}
        # 优先取对话框已登记的章号（指定章「查看问题」入口），避免误取 current_chapter
        if self._review_issue_num and str(self._review_issue_num) in rf:
            return rf[str(self._review_issue_num)].get("items", [])
        # 其次取 current_chapter
        cur = str(s.get("current_chapter", 0))
        if cur in rf:
            try:
                self._review_issue_num = int(cur)
            except ValueError:
                self._review_issue_num = 0
            return rf[cur].get("items", [])
        # 否则取最近一次
        if not rf:
            return []
        latest_num = max(rf.keys(), key=lambda k: rf[k].get("ts", ""))
        try:
            self._review_issue_num = int(latest_num)
        except ValueError:
            self._review_issue_num = 0
        return rf.get(latest_num, {}).get("items", [])

    @Slot(int, result="QVariantList")
    def reviewIssuesFor(self, num: int) -> list:
        """指定章的 issues（队列行「查看问题」入口），并记录对话框所属章号"""
        self._review_issue_num = int(num)
        if not self.proj:
            return []
        rf = st.load_state(self.proj).get("review_findings") or {}
        return rf.get(str(int(num)), {}).get("items", [])

    @Slot(int)
    def showReviewIssues(self, num: int):
        """章级问题入口：取该章 issues 并复用 onReviewIssuesChanged 打开对话框"""
        items = self.reviewIssuesFor(num)
        if not items:
            self.toast.emit("info", f"第 {num} 章没有登记的审校问题")
            return
        self.reviewIssuesChanged.emit()

    @Slot(str)
    def resolveReviewIssue(self, choice: str):
        """用户在 ReviewIssueDialog 选择 A/B/C 后的回执

        Args:
            choice: "upstream" | "local" | "ignore"
                - upstream: 返上游重做（标记 review_chain）
                - local: 仅本地改稿（不阻断）
                - ignore: 忽略通过（标记 human）
        """
        if not self.proj:
            return
        s = st.load_state(self.proj)
        # 回执对准对话框正在显示的章（而非 current_chapter，避免错位）
        cur = self._review_issue_num or int(s.get("current_chapter", 0) or 0)
        if not cur:
            return
        if choice == "ignore":
            st.mark_chapter_need_human(self.proj, s, cur)
            self.toast.emit("info", f"第 {cur} 章已忽略，标 human")
        elif choice == "upstream":
            # 登记上游重做请求（GUI 侧尚无上游 Agent 重做回路，执行走「带指导重写」）
            st.append_review_chain(self.proj, s, cur,
                                   issues=[], reworks=["upstream_requested"],
                                   verdict="UPSTREAM_REQUEST", round_no=999)
            self.toast.emit("info", f"第 {cur} 章已登记上游重做请求（执行请用章节右键「带指导重写」）")
        else:  # local：按登记问题本地定向改稿（一键修复同款流程）
            self.toast.emit("info", f"第 {cur} 章开始本地定向改稿…")
        # 注意：不要在此发 reviewIssuesChanged——QML 侧选择后已关闭对话框，
        # 再发会让 onReviewIssuesChanged 把同一对话框立刻重新弹出
        self.needsFixChanged.emit()
        if choice == "local":
            self._start_repair([cur])

    @Slot(result=str)
    def reviewVerdict(self) -> str:
        """当前问题对话框所属章节的登记裁决（供 badge 显示）"""
        if not self.proj or not self._review_issue_num:
            return ""
        rf = st.load_state(self.proj).get("review_findings") or {}
        return rf.get(str(self._review_issue_num), {}).get("verdict", "")

    @Slot()
    def clearReviewIssues(self):
        """清空 review_issues 显示（用户已处理完）"""
        self.reviewIssuesChanged.emit()

    # ---- 待修章节汇总 + 一键修复 ----

    def _needs_fix_entries(self) -> list:
        if not self.proj:
            return []
        return collect_needs_fix(st.load_state(self.proj))

    @Property(int, notify=needsFixChanged)
    def needsFixCount(self) -> int:
        return len(self._needs_fix_entries())

    @Property(bool, notify=repairChanged)
    def repairRunning(self) -> bool:
        return bool(self._repair_worker and self._repair_worker.isRunning())

    @Property(str, notify=repairChanged)
    def repairStatus(self) -> str:
        return self._repair_status

    @Slot(result="QVariantList")
    def needsFixChapters(self) -> list:
        """全部待修章节（含各章阻塞/建议数与裁决，供汇总对话框渲染）"""
        return self._needs_fix_entries()

    @Slot("QVariant")
    def repairChapters(self, nums):
        """修复指定章节列表（对话框「修复本章」）"""
        try:
            lst = [int(n) for n in list(nums or [])]
        except (TypeError, ValueError):
            lst = []
        self._start_repair(lst)

    @Slot()
    def repairAll(self):
        """一键修复全部待修章节（逐章按登记的审校问题定向修）"""
        self._start_repair([e["num"] for e in self._needs_fix_entries()])

    def _start_repair(self, nums: list):
        if self._running:
            self.toast.emit("warn", "流水线运行中，请先停止再做一键修复")
            return
        if self._repair_worker and self._repair_worker.isRunning():
            self.toast.emit("warn", "修复进行中，请稍候")
            return
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return
        nums = [n for n in nums if n and n > 0]
        if not nums:
            self.toast.emit("info", "当前没有待修章节")
            return
        if self._editor_dirty and self._cur_num in nums:
            self.toast.emit("warn", f"第 {self._cur_num} 章有未保存改动，请先保存再修复该章")
            return
        self._repair_status = f"开始修复 {len(nums)} 章…"
        self.repairChanged.emit()
        worker = ChapterRepairWorker(self.cfg, self.proj, nums, parent=self)
        worker.sig_log.connect(lambda m: self.logModel.append("info", m))
        worker.sig_chapter_done.connect(self._on_repair_chapter)
        worker.sig_all_done.connect(self._on_repair_done)
        self._repair_worker = worker
        worker.start()

    def _on_repair_chapter(self, num: int, ok: bool, detail: str):
        self._repair_status = f"第 {num} 章：{detail}"
        self.repairChanged.emit()
        self.logModel.append("ok" if ok else "warn",
                             f"修复 第{num}章 {'成功' if ok else '未采纳'}：{detail}")
        self.refreshQueue()
        # 若编辑器正显示刚修复的章且无未保存改动：跟随磁盘新内容（与定稿同款处理）
        if self._cur_num == num and self.proj and not self._editor_dirty:
            for n, _name, path in project.list_chapters(self.proj):
                if n == num:
                    self._chapter_path = path
                    self._chapter_text = project.read_file(path)
                    self.chapterTextChanged.emit()
                    self._reset_editor_state()
                    break

    def _on_repair_done(self, ok: int, fail: int):
        self._repair_status = f"修复完成：{ok} 章成功" + (f"，{fail} 章未采纳（原稿保留）" if fail else "")
        self.repairChanged.emit()
        self.refreshUsage()
        self.toast.emit("ok" if ok and not fail else "warn", self._repair_status)
        self._repair_worker = None
        self.refreshQueue()

    # ---- 编辑器偏好（M5）----

    EDITOR_DEFAULTS = {"fontScale": 1.0, "narrow": True, "streamSmooth": False}

    @Slot(result="QVariantMap")
    def editorPrefs(self) -> dict:
        prefs = dict(self.EDITOR_DEFAULTS)
        prefs.update(self.cfg.get("editor", {}))
        return prefs

    @Slot(str, "QVariant")
    def setEditorPref(self, key: str, value):
        self.cfg.setdefault("editor", {})[key] = value
        cfg_mod.save_config(self.cfg)

    @Slot(result=int)
    def chapterWordTarget(self) -> int:
        return int(self.cfg.get("writing", {}).get("chapter_word_target", 3000))

    @Slot(int)
    def setChapterWordTarget(self, v: int):
        self.cfg.setdefault("writing", {})["chapter_word_target"] = max(500, int(v))
        cfg_mod.save_config(self.cfg)
        self._refresh_progress()
        self.toast.emit("ok", f"章节字数目标已设为 {max(500, int(v))} 字")

    @Slot(result=bool)
    def reviewEnabled(self) -> bool:
        return bool(self.cfg.get("gates", {}).get("review_enabled", True))
    @Slot(bool)
    def setReviewEnabled(self, on: bool):
        self.cfg.setdefault("gates", {})["review_enabled"] = bool(on)
        cfg_mod.save_config(self.cfg)
        self.toast.emit("ok", on and "审校已启用（一致性检查 + 修改轮）" or "审校已停用（写完直接定稿）")

    # ---- 「正则」语义（M2：默认逻辑约束规则集；字面正则样本为备选，只影响解析与写入结构）----

    @Slot(result=str)
    def regexSemantics(self) -> str:
        return str(self.cfg.get("writing", {}).get("regex_semantics", "logic"))

    @Slot(str)
    def setRegexSemantics(self, mode: str):
        m = mode if mode in ("logic", "regex") else "logic"
        self.cfg.setdefault("writing", {})["regex_semantics"] = m
        cfg_mod.save_config(self.cfg)
        name = {"logic": "逻辑约束规则集", "regex": "字面正则样本"}[m]
        self.toast.emit("ok", f"「正则」语义已切换为「{name}」（影响解析与写入结构，不阻塞核心路径）")

    # ---- 导出（排版选项 + 预览 + 报告）----

    @Slot(str, str, int, result=str)
    def exportProjectOpts(self, fmt: str, sep: str, titleFmt: int) -> str:
        """导出全本（带排版选项）。返回导出路径，toast 附导出报告"""
        if not self.proj:
            self.toast.emit("warn", "请先打开项目")
            return ""
        try:
            from .. import export as export_mod
            path = os.path.abspath(export_mod.export_project(self.proj, fmt, sep=sep, title_fmt=int(titleFmt)))
            chapters = project.list_chapters(self.proj)
            words = sum(project.count_chars(project.read_file(p)) for _n, _m, p in chapters)
            self.toast.emit("ok", f"已导出 → {path}：{len(chapters)} 章 · "
                                  f"{words} 字 · {os.path.getsize(path) / 1024:.0f} KB")
            return path
        except ValueError as e:
            self.toast.emit("warn", str(e))
            return ""
        except Exception as e:  # noqa: BLE001
            self.toast.emit("error", f"导出失败: {e}")
            return ""

    @Slot(str, int, result=str)
    def exportPreviewText(self, sep: str, titleFmt: int) -> str:
        """导出排版预览（前两章实际效果）"""
        if not self.proj:
            return "（请先打开项目）"
        from .. import export as export_mod
        return export_mod.preview_txt(self.proj, sep=sep, title_fmt=int(titleFmt))

    @Slot(str)
    def revealPath(self, path: str):
        """在系统文件管理器中定位文件（Windows 用 explorer /select 选中）"""
        if not path:
            self.toast.emit("warn", "还没有导出文件")
            return
        if path.startswith("file:///"):
            from PySide6.QtCore import QUrl
            path = QUrl(path).toLocalFile()
        if not os.path.exists(path):
            self.toast.emit("warn", "文件不存在或已被移动")
            return
        try:
            import subprocess
            import sys
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(path))))
            self.toast.emit("ok", "已在文件管理器中定位导出文件")
        except Exception as e:  # noqa: BLE001
            self.toast.emit("error", f"无法打开文件管理器: {e}")

    @Slot(str)
    def copyText(self, text: str):
        """复制文本到系统剪贴板（发布物料粘贴到平台后台用）"""
        try:
            from PySide6.QtGui import QGuiApplication
            cb = QGuiApplication.clipboard()
            if cb is None:
                self.toast.emit("warn", "当前环境无剪贴板")
                return
            cb.setText(text or "")
            self.toast.emit("ok", "已复制到剪贴板")
        except Exception as e:  # noqa: BLE001
            self.toast.emit("error", f"复制失败: {e}")
