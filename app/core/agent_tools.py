# -*- coding: utf-8 -*-
"""Agent 应用操作工具层（v0.18.6）：让 Agent 真的能操作这个应用

背景：流水线里的每个 Agent 都是一次性文本生成器，彼此独立、对程序零掌控——
作者在人工审校门里说「回退到去味」，应用无动于衷，因为没有任何一层能把
这句话翻译成真实操作。本模块就是那一层：

- 工具注册表：每个工具 = 一项真实应用操作（复用既有能力，不重写业务逻辑），
  带安全级别（readonly / mutate / destructive）；
- 指令解析 parse_instruction：中文自然语言 → (工具, 参数)。规则层零成本、
  确定性强，覆盖高频表达；`/` 前缀强制走解析（失败则列出可用指令）；
- 执行器 execute：空闲态直接操作项目状态（断点/文件/设置）——断点续跑
  语义保证「改完断点，下次启动就从那里接着跑」；流水线运行中只放行
  readonly 与门内回退映射，写操作要求先停止（防止对运行中的内存状态做手术）。

安全纪律：
- destructive 工具一律先归档再删除（复用 versions/rollback 归档惯例），可恢复；
- set_setting 只认白名单键；
- 所有执行结果由调用方回显到对话区，作者永远知道 Agent 刚刚动了什么。
"""
from __future__ import annotations

import os
import re

# 微循环步骤序（与 stages.chapter_microcycle._ORDER 同源；复制以避免核心互相导入）
_STEPS = ["assemble", "draft", "enrich", "scan", "deslop", "review", "finalize"]

# 「从这里开始重跑」→ 断点 step_done（已完成至该步的上一步）
_STEP_ROLLBACK = {
    "draft": "",          # 重写草稿：断点清空 + 删草稿文件
    "enrich": "draft",    # 扩写重跑：草稿保留
    "scan": "enrich",
    "deslop": "scan",
    "review": "deslop",   # 审校重跑：审校票清空
    "finalize": "review",
}

_STEP_WORDS = {
    "草稿": "draft", "正文": "draft", "初稿": "draft",
    "扩写": "enrich", "字数": "enrich",
    "扫描": "scan",
    "去味": "deslop", "去ai味": "deslop", "去 ai 味": "deslop",
    "审校": "review", "审读": "review",
    "定稿": "finalize",
}

_SETTING_WORDS = {
    "人工审校": ("gates", "review_mode", "manual", "auto"),
    "ai审校": ("gates", "review_mode", "auto", "manual"),
    "审校": ("gates", "review_enabled", True, False),
    "连写": ("writing", "auto_gate", True, False),
    "章会话": ("writing", "chapter_session", True, False),
    "离峰": ("writing", "offpeak_run", True, False),
}

SETTING_WHITELIST = {
    ("gates", "review_mode"), ("gates", "review_enabled"),
    ("writing", "auto_gate"), ("writing", "chapter_session"),
    ("writing", "offpeak_run"), ("writing", "chapter_word_target"),
}


def _fmt_status(proj: str, cfg: dict) -> dict:
    from . import state as st
    from .. import project
    state = st.load_state(proj)
    cs = st.get_chapter_step(proj)
    chapters = project.list_chapters(proj)
    last = chapters[-1] if chapters else (0, "", "")
    return {
        "stage": state.get("stage") or "（未开始）",
        "stage_label": st.STAGE_LABELS.get(state.get("stage"), state.get("stage") or "未开始"),
        "current_chapter": state.get("current_chapter") or 0,
        "chapter_step": ("%s（断点：从下一步续跑）" % cs["step_done"]) if cs.get("step_done") else "无断点",
        "total_chapters": len(chapters),
        "latest_chapter": "第%d章 %s" % (last[0], last[1]) if chapters else "尚无正文",
        "latest_words": project.count_chars(last[2]) if chapters and os.path.isfile(last[2]) else 0,
        "review_mode": (cfg.get("gates") or {}).get("review_mode") or "auto",
        "gate_status": state.get("gate_status") or {},
    }


def _tool_status(proj, cfg, args) -> dict:
    d = _fmt_status(proj, cfg)
    msg = ("当前阶段：%s · 第 %s 章 · 共 %s 章\n断点：%s\n最新：%s（%s 字）\n审校模式：%s"
           % (d["stage_label"], d["current_chapter"] or "-", d["total_chapters"],
              d["chapter_step"], d["latest_chapter"], d["latest_words"], d["review_mode"]))
    return {"ok": True, "message": msg, "data": d, "level": "info"}


