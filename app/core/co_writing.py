# -*- coding: utf-8 -*-
"""共写档交互状态机（主线程驱动；对话/总结调用由 bridge 经 co_dialogue worker 执行）

- 六阶段：创建项目 → 核心设定 → 剧情总大纲 → 世界书与正则 → 单元细纲 → 正文写作
- 确认 = 总结定稿落盘 + 状态机前进；打回 = 级联失效下游产物并归档 + 阶段回退；
  reopen = 世界书回看软切（不级联删除，重确定后返回原阶段）。
- 与自动档完全隔离：只写 state['cw']，绝不碰 state['stage']。
"""
import datetime
import os
import shutil

from .. import project
from . import state as st
from .co_dialogue import prev_handoff, transcript_text

logger = __import__("logging").getLogger("qianbi.core")


class CoWriting:
    """共写档状态机：纯状态与文件逻辑，可脱离 Qt 单测"""

    def __init__(self, proj: str):
        self.proj = proj

    # ---------- 状态读取 ----------

    def load(self) -> dict:
        state = st.load_state(self.proj)
        st.ensure_cw(state)
        return state

    def save(self, state: dict):
        st.save_state(self.proj, state)

    def stage_index(self, key: str) -> int:
        try:
            return st.CW_STAGE_ORDER.index(key)
        except ValueError:
            return 0

    def is_cw(self, state: dict = None) -> bool:
        state = state or self.load()
        return st.ensure_cw(state).get("mode") == "cw"

    def current_agent(self, state: dict = None) -> str:
        state = state or self.load()
        stage = st.ensure_cw(state).get("stage", st.STAGE_CW_PROJECT)
        if stage == st.STAGE_CW_PROJECT:
            return "创建项目（表单）"
        from .. import prompts
        role = prompts.CO_ROLES.get(stage)
        return role["agent"] if role else stage

    def stage_summary(self, state: dict) -> dict:
        """当前阶段：阶段key/标签/产物文件/可回退/可回看世界书/是否回看中"""
        cw = st.ensure_cw(state)
        stage = cw.get("stage", st.STAGE_CW_PROJECT)
        return {
            "key": stage,
            "label": st.CW_STAGE_LABELS.get(stage, stage),
            "index": self.stage_index(stage),
            "products": list(st.CW_STAGE_PRODUCTS.get(stage, [])),
            "rollbackable": stage != st.STAGE_CW_PROJECT,
            "canReopen": stage in st.CW_REOPEN_SOURCES,
            "reopening": bool(cw.get("reopening")),
        }

    # ---------- 档位迁移（受控切换：仅阶段空闲时可切，由 bridge 守卫）----------

    def migrate_mode(self, state: dict, to_cw: bool) -> dict:
        """cw ↔ 自动档切换：mode 粘性写 state['cw']['mode']；进共写档时推断续跑阶段"""
        cw = st.ensure_cw(state)
        was_cw = cw.get("mode") == "cw"
        cw["mode"] = "cw" if to_cw else "auto"
        if to_cw and not was_cw:
            cw["stage"] = self._resume_stage()
            cw["reopening"] = ""
        return cw

    def _resume_stage(self) -> str:
        """旧项目进入共写档：按产物存在性推断首个未完成阶段"""
        for stage in st.CW_STAGE_ORDER:
            if stage == st.STAGE_CW_PROSE:
                return stage
            rels = st.CW_STAGE_PRODUCTS.get(stage, [])
            if not all(os.path.isfile(os.path.join(self.proj, r)) for r in rels):
                return stage
        return st.STAGE_CW_PROSE

    # ---------- 确认（总结定稿后推进；product 落盘由 bridge 完成）----------

    def advance(self, state: dict) -> str:
        """状态机前进一格；cw_prose 为终态不前进"""
        cw = st.ensure_cw(state)
        cur = cw.get("stage", st.STAGE_CW_PROJECT)
        nxt = st.CW_NEXT.get(cur, cur)
        if nxt != cur:
            cw["stage"] = nxt
        return nxt

    def confirm_reopen_return(self, state: dict) -> str:
        """回看回边重确定：写回世界书/正则后返回原阶段"""
        cw = st.ensure_cw(state)
        ret = cw.get("reopening", "")
        cw["reopening"] = ""
        if ret:
            cw["stage"] = ret
        return ret

    # ---------- 打回（级联失效下游产物 + 归档）----------

    def rollback(self, state: dict, stage_key: str = None) -> dict:
        """打回指定阶段（缺省=当前阶段）：级联失效下游产物并归档，阶段回退到该阶段"""
        cw = st.ensure_cw(state)
        stage = stage_key or cw.get("stage", st.STAGE_CW_PROJECT)
        patterns = st.CW_ROLLBACK_CASCADE.get(stage, [])
        archived = self._invalidate(stage, patterns)
        cw["stage"] = stage
        cw["reopening"] = ""
        # 下游交接块随产物失效（交接有唯一属主，产物没了交接即作废）
        idx = self.stage_index(stage)
        for k in st.CW_STAGE_ORDER[idx:]:
            cw.get("handoff", {}).pop(k, None)
        return {"archived": archived}

    def _invalidate(self, stage: str, patterns: list) -> list:
        if not patterns:
            return []
        roll_dir = os.path.join(self.proj, "pipeline_debug", "rollback",
                                f"cw_{stage}_{datetime.datetime.now().strftime('%m%d_%H%M%S')}")
        removed = []
        try:
            os.makedirs(roll_dir, exist_ok=True)
            for p in self._resolve_patterns(patterns):
                if not os.path.isfile(p):
                    continue
                try:
                    shutil.copy2(p, os.path.join(roll_dir, os.path.basename(p)))
                    os.remove(p)
                    removed.append(p)
                except OSError as e:
                    logger.warning("打回归档失败 %s: %s", p, e)
        except OSError as e:
            logger.warning("打回目录创建失败: %s", e)
        return removed

    def _resolve_patterns(self, patterns: list) -> list:
        """解析失效模式：精确相对路径（设定/世界书.md）或 大纲 目录前缀（细纲_）"""
        files = []
        for pat in patterns:
            if pat.startswith("细纲_"):
                d = os.path.join(self.proj, "大纲")
                if os.path.isdir(d):
                    files.extend(os.path.join(d, n) for n in os.listdir(d)
                                 if n.startswith(pat) and n.endswith(".md"))
            else:
                files.append(os.path.join(self.proj, pat))
        return files

    # ---------- 世界书回看回边（reopen 软切：不级联删除）----------

    def reopen(self, state: dict, target: str = st.STAGE_CW_WORLDBOOK) -> str:
        """软切到目标阶段（保留下游转写与已锁定产物）；返回目标阶段 key"""
        cw = st.ensure_cw(state)
        if target not in st.CW_STAGE_ORDER or cw.get("stage") not in st.CW_REOPEN_SOURCES:
            return ""
        cw["reopening"] = cw.get("stage", "")
        cw["stage"] = target
        return target

    def can_reopen(self, state: dict) -> bool:
        cw = st.ensure_cw(state)
        return cw.get("stage") in st.CW_REOPEN_SOURCES

    # ---------- 交接与对话快照（供 bridge/QML）----------

    def handoff_text(self, state: dict, stage: str = None) -> str:
        stage = stage or st.ensure_cw(state).get("stage")
        return prev_handoff(state, stage)

    def transcript(self, state: dict, stage: str = None) -> list:
        stage = stage or st.ensure_cw(state).get("stage")
        return list(st.ensure_cw(state).get("transcript", {}).get(stage, []))

    def transcript_tail(self, state: dict, stage: str = None, max_chars: int = 4000) -> str:
        stage = stage or st.ensure_cw(state).get("stage")
        return transcript_text(state, stage, max_chars)

    # ---------- 单元细纲（M3：滚动批次 ±10 章）----------

    def unit(self, state: dict) -> dict:
        return dict(st.ensure_cw(state).get("unit", {}) or {})

    def set_unit(self, state: dict, start: int, target_end: int, topic: str) -> dict:
        """登记单元范围/主题（±10 章由批次生成时校验）"""
        u = st.ensure_cw(state).setdefault("unit", {})
        u["start"] = max(1, int(start or 0))
        u["target_end"] = max(0, int(target_end or 0))
        u["topic"] = (topic or "").strip()
        return u

    def next_outline_batch(self, state: dict, batch_size: int = 5) -> list:
        """滚动批次：已写正文下一章起（或单元起始章），取下一批缺失细纲的章

        ±10 章约束：批次完结章 ≤ 单元目标完结章 + 10；未设单元时不限。
        """
        unit = st.ensure_cw(state).get("unit", {}) or {}
        start = max(1, int(unit.get("start") or 0))
        n = max(start, project.next_chapter_num(self.proj))
        existing = {n2 for n2, _ in project.list_outlines(self.proj)}
        while n in existing:
            n += 1
        target_end = int(unit.get("target_end") or 0)
        limit = (target_end + 10) if target_end else n + batch_size * 8
        batch = []
        for k in range(batch_size):
            if n + k > limit:
                break
            batch.append(n + k)
        return batch
