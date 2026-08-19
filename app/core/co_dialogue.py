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

def compose_reference_block(proj: str, stage: str) -> str:
    """各阶段参考块：只注入上一环节产物/世界书/细纲/上文结尾（M2 追加 grow_*）"""
    def rd(*rel):
        return project.read_file(os.path.join(proj, *rel))

    if stage == st.STAGE_CW_CORE:
        info = project.read_idea_info(proj)
        return (f"【选题信息】题材：{info['genre'] or '（不限）'} · 平台：{info['platform']} · "
                f"预计 {info['total_words_wan']} 万字\n灵感：{info['idea'] or '（无）'}")
    if stage == st.STAGE_CW_OUTLINE:
        core = rd("设定", "题材定位.md")[:4000]
        return f"【核心设定（已确定）】\n{core or '（尚未确定，先请作者确定设定）'}"
    if stage == st.STAGE_CW_WORLDBOOK:
        core = rd("设定", "题材定位.md")[:2000] or "（无）"
        outline = rd("大纲", "大纲.md")[:2000] or "（无）"
        return f"【核心设定摘要】\n{core}\n\n【全书大纲摘要】\n{outline}"
    if stage == st.STAGE_CW_UNIT:
        outline = rd("大纲", "大纲.md")[:2000] or "（无）"
        wb = rd("设定", "世界书.md")[:1500] or "（无）"
        return f"【全书大纲摘要】\n{outline}\n\n【世界书摘要】\n{wb}"
    if stage == st.STAGE_CW_PROSE:
        num = project.next_chapter_num(proj)
        outline = rd("大纲", f"细纲_第{num:03d}章.md") or "（本章细纲尚未生成）"
        wb = rd("设定", "世界书.md")[:1500] or "（无）"
        prev_ending = "（本章为第一章）"
        chapters = project.list_chapters(proj)
        if chapters:
            last_text = project.read_file(chapters[-1][2])
            prev_ending = last_text[-500:]
        return (f"【本章细纲】\n{outline}\n\n【世界书摘要】\n{wb}\n\n"
                f"【上一章结尾】\n{prev_ending}")
    return "（本阶段无参考块）"


# ---------- 一次性对话 worker ----------

class DialogueWorker(QThread):
    """每轮用户输入 → 独立 worker：流式回传增量，完成即退出（不进 orchestrator）"""
    chunk = Signal(str)
    reasoning = Signal(str)
    done = Signal(str)
    error = Signal(str)

    def __init__(self, cfg: dict, proj: str, stage: str, user_text: str,
                 router=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.proj = proj
        self.stage = stage
        self.user_text = user_text
        self.router = router or ModelRouter(cfg)
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
                handoff=prev_handoff(state, self.stage),
                reference_block=compose_reference_block(self.proj, self.stage),
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