def _tool_read_chapter(proj, cfg, args) -> dict:
    from .. import project
    num = int(args.get("chapter") or 0)
    chapters = {n: p for n, _t, p in project.list_chapters(proj)}
    if num not in chapters:
        return {"ok": False, "message": "没有第 %d 章的定稿正文" % num, "level": "warn"}
    text = project.read_file(chapters[num]) or ""
    excerpt = text[:1200] + ("\n…（后文省略，共 %s 字）" % project.count_chars(chapters[num])
                             if len(text) > 1200 else "")
    return {"ok": True, "message": "第 %d 章正文：\n%s" % (num, excerpt), "level": "info"}


def _archive(proj: str, src: str, tag: str) -> None:
    """删除前归档到 pipeline_debug/agent_tools/（可恢复）"""
    import shutil
    import datetime
    if not os.path.isfile(src):
        return
    roll = os.path.join(proj, "pipeline_debug", "agent_tools",
                        "%s_%s" % (tag, datetime.datetime.now().strftime("%m%d_%H%M%S")))
    os.makedirs(roll, exist_ok=True)
    shutil.copy2(src, os.path.join(roll, os.path.basename(src)))


def _tool_rollback_step(proj, cfg, args) -> dict:
    from . import state as st
    from .. import project
    num = int(args.get("chapter") or 0)
    to_step = str(args.get("to_step") or "")
    if to_step not in _STEP_ROLLBACK:
        return {"ok": False, "message": "未知的回退目标步骤：%s" % to_step, "level": "warn"}
    step_done = _STEP_ROLLBACK[to_step]
    # 保留既有 outline_fp：细纲没变，断点不作废（重写草稿除外——断点整体清空）
    prev_fp = st.get_chapter_step(proj).get("outline_fp", "")
    st.save_chapter_step(proj, num, step_done=step_done,
                         draft_path=os.path.relpath(project.chapter_draft_path(proj, num), proj)
                         if step_done else "",
                         votes=[], outline_fp=prev_fp)
    if step_done == "":   # 重写草稿：草稿文件一并归档删除
        draft = project.chapter_draft_path(proj, num)
        _archive(proj, draft, "draft_ch%d" % num)
        if os.path.isfile(draft):
            os.remove(draft)
    label = {"draft": "草稿重写（断点已清，草稿已归档删除）",
             "review": "审校重跑（已投票数清空）"}.get(to_step, "%s 起重跑" % to_step)
    return {"ok": True, "level": "warn",
            "message": "第 %d 章已回退：%s。下次启动流水线将从该步继续。" % (num, label)}


def _tool_regen_outline(proj, cfg, args) -> dict:
    from .. import project
    num = int(args.get("chapter") or 0)
    path = project.get_outline_path(proj, num)
    if not os.path.isfile(path):
        return {"ok": False, "message": "第 %d 章本来就没有细纲" % num, "level": "warn"}
    _archive(proj, path, "outline_ch%d" % num)
    os.remove(path)
    return {"ok": True, "level": "warn",
            "message": "第 %d 章细纲已归档并删除。下次启动流水线会自动重新生成（旧章内断点随之作废）。" % num}


def _tool_rewrite_chapter(proj, cfg, args) -> dict:
    from .. import project
    from . import state as st, versions
    num = int(args.get("chapter") or 0)
    guidance = str(args.get("guidance") or "").strip()
    chapters = {n: p for n, _t, p in project.list_chapters(proj)}
    if num not in chapters:
        return {"ok": False, "message": "没有第 %d 章的正文可重写" % num, "level": "warn"}
    versions.snapshot(proj, num, project.read_file(chapters[num]), "agent重写前归档")
    os.remove(chapters[num])
    st.clear_chapter_step(proj)
    if guidance:
        project.write_file(os.path.join(proj, "追踪", "阶段指导.md"), guidance)
    return {"ok": True, "level": "warn",
            "message": "第 %d 章正文已归档并清除，重写指导已带入（%s）。下次启动流水线将重写本章。"
                       % (num, "含你的指导" if guidance else "无附加指导")}


