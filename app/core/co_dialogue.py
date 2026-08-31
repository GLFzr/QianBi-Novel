# -*- coding: utf-8 -*-
"""共写档对话机制：转写管理 + 交接块唯一生成者 + 一次性对话/总结 worker

- DialogueWorker：每轮用户输入启动一次（QThread，不常驻不阻塞 UI），
  user 消息 = 角色提示词 + 上一环节交接块(≤800) + 本阶段参考块 + 对话转写(≤4k) + 本轮输入。
- SummarizeWorker：阶段「确定」时对已收敛讨论做一次总结定稿调用，
  输出 = 产物正文 + 文末固定小节「→ 下阶段交接」（3-6 条关键事实 + 开放问题，≤800 字）。
- build_handoff：交接小节的唯一生成者（解析 Summarize 输出并落 state['cw']['handoff']）。
"""
import os

from PySide6.QtCore import QThread, Signal

from .. import config as cfg_mod
from .. import project, prompts
from ..llm import ModelRouter, clean_llm_output
from . import state as st

TRANSCRIPT_MAX = 4000   # 对话转写截断上限（最近 ≤4k 字）
HANDOFF_MAX = 800       # 交接块上限


# ---------- 对话转写管理 ----------

def transcript_append(state: dict, stage: str, role: str, text: str):
    """追加一条转写（role: user / agent）并落盘"""
    cw = st.ensure_cw(state)
    items = cw.setdefault("transcript", {}).setdefault(stage, [])
    items.append({"role": role, "text": text})
    cw["transcript"][stage] = items