def _tool_set_setting(proj, cfg, args) -> dict:
    from .. import config as cfg_mod
    key = str(args.get("key") or "")
    on = bool(args.get("on"))
    if key not in _SETTING_WORDS:
        return {"ok": False, "message": "不支持的设置项：%s（支持：%s）"
                % (key, "、".join(_SETTING_WORDS)), "level": "warn"}
    section, name, v_on, v_off = _SETTING_WORDS[key]
    value = v_on if on else v_off
    c = cfg_mod.load_config()
    c.setdefault(section, {})[name] = value
    cfg_mod.save_config(c)
    return {"ok": True, "level": "info", "message": "已%s「%s」" % ("开启" if on else "关闭", key)}


TOOLS = {
    "status": {"label": "查看流水线状态", "level": "readonly", "fn": _tool_status},
    "read_chapter": {"label": "读某章正文", "level": "readonly", "fn": _tool_read_chapter},
    "rollback_step": {"label": "回退到某步重跑", "level": "destructive", "fn": _tool_rollback_step},
    "regen_outline": {"label": "重新生成细纲", "level": "destructive", "fn": _tool_regen_outline},
    "rewrite_chapter": {"label": "重写某章（可带指导）", "level": "destructive", "fn": _tool_rewrite_chapter},
    "set_setting": {"label": "修改设置", "level": "mutate", "fn": _tool_set_setting},
}


# ---------- 指令解析（中文规则层，零成本确定性） ----------

_CN_DIGITS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_CH_NUM = r"(?:第\s*([0-9一二两三四五六七八九十]+)\s*章)?"


def _to_int(s):
    """'3'→3；'三'/'十三'→3/13（中文用户说「第三章」远多于「第3章」）"""
    if not s:
        return 0
    s = str(s)
    if s.isdigit():
        return int(s)
    if s in _CN_DIGITS:
        return _CN_DIGITS[s]
    if s.startswith("十"):
        return 10 + _CN_DIGITS.get(s[1:], 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return _CN_DIGITS.get(a, 0) * 10 + (_CN_DIGITS.get(b, 0) if b else 0)
    return 0


def parse_instruction(text: str, default_chapter: int = 0) -> tuple:
    """自然语言 → (tool, args, confidence)；None = 不是可识别的指令。

    confidence: "exact"（/前缀或强动词命中）/ "guess"（弱信号，调用方可选择性确认）
    """
    t = (text or "").strip()
    forced = t.startswith("/")
    if forced:
        t = t[1:].strip()
    if not t:
        return None

    def _num(m, fallback=0):
        return _to_int(m.group(1)) if (m and m.group(1)) else fallback

    # 章级指示（无章号时 rewrite/read 的必要条件——「这一段」「这一章的钩子」这类
    # 讨论性文本不是章级操作指令，缺此条件会产生 D 类误触发）
    m_ch = re.search(r"第\s*([0-9一二两三四五六七八九十]+)\s*章", t)
    chapter_ref = (_to_int(m_ch.group(1)) if m_ch else None,
                   bool(re.search(r"本章|这章|那章|现在的这章|最新(?:一)?章|刚才那章|上一章", t)))
    has_chapter_ref = chapter_ref[0] is not None or chapter_ref[1]

    # 回退到某步重跑（优先于重写：「重写草稿」= 回退草稿重跑，不是 rewrite_chapter）
    _rollback_verb = re.search(r"回退|退回|回到|重跑|重来|从.*重新|推倒", t) or \
        re.search(r"重写\s*(?:草稿|正文|初稿|去味|审校|扩写)", t)
    if _rollback_verb and (forced or not re.search(r"细纲", t)):
        # 「回到扩写那步再来」：回退目标优先取「回到/退回/重来」之后的步骤词
        _ctx_text = re.sub(r"^.*?(?:回到|退回|重跑|重来|推倒)", "", t) if \
            re.search(r"回到|退回|重跑|重来|推倒", t) else t
        for word, step in _STEP_WORDS.items():
            if word in _ctx_text or (word in t and word not in ("正文", "字数")):
                return ("rollback_step",
                        {"chapter": chapter_ref[0] or default_chapter, "to_step": step},
                        "exact" if forced else "guess")

    # 重写某章（可带指导：「重写第2章，铺垫再足一点」「刚才那章的结尾太仓促了，重来一遍」）
    # guess 级必须带章级指示（「重写这一段的时候…」是写作讨论，不是指令）
    m = re.search(r"重写(?:一下)?%s[，,：:、\s]*(.*)" % _CH_NUM, t)
    if m and (forced or "重写" in t):
        guidance = (m.group(2) or "").strip()
        # 残留态（「重写一遍」）：真正的修改方向写在动词前——取动词前的描述
        if guidance in ("", "一遍", "一次", "一下") or guidance in _STEP_WORDS:
            pre = re.search(r"^(.{2,24}?)(?:重写|重来|重新来)", t)
            guidance = re.sub(r"(?:刚才那章|这章|本章|最新(?:一)?章|现在的这章|上一章|第\s*[0-9一二两三四五六七八九十]+\s*章)[的]?",
                              "", pre.group(1) if pre else guidance).strip(" ，,。：:、")
        if guidance and guidance not in _STEP_WORDS and (forced or has_chapter_ref):
            return ("rewrite_chapter",
                    {"chapter": chapter_ref[0] or default_chapter, "guidance": guidance},
                    "exact" if forced else "guess")
    m = re.search(r"^(.{0,24}?)(?:重来|重新来|重写)(?:一遍|一次)?", t)
    if m and has_chapter_ref and (forced or "重写" not in t or True):
        # guidance 取「动词前的描述」（作者把修改方向写在前面：这章的开头太温了，直接从冲突切入重写一遍）
        guidance = re.sub(r"(?:刚才那章|这章|本章|最新(?:一)?章|现在的这章|上一章|第\s*[0-9一二两三四五六七八九十]+\s*章)[的]?",
                          "", m.group(1) or "").strip(" ，,。：:、")
        if guidance:
            return ("rewrite_chapter",
                {"chapter": chapter_ref[0] or default_chapter, "guidance": guidance},
                "exact" if forced else "guess")

    # 重新生成细纲（含口语：「推倒细纲重新排」「第三章细纲不行，重新出」）
    m = re.search(r"(?:重新生成|重生成|重出?|再来一份?|推倒)\s*%s\s*的?\s*细纲" % _CH_NUM, t) or \
        re.search(r"%s\s*的?\s*细纲\s*(?:重新生成|重新?出|重排|推倒)" % _CH_NUM, t) or \
        re.search(r"细纲[^\n]{0,12}(?:重新生成|重新?出|重排|推倒)", t)
    if m and (forced or "细纲" in t):
        return ("regen_outline", {"chapter": chapter_ref[0] or default_chapter},
                "exact" if forced else "guess")

    # 看某章正文（含口语：「看下第2章写成什么样了」「看看最新这章」）。
    # 负向条件：带「注意…写法/改」等修改意图后缀的是写作讨论（「重新读一遍第二章，
    # 注意时间线的写法」），不是查看指令——否则 D 类误触发。
    m = re.search(r"(?:看看?下?|读(?:一下)?|给我看)\s*%s\s*的?\s*(?:正文|内容|写成什么样)?" % _CH_NUM, t)
    _talk_about_writing = re.search(r"注意|写法|要改|应该改|改得|改一下", t)
    if m and not (guess_talk := _talk_about_writing and not forced) and \
            (forced or re.search(r"看看?下?|读|给我看", t)) and \
            ("正文" in t or "内容" in t or "什么样" in t or forced
             or chapter_ref[0] is not None or chapter_ref[1]):
        return ("read_chapter", {"chapter": chapter_ref[0] or default_chapter},
                "exact" if forced else "guess")

    # 设置开关（「关闭人工审校」「开启连写模式」；「把 AI 审校关掉，我自己来」=切人工）
    m = re.search(r"(?:把\s*)?AI\s*审校[^。\n]{0,8}(?:关掉|关闭|停用)", t)
    if m and re.search(r"我自己来|我来审|人工", t):
        return ("set_setting", {"key": "人工审校", "on": True},
                "exact" if forced else "guess")
    for word, (_sec, _name, _on, _off) in _SETTING_WORDS.items():
        if word in t and re.search(r"开启|打开|关闭|关掉|停用|切回|切换", t):
            on = bool(re.search(r"开启|打开", t))
            return ("set_setting", {"key": word, "on": on},
                    "exact" if forced else "guess")

    # 查状态（guess 级必须是询问语气——「状态写得不错」这类评价不是查询；/状态 强制放行）
    if (forced and re.search(r"状态|进度", t)) or \
            re.search(r"进度|写到哪|到哪一步|第几章", t) or \
            (re.search(r"状态", t) and re.search(r"怎么样|如何|吗|？|\?", t)) or \
            (re.search(r"现在怎么样", t)):
        return ("status", {}, "exact" if forced else "guess")

    return None


def execute(name: str, args: dict, proj: str, cfg: dict, *, pipeline_running: bool = False) -> dict:
    """执行工具。流水线运行中：readonly 放行，写操作拒绝（防对运行中的内存状态做手术）。"""
    tool = TOOLS.get(name)
    if not tool:
        return {"ok": False, "level": "warn", "message": "未知指令：%s" % name}
    if pipeline_running and tool["level"] != "readonly":
        return {"ok": False, "level": "warn",
                "message": "流水线正在运行，「%s」需要先停止流水线再执行（决策门内可用「回退」按钮）。"
                           % tool["label"]}
    try:
        return tool["fn"](proj, cfg, args or {})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "level": "error", "message": "执行失败：%s" % e}