def transcript_text(state: dict, stage: str, max_chars: int = TRANSCRIPT_MAX) -> str:
    """拼装某阶段转写为文本（最近 ≤max_chars 字，截断保尾）"""
    items = st.ensure_cw(state).get("transcript", {}).get(stage) or []
    parts = []
    for it in items:
        role = "作者" if it.get("role") == "user" else "Agent"
        parts.append(f"{role}：{it.get('text', '')}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        prefix = "…（较早讨论已截断）\n\n"
        text = prefix + text[-(max_chars - len(prefix)):]
    return text


def clear_transcript(state: dict, stage: str):
    st.ensure_cw(state).setdefault("transcript", {})[stage] = []


# ---------- 交接块（唯一生成者）----------

def build_handoff(stage: str, summary_text: str):
    """解析 Summarize 输出 → (产物正文, 交接小节)

    以固定小节「→ 下阶段交接」为界：前半=产物正文，后半=交接块（≤800 字）。
    模型漏输出小节时：产物=全文，交接=空（调用方记日志，不阻塞落盘）。
    """
    text = (summary_text or "").strip()
    idx = text.rfind(prompts.HANDOFF_MARKER)
    if idx < 0:
        return text, ""
    product = text[:idx].rstrip()
    handoff = text[idx + len(prompts.HANDOFF_MARKER):].strip()
    if len(handoff) > HANDOFF_MAX:
        handoff = handoff[:HANDOFF_MAX] + "…（截断）"
    return product, handoff


def prev_handoff(state: dict, stage: str) -> str:
    """上一阶段交接块（下一 Agent 的唯一上文来源）；无则占位"""
    order = st.CW_STAGE_ORDER
    try:
        i = order.index(stage)
    except ValueError:
        return "（无交接块）"
    if i <= 0:
        return "（第一个阶段，无上一环节交接块）"
    prev = order[i - 1]
    h = st.ensure_cw(state).get("handoff", {}).get(prev, "")
    if not h:
        return "（上一阶段尚未确定，暂无交接块——按参考块与转写继续）"
    return h


def store_handoff(state: dict, stage: str, handoff: str):
    st.ensure_cw(state).setdefault("handoff", {})[stage] = (handoff or "")[:HANDOFF_MAX]


# ---------- 参考块（本阶段只注入的上下文）----------

def _grow(preset_id: str, field: str) -> str:
    """grow_* 参考块（M2：仅共写档阶段 Agent 读取，不进 genre_block）"""
    try:
        from .. import presets as genre_presets
        return genre_presets.grow_block(preset_id, field)
    except Exception:
        return "（该预设未提供此参考）"


def compose_reference_block(proj: str, stage: str, preset_id: str = "",
                            focus_chapter: int = 0) -> str:
    """各阶段参考块：上一环节产物 + grow_* 参考 + 世界书/正则（M2 注入）

    focus_chapter（仅 prose 阶段）：用户当前打开/选中的章号；0 = 沿用旧行为
    （next_chapter_num，即追加下一章）。
    """
    def rd(*rel):
        return project.read_file(os.path.join(proj, *rel))

    if stage == st.STAGE_CW_CORE:
        info = project.read_idea_info(proj)
        base = (f"【选题信息】题材：{info['genre'] or '（不限）'} · 平台：{info['platform']} · "
                f"预计 {info['total_words_wan']} 万字\n灵感：{info['idea'] or '（无）'}")
        return base + "\n\n" + _grow(preset_id, "grow_core_template")
    if stage == st.STAGE_CW_OUTLINE:
        core = rd("设定", "题材定位.md")[:4000]
        return (f"【核心设定（已确定）】\n{core or '（尚未确定，先请作者确定设定）'}\n\n"
                + _grow(preset_id, "grow_outline_template"))
    if stage == st.STAGE_CW_WORLDBOOK:
        core = rd("设定", "题材定位.md")[:2000] or "（无）"
        outline = rd("大纲", "大纲.md")[:2000] or "（无）"
        wb = project.worldbook_text(proj, 1500)
        rg = project.regex_block(proj, "logic", 1200)
        return (f"【核心设定摘要】\n{core}\n\n【全书大纲摘要】\n{outline}\n\n"
                f"【现有世界书】\n{wb}\n\n【现有正则】\n{rg}\n\n"
                + _grow(preset_id, "grow_worldbook_direction") + "\n\n"
                + _grow(preset_id, "grow_regex_direction"))
    if stage == st.STAGE_CW_UNIT:
        outline = rd("大纲", "大纲.md")[:2000] or "（无）"
        wb = project.worldbook_text(proj, 1200)
        rg = project.regex_block(proj, "logic", 1000)
        return (f"【全书大纲摘要】\n{outline}\n\n【世界书摘要】\n{wb}\n\n【正则约束】\n{rg}\n\n"
                + _grow(preset_id, "grow_unit_logic"))
    if stage == st.STAGE_CW_PROSE:
        chapters = project.list_chapters(proj)
        num = int(focus_chapter) if int(focus_chapter or 0) > 0 else project.next_chapter_num(proj)
        by_num = {n: p for n, _name, p in chapters}
        outline = rd("大纲", f"细纲_第{num:03d}章.md") or "（本章细纲尚未生成）"
        wb = project.worldbook_text(proj, 1200)
        rg = project.regex_block(proj, "logic", 1000)
        prev_nums = [n for n in by_num if n < num]
        next_nums = [n for n in by_num if n > num]
        prev_ending = "（本章为第一章）"
        if prev_nums:
            prev_ending = project.read_file(by_num[max(prev_nums)])[-500:]
        next_opening = "（本章之后暂无已写章节）"
        if next_nums:
            next_opening = project.read_file(by_num[min(next_nums)])[:500]
        own = by_num.get(num, "")
        own_text = project.read_file(own) if own else ""
        if own_text.strip():
            status = f"已有草稿（约 {project.count_chars(own_text)} 字），按作者意见修改或续写"
        else:
            status = ("尚未写成。作者要求写作时，请依据上一章结尾、下一章开头与本章细纲"
                      "补写完整正文，注意与前后章无缝衔接")
        return (f"【焦点章节】锚定第 {num} 章（用户在编辑器打开的章；若与作者本轮所指不同，以作者为准并提醒）\n\n"
                f"【本章细纲】\n{outline}\n\n【世界书摘要】\n{wb}\n\n【正则约束】\n{rg}\n\n"
                f"【上一章结尾】\n{prev_ending}\n\n【下一章开头】\n{next_opening}\n\n"
                f"【本章现状】{status}")
    return "（本阶段无参考块）"


def _preset_id(proj: str) -> str:
    """项目当前预设（共写档 preset 优先，回退 genre_preset）"""
    state = st.load_state(proj)
    cw = st.ensure_cw(state)
    return cw.get("preset") or state.get("genre_preset") or ""


# ---------- 一次性对话 worker ----------

class DialogueWorker(QThread):
    """每轮用户输入 → 独立 worker：流式回传增量，完成即退出（不进 orchestrator）"""
    chunk = Signal(str)
    reasoning = Signal(str)
    done = Signal(str)
    error = Signal(str)

    def __init__(self, cfg: dict, proj: str, stage: str, user_text: str,
                 router=None, parent=None, focus_chapter: int = 0):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.stage = stage
        self.user_text = user_text
        self.router = router or ModelRouter(cfg)
        self.focus_chapter = int(focus_chapter or 0)
        self.last_prompt = ""
        self.result_text = ""

    def run(self):
        try:
            role = prompts.CO_ROLES.get(self.stage)
            if not role:
                self.error.emit(f"未知共写阶段：{self.stage}")
                return
            state = st.load_state(self.proj)
            prompt = prompts.CO_DIALOGUE_PROMPT.format(
                role_desc=role["role"],
                agent_name=role["agent"],
                stage_label=st.CW_STAGE_LABELS.get(self.stage, self.stage),
                handoff=prev_handoff(state, self.stage),
                reference_block=compose_reference_block(self.proj, self.stage, _preset_id(self.proj),
                                                        focus_chapter=self.focus_chapter),
                transcript=transcript_text(state, self.stage),
                user_message=self.user_text,
            )
            self.last_prompt = prompt
            text = clean_llm_output(self.router.client(role["slot"]).chat_stream(
                prompt, on_chunk=self.chunk.emit, on_reasoning=self.reasoning.emit))
            if not text.strip():
                self.error.emit("模型返回为空，请重试")
                return
            self.result_text = text
            self.done.emit(text)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


# ---------- 确定按钮：总结定稿 worker ----------

class SummarizeWorker(QThread):
    """阶段「确定」：对已收敛对话做一次总结调用（不是新开讨论）"""
    done = Signal(str)
    error = Signal(str)

    def __init__(self, cfg: dict, proj: str, stage: str, router=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.stage = stage
        self.router = router or ModelRouter(cfg)
        self.last_prompt = ""
        self.result_text = ""

    def run(self):
        try:
            state = st.load_state(self.proj)
            structure = prompts.CO_PRODUCT_STRUCTURES.get(self.stage, "（按该阶段常规产物结构总结）")
            prompt = prompts.CO_SUMMARIZE_PROMPT.format(
                stage_label=st.CW_STAGE_LABELS.get(self.stage, self.stage),
                product_structure=structure,
                transcript=transcript_text(state, self.stage),
            )
            self.last_prompt = prompt
            role = prompts.CO_ROLES.get(self.stage)
            slot = role["slot"] if role else cfg_mod.SLOT_HELPER
            text = clean_llm_output(self.router.client(slot).chat(prompt))
            if not text.strip():
                self.error.emit("总结为空，请先在对话区把关键决策聊清楚再点确定")
                return
            self.result_text = text
            self.done.emit(text)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


# ---------- M4：读改揣摩（保存后有变 → review 槽读一遍改动，揣摩意图）----------

class ReadbackWorker(QThread):
    """读改揣摩：通读用户改动 → 对话区简短输出理解（复用 review 槽）"""
    done = Signal(str)
    error = Signal(str)

    def __init__(self, cfg: dict, proj: str, num: int, old_text: str, new_text: str,
                 router=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.num = num
        self.old_text = old_text or ""
        self.new_text = new_text or ""
        self.router = router or ModelRouter(cfg)
        self.last_prompt = ""
        self.result_text = ""

    def run(self):
        from ..core import versions as ver_mod
        try:
            diffs = ver_mod.diff_texts(self.old_text, self.new_text)
            diff_text = "\n".join(f"{'-' if d.get('op') == 'del' else '+'} {d.get('text', '')}"
                                  for d in diffs if d.get("op") in ("del", "add"))[:2000] or "（无）"
            diff_summary = (f"改动 {len(diffs)} 处；删除 {sum(len(d.get('text','')) for d in diffs if d.get('op')=='del')} 字，"
                            f"新增 {sum(len(d.get('text','')) for d in diffs if d.get('op')=='add')} 字")
            prompt = prompts.CO_READBACK_PROMPT.format(
                diff_summary=diff_summary,
                diff_text=diff_text or "（无行级差异）",
                chapter_text=self.new_text[:1500],
            )
            self.last_prompt = prompt
            text = clean_llm_output(self.router.client(cfg_mod.SLOT_REVIEW).chat(prompt))
            if not text.strip():
                self.error.emit("读改返回为空，请重试")
                return
            self.result_text = text
            self.done.emit(text)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


# ---------- M5：主 Agent（Supervisor）——每章定稿前衔接比对报告（复用 review 槽）----------

class SupervisorWorker(QThread):
    """主 Agent 触发点①：每章定稿前衔接比对（上章结尾↔本章↔下章细纲）

    只出报告（进对话区报告区），绝不产正文；上下文 ≤6k 字。
    """
    done = Signal(str)
    error = Signal(str)

    def __init__(self, cfg: dict, proj: str, num: int, router=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.num = num
        self.router = router or ModelRouter(cfg)
        self.last_prompt = ""
        self.result_text = ""

    def run(self):
        from . import memory
        try:
            chapters = project.list_chapters(self.proj)
            prev_ending = "（本章为第一章）"
            # 补写/重写中间章时，上一章 = 小于本章的最近存在章（不是磁盘最后一章）
            prev = sorted([c for c in chapters if c[0] < self.num])
            if prev:
                prev_ending = project.read_file(prev[-1][2])[-800:]
            chapter_text = project.read_file(project.get_chapter_path(self.proj, self.num))[:3000]
            if not chapter_text.strip():
                # 正文可能尚未落盘（编辑器工作副本）：读细纲兜底
                chapter_text = project.read_file(project.get_outline_path(self.proj, self.num))[:3000]
            next_brief = project.read_file(project.get_outline_path(self.proj, self.num + 1))[:600] \
                or "（本章为当前最后一章细纲）"
            prompt = prompts.CO_SUPERVISOR_PROMPT.format(
                global_summary=(memory.read_global_summary(self.proj) or "（尚未开始）")[:800],
                previous_ending=prev_ending,
                chapter_text=chapter_text or "（本章正文尚在工作副本中）",
                next_outline_brief=next_brief,
                worldbook_block=project.worldbook_text(self.proj, 1200),
                regex_block=project.regex_block(self.proj, "logic", 1000),
            )
            self.last_prompt = prompt
            text = clean_llm_output(self.router.client(cfg_mod.SLOT_REVIEW).chat(prompt))
            if not text.strip():
                self.error.emit("主 Agent 报告为空，请重试")
                return
            self.result_text = text
            self.done.emit(text)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


# ---------- M3：章细纲滚动生成（确定单元后，helper 槽，≈200 字/章）----------

class OutlineBatchWorker(QThread):
    """滚动生成下一批 5 章细纲并落盘 大纲/细纲_第N章.md"""
    done = Signal(list)      # [(num, title, content)]
    error = Signal(str)

    def __init__(self, cfg: dict, proj: str, batch: list, unit: dict,
                 router=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.batch = list(batch or [])
        self.unit = dict(unit or {})
        self.router = router or ModelRouter(cfg)
        self.last_prompt = ""
        self.result = []

    def run(self):
        from . import stages as stages_mod
        from .. import presets as genre_presets
        try:
            if not self.batch:
                self.error.emit("本批为空（细纲可能已全部生成）")
                return
            state = st.load_state(self.proj)
            nearby = []
            for n, p in project.list_outlines(self.proj):
                if self.batch[0] - 2 <= n <= self.batch[-1] + 2:
                    nearby.append(project.read_file(p)[:400])
            prev_ending = "（本章为第一章）"
            chapters = project.list_chapters(self.proj)
            if chapters:
                last = chapters[-1]
                if last[0] == self.batch[0] - 1:
                    prev_ending = project.read_file(last[2])[-400:]
            prompt = prompts.CO_UNIT_OUTLINE_PROMPT.format(
                unit_block=prompts.unit_text(self.unit),
                handoff=prev_handoff(state, st.STAGE_CW_UNIT),
                worldbook_block=project.worldbook_text(self.proj, 1500),
                regex_block=project.regex_block(self.proj, "logic", 1200),
                genre_block=genre_presets.genre_block(state.get("genre_preset", "")),
                nearby_outlines="\n\n".join(nearby) or "（无相邻细纲）",
                previous_ending=prev_ending,
                start=self.batch[0], end=self.batch[-1], count=len(self.batch),
            )
            self.last_prompt = prompt
            text = clean_llm_output(self.router.client(cfg_mod.SLOT_HELPER)
                                    .chat_stream(prompt, on_chunk=lambda c: None))
            outlines = stages_mod.parse_outlines(text)
            valid = [o for o in outlines if o[0] in self.batch]
            for num, _title, content in valid:
                project.write_file(project.get_outline_path(self.proj, num), content)
            self.result = valid
            if not valid:
                self.error.emit(f"细纲解析失败：未能按格式解析出目标章 {self.batch}")
                return
            self.done.emit(valid)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


# ---------- M3：确定细纲 = Agent 重读校验（衔接/世界书/正则/单元范围）----------

class ReviewOutlinesWorker(QThread):
    """重读用户修改后的细纲并校验衔接，输出 BLOCKING/ADVISORY 两段"""
    done = Signal(str)
    error = Signal(str)

    def __init__(self, cfg: dict, proj: str, nums: list, unit: dict,
                 router=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.nums = list(nums or [])
        self.unit = dict(unit or {})
        self.router = router or ModelRouter(cfg)
        self.last_prompt = ""
        self.result_text = ""

    def run(self):
        try:
            state = st.load_state(self.proj)
            parts = []
            for n in self.nums:
                c = project.read_file(project.get_outline_path(self.proj, n))
                if c:
                    parts.append(f"===第{n}章===\n{c}")
            outlines = "\n\n".join(parts) or "（无细纲）"
            prev_ending = "（本章为第一章）"
            chapters = project.list_chapters(self.proj)
            if chapters:
                last = chapters[-1]
                prev_ending = project.read_file(last[2])[-400:] if last[0] < (self.nums or [1])[0] else prev_ending
            prompt = prompts.CO_OUTLINE_REVIEW_PROMPT.format(
                outlines=outlines,
                worldbook_block=project.worldbook_text(self.proj, 1500),
                regex_block=project.regex_block(self.proj, "logic", 1200),
                previous_ending=prev_ending,
                unit_block=prompts.unit_text(self.unit),
            )
            self.last_prompt = prompt
            text = clean_llm_output(self.router.client(cfg_mod.SLOT_HELPER).chat(prompt))
            if not text.strip():
                self.error.emit("校验返回为空，请重试")
                return
            self.result_text = text
            self.done.emit(text)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