def help_text() -> str:
    return ("可用指令（自然语言或 / 前缀）：\n"
            "· 状态：「现在进度怎么样」\n"
            "· 读章：「看看第3章正文」\n"
            "· 回退重跑：「回退到去味之前」「重跑第4章审校」\n"
            "· 重新生成细纲：「重新生成第3章的细纲」\n"
            "· 重写本章（可带指导）：「重写第2章，铺垫再足一点」\n"
            "· 设置：「关闭人工审校」「开启离峰挂机」")


# ---------- L2：LLM 意图兜底（规则未命中时的口语化泛化） ----------

_LLM_SYSTEM = """你是写作应用的指令解析器。把作者的一句话解析为应用操作。

可用工具与参数（只能输出这些工具名，不能编造）：
- status {}  查看流水线状态/进度
- read_chapter {"chapter": int}  读某章正文
- rollback_step {"chapter": int, "to_step": "draft|enrich|scan|deslop|review|finalize"}  回退到某步重跑
- regen_outline {"chapter": int}  重新生成细纲
- rewrite_chapter {"chapter": int, "guidance": str}  重写某章（guidance=作者给的修改方向）
- set_setting {"key": "人工审校|连写|章会话|离峰|审校", "on": bool}  开关设置

裁决规则：
1. 作者想「看/了解」→ read_chapter 或 status；想「重跑某一步」→ rollback_step；
   想整章推倒重来并给了方向 → rewrite_chapter；提到细纲重来 → regen_outline。
2. 信息不完整（没说哪章/哪一步/开什么）或这不是操作指令（是写作讨论、问题清单、闲聊）
   → 输出 {"tool": null}。宁可 null 不可猜。
3. 只输出一行 JSON：{"tool": "...", "args": {...}, "confidence": 0到1}；没有 tool 字段则 args 略。"""


def parse_instruction_llm(text: str, client, default_chapter: int = 0) -> tuple | None:
    """L2 意图兜底：规则层未命中时调用（调用方负责判断时机与计费）。

    信任链：工具名白名单 + args 键校验 + confidence≥0.6，任一不过返回 None。
    """
    if not text or not text.strip():
        return None
    try:
        raw = client.chat(
            "作者说：%s（当前章：%d）只输出一行 JSON。" % (text.strip(), default_chapter),
            system=_LLM_SYSTEM, temperature=0.1, phase="agent_intent")
        import json as _json
        import re as _re
        m = _re.search(r"\{.*\}", raw or "", _re.S)
        if not m:
            return None
        d = _json.loads(m.group(0))
        tool = str(d.get("tool") or "")
        if tool not in TOOLS:
            return None
        conf = float(d.get("confidence") or 0)
        if conf < 0.6:
            return None
        args = d.get("args") or {}
        if tool == "rollback_step" and args.get("to_step") not in _STEP_ROLLBACK:
            return None
        if tool == "read_chapter" or tool == "regen_outline" or tool == "rewrite_chapter":
            args["chapter"] = int(args.get("chapter") or default_chapter)
        if tool == "set_setting" and str(args.get("key") or "") not in _SETTING_WORDS:
            return None
        return (tool, args, "llm")
    except Exception:  # noqa: BLE001
        return None
