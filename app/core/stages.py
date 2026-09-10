# -*- coding: utf-8 -*-
"""流水线各阶段实现：核心设定 / 全书大纲 / 章节细纲 / 章节微循环

每个 stage 是同步函数，由 orchestrator 在工作线程中顺序调度。
ctx 约定属性：
  proj: 项目路径
  router: ModelRouter
  cfg: 应用配置
  log(level, msg): 日志回调
  step(num, step_key): 微循环步骤回调
  checkpoint(): 暂停/停止检查点（在每次 LLM 调用前后调用）
"""
import hashlib
import json
import logging
import os
import re
from contextlib import contextmanager as _contextmanager

from .. import config as cfg_mod
from .. import project, prompts, deslop, mustscan, wb
from ..llm import clean_llm_output
from ..prompts import scene_cards
from . import gates, memory, scan, state as st, versions
from .shared_prefix import chapter_header, project_header
from .. import presets as genre_presets


class StageError(Exception):
    pass


class PipelineStopped(Exception):
    """用户停止流水线时抛出"""
    pass


# 阶段标识：预设 stage_params 的键 + 章级配置快照的 phase 字段（双端同名，勿改字面量）
PHASE_CORE_SETTING = "core_setting"
PHASE_VOLUME_OUTLINE = "volume_outline"
PHASE_WORLDBOOK = "worldbook"
PHASE_OUTLINE = "outline"
PHASE_PROSE = "prose"
PHASE_ENRICH = "enrich"
PHASE_TRIM = "trim"
PHASE_DESLOP = "deslop"
PHASE_REVIEW = "review"
PHASE_ROOT_CAUSE = "root_cause"
PHASE_REVIEW_FIX = "review_fix"
PHASE_TRACKING = "tracking"
PHASE_CH_SUMMARY = "chapter_summary"
PHASE_G_SUMMARY = "global_summary"
PHASE_CANON_AUDIT = "canon_audit"
PHASE_CANON_AUDIT_REVIEW = "canon_audit_review"   # W-7：级联终审（此前相位表点不到，档位写死）


def _wb_rg_blocks(proj: str, cfg: dict, num: int = 0) -> tuple:
    """世界书/正则注入块内核（proj/cfg 版，供流水线与共写两条调用链共用）

    语义按设置 writing.regex_semantics：logic=逻辑约束规则集（默认）/ regex=字面正则样本。
    num 下传给装配内核（app/wb.py）：本章锚点决定条目激活优先级，近章登记条目升档。
    第三项是装配元信息（activated/dropped/budget）——章级配置快照（P2）的唯一来源。
    """
    sem = cfg.get("writing", {}).get("regex_semantics", "logic")
    meta = wb.assemble(proj, num=num, budget=2000,
                       anchors=project.worldbook_anchors(proj, num))
    return (meta["text"], project.regex_block(proj, sem), meta)


def _worldbook_regex_blocks(ctx, num: int = 0) -> tuple:
    """ctx 薄封装（方案 §4.1：.format 注入 + 空串回退占位）"""
    return _wb_rg_blocks(ctx.proj, ctx.cfg, num)


def _compose_guidance(guidance: str, cfg: dict) -> str:
    """重写指导 + 全局写作偏好（文风/禁忌/节奏）合成注入正文 prompt

    全局偏好来自 设置→写作偏好，独立保存、注入所有章节，作者不改代码就能调全书文风。
    """
    w = cfg.get("writing", {})
    parts = []
    if (guidance or "").strip():
        parts.append(guidance.strip())
    prefs = []
    if (w.get("style_pref") or "").strip():
        prefs.append(f"文风：{w['style_pref'].strip()}")
    if (w.get("taboos") or "").strip():
        prefs.append(f"禁忌（绝不出现）：{w['taboos'].strip()}")
    if (w.get("pace_pref") or "").strip():
        prefs.append(f"节奏：{w['pace_pref'].strip()}")
    if prefs:
        parts.append("【全局写作偏好（每章必须遵守）】\n" + "\n".join(prefs))
    return "\n\n".join(parts) if parts else "无特殊指导"

# ---- 动态口头禅黑名单（封禁式去味的"禁A生B"打地鼠解法：统计实际高频词限量）----

_TIC_LEXICON = [
    "指腹", "攥", "没说话", "顿了顿", "指节发白", "台灯", "眯起眼", "深吸一口气",
    "勾起", "眸", "睫毛", "喉咙", "后颈", "指节", "垂下眼", "颔首", "挑眉", "咬了咬牙",
    "心中一凛", "呼吸一滞", "眼皮跳了跳", "抱着手臂", "捏了捏眉心",
]


def _genre_block(proj: str, stage: str = "prose") -> str:
    """项目当前题材预设 → 注入正文/细纲 prompt（从 pipeline_state 现读，切换后下一章生效）

    Args:
        stage: v2 分环节特化键（core_setting/outline/unit_outline/prose/worldbook/review）
               无效或空 → 走 v1 genre_block 全量注入（向后兼容）
    """
    try:
        pid = st.load_state(proj).get("genre_preset", "")
    except Exception:
        pid = ""
    if not pid:
        return "（本书未启用题材预设，按通用网文规范写作）"
    if stage and stage in st.STAGE_KEY_SET:
        try:
            return genre_presets.genre_block_for(pid, stage)
        except Exception:
            pass
    # 兜底：v1 全量注入
    try:
        return genre_presets.genre_block(pid)
    except Exception:
        return "（本书未启用题材预设，按通用网文规范写作）"


def _genre_review_extra(proj: str) -> str:
    """题材预设的审校专项附加项（双端同名符号，改动须同步）

    W0c 前 TUI 的终审装配引用了本函数却未定义——每次审校都抛 NameError。
    v1 的 review_extra 与 v2 的 stage_hints.review 都写在这张预设上，共用同一个槽，
    否则后者只能在设置页里看着，永远进不了审校 prompt。
    """
    try:
        pid = st.load_state(proj).get("genre_preset", "")
        parts = [x for x in (genre_presets.review_extra(pid),
                             genre_presets.stage_hint(pid, "review")) if x]
        return "\n\n".join(parts) or "（无题材专项检查）"
    except Exception:
        return "（无题材专项检查）"


def _preset_id(proj: str) -> str:
    """项目当前题材预设 id；state 读不到就按「无预设」处理

    参数档是锦上添花，不能让一次 state 异常把整条流水线拖停。
    """
    if not proj:
        return ""
    try:
        return st.load_state(proj).get("genre_preset", "") or ""
    except Exception:
        return ""


# 内置机械相位表（体验轮 B1'）：不需要发散思考的调用关思考、收 max_tokens。
# 合并语义：genre 预设显式配置同相位时压过内置（setdefault，尊重预设作者）；
# 创作相位（prose/outline/review）不内置——思考档位留给 genre/连接配置。
BUILTIN_PHASE_PARAMS = {
    # outline：细纲排期是结构化设计任务，low 档推理足够（v4 默认 high 是 outline
    # 38k 输出/笔的主因）；档位由能力对照验证兜底，genre 显式配置可压过
    "outline":         {"reasoning_effort": "low"},
    "tracking":        {"thinking": "disabled", "max_tokens": 8192},
    "chapter_summary": {"thinking": "disabled", "max_tokens": 2048},
    "global_summary":  {"thinking": "disabled", "max_tokens": 2048},
    "deslop":          {"thinking": "disabled", "max_tokens": 16384},
    "enrich":          {"thinking": "disabled", "max_tokens": 16384},
    # 清算预扫档（v0.19 级联）：flash+low 全文预扫，干净采信、有硬伤才升 pro 复核
    # flagged 项（E5a 实测：low 检出引文真实性 88%，单次过；pro 单价 ×3 只花在刀刃上）
    "canon_audit":     {"thinking": "enabled", "reasoning_effort": "low",
                        "max_tokens": 8192},
    # 审校=六维对照检查表任务（埋雷实测 disabled 召回 4/4 vs high 3/4、引文全真、
    # 假阳性 0；单票 5.2k→0.6k tok、82s→5.4s）。跨章对账由清算（pro 严格档）把守。
    # 需要更强审校时预设显式覆盖：{"review": {"thinking": "enabled", "reasoning_effort": "high"}}
    "review":          {"thinking": "disabled"},
}


def preset_param_layers(proj: str) -> dict:
    """预设喂给路由的两层参数覆盖（ModelRouter kwargs）：一次 state 读取取全

    阶段档随「下一章生效」重绑；采样基线与它同源于同一个预设，不单独走第二条链。
    内置机械相位表在此合并：genre 显式配置同相位时压过内置表。
    """
    pid = _preset_id(proj)
    sp = genre_presets.stage_params(pid)
    for ph, kv in BUILTIN_PHASE_PARAMS.items():
        tgt = sp.setdefault(ph, {})
        for k, v in kv.items():
            tgt.setdefault(k, v)     # 键级 setdefault：genre 显式键优先，内置只补缺
    return {"stage_params": sp,
            "payload_defaults": genre_presets.sampling(pid)}


def _author_note(proj: str) -> str:
    """预设「作者按」→ 正文 prompt 近端注入（SillyTavern Author's Note 语义）"""
    return genre_presets.author_note(_preset_id(proj)) or "（本章无作者按）"


def _total_chapters(proj: str, chapter_words: int) -> int:
    """计划总章数（场景卡轴变体用）；未规划返回 0——轴按章号照样轮转，不造假值"""
    try:
        total = int(st.load_state(proj).get("total_chapters", 0) or 0)
    except Exception:
        total = 0
    if not total:
        try:
            total = project.planned_chapters(proj, chapter_words)
        except Exception:
            total = 0
    return total


def _tic_blacklist(proj: str, last_n: int = 10) -> str:
    """写作/去味 prompt 的「红线」段：本地统计的过量口头禅 + 预设声明的题材专属限量

    两段同属「写时就要避开」，合在一处注入；题材段走这个槽而不是题材块，
    是因为扩写/压缩/去味改写三张模板只有本槽、没有题材块。
    """
    chapters = project.list_chapters(proj)[-last_n:]
    if chapters:
        text = "".join(project.read_file(p2) for _n, _m, p2 in chapters)
        hits = []
        per_chapter = len(chapters)
        for word in _TIC_LEXICON:
            cnt = text.count(word)
            if cnt >= max(4, per_chapter * 0.8):
                hits.append(f"{word}（近期{cnt}次）")
        if hits:
            measured = "以下词近期已过量，本章每词最多出现1次：" + "、".join(hits)
        else:
            measured = "（近期无过量口头禅）"
    else:
        measured = "（样本不足，暂无）"
    genre = genre_presets.deslop_extra(_preset_id(proj))
    if not genre:
        return measured
    return measured + "\n题材专属限量（本书腔调配额，超出即算 AI 味）：" + genre


# 契约段前言：四张重写模板共用，单点措辞（分散抄四份必然互相漂）
_MUST_POLICY = (
    "优先级：作者显式指令 > 本节 must 契约 > 世界书 > 本章细纲 > 题材预设。\n"
    "改写时**不得为凑下列规则改动字数或删掉本章信息增量**；某条契约在现有正文里"
    "本就没有落点时，保持现状并在结尾用一句话说明，不要自行绕开，"
    "也不要新增主线事件去补。"
)


def _must_block(proj: str, cfg: dict = None) -> str:
    """扩写/压缩/去味/局部改写四张模板的近端契约段（与 _tic_blacklist 同侧）

    这四张模板只有本槽、没有题材块，也从不带契约——而它们全在整章/整段重写正文：
    为凑字数新写的句子、为压缩删掉的段落，都可能悄悄破掉 must 规则，只能等终审
    概率性地抓。这里把 must 条直接送到改写的现场。

    全量注入不截断：静默丢规则正是本机制要防的事故。max_chars 只作病态输入兜底，
    且过滤路径是整行取舍 + 显式声明漏了几条，不会给模型半句残规则。
    """
    sem = ((cfg or {}).get("writing", {}) or {}).get("regex_semantics", "logic")
    return _MUST_POLICY + "\n" + project.regex_block(proj, sem, 8000, levels=("must",))


def _used_setpieces(proj: str) -> str:
    """从追踪/上下文 提取已用名场面清单"""
    ctx = project.read_file(project.get_tracking_path(proj, "上下文"))
    if "已用名场面" in ctx:
        start = ctx.find("已用名场面")
        return ctx[start:start + 300]
    return "（暂无名场面登记——本章若出现全书级大意象，属首次使用）"


def _roster(proj: str) -> str:
    """核心设定的主要角色表（花名册基准，追踪更新不得丢角色）"""
    core = project.read_file(os.path.join(proj, "设定", "题材定位.md"))
    m = re.search(r"##\s*主要角色表(.*?)(?=\n##\s|\Z)", core, re.S)
    return m.group(1).strip()[:1500] if m else "（设定中未找到主要角色表）"


def _unit_contract(proj: str, start: int) -> str:
    """从大纲抽取覆盖当前章节区间的单元段落（对账基准）"""
    outline = project.read_file(os.path.join(proj, "大纲", "大纲.md"))
    if not outline:
        return "（无大纲）"
    blocks = re.split(r"\n(?=##\s)", outline)
    hit = [b for b in blocks if re.search(rf"第\s*{start}\s*章|{start}\s*[-—~]\s*\d+\s*章|\d+\s*[-—~]\s*{start}\s*章", b)]
    text = "\n\n".join(hit)[:1200] if hit else outline[:1200]
    return text + "\n（若以上单元含承诺事件，本批细纲必须逐章对账）"


# ============ 章级配置快照（P2）：这章吃了什么，全部留在 正文/.annotations/第N.json ============
#
# 质量飞轮的口径是「用户人工点赞」，前提是点赞时能说清这一章的生成条件；
# state.json 由多线程读写且要背 500 章的体量，所以快照进标注仓、不进 state。

def begin_gen_trace(ctx):
    """开一章的生成轨迹（orchestrator 在每章起点调用；重复调用即重置）"""
    ctx.gen_trace = []
    ctx.gen_worldbooks = {}


def _trace(ctx):
    """取轨迹容器：ctx 没配合（共写/探针替身）就返回 None，调用方静默跳过"""
    tr = getattr(ctx, "gen_trace", None)
    return tr if isinstance(tr, list) else None


def _record_call(ctx, phase: str, slot: str, client, prompt: str):
    """记一次实际发生的调用：模型/槽/相位 + prompt 指纹 + 真实下发的采样"""
    tr = _trace(ctx)
    if tr is None:
        return
    tr.append({"phase": phase or "", "slot": slot,
               "model": getattr(client, "model", "") or "",
               "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
               "sampling": dict(getattr(client, "last_sampling", None) or {}),
               "degraded": bool(getattr(client, "last_degraded", False))})


def _record_worldbook(ctx, phase: str, meta):
    """记本章某个装配点吃了哪些世界书条目（activated 带触发原因与内容哈希）"""
    if _trace(ctx) is None or not isinstance(meta, dict):
        return
    ctx.gen_worldbooks[phase] = {
        "budget": meta.get("budget", 0),
        "activated": [{"id": a.get("id", ""), "name": a.get("name", ""),
                       "why": a.get("why", ""), "hash": a.get("hash", "")}
                      for a in meta.get("activated") or [] if a.get("kind") != "prose"],
        "dropped": [d.get("name", "") for d in meta.get("dropped") or []],
    }


def write_gen_config(ctx, num: int) -> dict:
    """汇总本章轨迹 → 落标注仓（返回快照本身；写失败只记日志，绝不断流水线）"""
    layers = preset_param_layers(getattr(ctx, "proj", ""))
    cfg = {"ts": st._now_str(), "num": num,
           "preset": _preset_id(getattr(ctx, "proj", "")),
           "stage_params": layers["stage_params"], "sampling": layers["payload_defaults"],
           "worldbook": getattr(ctx, "gen_worldbooks", {}) or {},
           "calls": list(getattr(ctx, "gen_trace", None) or [])}
    try:
        project.set_chapter_gen_config(ctx.proj, num, cfg)
    except Exception as e:  # noqa: BLE001
        ctx.log("warn", f"第 {num} 章生成配置快照写入失败（不影响正文）：{e}")
    return cfg


def _stream(ctx, slot: str, prompt: str, label: str = "", *, phase: str = "") -> str:
    """流式 LLM 调用：增量实时转发到 UI（ctx.stream_chunk），返回完整文本

    label 非空时先通知 UI 阶段切换（清空流式区并显示阶段标签），
    实现"人和 AI 一起读"的全程流式创作视图。

    phase 是阶段标识（PHASE_*），供预设 stage_params 选档与章级配置快照使用；
    它不进 HTTP 请求体，只影响采样参数解析。
    """
    if label:
        ctx.stream_stage(label)
    # 阶段选槽：预设 stage_params[phase].slot 覆盖默认槽（如「正文走写作槽、审校走强模型槽」）
    slot = genre_presets.stage_slot(_preset_id(getattr(ctx, "proj", "")), phase) or slot
    def on_chunk(c):
        ctx.stream_chunk(c)
    def on_reasoning(r):
        ctx.stream_reasoning(r)
        # T4.3 M1：带槽位上下文增量 → Agent Console 分组留存（缺方法时静默降级，兼容旧 ctx）
        st_thinking = getattr(ctx, "stream_thinking", None)
        if callable(st_thinking):
            st_thinking(slot, r)
    client = ctx.router.client(slot)
    # 停止请求要能打断「本次」流式，而不是等它跑完才在下一个 checkpoint 生效：
    # 干净章最近的 checkpoint 在正文落盘之后，中间还白烧一轮多票审校。
    # 旧 ctx 桩（测试 FakeCtx）无此属性 → 恒 False，行为与改动前一致。
    _abort = (lambda: bool(getattr(ctx, "stopped", False)))
    text = clean_llm_output(client.chat_stream(
        prompt, on_chunk=on_chunk, on_reasoning=on_reasoning, phase=phase,
        abort=_abort))
    _record_call(ctx, phase, slot, client, prompt)
    if getattr(client, "last_aborted", False):
        raise PipelineStopped()
    return text


# ---- 章会话辅助（v0.19）：同章阶段共享 system 前缀与正文历史；关闭时回退单轮 ----

def _session_usable(session) -> bool:
    return session is not None and getattr(session, "enabled", False)


def _save_session_checkpoint(ctx, session, where: str = "") -> None:
    """W-3 章内里程碑落盘（append-only，只写新行）。

    改造前整章只在定稿后 save 一次 ⇒ 崩在章中＝整卷栈停在上一章末尾，
    下一章起的全部历史都要重打；现在崩点最多回退到一个里程碑，续跑时
    open_chapter 的同章重入会把本章半截尝试截掉（不留双份正文）。"""
    if not (_session_usable(session) and hasattr(session, "save")):
        return
    try:
        session.save()
    except Exception as e:  # noqa: BLE001
        ctx.log("warn", f"卷会话消息栈落盘失败（不阻断{'·' + where if where else ''}）：{e}")


def _session_seed(session, prose_text: str):
    """会话栈尚无正文（断点续跑等场景）时先播种，保证历史前缀完整。"""
    if _session_usable(session) and session.turn_count() == 0 and prose_text:
        session.restart_with_prose(prose_text)
    return session


def _session_ask(ctx, session, slot: str, prompt: str, label: str = "", *,
                 phase: str = "", temperature=None, stream=True):
    """章会话追加轮调用：镜像 _stream 的槽位路由/阶段标签/流式回显/中止语义。"""
    if label:
        ctx.stream_stage(label)
    resolved = genre_presets.stage_slot(_preset_id(getattr(ctx, "proj", "")), phase) or slot
    client = ctx.router.client(resolved)
    _abort = (lambda: bool(getattr(ctx, "stopped", False)))
    text = session.ask(
        prompt,
        client=client,
        on_chunk=ctx.stream_chunk if stream else None,
        on_reasoning=ctx.stream_reasoning,
        phase=phase, temperature=temperature, abort=_abort,
        postprocess=clean_llm_output)
    _record_call(ctx, phase, resolved, client, prompt)
    if getattr(client, "last_aborted", False):
        raise PipelineStopped()
    return text


# ============ 相位旗标与 span 改写器（v0.20 成本战役 E1.1/O2/E4.1）============

def _phase_param(ctx, phase: str, key: str, default=None):
    """读相位旗标（router.stage_params[phase][key]）——预设旗标经 presets.stage_params
    校验透传，内置机械相位表不设旗标。router 无该相位/键时返回 default。"""
    sp = getattr(getattr(ctx, "router", None), "stage_params", None) or {}
    return (sp.get(phase) or {}).get(key, default)


_MISSING = object()


@_contextmanager
def _stage_param_override(ctx, phase: str, **kv):
    """临时覆盖 router.stage_params[phase] 的若干键（退出恢复原值）。

    用途：调整四的紧凑票回退重投（max_tokens 1400）。router 的 stage_params 是
    与全部客户端共享的同一 dict——原位改键客户端立即看到；仅在单线程窗口内使用
    （副本票并发开始前），退出时逐键恢复。"""
    sp = getattr(getattr(ctx, "router", None), "stage_params", None)
    if not isinstance(sp, dict) or not kv:
        yield
        return
    layer = dict(sp.get(phase) or {})
    saved = {k: layer.get(k, _MISSING) for k in kv}
    layer.update(kv)
    sp[phase] = layer
    try:
        yield
    finally:
        restored = dict(sp.get(phase) or {})
        for k, v in saved.items():
            if v is _MISSING:
                restored.pop(k, None)
            else:
                restored[k] = v
        sp[phase] = restored


def _pace_after_long_call(ctx, cfg_mod, session, default_seconds: int = 0):
    """S5：长生成后的注册窗口节拍——给服务端缓存单元注册留时间。

    `writing.session_pace_seconds` 控制时长，**默认 0（关闭）**——由实验预设/用户
    设置显式开启（如 s3_pace 的 45s）。仅会话启用时生效；休眠可被 ctx.stopped 打断。
    """
    try:
        seconds = int((ctx.cfg.get("writing", {}) or {}).get("session_pace_seconds",
                                                             default_seconds))
    except (TypeError, ValueError):
        seconds = default_seconds
    if seconds <= 0 or not _session_usable(session):
        return
    import time as _time
    _end = _time.monotonic() + seconds
    while _time.monotonic() < _end:
        if bool(getattr(ctx, "stopped", False)):
            return
        _time.sleep(0.5)


def _merge_audit_effort_low(stage_params) -> bool:
    """调整三（writing.audit_effort_low）：canon_audit 层原位合并 reasoning_effort=low。

    客户端与 router 共享同一 stage_params dict——原位改键当章即生效；pro 终审
    自建显式档位（canon_audit_review）不受影响。已 low 则幂等返回 False；
    thinking 未显式配置时补 enabled（effort 仅思考模式生效，W-7）。"""
    if not isinstance(stage_params, dict):
        return False
    if (stage_params.get("canon_audit") or {}).get("reasoning_effort") == "low":
        return False
    layer = dict(stage_params.get("canon_audit") or {})
    layer.setdefault("thinking", "enabled")
    layer["reasoning_effort"] = "low"
    stage_params["canon_audit"] = layer
    return True


def _apply_volume_effort(ctx, proj: str, num: int) -> None:
    """调整三：卷内 reasoning_effort 统一（writing.volume_effort，缺省空=关闭）。

    - 设了档位 → 写入三个会话槽位客户端的实例 effort（最弱层：显式实参/预设
      stage_params 仍可按相位覆盖——机械相位的显式降档不受影响）；
    - 档位与卷号钉进 pipeline_state：同卷内改档 → 拒绝并沿用钉住值（Think Max
      的 system 前端注入会打死冻结头，卷界才允许切换）；
    - 关闭（空串）时零动作——请求体与改造前逐字节一致。
    """
    try:
        effort = str(((ctx.cfg or {}).get("writing", {}) or {})
                     .get("volume_effort", "") or "").strip().lower()
    except AttributeError:
        effort = ""
    if effort not in ("low", "high", "max"):
        if effort:
            ctx.log("warn", f"volume_effort={effort!r} 非法（仅 low/high/max），忽略")
        return
    volume = 0
    try:
        from .volume_session import resolve_volume_number
        volume = resolve_volume_number(proj, num)
    except Exception:  # noqa: BLE001
        pass
    try:
        state = st.load_state(proj)
        pinned = str(state.get("volume_effort", "") or "")
        pinned_vol = int(state.get("volume_effort_vol", 0) or 0)
        if pinned and pinned_vol == volume and pinned != effort:
            ctx.log("warn", f"卷 {volume} effort 已钉住 {pinned}，拒绝中途改为 {effort}"
                            f"（卷内统一纪律，卷界才可切换）")
            effort = pinned
        for slot in (cfg_mod.SLOT_WRITING, cfg_mod.SLOT_REVIEW, cfg_mod.SLOT_HELPER):
            try:
                ctx.router.client(slot).reasoning_effort = effort
            except Exception:  # noqa: BLE001
                continue
        if pinned != effort or pinned_vol != volume:
            state["volume_effort"] = effort
            state["volume_effort_vol"] = volume
            st.save_state(proj, state)
        ctx.log("info", f"第 {num} 章 卷 effort 统一为 {effort}（volume_effort，卷 {volume}）")
    except Exception as e:  # noqa: BLE001
        ctx.log("warn", f"volume_effort 应用失败（不阻断）：{e}")


# ============ S4 指令库前置（成本优化方案 v3 §3/S4；仅卷会话模式触达）============

# S4-c：追踪卷会话轮的冗余节引用行——{character_state}/{foreshadow_table}/
# {timeline}/{old_context}/{worldbook} 五节与本章开幕轮/会话历史逐字重复，
# 卷会话模式下替换为本行；{roster}（花名册）是追踪的功能性输入，保留。
TRACKING_SESSION_REF = "（角色状态/伏笔/时间线以本章开幕轮共享上下文为准，本步输出其增量更新）"


def _volume_prose_opening_values(*, num: int, word_target: int, next_brief: str,
                                 user_guidance: str, user_ideas: str,
                                 used_setpieces: str, craft_block: str,
                                 author_note: str, tic_blacklist: str) -> str:
    """S4-a：卷会话开幕轮的「本章动态值」段。

    PROSE 指令体已模板化冻结进卷会话 system（volume_session.volume_system_text），
    开幕轮只携带 chapter_header（volume_mode，S4-b）+ 逐章动态值 + 一行指令库
    执行指针。条目名与 prose_instruction_library 的引用行逐名对应——指令库说
    「以开幕轮给定的 X 为准」，这里就提供 X；静态部分一字不重复（重复即烧 miss）。
    """
    return "\n".join([
        "## 本章动态值（逐章变化；写作指令与固定红线见系统「写作指令库」，不在此重复）",
        f"- 本章章号：第 {num} 章",
        f"- 字数目标：{word_target} 字",
        f"- 下一章预告：{next_brief}",
        f"- 用户补充指导：{user_guidance}",
        f"- 用户创作想法：{user_ideas}",
        f"- 名场面不复用清单：{used_setpieces}",
        f"- 本章工艺路线：{craft_block}",
        f"- 作者按：{author_note}",
        "- 口头禅黑名单：",
        tic_blacklist,
        "",
        "按写作指令库执行本章写作。",
    ])


def _dyn_directives(ctx, phase: str) -> str:
    """预设旗标 → prompt 尾部动态指令块（E1.2/O2）。

    L1/s1 的 budget forcing 证据：把目标长度显式写进 prompt 能实际改变输出与思考
    长度。未配置任何旗标时返回空串——**基线请求体逐字节不变**（变量隔离纪律，
    对照实验的公共前提）。放尾部是缓存纪律：动态内容永远殿后（shared_prefix 三定律）。
    """
    lines = []
    lb = _phase_param(ctx, phase, "length_budget")
    if lb:
        lines.append(f"- 输出总长硬上限：约 {lb} 字。超出上限即视为任务失败，"
                     "先收束场景再收尾，宁少勿超。")
    tb = _phase_param(ctx, phase, "think_budget")
    if tb:
        lines.append(f"- 思考预算：总思考量控制在约 {tb} tokens 内，按当前证据直接给结论，"
                     "不要反复重推已确定的点。")
    struct = _phase_param(ctx, phase, "output_structure")
    if struct == "scene_card":
        lines.append("- 输出结构：正文之前先输出「本章场景卡」（每场景一行："
                     "地点｜在场人物｜事件推进｜章末钩子归属），场景卡之后空一行直接输出正文；"
                     "场景卡不算正文字数。")
    if not lines:
        return ""
    return "\n\n## 输出预算与结构（预设硬约束，优先级高于常规写法取舍）\n" + "\n".join(lines)


def _use_session(ctx, session, slot: str, phase: str) -> bool:
    """本相位是否走章会话栈（E4.1 的 N2 红线守卫）。

    会话栈的历史前缀属于「栈基座模型」的缓存域：某相位经 stage_params.slot 外迁到
    异构网关（qwen/doubao 等）时，整栈重发=逐 token 全价 miss（缓存按模型索引清零，
    ProjectDiscovery 实测 7% 命中的翻车路径）。此时该相位降级为无栈单发——显式喂
    所需文本（stateless），栈内其余相位不动。"""
    if not _session_usable(session):
        return False
    resolved = genre_presets.stage_slot(_preset_id(getattr(ctx, "proj", "")), phase) or slot
    if resolved == slot:
        return True
    c_ext = ctx.router.client(resolved)
    c_base = ctx.router.client(slot)
    return (c_ext.base_url, c_ext.model) == (c_base.base_url, c_base.model)


def _rewrite_phase(ctx, session, slot: str, phase: str, template: str, kw: dict,
                   *, prose: str, label: str = "", stream: bool = True,
                   temperature=None, strip_static: str = "",
                   strip_replacement: str = "") -> str:
    """修订类相位统一入口（deslop/trim/enrich/review_fix 四相位共用）。

    strip_static（调整一，instruction_in_head）：静态指令段已在卷级冻结头时，
    会话轮剥掉同段换一行指针——会话/单轮路径不受影响（单轮路径没有冻结头）。
    剥不干净（模板版式变了）出声告警并保留全文——静默重复计价比报错更糟。

    stage_params[phase].output_mode == "span" 时先走 span 路径：
      标注正文 → 模型回 JSON 编辑列表 → apply_spans 合并 → 会话内固化合成轮
      （user=标注稿请求，assistant=合并后全文——历史里"最近一条章正文消息"
      仍指向最新正文，后续相位的 {prose} 历史引用语义不变）；
    span 输出畸形/空/无变化 → 回退全量路径重试一次（E1.1 kill criteria），
    全量路径即改造前的 session/stream 双分支，语义逐字保留。

    返回改写后全文；完全失败返回空串（调用方既有守卫接管）。
    """
    use_sess = _use_session(ctx, session, slot, phase)
    if _phase_param(ctx, phase, "output_mode") == "span" and prose.strip():
        from . import span_edit
        t_before = session.turn_count() if use_sess else 0
        kw_span = dict(kw)
        kw_span["prose"] = span_edit.annotate(prose)
        try:
            if use_sess:
                req = prompts.session_turn_text(template, prose_sentinel="").format(**kw_span) \
                    + "\n\n" + span_edit.OUTPUT_CONTRACT
                client = ctx.router.client(
                    genre_presets.stage_slot(_preset_id(ctx.proj), phase) or slot)
                ctx.last_prompt = req
                raw = clean_llm_output(client.chat_turn(
                    session.snapshot() + [{"role": "user", "content": req}],
                    on_chunk=ctx.stream_chunk, phase=phase,
                    temperature=temperature,
                    abort=(lambda: bool(getattr(ctx, "stopped", False)))))
                if getattr(client, "last_aborted", False):
                    raise PipelineStopped()
                _record_call(ctx, phase, slot, client, req)
            else:
                req = template.format(**kw_span) + "\n\n" + span_edit.OUTPUT_CONTRACT
                ctx.last_prompt = req
                raw = clean_llm_output(_stream(ctx, slot, req, label=label,
                                               phase=phase))
            spans = span_edit.parse_spans(raw)
            merged = span_edit.apply_spans(prose, spans)
            if merged.strip() and merged != prose:
                if use_sess:
                    session.commit_turn(req, merged)
                try:
                    stats = span_edit.span_stats(prose, spans)
                    ctx.log("info", f"span 修订生效：{stats['ops']}，"
                                    f"点名 {len(stats['paras_touched'])}/{stats['total_paras']} 段")
                except Exception:
                    pass
                span_edit.record_event(ctx.proj, phase, "merged")
                return merged
            if merged == prose:
                span_edit.record_event(ctx.proj, phase, "zero_edit")
                return prose   # 模型认为无需改动：零编辑是合法结论，不算失败
            span_edit.record_event(ctx.proj, phase, "fallback", "empty_merge")
            ctx.log("warn", "span 合并结果为空，回退全量模式重试")
        except PipelineStopped:
            raise
        except Exception as e:  # noqa: BLE001
            if use_sess:
                session.rollback_to(t_before)   # span 尝试未固化，栈保持原状
            span_edit.record_event(ctx.proj, phase, "fallback", str(e))
            ctx.log("warn", f"span 输出无效（{e}），回退全量模式重试")
    # —— 全量路径（改造前原语义）——
    prompt = template.format(**kw)
    ctx.last_prompt = prompt
    if use_sess:
        _session_seed(session, prose)
        turn_text = prompts.session_turn_text(template).format(**kw)
        if strip_static:
            if strip_static in turn_text:
                turn_text = turn_text.replace(
                    strip_static, strip_replacement or "（本段规则见系统卷级冻结指令，不重复）", 1)
            else:
                ctx.log("warn", f"{label or phase} 会话轮未匹配到静态指令段（模板变了？），本轮保留全文指令")
        ctx.last_prompt = turn_text
        return _session_ask(ctx, session, slot, turn_text, label=label,
                            phase=phase, stream=stream, temperature=temperature)
    return _stream(ctx, slot, prompt, label=label, phase=phase)


# ============ 阶段①：核心设定 ============

# ---- 调整五：deslop 定点修复（writing.deslop_pinned，缺省关）----
DESLOP_PINNED_MAX_PARAS = 2      # 命中段上限：超过即回退整章重写
DESLOP_PINNED_MAX_GROW = 0.25    # 替换后全文长度变化上限，超过即回退

_PINNED_LINE_RE = re.compile(r"^\s*⟦P(\d{1,4})⟧\s*(.+)$", re.M)


def _findings_para_map(prose: str, findings: list) -> dict:
    """finding（带 start/end 偏移）→ 段号映射（段号口径与 span_edit.annotate 一致：
    非空行按出现顺序从 1 编号）。偏移越界/缺 start 的 finding 忽略。"""
    lines = (prose or "").split("\n")
    starts, off, k, line_para = [], 0, 0, []
    for ln in lines:
        starts.append(off)
        off += len(ln) + 1
        if ln.strip():
            k += 1
        line_para.append(k)
    out = {}
    for f in findings:
        s = getattr(f, "start", None)
        if not isinstance(s, int) or s < 0 or s >= len(prose):
            continue
        lo, hi = 0, len(starts) - 1
        while lo < hi:   # 二分：最后一个 start <= s 的行
            mid = (lo + hi + 1) // 2
            if starts[mid] <= s:
                lo = mid
            else:
                hi = mid - 1
        para = line_para[lo]
        if para:
            out.setdefault(para, []).append(f)
    return out


def _parse_pinned_output(raw: str) -> list:
    """定点修复回复 → span 编辑列表（⟦Pnn⟧ 替换段全文）；同段多行取最后一行"""
    spans = {}
    for m in _PINNED_LINE_RE.finditer(raw or ""):
        spans[int(m.group(1))] = m.group(2).strip()
    return [{"op": "replace", "para": p, "text": t} for p, t in spans.items()]


def _deslop_pinned_rewrite(ctx, session, prose: str, blocking: list,
                           advisory: list, num: int) -> str:
    """命中段 ≤DESLOP_PINNED_MAX_PARAS 处时只让模型输出替换段全文，本地按段号拼回。

    与 E11/T4b 失败版 span 模式的差异：输入只带命中段（不带整章）、输出是纯文本
    替换对（无 JSON 编辑列表与推理膨胀）。返回新 prose；不适定/失败返回 ""
    （调用方回退整章重写），失败轮一律 rollback 不留史。"""
    from . import span_edit
    if not _session_usable(session):
        return ""
    para_map = _findings_para_map(prose, list(blocking) + list(advisory))
    paras = sorted(para_map)
    if not paras or len(paras) > DESLOP_PINNED_MAX_PARAS:
        return ""
    para_text, k = {}, 0
    for ln in prose.split("\n"):
        if ln.strip():
            k += 1
            para_text[k] = ln
    findings_lines, para_block = [], []
    for p in paras:
        para_block.append("⟦P%02d⟧ %s" % (p, para_text.get(p, "")))
        for f in para_map[p]:
            findings_lines.append("- [%s] %s（命中：%s）"
                                  % (getattr(f, "level", "?"), getattr(f, "message", ""),
                                     str(getattr(f, "text", ""))[:40]))
    kw = dict(findings="\n".join(findings_lines) or "（见各段行首标记）",
              para_block="\n".join(para_block),
              tic_blacklist=_tic_blacklist(ctx.proj),
              must_block=_must_block(ctx.proj, ctx.cfg))
    req = ("（作用域：仅依据系统设定基准与本会话中的章正文消息执行本步；"
           "本步为定点修复，只处理下方点名的段落。）\n\n" +
           prompts.DESLOP_PINNED_PROMPT.format(**kw))
    t_before = session.turn_count()
    try:
        ctx.last_prompt = req
        raw = _session_ask(ctx, session, cfg_mod.SLOT_WRITING, req,
                           label=f"去味定点修复 第{num}章", phase=PHASE_DESLOP, stream=True)
        spans = _parse_pinned_output(raw)
        if not spans:
            span_edit.record_event(ctx.proj, "deslop", "pinned_fallback", "no_spans")
            session.rollback_to(t_before)
            return ""
        merged = span_edit.apply_spans(prose, spans)
        if not merged.strip() or merged == prose:
            span_edit.record_event(ctx.proj, "deslop", "pinned_fallback", "empty_merge")
            session.rollback_to(t_before)
            return ""
        if abs(len(merged) - len(prose)) > DESLOP_PINNED_MAX_GROW * max(len(prose), 1):
            span_edit.record_event(ctx.proj, "deslop", "pinned_fallback", "grow_over_25pct")
            session.rollback_to(t_before)
            return ""
        session.commit_turn(req, merged)   # 固化合成轮：「最近一条章正文消息」仍指向最新正文
        span_edit.record_event(ctx.proj, "deslop", "pinned", "paras=%s" % paras)
        return merged
    except PipelineStopped:
        raise
    except Exception as e:  # noqa: BLE001
        try:
            session.rollback_to(t_before)
        except Exception:  # noqa: BLE001
            pass
        span_edit.record_event(ctx.proj, "deslop", "pinned_fallback", str(e)[:120])
        ctx.log("warn", f"去味定点修复失败（{e}），回退整章重写")
        return ""


def stage_core_setting(ctx) -> str:
    ctx.log("info", "阶段① 生成核心设定…")
    info = project.read_idea_info(ctx.proj)
    if not info["idea"]:
        raise StageError("选题信息缺失（设定/选题信息.md），请先立项")
    ctx.checkpoint()
    prompt = prompts.CORE_SETTING_PROMPT.format(
        project_header=project_header(ctx.proj),
        book_name=os.path.basename(ctx.proj),
        genre=info["genre"] or "（不限）",
        platform=info["platform"],
        idea=info["idea"],
        emotion="（由你根据题材推荐）",
        total_words=info.get("total_words_wan", 0) or 100,
        genre_block=_genre_block(ctx.proj, "core_setting"),
    )
    # 同人禁则（方案 D3）：拆解底册存在时，前期阶段也带着禁则走，不等到世界书阶段
    canon = project.canon_digest(ctx.proj, 800)
    if canon:
        prompt += "\n\n" + canon + "\n（核心设定不得与上述禁则冲突。）"
    ctx.last_prompt = prompt
    result = _stream(ctx, cfg_mod.SLOT_WRITING, prompt, label="核心设定",
                     phase=PHASE_CORE_SETTING)
    if not result:
        raise StageError("核心设定生成失败：模型返回为空")
    path = os.path.join(ctx.proj, "设定", "题材定位.md")
    project.write_file(path, result)
    ctx.log("ok", "核心设定已生成 → 设定/题材定位.md")
    return result


# ============ 阶段②：全书大纲 ============

def stage_volume_outline(ctx, total_words_wan: int = 0) -> str:
    ctx.log("info", "阶段② 生成全书大纲…")
    core_setting = project.read_file(os.path.join(ctx.proj, "设定", "题材定位.md"))
    if not core_setting:
        raise StageError("缺少核心设定（设定/题材定位.md）")
    # 设定截断：max 思考下输入过长 + 推理会把输出预算吃光，超长设定只取关键前半段
    core_setting = core_setting[:4000]
    if not total_words_wan:
        total_words_wan = project.read_idea_info(ctx.proj).get("total_words_wan", 0) or 100
    chapter_words = ctx.cfg.get("writing", {}).get("chapter_word_target", 3000)
    ctx.checkpoint()
    prompt = prompts.VOLUME_OUTLINE_PROMPT.format(
        project_header=project_header(ctx.proj),
        core_setting=core_setting,
        total_words=total_words_wan,
        chapter_words=chapter_words,
        genre_block=_genre_block(ctx.proj, "outline"),
    )
    # 同人禁则（方案 D3）：大纲剧情不得与禁则冲突，并按单元安排原作专名出场
    canon_o = project.canon_digest(ctx.proj, 800)
    if canon_o:
        prompt += "\n\n" + canon_o + "\n（大纲剧情不得与禁则冲突，并按单元安排原作专名出场。）"
    ctx.last_prompt = prompt
    result = _stream(ctx, cfg_mod.SLOT_WRITING, prompt, label="全书大纲",
                     phase=PHASE_VOLUME_OUTLINE)
    if not result:
        raise StageError("全书大纲生成失败：模型返回为空")
    project.write_file(os.path.join(ctx.proj, "大纲", "大纲.md"), result)
    ctx.log("ok", f"全书大纲已生成（按 {total_words_wan} 万字规划）")
    return result


def stage_worldbook_gen(ctx) -> str:
    """阶段②.5 世界书首版（自动档）：核心设定+大纲 → 四节登记表。

    仅在 设定/世界书.md 缺失/为空时由 orchestrator 调用；失败不阻断流水线
    （共写/手动路径仍可后续建书）。
    """
    ctx.log("info", "阶段②.5 生成世界书首版…")
    proj = ctx.proj
    core_setting = project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:2500]
    outline = project.read_file(os.path.join(proj, "大纲", "大纲.md"))[:3000]
    if not core_setting.strip() and not outline.strip():
        ctx.log("warn", "核心设定与大纲均为空，跳过世界书首版生成")
        return ""
    try:
        ctx.checkpoint()
        prompt = prompts.WORLDBOOK_GEN_PROMPT.format(
            core_setting=core_setting or "（未提供）",
            outline=outline or "（未提供）",
            genre_block=_genre_block(proj, "worldbook"),
        )
        ctx.last_prompt = prompt
        result = _stream(ctx, cfg_mod.SLOT_HELPER, prompt, label="世界书首版",
                         phase=PHASE_WORLDBOOK)
        doc = (result or "").strip()
        if not doc:
            ctx.log("warn", "世界书首版生成失败：模型返回为空（不阻断）")
            return ""
        # 正则段独立落盘（与共写确认路径同口径）：否则自动档书 regex_rules 恒空
        doc, regex_part = project.split_worldbook_product(doc)
        if not doc.startswith("#"):
            doc = "## 世界书\n\n" + doc
        project.write_file(os.path.join(proj, project.WORLDBOOK_PATH), doc + "\n")
        regex_path = os.path.join(proj, project.REGEX_PATH)
        if regex_part and not (project.read_file(regex_path) or "").strip():
            project.write_file(regex_path, regex_part + "\n")
        ctx.log("ok", "世界书首版已生成（可在设定目录人工修订，反哺会持续追加登记）")
        return doc
    except PipelineStopped:
        raise
    except Exception as e:  # noqa: BLE001
        ctx.log("warn", f"世界书首版生成失败（不阻断）：{e}")
        return ""


# ============ 阶段③：章节细纲（分块 + 断点续传）============

def stage_chapter_outlines(ctx, start: int, end: int) -> list:
    """生成 [start, end] 章细纲，返回 [(num, title, content)]；已有细纲的章节跳过

    整批失败时拆半递归重试，单章仍失败则记录日志跳过（不阻断后续章）。
    """
    chapter_words = ctx.cfg.get("writing", {}).get("chapter_word_target", 3000)
    existing = {n for n, _ in project.list_outlines(ctx.proj)}
    todo = [n for n in range(start, end + 1) if n not in existing]
    if not todo:
        return []
    start, end = todo[0], todo[-1]
    ctx.log("info", f"阶段③ 生成第 {start}-{end} 章细纲…")

    wb_block, rg_block, wb_meta = _worldbook_regex_blocks(ctx, start)
    _record_worldbook(ctx, PHASE_OUTLINE, wb_meta)

    core_setting = project.read_file(os.path.join(ctx.proj, "设定", "题材定位.md"))
    if not core_setting:
        parts = []
        for sub in ["关系.md", "题材定位.md"]:
            c = project.read_file(os.path.join(ctx.proj, "设定", sub))
            if c:
                parts.append(c)
        core_setting = "\n\n".join(parts)[:3000] or "（未提供）"
    volume_outline = project.read_file(os.path.join(ctx.proj, "大纲", "大纲.md"))[:4000] or "（未提供）"
    if not volume_outline.strip() or volume_outline == "（未提供）":
        raise StageError("缺少全书大纲（大纲/大纲.md）")

    nearby = []
    for n, p in project.list_outlines(ctx.proj):
        if start - 2 <= n <= end + 2:
            nearby.append(project.read_file(p)[:800])
    nearby_text = "\n\n".join(nearby) if nearby else "（无相邻细纲）"

    # 场景承接锚点：上一章「实际写出来的结尾」（细纲只看摘要会丢章末钩子，导致剧情断裂）
    # 统一锚定：取小于批首章的最近存在章（非线性安全——补写中间单元时不再误报第一章）
    prev_ending_text, _style = prev_chapter_pack(ctx.proj, start, tail=500)
    previous_ending = prev_ending_text or "（本章为第一章，无上一章结尾）"
    # 待回收伏笔（细纲层排期，防"回收：未定"无限堆积）
    foreshadows = memory.unfished_foreshadows(ctx.proj) or "（暂无待回收伏笔）"

    outlines = _generate_outline_batch(ctx, todo, chapter_words,
                                       core_setting, volume_outline, nearby_text,
                                       previous_ending, foreshadows,
                                       wb_block, rg_block)
    saved = []
    for num, title, content in outlines:
        if num in existing:
            continue
        project.write_file(project.get_outline_path(ctx.proj, num), content)
        saved.append((num, title, content))
    if not saved:
        raise StageError("细纲生成失败：批次全部失败（详见日志）")
    ctx.log("ok", f"细纲已生成 {len(saved)} 章：{[s[0] for s in saved]}")
    return saved


def _generate_outline_batch(ctx, todo: list, chapter_words: int,
                            core_setting: str, volume_outline: str,
                            nearby_text: str, previous_ending: str = "",
                            foreshadows: str = "",
                            wb_block_text: str = "", rg_block_text: str = "") -> list:
    """一次调用生成一批细纲；解析失败或调用失败 → 拆半递归；单章失败跳过

    todo: 待生成章号列表（有序）。返回 [(num, title, content)]，失败章不在其中。
    """
    if not todo:
        return []
    start, end = todo[0], todo[-1]
    ctx.checkpoint()
    # 记忆锚：长篇细纲的主线进度锚点（全局摘要 + 近期章节摘要 + 角色状态），防后段卷细纲漂移
    global_summary = memory.read_global_summary(ctx.proj) or "（全书尚未开始）"
    recent_summaries = _sanitize_chapter_refs(
        memory.read_recent_summaries(ctx.proj, start, n=3)) or "（无更前章节摘要）"
    character_states = project.read_file(project.get_tracking_path(ctx.proj, "角色状态"))[:1500] \
        or "（暂无）"
    prompt = prompts.CHAPTER_OUTLINE_PROMPT.format(
        project_header=project_header(ctx.proj),
        volume_outline=volume_outline,
        nearby_outlines=nearby_text,
        core_setting_brief=core_setting[:2500],
        global_summary=global_summary,
        recent_summaries=recent_summaries,
        character_states=character_states,
        start_chapter=start,
        end_chapter=end,
        count=end - start + 1,
        chapter_words=chapter_words,
        chapter_words_max=int(chapter_words * 1.1),
        previous_ending=previous_ending or "（无）",
        foreshadows=foreshadows or "（无）",
        unit_contract=_unit_contract(ctx.proj, start),
        genre_block=_genre_block(ctx.proj, "unit_outline"),
        worldbook_block=wb_block_text,
        regex_block=rg_block_text,
        user_directive=ctx.consume_gate_idea() or "（无）",
    ) + _dyn_directives(ctx, PHASE_OUTLINE)   # O2 长度预算（未配置=空串，基线字节不变）
    ctx.last_prompt = prompt  # 失败现场 dump 用
    try:
        result = _stream(ctx, cfg_mod.SLOT_HELPER, prompt, label="细纲",
                         phase=PHASE_OUTLINE)
        outlines = parse_outlines(result)
        valid = [o for o in outlines if o[0] in todo]
        if not valid:
            raise StageError(
                f"细纲解析失败：模型输出 {len(result)} 字，无法按格式解析出目标章"
                f"（已解析 {[o[0] for o in outlines]}，待生成 {todo}）")
        return valid
    except PipelineStopped:
        raise   # 用户点停止 ≠ 批次失败：吞掉它就会报红 + 落一份假的失败现场
    except Exception as e:
        if len(todo) == 1:
            ctx.log("warn", f"第 {start} 章细纲生成失败：{e}（已跳过，下次运行自动补）")
            return []
        ctx.log("warn", f"第 {start}-{end} 章细纲批失败：{e}，拆半重试…")
        mid = len(todo) // 2
        left = _generate_outline_batch(ctx, todo[:mid], chapter_words,
                                       core_setting, volume_outline, nearby_text,
                                       previous_ending, foreshadows,
                                       wb_block_text, rg_block_text)
        right = _generate_outline_batch(ctx, todo[mid:], chapter_words,
                                        core_setting, volume_outline, nearby_text,
                                        previous_ending, foreshadows,
                                        wb_block_text, rg_block_text)
        return left + right


def parse_outlines(text: str) -> list:
    """按 ===第N章=== 分隔符解析细纲；兼容带空格/变体分隔符与 markdown 标题格式"""
    result = []
    # 主格式：===第N章===
    parts = re.split(r"===\s*第\s*(\d+)\s*章\s*===", text or "")
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            num = int(parts[i])
            content = parts[i + 1].strip()
            result.append((num, _outline_title(content, num), content))
        return result
    # 降级格式：## / ### 第N章：标题（无 === 分隔符时）
    chunks = re.split(r"^#{1,4}\s*第\s*(\d+)\s*章[\s:：]*", text or "", flags=re.M)
    if len(chunks) >= 3:
        for i in range(1, len(chunks) - 1, 2):
            num = int(chunks[i])
            content = chunks[i + 1].strip()
            result.append((num, _outline_title(content, num), content))
    return result


def _outline_title(content: str, num: int) -> str:
    m = re.search(r"###\s*第\s*\d+\s*章[：:]\s*(.+)", content)
    if m:
        return m.group(1).strip()
    m = re.search(r"^#+\s*第\s*\d+\s*章[：: ]*\s*(.+)", content, re.M)
    if m:
        return m.group(1).strip()
    return ""


# ============ 阶段④：章节微循环（每章 6 步）============

# 「第N章」引用清洗与上一章锚点已上移到 memory 层（shared_prefix 复用同源实现）
_sanitize_chapter_refs = memory.sanitize_chapter_refs
prev_chapter_pack = memory.prev_chapter_pack


def _outline_word_target(proj: str, num: int, default: int) -> int:
    """正文目标字数：委托 gates.chapter_word_target（细纲优先 + 50% 幻觉防御）"""
    return gates.chapter_word_target(proj, num, default)


def _archive_inner_rollback(ctx, proj: str, num: int, gate_key: str, prose: str):
    """内侧门回退数据安全（plan_step_gates_v1 §4）：将被丢弃的正文快照归档"""
    import datetime
    if not prose:
        return
    ts = datetime.datetime.now().strftime("%m%d_%H%M%S")
    d = os.path.join(proj, "pipeline_debug", "rollback", f"{gate_key}_ch{num}_{ts}")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "正文.md"), "w", encoding="utf-8") as f:
            f.write(prose)
        ctx.log("info", f"{gate_key} 回退快照已归档：{os.path.basename(d)}")
    except Exception as e:  # noqa: BLE001
        ctx.log("warn", f"{gate_key} 回退快照归档失败（不阻断）：{e}")


def _store_inner_gate_idea(ctx, proj: str, num: int, gate_key: str, idea: str):
    """内侧门带的想法落 pending_guidance（下次重写本章时经 G5L 指导通道注入）"""
    state = st.load_state(proj)
    prev = (state.get("pending_guidance") or {}).get(str(num), "")
    combined = (prev + "\n" if prev else "") + f"[{gate_key}] {idea}"
    st.set_guidance(proj, state, num, combined)
    ctx.log("info", f"{gate_key} 想法已登记（重写本章时注入）：{idea[:60]}")


def _acquire_volume_session(ctx, proj: str, num: int, static_freeze: bool = False,
                            compaction: bool = False):
    """S1 卷级会话栈（writing.volume_session，v3 §2）：按卷取/建 VolumeSession。

    生命周期挂在 ctx（orchestrator.run）持有的按卷缓存上：每次连跑一个实例集，
    卷内各章在同一实例上 open_chapter 累积跨章历史；进程重启后首次取用时从
    项目/会话/卷N_messages.jsonl 恢复（消息逐字节一致 → 服务端前缀缓存继续
    有效）。ctx 无缓存表（旁路调用方）/客户端不支持 chat_turn → 返回 None，
    本章回退单轮路径。flag 关闭时本函数不被触达（行为逐字节不变）。

    static_freeze（writing.s4_static_freeze，S4 指令库前置的独立 A/B 开关，默认
    关）：开启时 system = 全书冻结前缀 + PROSE 指令库（volume_system_text）；
    关闭时 system 仍只含全书前缀——S1 行为逐字节不变（test_volume_session 的
    旗标开字节锁钉住的正是这份请求体）。
    """
    cache = getattr(ctx, "volume_sessions", None)
    if not isinstance(cache, dict):
        return None
    try:
        from .volume_session import (VolumeSession, resolve_volume_number,
                                     volume_messages_path, volume_system_text)
        vol = resolve_volume_number(proj, num)
        sess = cache.get(vol)
        if sess is None:
            probe = ctx.router.client(cfg_mod.SLOT_HELPER)
            if not callable(getattr(probe, "chat_turn", None)):
                return None
            # S4-a：指令库开启时 system = 全书冻结前缀 + PROSE 指令库（模板化
            # 冻结版）——指令体不再随每章开幕轮重发（prose 首轮 miss 的大头）；
            # 关闭时与 S1 逐字节一致。旧栈 system 失配 → load 拒绝，按全新栈继续
            # （缓存域切换本就该全灭一次）。
            system_text = (volume_system_text(proj) if static_freeze
                           else project_header(proj))
            # V1-③（writing.review_in_system，缺省关）：审校静态指令尾段一次性进
            # system——每章审校轮只带动态块，指令体不再随章数在历史里累积
            # （T 轮实测审校轮指令体 4.6k chars/章逐章重发）。旧行为逐字节不变。
            if bool((ctx.cfg or {}).get("writing", {}).get("review_in_system", False)):
                _rt = prompts.review_static_tail()
                if _rt:
                    system_text = system_text + "\n\n" + _rt
            # 压缩开时接最新一代栈（卷V_cK），关时 gen 恒 0 = 文件名与行为逐字节不变
            gen = _live_stack_gen(proj, vol) if compaction else 0
            sess = VolumeSession(probe, system_text=system_text,
                                 volume=vol, proj=proj, gen=gen)
            path = volume_messages_path(proj, vol, gen)
            if os.path.exists(path):
                if sess.load(path):
                    ctx.log("info", f"卷 {vol} 会话已从盘恢复（{sess.turn_count()} 轮，"
                                    f"历史前缀缓存继续有效）")
                else:
                    r = dict(getattr(sess, "reject", None) or {})
                    turns = int(r.get("turns") or 0)
                    tok = int(r.get("tok") or 0)
                    ctx.log("warn", f"卷 {vol} 会话恢复失败（{r.get('event') or '未知原因'}）"
                                    f"：丢弃 {turns} 轮 / 约 {tok:,} tok 历史，"
                                    f"本章起按全新栈继续，每次调用全量 miss 重发 "
                                    f"≈¥{float(r.get('cost') or 0):.4f}")
            cache[vol] = sess
            ctx.log("info", f"第 {num} 章 卷会话已启用（卷 {vol}：跨章共享历史，"
                            f"章头入开幕轮）")
        return sess
    except Exception as e:  # noqa: BLE001
        # W-3：不静默。无会话比空栈更贵（每个相位都重发整条双层前缀），且这种
        # 降级会一路跑完整本书——fd7b8fe 就是缺一个导出符号导致 v7_long13 整卷无会话。
        try:
            from .volume_session import record_event
            record_event(proj, "acquire_failed", chapter=num,
                         err=f"{type(e).__name__}: {e}"[:160])
        except Exception:  # noqa: BLE001
            pass
        try:
            ctx.log("warn", f"卷级会话不可用（{type(e).__name__}: {e}），"
                            f"第 {num} 章按无会话继续（每相位重发整条前缀）")
        except Exception:
            pass
        return None


def _live_stack_gen(proj: str, vol: int) -> int:
    """盘上该卷最新的会话栈代次：接力压缩会另起 卷V_cK 新栈（旧栈留盘作证据），
    崩溃续跑必须接最新那一代，否则会把压缩前的长历史又续上（writing.compaction
    关时恒 0 = 改造前的文件名与字节）。"""
    best = 0
    d = os.path.join(proj, "会话")
    if not os.path.isdir(d):
        return 0
    pat = re.compile(r"^卷%d_c(\d+)_messages\.jsonl$" % int(vol))
    for fn in os.listdir(d):
        m = pat.match(fn)
        if m:
            best = max(best, int(m.group(1)))
    return best


def _compaction_step(ctx, proj: str, num: int, session):
    """长程压缩 §4.3「接力压缩」接线（writing.compaction，默认关）。

    触发（§6.2 卷界 / 输入越阈 / 手动）时：把本卷历史折叠成装配式交接块（零 LLM
    调用），另起一代会话栈——system 逐字节沿用旧栈（它就是新前缀的共享段），
    交接块作为新栈首个开幕轮的前置段给一次，此后随历史永久命中。
    旧栈文件不删不改：压缩前后对照与 T2 A/B 的证据都在盘上。

    返回 (session, preface)；旗标关闭时调用方根本不触达本函数。
    """
    from . import history_compaction as hc
    cfg = ctx.cfg or {}
    if session is None:
        return session, ""
    # V1-a：covered 取本卷与上一卷落盘块的 to_chapter 最大值——卷界场景覆盖块
    # 落在上一卷文件里，只查本卷会算成 0、守卫失效（T2 实测 ch25 二次点火根源之一）
    _d_cur = hc.load_handoff(proj, session.volume) or {}
    _d_prev = hc.load_handoff(proj, session.volume - 1) if session.volume > 1 else {}
    covered = max(int(_d_cur.get("to_chapter") or 0), int(_d_prev.get("to_chapter") or 0))
    trig = hc.should_compact(proj, num, cfg=cfg, volume=session.volume)
    if trig.fire and covered < num - 1:
        # V1-b：被顶替规模按旧栈实测计（ha 口径）——不再用单章正文那把失真的尺子
        from .history_compaction import han_tokens as _han
        _msgs = getattr(session, "_messages", None) or []
        replaced_hint = _han("\n".join(str(m.get("content") or "") for m in _msgs))
        ob = hc.opening_block(proj, num, cfg=cfg, volume=session.volume,
                              replaced_hint=replaced_hint)
        if not ob.contributed:
            ctx.log("info", f"第 {num} 章 压缩触发（{trig.reason}）但装配拒绝："
                            f"{ob.reason}——沿用当前会话（fail-open）")
            return session, ""
        from .volume_session import VolumeSession
        probe = ctx.router.client(cfg_mod.SLOT_HELPER)
        new = VolumeSession(probe, system_text=session.system_text,
                            volume=session.volume, proj=proj, gen=session.gen + 1)
        cache = getattr(ctx, "volume_sessions", None)
        if isinstance(cache, dict):
            cache[session.volume] = new
        new._handoff = ob.text
        ctx.log("ok", f"第 {num} 章 接力压缩（{trig.reason}）：交接块 {ob.tokens} tok "
                      f"顶替逐字历史 {ob.replaced_tokens} tok（压缩比 "
                      f"{100 * (1 - ob.shrink_ratio):.0f}%），另起会话栈 "
                      f"卷{new.volume}_c{new.gen}")
        session = new
    preface = getattr(session, "_handoff", "") or ""
    if preface:
        session._handoff = ""      # 只给一次：新栈开幕轮之后它进入历史、永久命中
    return session, preface


def chapter_microcycle(ctx, num: int, guidance: str = "", ideas: list = None) -> dict:
    """上下文组装→草稿→字数闸门→AI味扫描→去味→定稿落库。返回章节记录"""
    proj = ctx.proj
    # 用量行归属章号：T 轮的逐章曲线一直靠"prose 每章恰一次"反推，就是缺这一格
    from .. import usage as _usage
    _usage.set_chapter(num)
    chapter_words = _outline_word_target(
        proj, num, ctx.cfg.get("writing", {}).get("chapter_word_target", 3000))
    gates_cfg = ctx.cfg.get("gates", {})
    tolerance = gates_cfg.get("word_tolerance", 0.1)
    max_deslop_rounds = gates_cfg.get("deslop_max_rounds", 2)
    gr = gates.GateResult()
    gr.word_target = chapter_words

    # ---- 章会话（v0.19）：system=双层稳定前缀，正文与后续阶段作为追加轮次。
    # 关闭（writing.chapter_session=false）或客户端不支持 chat_turn 时回退单轮路径。
    # S1 卷级会话栈（writing.volume_session，默认关，v3 §2）：开启时跨章复用一个
    # VolumeSession（system 只含 project_header，章头挪到每章开幕轮）；flag 关闭
    # 时走下方原分支，请求体与改造前逐字节一致（A/B 对照的公共前提）。
    # S4 指令库前置（writing.s4_static_freeze，默认关，v3 §3）：挂在本旗标下的
    # 独立 A/B 步——卷会话开 + 本旗标开才生效（system 入指令库/开幕轮瘦身/
    # 追踪轮引用行）；卷会话开 + 本旗标关 = S1 请求体逐字节不变。
    _w_cfg = (ctx.cfg or {}).get("writing", {})
    _s4_freeze = bool(_w_cfg.get("s4_static_freeze", False))
    # 长程压缩（writing.compaction，默认关，长程压缩文档 §6.2）：只在卷会话之上
    # 加一步「历史折叠成交接块 + 另起会话栈」，关闭时下方 _compaction_step 不触达。
    _compaction = bool(_w_cfg.get("compaction", False))
    # 缺省无会话：纯单轮路径（旧客户端/配置全关），后续 _session_usable(None) 兜底
    session = None
    _comp_preface = ""
    # 调整三（writing.audit_effort_low，缺省关）：清算属对照检查任务（V4 报告
    # High/Max 差距只在 HLE/Apex 难题），预扫降 effort=low 砍推理输出。
    if bool(_w_cfg.get("audit_effort_low", False)):
        if _merge_audit_effort_low(getattr(getattr(ctx, "router", None), "stage_params", None)):
            ctx.log("info", f"第 {num} 章 清算降档：canon_audit effort=low（audit_effort_low）")
    # 调整三（writing.volume_effort，缺省空=关）：卷内 effort 统一——防 Think Max
    # 档的 system 前端注入打死冻结头。落到连接实例层（最弱层，显式 stage_params
    # 仍可按相位覆盖）；档位写入 state，同卷内拒绝变更（卷界才允许切换）。
    _apply_volume_effort(ctx, proj, num)
    # L4（writing.head_rebuild，缺省关，深化计划 v2 §1）：每章重建——system=冻结
    # 稳定头（volume_system_text：全书前缀+PROSE 指令库，卷内逐字节一致→按 E0 实测
    # 连续命中），只挂本章轮次，跨章历史不入栈（有界上下文）。E0 判据：hit 随前缀
    # 长度连续增长、无 32k 台阶（看板 2026-09-10 00:30 条）。每章 fresh 实例 +
    # persist=False（不落盘；W-8 turn_cleaned 事件仪器仍工作）。优先级高于
    # volume_session/chapter_session；compaction 在此模式下无意义（栈不过章）。
    if _w_cfg.get("head_rebuild", False):
        try:
            probe = ctx.router.client(cfg_mod.SLOT_HELPER)
            if callable(getattr(probe, "chat_turn", None)):
                from .volume_session import (VolumeSession, volume_system_text,
                                             head_rebuild_system_text,
                                             resolve_volume_number as _rvn)
                # 头 v2（深化计划 §1-L4）：卷首冻结快照（设定底册/世界书/卷纲）并入
                # 稳定头——头越大，综合命中率越高（每章 ~9 次调用全部命中头）。
                _head = head_rebuild_system_text(
                    proj, _rvn(proj, num),
                    review_in_system=bool(_w_cfg.get("review_in_system", False)),
                    review_tail=prompts.review_static_tail(),
                    instruction_in_head=bool(_w_cfg.get("instruction_in_head", False)),
                    corpus_head=bool(_w_cfg.get("corpus_head", False)))
                session = VolumeSession(probe, system_text=_head,
                                        volume=_rvn(proj, num), proj=proj,
                                        persist=False,
                                        commit_raw=bool(_w_cfg.get("commit_raw", False)))
                ctx.log("info", f"第 {num} 章 L4 每章重建：system=冻结稳定头"
                                f"（{len(_head)} chars），跨章历史不入栈")
        except Exception:
            session = None
    elif _w_cfg.get("volume_session", False):
        session = _acquire_volume_session(ctx, proj, num, static_freeze=_s4_freeze,
                                          compaction=_compaction)
        if _compaction and session is not None:
            session, _comp_preface = _compaction_step(ctx, proj, num, session)
    elif _w_cfg.get("chapter_session", True):
        try:
            probe = ctx.router.client(cfg_mod.SLOT_HELPER)
            if callable(getattr(probe, "chat_turn", None)):
                from .chapter_session import ChapterSession
                session = ChapterSession(
                    probe, system_text=f"{project_header(proj)}\n\n{chapter_header(proj, num)}")
                ctx.log("info", f"第 {num} 章 章会话已启用（同章阶段共享前缀与正文历史）")
        except Exception:
            session = None

    # ---- 步骤级断点（方案 H）：草稿即文件，停在哪从哪继续 ----
    # 恢复语义：重跑被打断的那一步，之前完成的步骤全部保留
    # （草稿文件在盘、已投审校票持久化）——不再「停一次全章白写」。
    _ORDER = ["assemble", "draft", "enrich", "scan", "deslop", "review", "finalize"]
    import hashlib
    # 断点在草稿之后时，后续步骤（去味/审校）仍需要的材料本地重读（零成本）；
    # 同时细纲内容是指纹——细纲重生成后旧断点作废
    outline = _sanitize_chapter_refs(project.read_file(project.get_outline_path(proj, num)))
    outline_fp = hashlib.sha1((outline or "").encode("utf-8")).hexdigest()[:12]
    saved_cs = st.get_chapter_step(proj)
    resume_at = ""
    saved_votes: list = []
    if saved_cs.get("num") == num and saved_cs.get("step_done") in _ORDER:
        if saved_cs.get("outline_fp", "") != outline_fp:
            # 无指纹的旧格式断点同样不可信（无法证明它属于当前细纲）
            ctx.log("warn", f"第 {num} 章 章内断点作废：细纲与断点记录不一致，按新细纲全量重写")
            saved_cs = {}
        if saved_cs.get("num") == num and saved_cs.get("step_done") in _ORDER:
            resume_at = saved_cs["step_done"]
            saved_votes = list(saved_cs.get("votes") or [])
            ctx.log("info", f"第 {num} 章 断点续跑：已完成至 {resume_at}（审校票 {len(saved_votes)} 张保留），从断点继续")
    resume_prose = ""
    if resume_at:
        resume_prose = project.read_file(project.chapter_draft_path(proj, num))
        if not resume_prose.strip():
            ctx.log("warn", "断点草稿文件丢失，本章从头重写")
            resume_at = ""
    draft_rel = os.path.relpath(project.chapter_draft_path(proj, num), proj)
    # 细纲预算闸门（迭代②）：细纲「预算合计：约 X—Y 字」优先于全局目标，
    # 正文超预算上限 15% 在字数闸门处自然触发压缩/扩写
    m_budget = re.search(r"预算合计[：:]\s*约?\s*(\d+)\s*[—\-～~]\s*(\d+)", outline or "")
    if m_budget:
        chapter_words = (int(m_budget.group(1)) + int(m_budget.group(2))) // 2
        gr.word_target = chapter_words

    # ---- ① 上下文组装（G4 门：回退=改材料后重新组装读盘，T4.1 内侧门）----
    draft_extra_ideas: list = []
    while resume_at == "" and True:
        ctx.step(num, st.STEP_ASSEMBLE)
        outline_path = project.get_outline_path(proj, num)
        outline = _sanitize_chapter_refs(project.read_file(outline_path))
        if not outline:
            raise StageError(f"第 {num} 章细纲不存在")

        next_outline = project.read_file(project.get_outline_path(proj, num + 1))
        next_brief = _sanitize_chapter_refs(next_outline[:600]) if next_outline else "（本章为当前最后一章细纲）"
        core_setting = (project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1500]
                        or "（未提供）")
        # 章级上下文（全局摘要/近章摘要/角色状态/时间线/伏笔/上一章结尾与文风样本）
        # 已统一收敛到 chapter_header（八节，两层前缀的第二层），不再散装注入——
        # 截断取各消费方上限最大值，信息只增不减。
        ctx.log("info", f"第 {num} 章 上下文组装完成（核心设定 + 八节章级共享段（含细纲/摘要/状态/伏笔/上一章锚点））")
        # 决策门 G4：素材组装后（软门：默认轻提示）
        g4_idea = ctx.gate("G4", f"材料就绪：细纲 + 章级共享段（摘要/状态/伏笔/上一章锚点）（草稿目标 {chapter_words} 字）",
                           chapter=num)
        if g4_idea is None:
            g4_idea = ctx.consume_gate_idea()   # 回退想法就地消费，防串章
            ctx.log("warn", "G4 回退：重新组装（可趁隙修改设定/细纲/追踪文件）")
            continue
        if g4_idea:
            draft_extra_ideas.append(g4_idea)   # 带想法继续 → 注入草稿 user_ideas
        break

    if resume_at:
        # 断点续跑：草稿已在盘上（正文/.drafts），跳过组装与草稿生成。
        # 审校修复 prompt 仍需要 core_setting——本地重读
        core_setting = (project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1500]
                        or "（未提供）")
        prose = resume_prose
        st.save_chapter_step(proj, num, step_done="enrich",
                             draft_path=draft_rel, votes=saved_votes,
                             outline_fp=outline_fp)
        ctx.log("ok", f"第 {num} 章 已从断点恢复草稿（{project.count_chars(prose)} 字）")

    # S1 卷会话断点续跑：卷栈逐章落盘，崩在中途=盘上栈只到上一章末尾——本章
    # 开幕轮与正文都缺。先把盘上草稿播种进下一次会话调用（语义同章会话恢复的
    # restart_with_prose，只是不清 1..N-1 章历史），防「最近一条章正文消息」
    # 仍指向上章正文导致后续相位审错对象。
    if resume_at and _session_usable(session) and hasattr(session, "seed_prose") \
            and getattr(session, "current_chapter", 0) != num:
        session.seed_prose(prose, chapter_num=num)
        ctx.log("info", f"第 {num} 章 卷会话断点续跑：草稿已播种（下次会话调用并入历史）")

    # ---- ② 草稿生成 ----
    if resume_at == "":
        ctx.step(num, st.STEP_DRAFT)
        ctx.checkpoint()
        wb_block, rg_block, wb_meta = _worldbook_regex_blocks(ctx, num)
        _record_worldbook(ctx, PHASE_PROSE, wb_meta)
        # 阶段重生成时 bridge 写入的「阶段指导」：消费即删，拼进本章写作指导
        sg_path = os.path.join(proj, "追踪", "阶段指导.md")
        stage_guidance = project.read_file(sg_path).strip()
        if stage_guidance:
            guidance = f"{guidance}\n{stage_guidance}".strip() if guidance else stage_guidance
            try:
                os.remove(sg_path)
            except OSError:
                pass
        prose_kw = {
            "chapter_num": num,
            "next_chapter_brief": next_brief,
            "user_guidance": _compose_guidance(guidance, ctx.cfg),
            "user_ideas": chr(10).join(f"- {t}" for t in ((ideas or []) + draft_extra_ideas)) or "（无）",
            "word_target": chapter_words,
            "tic_blacklist": _tic_blacklist(proj),
            "used_setpieces": _used_setpieces(proj),
            "project_header": project_header(proj),
            "chapter_header": chapter_header(proj, num),
            "style_discipline": prompts.STYLE_DISCIPLINE,
            "worldbook_block": wb_block,
            "regex_block": rg_block,
            "craft_block": scene_cards.craft_block(num, _total_chapters(proj, chapter_words), outline),
            "author_note": _author_note(proj),
        }
        _prose_directives = _dyn_directives(ctx, PHASE_PROSE)   # E1.2/O2（未配置=空串）
        if _session_usable(session):
            # 章会话：正文写作是本会话首轮，回复固化为章正文轮。
            # S1 卷会话：本轮同时是「本章开幕轮」——开幕声明 + 章头并入同一
            # user 轮（system 只含全书冻结前缀；章头逐卷只 miss 一次，此后
            # 永久命中）。开幕声明显式锚定「本章正文以本次回复为准」。
            if (_s4_freeze or _w_cfg.get("head_rebuild", False)) \
                    and hasattr(session, "open_chapter"):
                # head_rebuild：指令库已在冻结头里（获取分支构造），开幕同样走
                # S4 组合（动态值 + 八节），否则指令体会双重出现。
                # S4（v3 §3 指令库前置）：PROSE 指令体已模板化冻结进卷会话
                # system（volume_system_text），开幕轮只带本章共享上下文
                # （volume_mode 八节去三节，S4-b）+ 逐章动态值 + 一行指令库
                # 执行指针。S1 卷会话/章会话/单轮走 else，请求体逐字节不变。
                turn_text = _volume_prose_opening_values(
                    num=num, word_target=chapter_words, next_brief=next_brief,
                    user_guidance=prose_kw["user_guidance"],
                    user_ideas=prose_kw["user_ideas"],
                    used_setpieces=prose_kw["used_setpieces"],
                    craft_block=prose_kw["craft_block"],
                    author_note=prose_kw["author_note"],
                    tic_blacklist=prose_kw["tic_blacklist"]) + _prose_directives
                turn_text = session.open_chapter(
                    chapter_header(proj, num,
                                   volume_mode=not _w_cfg.get("head_rebuild", False)),
                    turn_text,
                    chapter_num=num, preface=_comp_preface)
            else:
                turn_text = prompts.session_turn_text(prompts.PROSE_WRITING_PROMPT).format(**prose_kw) \
                    + _prose_directives
                if hasattr(session, "open_chapter"):
                    turn_text = session.open_chapter(chapter_header(proj, num), turn_text,
                                                     chapter_num=num,
                                                     preface=_comp_preface)
            ctx.last_prompt = turn_text
            prose = _session_ask(ctx, session, cfg_mod.SLOT_WRITING, turn_text,
                                 label=f"草稿 第{num}章", phase=PHASE_PROSE)
        else:
            prompt = prompts.PROSE_WRITING_PROMPT.format(**prose_kw) + _prose_directives
            ctx.last_prompt = prompt
            prose = _stream(ctx, cfg_mod.SLOT_WRITING, prompt, label=f"草稿 第{num}章",
                            phase=PHASE_PROSE)
        if not prose.strip():
            raise StageError(f"第 {num} 章草稿生成失败：模型返回为空")
        actual = project.count_chars(prose)
        ctx.log("ok", f"第 {num} 章 草稿完成：{actual} 字（目标 {chapter_words}）")

        # ---- 字数闸门：不足自动扩写（最多 word_enrich_rounds 轮，真机缺陷④收紧）/ 超标自动压缩一次 ----
        max_enrich_rounds = max(1, int(gates_cfg.get("word_enrich_rounds", 2)))
        low_ok, high_ok, actual = gates.check_word_bounds(prose, chapter_words, tolerance)
        # S5 注册窗口节拍：正文是长生成（130s+），紧随其后的快调用会在前轮输出单元
        # 注册完成前发车，吃全价 miss（S1 实测 enrich 12.7k miss/笔）。在会话模式下
        # 等一个注册窗口再发（本地扫描/断点保存已消耗一部分窗口）。
        _pace_after_long_call(ctx, cfg_mod, session)
        enrich_rounds = 0
        _enrich_tail = bool(_w_cfg.get("enrich_tail", False))
        while not low_ok and enrich_rounds < max_enrich_rounds:
            enrich_rounds += 1
            ctx.step(num, st.STEP_ENRICH)
            ctx.log("warn", f"第 {num} 章 字数不足（{actual} / 目标 {chapter_words}），自动扩写（第 {enrich_rounds} 轮）…")
            ctx.checkpoint()
            # V7（writing.enrich_tail，缺省关）：补尾式扩写——只续写缺口（400-600 字），
            # 输出∝缺口；旧全量重写每轮输出整章且模型对「扩写」天然保守（每轮只加
            # 300-400 字、常需 2 轮）。续写完成后把「完整正文」固化进会话，保持
            # 「最近一条章正文消息」语义不变。
            if _enrich_tail:
                gap = max(chapter_words - actual, 200)
                tail_kw = dict(chapter_num=num, actual=actual, target=chapter_words,
                               gap=gap,
                               ending=prose[-400:],
                               tic_blacklist=_tic_blacklist(proj),
                               must_block=_must_block(proj, ctx.cfg),
                               chapter_header=chapter_header(proj, num),
                               project_header=project_header(proj))
                _slot = genre_presets.stage_slot(_preset_id(proj), PHASE_ENRICH) or cfg_mod.SLOT_WRITING
                req = prompts.ENRICH_TAIL_PROMPT.format(**tail_kw)
                ctx.last_prompt = req
                cont = clean_llm_output(ctx.router.client(_slot).chat(
                    req, phase=PHASE_ENRICH))
                cont = (cont or "").strip()
                if cont and len(cont) >= gap * 0.35:
                    prose = prose.rstrip("\n") + "\n\n" + cont
                    if _session_usable(session):
                        try:
                            session.commit_turn(
                                f"（字数补尾第 {enrich_rounds} 轮已并入，以下为并入后的完整本章正文）",
                                prose)
                        except Exception:  # noqa: BLE001
                            pass
                else:
                    ctx.log("warn", f"补尾产出过短（{len(cont)} 字），本轮回退全量扩写")
                    enrich_full_kw = dict(chapter_num=num, actual=actual,
                                          target=chapter_words, prose=prose,
                                          tic_blacklist=_tic_blacklist(proj),
                                          must_block=_must_block(proj, ctx.cfg),
                                          chapter_header=chapter_header(proj, num),
                                          project_header=project_header(proj))
                    rewritten = _rewrite_phase(ctx, session, cfg_mod.SLOT_WRITING, PHASE_ENRICH,
                                               prompts.ENRICH_PROMPT, enrich_full_kw,
                                               prose=prose,
                                               label=f"扩写(全量) 第{enrich_rounds}轮")
                    if rewritten.strip() and project.count_chars(rewritten) >= actual:
                        prose = rewritten
                low_ok, high_ok, actual = gates.check_word_bounds(prose, chapter_words, tolerance)
                continue
            enrich_kw = dict(chapter_num=num, actual=actual,
                             target=chapter_words, prose=prose,
                             tic_blacklist=_tic_blacklist(proj),
                             must_block=_must_block(proj, ctx.cfg),
                             chapter_header=chapter_header(proj, num),
                             project_header=project_header(proj))
            rewritten = _rewrite_phase(ctx, session, cfg_mod.SLOT_WRITING, PHASE_ENRICH,
                                       prompts.ENRICH_PROMPT, enrich_kw, prose=prose,
                                       label=f"扩写 第{enrich_rounds}轮")
            # 扩写稿健全性守卫：返回为空或比原稿更短 → 丢弃本轮结果（防越写越少）
            if rewritten.strip() and project.count_chars(rewritten) >= actual:
                prose = rewritten
            low_ok, high_ok, actual = gates.check_word_bounds(prose, chapter_words, tolerance)
        if enrich_rounds:
            ctx.log("ok" if low_ok else "warn",
                    f"扩写后 {actual} 字" + ("，达标" if low_ok
                                            else f"，{enrich_rounds} 轮后仍不足，标记不阻断"))
        elif not high_ok:
            ctx.step(num, st.STEP_ENRICH)
            ctx.log("warn", f"第 {num} 章 字数超标（{actual} > 目标 {chapter_words}×{1 + tolerance:.0%}），自动压缩…")
            ctx.checkpoint()
            pre_prose, pre_actual = prose, actual
            cut_pct = max(5, int(100 * (1 - chapter_words * (1 + tolerance) / max(actual, 1))))
            t_trim = session.turn_count() if _session_usable(session) else 0
            trim_kw = dict(chapter_num=num, actual=actual, target=chapter_words,
                           cut_pct=cut_pct, prose=prose,
                           tic_blacklist=_tic_blacklist(proj),
                           must_block=_must_block(proj, ctx.cfg),
                           chapter_header=chapter_header(proj, num),
                           project_header=project_header(proj))
            prose = _rewrite_phase(ctx, session, cfg_mod.SLOT_WRITING, PHASE_TRIM,
                                   prompts.TRIM_PROMPT, trim_kw, prose=prose,
                                   label="压缩")
            low_ok, high_ok, actual = gates.check_word_bounds(prose, chapter_words, tolerance)
            if not high_ok and actual < chapter_words * 0.6 and pre_actual <= chapter_words * 1.5:
                # 压缩过度删减（<60%）且原稿未严重超标（≤150%）→ 回退原稿，防章节被压残
                prose, actual = pre_prose, pre_actual
                if _session_usable(session):
                    session.rollback_to(t_trim)   # 压缩稿被否决 → 历史截断回压缩前
                ctx.log("warn", f"压缩过度删减（{actual} < 60% 目标），已回退原稿（{pre_actual} 字）")
            else:
                ctx.log("ok" if high_ok else "warn",
                        f"压缩后 {actual} 字" + ("，达标" if high_ok else "，仍超标，标记不阻断"))

    # 断点保存（方案 H）：草稿即文件——此后扫描/去味/审校/定稿任何位置停止，
    # 重启都从盘上这份草稿继续，不再整章重写
    project.write_file(project.chapter_draft_path(proj, num), prose)
    st.save_chapter_step(proj, num, step_done="enrich",
                         draft_path=draft_rel, votes=saved_votes, outline_fp=outline_fp)
    # W-3 里程碑①：与草稿同步把卷栈落一次盘（此后崩在扫描/去味/审校都不用重打整卷）
    _save_session_checkpoint(ctx, session, "enrich 后")

    # ---- ③ AI 味扫描（本地，零成本；断点在此步之后时跳过）----
    skip_scan_deslop = resume_at in ("deslop", "review", "finalize")
    blocking, advisory = ([], []) if skip_scan_deslop else ([], [])
    ctx.step(num, st.STEP_SCAN)
    blocking, advisory = ([], []) if skip_scan_deslop else gates.scan_deslop(prose)
    gr.blocking_findings, gr.advisory_findings = blocking, advisory
    ctx.log("info", "第 %d 章 本地扫描：阻断 %d 处 / 建议 %d 处%s"
            % (num, len(blocking), len(advisory), "（断点续跑：跳过扫描与去味）" if skip_scan_deslop else ""))

    # ---- ③.5 决策门 G6：扫描完成后（T4.1 内侧门；回退=保留原稿跳过去味）----
    deslop_extra_text = ""
    g6_idea = ""
    if not skip_scan_deslop:
        g6_idea = ctx.gate("G6", f"AI 味扫描完成：阻断 {len(blocking)} / 建议 {len(advisory)}"
                             f"（下一步去味改写，最多 {max_deslop_rounds} 轮）", chapter=num)
    if g6_idea is None:
        g6_idea = ctx.consume_gate_idea()   # 回退想法就地消费，防串章
        ctx.log("warn", f"G6 回退：保留原稿继续（{len(blocking)} 处阻断按人工裁决保留，跳过去味）")
        advisory = advisory + blocking
        blocking = []
        gr.blocking_findings, gr.advisory_findings = blocking, advisory
    elif g6_idea:
        deslop_extra_text = f"\n【人工补充要求（G6 想法）】{g6_idea}"

    # ---- ④ 去味改写（仅阻断级触发，最多 max_deslop_rounds 轮）----
    pre_deslop_prose = prose   # G7 回退还原点
    pre_deslop_turns = session.turn_count() if _session_usable(session) else 0
    rounds = 0
    # 调整五（writing.deslop_pinned，缺省关）：命中段 ≤2 处走定点修复——只输出
    # 替换段全文（无 JSON 编辑列表），本地拼回；不适定自动回退整章重写。
    _deslop_pinned_on = bool(_w_cfg.get("deslop_pinned", False))
    # 调整一（writing.instruction_in_head）：去味改写原则段已在卷级冻结头时，
    # 整章重写轮剥掉同段（定点修复模板自身不带该段，无需瘦身）。
    _deslop_strip = prompts.deslop_static_rules() \
        if (bool(_w_cfg.get("instruction_in_head", False)) and not _deslop_pinned_on) else ""
    while blocking and rounds < max_deslop_rounds:
        rounds += 1
        ctx.step(num, st.STEP_DESLOP)
        ctx.log("warn", f"第 {num} 章 阻断 {len(blocking)} 处 → 去味改写（第 {rounds} 轮）…")
        ctx.checkpoint()
        rewritten = ""
        if _deslop_pinned_on:
            rewritten = _deslop_pinned_rewrite(ctx, session, prose, blocking, advisory, num)
        if not rewritten:
            findings_text = deslop.findings_to_prompt_text(blocking + advisory) + deslop_extra_text
            t_round = session.turn_count() if _session_usable(session) else 0
            deslop_kw = dict(findings=findings_text, prose=prose,
                             tic_blacklist=_tic_blacklist(proj),
                             must_block=_must_block(proj, ctx.cfg),
                             chapter_header=chapter_header(proj, num),
                             project_header=project_header(proj))
            rewritten = _rewrite_phase(ctx, session, cfg_mod.SLOT_WRITING, PHASE_DESLOP,
                                       prompts.DESLOP_REWRITE_PROMPT, deslop_kw, prose=prose,
                                       label=f"去味改写 第{rounds}轮",
                                       strip_static=_deslop_strip,
                                       strip_replacement="（改写原则见系统「去味改写规则」"
                                                         "（卷级冻结），本步照常执行。）")
        if rewritten.strip():
            prose = rewritten
        elif _session_usable(session):
            session.rollback_to(t_round)   # 空改写稿不采纳 → 历史不留坏正文轮
        blocking, advisory = gates.scan_deslop(prose)
        gr.blocking_findings, gr.advisory_findings = blocking, advisory
    gr.deslop_rounds_used = rounds
    if blocking:
        gates.resolve_failed(ctx, f"第 {num} 章去味未通过（{len(blocking)} 处阻断）", gr)
    else:
        gr.final_status = "pass"
        if rounds:
            ctx.log("ok", f"第 {num} 章 去味完成，复扫通过")

    # ---- ④.4 决策门 G7：去味完成后（T4.1 内侧门；回退=保留原稿=还原去味前文本）----
    g7_idea = "" if skip_scan_deslop else ctx.gate("G7", f"去味改写完成：{rounds} 轮 · 复扫{'通过' if not blocking else f'仍 {len(blocking)} 处阻断'}"
                             f"（当前 {project.count_chars(prose)} 字，下一步审校）", chapter=num)
    if g7_idea is None:
        g7_idea = ctx.consume_gate_idea()   # 回退想法就地消费，防串章
        ctx.log("warn", "G7 回退：保留去味前原稿继续")
        if rounds and prose != pre_deslop_prose:
            _archive_inner_rollback(ctx, proj, num, "G7", prose)   # 去味稿归档
            prose = pre_deslop_prose                                # 还原原稿
            if _session_usable(session):
                session.rollback_to(pre_deslop_turns)   # 历史截断回去味前，正文消息与实际一致
            blocking, advisory = gates.scan_deslop(prose)
            gr.blocking_findings, gr.advisory_findings = blocking, advisory
            gr.deslop_rounds_used = 0
        if blocking:
            ctx.log("warn", f"G7：原稿 {len(blocking)} 处阻断按人工裁决保留（降级为建议）")
            gr.advisory_findings = gr.advisory_findings + blocking
            gr.blocking_findings = blocking = []
            gr.final_status = "pass"   # 人工裁决保留原稿 = 本步通过
    elif g7_idea:
        _store_inner_gate_idea(ctx, proj, num, "G7", g7_idea)

    # ---- ④.5 审校（v2 6 维最终审核，可开关；用审校槽）----
    # 断点续跑（方案 H）：停在审校中途时，已投票数从 chapter_step 恢复，只补投剩余的票
    skip_review = resume_at in ("review", "finalize")
    verdict_review, blocking_review, review_ran = "", [], False
    pre_review_prose = prose   # G8 回退还原点
    review_enabled = gates_cfg.get("review_enabled", True)
    post_review_turns = session.turn_count() if _session_usable(session) else 0
    review_mode = str(gates_cfg.get("review_mode") or "auto").strip().lower()
    manual_review = review_enabled and review_mode == "manual"
    if manual_review:
        review_ran = not skip_review
        if skip_review:
            ctx.log("info", f"第 {num} 章 断点续跑：审校已完成，跳过（进入定稿）")
        else:
            ctx.stream_stage(f"人工审校 第{num}章")
            blocking_review, advisory_review, verdict_review, prose = _author_review_entry(
                ctx, num, prose,
                pre_review_prose=pre_review_prose, session=session,
                post_review_turns=post_review_turns, gr=gr, gates_cfg=gates_cfg)
            post_review_turns = session.turn_count() if _session_usable(session) else 0
    elif review_enabled and cfg_mod.slot_connection(ctx.cfg, cfg_mod.SLOT_REVIEW):
        # resume="review" = 审校与 G8 都已走完 → 一并跳过，不二次问门
        review_ran = not skip_review
        if skip_review:
            ctx.log("info", f"第 {num} 章 断点续跑：审校已完成，跳过（进入定稿）")
        else:
            ctx.stream_stage(f"审校 第{num}章")
            blocking_review, advisory_review, verdict_review = _chapter_review(
                ctx, num, prose, done_votes=saved_votes, session=session,
                vote_saver=lambda pl: st.save_chapter_step(
                    proj, num, step_done="deslop", draft_path=draft_rel, votes=pl,
                    outline_fp=outline_fp))
            post_review_turns = session.turn_count() if _session_usable(session) else 0
            gr.review_blocking = blocking_review

        def _demote_word_block():
            """全 [字数] 阻塞 → 降级建议：修复 prompt 有 ±5% 纪律扩不了字数，强修只会原地打转（#37 教训）"""
            nonlocal blocking_review, advisory_review, verdict_review
            ctx.log("warn", f"第 {num} 章 字数不足（{blocking_review[0]}）：字数问题不走修复环，降级为建议"
                            "（请手动扩写或调高扩写轮数）")
            advisory_review = list(advisory_review) + [str(b) for b in blocking_review]
            try:
                st.save_review_findings(proj, st.load_state(proj), num, "PASS_WITH_NOTES",
                                        [{"dim": "D_PLOT", "level": "marginal", "text": str(b),
                                          "quote": "", "root_layer": "ROOT_PROSE", "line": ""}
                                         for b in blocking_review],
                                        [], advisory_review)
            except Exception:
                pass
            blocking_review, verdict_review = [], "PASS_WITH_NOTES"

        if blocking_review and all(str(b).startswith("[字数]") for b in blocking_review):
            _demote_word_block()
        review_rounds = 0
        # v2 反馈环触发：verdict == REJECT/REJECT-HARD 且未达 3 次熔断
        max_review_rounds = max(gates_cfg.get("review_max_rounds", 1), 3)
        while blocking_review and review_rounds < max_review_rounds:
            if all(str(b).startswith("[字数]") for b in blocking_review):
                _demote_word_block()
                break
            review_rounds += 1
            prev_n = len(blocking_review)
            ctx.step(num, st.STEP_REVIEW)
            ctx.log("warn",
                    f"第 {num} 章 6 维审校 {verdict_review} → 修复（第 {review_rounds} 轮）· 阻塞 {prev_n} 处")
            ctx.checkpoint()
            # v2 反馈环：若 REJECT 且 review_rounds >= 2 → 调 ROOT_CAUSE_PROMPT 重新生成问题列表
            if verdict_review in ("REJECT", "REJECT-HARD") and review_rounds >= 2:
                try:
                    issues = (getattr(ctx, "review_v2", None)
                              or parse_final_review_v2(ctx.review_raw or "")).get("items", [])
                    anchors = prompts.build_upstream_anchors(proj, num)
                    issues_brief = prompts.build_issues_brief(issues)
                    root_prompt = prompts.ROOT_CAUSE_PROMPT.format(
                        issues_brief=issues_brief,
                        upstream_anchors=anchors,
                    )
                    ctx.last_prompt = root_prompt
                    root_result = clean_llm_output(
                        ctx.router.client(cfg_mod.SLOT_REVIEW).chat_stream(
                            root_prompt, on_chunk=ctx.stream_chunk,
                            temperature=gates_cfg.get("review_temperature", 0.2),
                            phase=PHASE_ROOT_CAUSE
                        )
                    )
                    # 记录根因
                    try:
                        st.append_review_chain(proj, st.load_state(proj), num,
                                               issues, [root_result[:200]],
                                               verdict_review, review_rounds)
                    except Exception:
                        pass
                    ctx.log("info", f"第 {num} 章 根因溯源完成（{len(issues)} issue · 详见 review_chain）")
                except Exception as e:
                    ctx.log("warn", f"第 {num} 章 根因溯源失败：{e}")
            # 普通修改（v1 REVIEW_FIX_PROMPT + worst_segment_quotes）
            fix_kwargs = dict(chapter_num=num, findings="\n".join(blocking_review), prose=prose,
                              project_header=project_header(proj),
                              chapter_header=chapter_header(proj, num))
            t_fix = session.turn_count() if _session_usable(session) else 0
            rewritten = _rewrite_phase(ctx, session, cfg_mod.SLOT_REVIEW, PHASE_REVIEW_FIX,
                                       prompts.REVIEW_FIX_PROMPT, fix_kwargs, prose=prose,
                                       label=f"审校修改 第{review_rounds}轮")
            # 修复稿健全性守卫（真机缺陷修复：模型可能返回 ===REVISIONS=== 修订计划
            # 而非改后正文；采纳会把整章替换成指令清单，且空文本复检阻塞更少被误判改善）
            looks_like_plan = rewritten.lstrip().startswith("===")
            too_short = len(rewritten.strip()) < max(300, int(len(prose) * 0.5))
            if not rewritten.strip() or looks_like_plan or too_short:
                if _session_usable(session):
                    session.rollback_to(t_fix)   # 修复稿被否决 → 历史截断，正文消息不指向废稿
                ctx.log("warn", f"第 {num} 章 审校修复返回非正文"
                                f"（{'空' if not rewritten.strip() else '修订计划' if looks_like_plan else '长度骤减'}），保留原稿")
                break
            # 回滚保护：修复后复扫，未改善（阻塞不减反增）则保留原稿
            # 复扫只投 review_votes_recheck 票（默认 1）控成本——修复环内不做全量投票
            new_blocking, new_advisory, new_verdict = _chapter_review(
                ctx, num, rewritten, session=session,
                votes=max(1, int(gates_cfg.get("review_votes_recheck", 1))))
            if len(new_blocking) < prev_n:
                prose = rewritten
                blocking_review, advisory_review, verdict_review = new_blocking, new_advisory, new_verdict
                gr.review_blocking = new_blocking
            else:
                if _session_usable(session):
                    session.rollback_to(t_fix)   # 修复稿未改善被否决 → 同步截断修复稿与复检轮
                ctx.log("warn", f"第 {num} 章 审校修复未改善（{prev_n}→{len(new_blocking)} 处），保留原稿")
                blocking_review = new_blocking
                gr.review_blocking = new_blocking
                break
        gr.review_rounds_used = review_rounds
        if blocking_review:
            # 3 次不收敛 → 标 human
            if review_rounds >= max_review_rounds:
                try:
                    st.mark_chapter_need_human(proj, st.load_state(proj), num)
                    ctx.log("warn",
                            f"第 {num} 章 审校 {review_rounds} 轮后仍 {len(blocking_review)} 处阻塞 → 标 chapter_need_human，跳过本轮")
                except Exception:
                    pass
            else:
                ctx.log("warn", f"第 {num} 章 审校 {review_rounds} 轮后仍有 {len(blocking_review)} 处阻塞")
            gates.resolve_failed(ctx, f"第 {num} 章审校未通过（{len(blocking_review)} 处阻塞）", gr)
            _save_review_findings(proj, num, blocking_review)
        elif review_rounds:
            ctx.log("ok", f"第 {num} 章 审校通过（复检 {review_rounds} 轮 · verdict={verdict_review}）")
        else:
            ctx.log("ok", f"第 {num} 章 审校通过（verdict={verdict_review or 'PASS'}）")
    else:
        ctx.log("info", "审校已跳过（未启用或审校槽未绑定连接）")

    # W-3 里程碑②：审校与修复环的轮次先落盘（G8 若要回退，rollback_to 自己会重写持久层）
    _save_session_checkpoint(ctx, session, "审校后")

    # ---- ④.9 决策门 G8：审校完成后（T4.1 内侧门；回退=保留原稿=还原审校前文本）----
    # 人工审校模式下 G8 门已由人工审校循环承担，不再二次弹门
    if review_ran and not manual_review:
        g8_idea = ctx.gate("G8", f"审校完成：verdict {verdict_review or 'PASS'} · 阻塞 {len(blocking_review)} 处"
                                 f"（下一步定稿落库，G9 仍会把关）", chapter=num)
        if g8_idea is None:
            g8_idea = ctx.consume_gate_idea()   # 回退想法就地消费，防串章
            ctx.log("warn", "G8 回退：保留审校前原稿继续")
            if prose != pre_review_prose:
                _archive_inner_rollback(ctx, proj, num, "G8", prose)   # 审校修改稿归档
                prose = pre_review_prose                                # 还原原稿
            if _session_usable(session):
                # 历史截回「首轮审校票固化后」：修复稿轮次作废，正文消息与还原稿一致
                session.rollback_to(post_review_turns)
            if blocking_review:
                ctx.log("warn", f"G8：{len(blocking_review)} 处审校阻塞按人工裁决保留（定稿照常进行，G9 把关）")
                gr.review_blocking = []
                gr.final_status = "pass"
        elif g8_idea:
            _store_inner_gate_idea(ctx, proj, num, "G8", g8_idea)

    # ---- ⑤ 定稿落库：正文 + 追踪四文件 + 摘要链 ----
    ctx.step(num, st.STEP_FINALIZE)
    title = ""
    m = re.search(r"^#+\s*第\s*\d+\s*章[：: ]*\s*(.+)", prose, re.M)
    if m:
        title = m.group(1).strip()
    chapter_path = project.get_chapter_path(proj, num, title)
    # 保存驱动版本体系：定稿落库归档（重写场景归档旧正文；首版则存 v1=定稿）
    old_text = project.read_file(chapter_path)
    if not versions.list_versions(proj, num):
        # 首版：定稿内容本身即 v1（AI 的"保存"动作）
        versions.snapshot(proj, num, prose, versions.SOURCE_FINALIZE)
    elif old_text and old_text != prose:
        versions.snapshot(proj, num, old_text, versions.SOURCE_REREWRITE)
    project.write_file(chapter_path, prose)

    # 追踪四文件
    ctx.checkpoint()
    try:
        tracking = _update_tracking(ctx, num, prose, session=session)
        applied = [k for k in tracking.keys()]
        ctx.log("ok", f"追踪文件已更新：{', '.join(applied) if applied else '（无变化）'}")
    except PipelineStopped:
        # 停止请求在定稿收尾中到达：正文已落库，保留本记录，返回后由调度层停止
        ctx.log("info", f"第 {num} 章已落库，停止请求在收尾中到达，记录保留")
    except Exception as e:
        ctx.log("warn", f"追踪更新失败（不阻断）：{e}")

    # 章节摘要 + 全局摘要链
    ctx.checkpoint()
    try:
        # 头 2000 + 尾 800：模板要求「结尾落点」，只喂开头会让超标章的结尾缺席
        if len(prose) > 3000:
            excerpt = prose[:2000] + "\n…（中段省略）…\n" + prose[-800:]
        else:
            excerpt = prose[:3000]
        summary_prompt = prompts.CHAPTER_SUMMARY_PROMPT.format(
            chapter_num=num, title=title or f"第{num}章",
            prose_excerpt=excerpt, project_header=project_header(proj),
            chapter_header=chapter_header(proj, num))
        ctx.last_prompt = summary_prompt
        if _use_session(ctx, session, cfg_mod.SLOT_HELPER, PHASE_CH_SUMMARY):
            _session_seed(session, prose)
            turn_text = prompts.session_turn_text(
                prompts.CHAPTER_SUMMARY_PROMPT, prose_sentinel="{prose_excerpt}").format(
                chapter_num=num, title=title or f"第{num}章", prose_excerpt=excerpt,
                project_header=project_header(proj), chapter_header=chapter_header(proj, num))
            ctx.last_prompt = turn_text
            chapter_summary = _session_ask(ctx, session, cfg_mod.SLOT_HELPER, turn_text,
                                           phase=PHASE_CH_SUMMARY, stream=False
                                           ).splitlines()[0].strip()
        else:
            chapter_summary = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(
                summary_prompt, phase=PHASE_CH_SUMMARY)).splitlines()[0].strip()
        if chapter_summary:
            memory.append_chapter_summary(proj, num, title or f"第{num}章", chapter_summary)
            # V7（writing.summary_every，缺省 1=每章重算）：全局摘要降频——非重算章
            # 沿用旧摘要（滞后至多 N-1 章，消费方为章头快照，可容忍）。
            _every = max(1, int(((ctx.cfg or {}).get("writing", {}) or {})
                                .get("summary_every", 1)))
            if _every > 1 and num % _every != 0:
                ctx.log("info", f"第 {num} 章 全局摘要降频跳过（每 {_every} 章重算一次）")
            else:
                old_global = memory.read_global_summary(proj)
                ctx.checkpoint()
                global_prompt = prompts.GLOBAL_SUMMARY_PROMPT.format(
                    old_summary=old_global or "（全书刚开始）",
                    chapter_num=num, chapter_summary=chapter_summary,
                    chapter_header=chapter_header(proj, num),
                    project_header=project_header(proj))
                ctx.last_prompt = global_prompt
                if _use_session(ctx, session, cfg_mod.SLOT_HELPER, PHASE_G_SUMMARY):
                    # W-2 ②-c：既有全局摘要＝上一章本相位自己的回复，多半已逐字节固化在
                    # 栈里（t3b 实测 ~2.4k han 字/章、类内重复率 95%）。**可证才替换**：
                    # 判定命中才换引用行，否则与改造前逐字相同（崩溃续跑/无历史时必然走这条）
                    _old_g = old_global or "（全书刚开始）"
                    if old_global and getattr(session, "has_history", None) \
                            and session.has_history(old_global):
                        _old_g = ("【＝本会话历史中最近一条全局摘要（既有内容已在其中），"
                                  "在它基础上更新，不要要求重新输出旧摘要】")
                    turn_text = prompts.session_turn_text(prompts.GLOBAL_SUMMARY_PROMPT).format(
                        old_summary=_old_g,
                        chapter_num=num, chapter_summary=chapter_summary,
                        chapter_header=chapter_header(proj, num), project_header=project_header(proj))
                    ctx.last_prompt = turn_text
                    new_global = _session_ask(ctx, session, cfg_mod.SLOT_HELPER, turn_text,
                                              phase=PHASE_G_SUMMARY, stream=False)
                else:
                    new_global = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(
                        global_prompt, phase=PHASE_G_SUMMARY))
                if new_global.strip():
                    memory.write_global_summary(proj, new_global)
                ctx.log("ok", f"摘要链已更新（全局摘要 {len(new_global)} 字）")
    except PipelineStopped:
        ctx.log("info", f"第 {num} 章摘要链更新被停止请求中断（不影响已落库正文与记录）")
    except Exception as e:
        ctx.log("warn", f"摘要链更新失败（不阻断）：{e}")

    # ---- 设定清算（方案 D1）：本章自创设定三分类对账（不阻断，产物落追踪/）----
    try:
        from .canon_audit import audit_chapter
        # v10 audit 鲸鱼修复（深化计划 §8）：审校票的缓存单元注册需要写延迟窗——
        # 13/13 章实测清算首笔在审校末票（hit 99%）后 2-5 秒只记到头部（-65~-81pp）。
        # 复用 S5 节拍窗（session_pace_seconds），缺省 0 不改变既有行为。
        _pace_after_long_call(ctx, cfg_mod, session)
        audit = audit_chapter(proj, num, prose, ctx.cfg, ctx.router, session=session)
        v = audit.get("violations") or []
        hard = [x for x in v if x.get("severity") == "硬伤"]
        adopt = audit.get("adoptions") or []
        if audit.get("failed"):
            ctx.log("warn", f"第 {num} 章 设定清算执行失败（{str(audit.get('error', ''))[:60]}）——"
                            f"本章未对账，勿当作已通过；可用「世界观对账」重跑")
        elif v or adopt:
            ctx.log("warn", f"第 {num} 章 设定清算：违反 {len(v)}（硬伤 {len(hard)}）· "
                            f"可收编自创 {len(adopt)}——详见 追踪/设定清算_第{num:03d}.json")
        else:
            ctx.log("ok", f"第 {num} 章 设定清算：无越界")
    except Exception as e:
        ctx.log("warn", f"设定清算失败（不阻断）：{e}")

    # 断点收尾（方案 H）：本章全流程完成，清除章内断点
    st.clear_chapter_step(proj)
    # S1 卷会话：逐章 append-only 落盘（v3 §2.4）——崩溃恢复后消息逐字节一致，
    # 服务端前缀缓存继续有效（不重放、不重新 miss）。
    _save_session_checkpoint(ctx, session, "定稿后")
    gr.word_actual = project.count_chars(prose)
    record = {"num": num, "title": title, **gr.to_record()}
    return record


# ============ 审校（v1 一致性检查 + v2 6 维最终审核）============

def review_l0_block(proj: str, num: int, prose: str) -> str:
    """L0 确定性预检组装（流水线/修复复审/共写审校三注入点共用）

    专名/跨章复读/数值账/章末弱钩/题材禁词 → 格式化注入审校 prompt；
    再接本书正则 must 的确定性命中（app/mustscan）。后者是契约违规的
    第二层处置：不另起一个自动重试环（那会和 ±20% 字数纪律互相拉扯出振荡），
    直接交给既有审校反馈环——它带着全量上下文改，且本就有三轮熔断。
    """
    prev = project.nearest_chapter_before(proj, num)
    prev_prose = (project.read_file(prev[2]) if prev else "") or ""
    ledger_text = "\n".join([
        project.worldbook_text(proj, 1500, num=num),
        project.read_file(project.get_tracking_path(proj, "角色状态")) or "",
    ])
    genre = (project.read_idea_info(proj) or {}).get("genre", "") or ""
    forbidden = [] if any(k in genre for k in ("修仙", "仙侠", "玄幻")) else scan.GENERIC_FORBIDDEN
    block = scan.format_scan_block(scan.scan_chapter(
        prose, prev_prose, roster=project.worldbook_anchors(proj, 0),
        ledger_text=ledger_text, forbidden_words=forbidden))
    must_fs = mustscan.scan_proj(proj, prose)
    if must_fs:
        block += "\n\n【正则 must 契约·本地确定性命中】\n" + mustscan.format_must_findings(must_fs)
    # V5（深度研究 §5）：账本对照——爽点兑现/钟点复现/禁止释放三探测器 + 状态在场
    # 清单（证据供给）。确定性正则，fail-open，绝不阻断。
    from .l0_checks import build_v5_block
    _v5 = build_v5_block(
        proj, num, prose,
        read_outline=lambda: project.read_file(project.get_outline_path(proj, num)),
        read_states=lambda: project.read_file(project.get_tracking_path(proj, "角色状态")))
    if _v5:
        block += "\n\n" + _v5
    return block


def build_final_review_prompt(proj: str, cfg: dict, num: int, prose: str,
                              template: str = None) -> str:
    """组装 6 维终审 prompt（**唯一装配点**：流水线/共写查验/复审共用）

    共写侧原先自带一份同构 .format，两处的 budget/anchors 传参极易漂移；
    收敛后新增注入项只需改这里（回归由 tests/probe_prompt_baseline.py 兜底）。
    template（调整四）：传 prompts.FINAL_REVIEW_COMPACT 走紧凑票协议，注入项相同。
    """
    wb_block, rg_block, _meta = _wb_rg_blocks(proj, cfg, num)
    # 上下文事实（核心设定/全局摘要/角色状态/伏笔/时间线/细纲）由双层前缀统一承载，
    # 此处只注入审校专属的激活条目/正则/题材专项/本地预检/正文
    return (template or prompts.FINAL_REVIEW_PROMPT).format(
        project_header=project_header(proj),
        chapter_header=chapter_header(proj, num),
        prose=prose[:6000],
        worldbook_block=wb_block,
        regex_block=rg_block,
        genre_review_extra=_genre_review_extra(proj),
        l0_findings=review_l0_block(proj, num, prose),
    )


def _build_final_review_prompt(ctx, num: int, prose: str) -> str:
    """ctx 薄封装（流水线调用）"""
    return build_final_review_prompt(ctx.proj, ctx.cfg, num, prose)


_LEVEL_STRICT = {"fail": 2, "marginal": 1, "pass": 0}

# CISC 置信权重（E3.2，arXiv:2502.06233：置信加权投票在路径数 -40% 后仍胜普通 SC）
_VOTE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}


def merge_review_votes(parsed_list: list) -> dict:
    """多轮独立审校结果聚合（P5）：每维多数票，平票从严。

    - fail（阻塞）需 ≥2 票（不足票数的 fail 维降 marginal 并进 advisory）；k=1 时 quorum=1
    - 每维合并为一条代表条目（阻塞项跨票去重合并）
    - summary/verdict 全部重算（丢弃单票声明的判决）
    - **CISC 置信加权**（E3.2）：所有票都带 confidence（parse_final_review_v2 从
      ===CONFIDENCE=== 行解析）时切换加权制——每维等级按票权计分（high 1.0/medium
      0.6/low 0.3），得分最高者为合并等级（平票从严）；fail 维阻塞线=加权分 ≥1.0
      （≈两票 high，或 high+medium+low），不足降级 marginal 进 advisory。
      任一票缺 confidence → 整体回退多数票制（向后兼容，断点续跑混票也安全）。
    """
    k = len(parsed_list)
    quorum = 2 if k >= 2 else 1
    confs = [str(v.get("confidence") or "").strip().lower() for v in parsed_list]
    weights = ([_VOTE_WEIGHTS[c] for c in confs]
               if parsed_list and all(c in _VOTE_WEIGHTS for c in confs) else None)
    dim_items = {}    # dim -> [item, ...]（跨票）
    dim_levels = {}   # dim -> [level, ...]
    order = []
    for parsed in parsed_list:
        for it in parsed.get("items", []):
            d = it.get("dim")
            lvl = it.get("level")
            if not d or lvl not in _LEVEL_STRICT:
                continue
            if d not in dim_items:
                dim_items[d] = []
                dim_levels[d] = []
                order.append(d)
            dim_items[d].append(it)
            dim_levels[d].append(lvl)
    items, blocking, advisory = [], [], []
    summary = {"pass": 0, "marginal": 0, "fail": 0}
    for d in order:
        levels = dim_levels[d]
        scores = {}
        if weights:
            for lvl, w in zip(levels, weights):
                scores[lvl] = scores.get(lvl, 0.0) + w
            top = max(scores.values())
            cands = [lvl for lvl, sc in scores.items() if abs(sc - top) < 1e-9]
        else:
            counts = {}
            for lvl in levels:
                counts[lvl] = counts.get(lvl, 0) + 1
            scores = {lvl: float(c) for lvl, c in counts.items()}
            top = max(counts.values())
            cands = [lvl for lvl, c in counts.items() if c == top]
        merged_lvl = max(cands, key=lambda x: _LEVEL_STRICT[x])   # 平票从严
        cand_items = dim_items[d]
        if merged_lvl == "fail":
            if weights:
                fail_votes = scores.get("fail", 0.0)
                fail_ok = fail_votes >= 1.0
                votes_txt = "w%.1f/%d" % (fail_votes, k)
                demote_prefix = "[票权不足降级 %s] " % votes_txt
            else:
                fail_votes = int(scores.get("fail", 0.0))
                fail_ok = fail_votes >= quorum
                votes_txt = f"{fail_votes}/{k}"
                demote_prefix = f"[票数不足降级 {votes_txt}] "
            fail_items = [it for it in cand_items if it.get("level") == "fail"]
            if fail_ok:
                # 阻塞项跨票去重合并（引证或文首 30 字为键）
                seen, merged_texts = set(), []
                for it in fail_items:
                    key = (it.get("quote") or "").strip() or it.get("text", "")[:30]
                    if key in seen:
                        continue
                    seen.add(key)
                    merged_texts.append(it.get("text", ""))
                rep = fail_items[0]
                item = {"dim": d, "level": "fail",
                        "text": " ｜ ".join(t for t in merged_texts if t),
                        "quote": rep.get("quote", ""),
                        "root_layer": rep.get("root_layer", "ROOT_PROSE"),
                        "line": "", "votes": votes_txt}
                items.append(item)
                blocking.append(item["text"])
                summary["fail"] += 1
            else:
                rep = fail_items[0] if fail_items else cand_items[0]
                item = {"dim": d, "level": "marginal",
                        "text": demote_prefix + rep.get("text", ""),
                        "quote": rep.get("quote", ""),
                        "root_layer": rep.get("root_layer", ""),
                        "line": "", "votes": votes_txt}
                items.append(item)
                advisory.append(item["text"])
                summary["marginal"] += 1
        elif merged_lvl == "marginal":
            marg_items = [it for it in cand_items if it.get("level") == "marginal"]
            rep = marg_items[0] if marg_items else cand_items[0]
            item = {"dim": d, "level": "marginal", "text": rep.get("text", ""),
                    "quote": rep.get("quote", ""),
                    "root_layer": rep.get("root_layer", ""), "line": "",
                    "votes": f"{scores.get('marginal', 0):g}/{k}"}
            items.append(item)
            advisory.append(item["text"])
            summary["marginal"] += 1
        else:
            summary["pass"] += 1
    verdict = compute_verdict(summary, items, "")   # 丢弃单票声明，按聚合计数重算
    return {"verdict": verdict, "items": items, "blocking": blocking,
            "advisory": advisory, "summary": summary, "vote_count": k,
            "vote_mode": "confidence_weighted" if weights else "majority"}


def _votes_identical(a: dict, b: dict) -> bool:
    """两票是否完全一致（早停判据：维度等级全同且判决相同）"""
    if (a.get("verdict") or "") != (b.get("verdict") or ""):
        return False
    la = {it.get("dim"): it.get("level") for it in a.get("items", [])}
    lb = {it.get("dim"): it.get("level") for it in b.get("items", [])}
    return la == lb


REVIEW_PROTOCOL_MARKS = ("===A_GOLDEN_OPEN===", "===B_PAYOFF===", "===C_FINGER===",
                         "===D_PLOT===", "===E_CHARACTER===", "===F_HOOK===",
                         "===VERDICT===")


def review_vote_structured(raw: str) -> bool:
    """审校票是否真按协议产出。

    一条协议标记都没有＝模型在整章回声（或网关吞了格式），**不能**当成"审过、没问题"——
    2026-09-09 的 v7_long13 就是 11/11 空转、0 findings、verdict 恒 PASS、修复环 0 次。"""
    return any(m in (raw or "") for m in REVIEW_PROTOCOL_MARKS)


def _record_vote_fingerprints(proj: str, num: int, raws: list, parsed_list: list) -> None:
    """W-6 前置仪器：**不装仪器不许降票**。

    审校是 `review_temperature=0.2` + `thinking:disabled` + TEMP_LOCKED_PHASES ⇒ 三票近乎
    确定性；代码注释里的"票间必不同构"只在思考模式下成立。但票原文从不落盘，
    于是"3 票里有多少是真独立信息"根本量不出来，而降票（k=3→1）省的是最贵的钱。
    这里逐票落指纹：sha1 + 六维等级向量 + fail/marginal 计数 + 是否整章回声 + 是否未产出协议，
    追加到 项目/追踪/vote_fingerprints.jsonl（cost_bench 聚合成 metrics["vote_iso"]）。
    纯观测件：任何失败静默，绝不影响主流水线。"""
    try:
        import datetime as _dt
        import hashlib
        import json as _json
        import os as _os
        path = _os.path.join(proj, "追踪", "vote_fingerprints.jsonl")
        _os.makedirs(_os.path.dirname(path), exist_ok=True)
        for i, raw in enumerate(raws):
            v2 = parsed_list[i] if i < len(parsed_list) and isinstance(parsed_list[i], dict) else {}
            levels, fails, marg = {}, 0, 0
            for it in (v2.get("items") or []):
                if not isinstance(it, dict):
                    continue
                dim = str(it.get("dim") or "?")
                lvl = str(it.get("level") or "")
                levels[dim[:24]] = lvl[:9]
                if lvl == "fail":
                    fails += 1
                elif lvl == "marginal":
                    marg += 1
            txt = raw or ""
            rec = {"ts": _dt.datetime.now().strftime("%H:%M:%S"),
                   "ch": int(num or 0), "i": i + 1,
                   "sha1": hashlib.sha1(txt.encode("utf-8")).hexdigest()[:12],
                   "han": sum(1 for c in txt if "一" <= c <= "鿿"),
                   "levels": levels, "fail": fails, "marginal": marg,
                   "echo": txt.lstrip().startswith("# 第"),
                   "unstructured": bool(v2.get("unstructured"))}
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def review_with_votes(ctx, num: int, prose: str, votes: int,
                      done_votes: list = None, vote_saver=None, session=None) -> dict:
    """k 次独立审校投票（P5）：温度治理 + 引证验真后按维聚合。

    投票调度（v0.19 缓存版）：首票单发（流式回显）→ 其余票并行。首票把审校
    prompt（含两层前缀+本章正文）写进 DeepSeek 前缀缓存，并行票全量命中——
    旧「前两票并行」方案因缓存写竞态烧掉两份全价 miss；两阶段墙钟不变。
    v4 thinking 模式下 temperature 无效、票间必不同构，早停判据（票完全一致）
    名存实亡，已移除。
    章会话（session 生效时）：首票经会话追加轮（正文引用历史），其余票以
    首票请求的快照并行重采样，仅首票轮次固化。
    断点续跑（方案 H）：done_votes 为已完成的票（章内断点恢复），只补投差额；
    vote_saver 在每票落袋时被调用（持久化到 chapter_step，停止不丢票）。
    返回聚合后的 v2 结构；ctx.review_raw 记录第 1 张新票原始输出。
    """
    votes = max(1, int(votes))
    gates_cfg = ctx.cfg.get("gates", {})
    temp = gates_cfg.get("review_temperature", 0.2)
    use_sess = _session_usable(session)
    if use_sess:
        _session_seed(session, prose)
    wb_block, rg_block, _wbmeta = _wb_rg_blocks(ctx.proj, ctx.cfg, num)
    kw = dict(
        project_header=project_header(ctx.proj),
        chapter_header=chapter_header(ctx.proj, num),
        prose=prose,
        worldbook_block=wb_block,
        regex_block=rg_block,
        genre_review_extra=_genre_review_extra(ctx.proj),
        l0_findings=review_l0_block(ctx.proj, num, prose),
    )
    # 调整四（writing.review_compact，缺省关）：票输出走紧凑 JSON 协议——
    # rubric 前缀与长文版逐字节共用，只换输出协议；解析失败自动回退长文重投。
    _compact_on = bool((ctx.cfg or {}).get("writing", {}).get("review_compact", False))
    _review_template = prompts.FINAL_REVIEW_COMPACT if _compact_on else prompts.FINAL_REVIEW_PROMPT
    prompt = _build_final_review_prompt(ctx, num, prose) if not _compact_on \
        else build_final_review_prompt(ctx.proj, ctx.cfg, num, prose, template=_review_template)
    turn_text = prompts.session_turn_text(_review_template).format(**kw) if use_sess else ""
    if use_sess and bool((ctx.cfg or {}).get("writing", {}).get("review_in_system", False)):
        # V1-③：rubric 已随会话 system 载入（_acquire_volume_session），审校轮剥掉它；
        # **输出协议必须留在近场**——2026-09-09 v7_long13 实测：整条尾段一起搬进 system 后
        # 审校轮只剩 394 字、零协议标记，11/11 整章回声 → 0 findings → verdict 恒 PASS。
        _rubric = prompts.review_static_tail()
        _proto = prompts.review_compact_protocol() if _compact_on \
            else prompts.review_output_protocol()
        _full = _rubric + _proto
        if _full and turn_text.endswith(_full):
            turn_text = (turn_text[:-len(_full)].rstrip("\n")
                         + ("\n\n" + _proto if _proto else ""))
    ctx.last_prompt = turn_text or prompt
    # 副本票基线快照：必须在首票固化**之前**取（否则副本栈里带着首票回复，
    # 变成"审过一次再重审"而非独立重采样）
    replica_base = session.snapshot() if use_sess else None

    # E3.2 CISC 置信票：gates.review_confidence_vote 开启时票尾追加 ===CONFIDENCE=== 行，
    # merge_review_votes 检测到全票带置信度即切换加权制（任一票缺失→回退多数票制）
    _vote_base_extra = ""
    if bool(gates_cfg.get("review_confidence_vote", False)):
        _vote_base_extra += (
            "\n\n===CONFIDENCE===\n"
            "输出最后追加一行：===CONFIDENCE=== high|medium|low"
            "（对本次审校整体判断的置信度：每条 fail 都核到真实原文引证才给 high；"
            "拿不准的判据较多给 low）。")

    def _vote_extra(vote_idx: int) -> str:
        """每票附加段：shuffle_dims 旗标按票序随机化六维检查顺序——LLM-as-judge 的
        首位偏置消除（MT-Bench 系证据），零成本；种子=(章号,票号) 可重放。"""
        if not _phase_param(ctx, PHASE_REVIEW, "shuffle_dims"):
            return _vote_base_extra
        import random
        order = list(_DIM_MAP.values())
        random.Random((int(num), int(vote_idx))).shuffle(order)
        return _vote_base_extra + (
            "\n\n（本次投票建议按以下顺序逐维检查，六维全部输出、不得缺维："
            + "、".join(order) + "）")

    def _parse(raw: str) -> dict:
        parsed = parse_compact_review_json(raw, prose) if _compact_on else None
        if parsed is not None:
            v2 = verify_review_quotes(prose, parsed)
            v2["unstructured"] = False
            return v2
        v2 = verify_review_quotes(prose, parse_final_review_v2(raw))
        if not v2["verdict"]:   # v1 兜底
            fb, fa = parse_review_findings(raw)
            v2["blocking"] = v2["blocking"] or fb
            v2["advisory"] = v2["advisory"] or fa
        v2["unstructured"] = not review_vote_structured(raw)
        return v2

    parsed_list = [dict(v) for v in (done_votes or [])][:votes]
    remaining = votes - len(parsed_list)
    if remaining <= 0:
        return merge_review_votes(parsed_list) if len(parsed_list) > 1 else (parsed_list[0] if parsed_list else {})
    raws = []
    _review_slot = genre_presets.stage_slot(_preset_id(getattr(ctx, "proj", "")), PHASE_REVIEW) or cfg_mod.SLOT_REVIEW

    _RETRY_PROTOCOL = ("\n\n（重申：上一条回复没有按协议输出。必须逐维输出 "
                       "===A_GOLDEN_OPEN=== … ===F_HOOK=== 六段，再输出 ===VERDICT===/===ITEMS===/===END===，"
                       "不得复述正文。）")

    def _cast_solo(extra: str = "", *, text: str = None) -> tuple:
        """首票：单发流式（写前缀缓存 / 会话固化首票轮）；text 可覆写轮文本
        （调整四：紧凑票失败回退长文格式重投时传入长文版轮文本）"""
        body = (turn_text if use_sess else prompt) if text is None else text
        body = body + _vote_extra(1) + extra
        if use_sess:
            raw = _session_ask(ctx, session, cfg_mod.SLOT_REVIEW, body,
                               label=f"审校投票 第{num}章", phase=PHASE_REVIEW,
                               temperature=temp)
        else:
            client = ctx.router.client(_review_slot)
            raw = clean_llm_output(client.chat_stream(
                body, on_chunk=ctx.stream_chunk, temperature=temp, phase=PHASE_REVIEW))
        return raw, _parse(raw)

    def _cast_replica(vote_idx: int = 2) -> tuple:
        """副本票：以首票请求快照并行重采样（输出不计入会话正史）"""
        if use_sess:
            msgs = replica_base + [{"role": "user", "content": turn_text + _vote_extra(vote_idx)}]
            client = ctx.router.client(_review_slot)
            raw = clean_llm_output(client.chat_turn(msgs, temperature=temp, phase=PHASE_REVIEW))
        else:
            client = ctx.router.client(_review_slot)
            raw = clean_llm_output(client.chat_stream(
                prompt + _vote_extra(vote_idx), temperature=temp, phase=PHASE_REVIEW))
        return raw, _parse(raw)

    def _collect(replicas: int):
        """副本票并发下发——墙钟≈最慢一票"""
        if replicas <= 0:
            return
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=replicas) as ex:
            futs = [ex.submit(_cast_replica, len(parsed_list) + j + 1)
                    for j in range(replicas)]
            for f in futs:
                raw, v2 = f.result()
                raws.append(raw)
                parsed_list.append(v2)
                if vote_saver:
                    try:
                        vote_saver(parsed_list)
                    except Exception:
                        pass
                try:
                    ctx.log("info", f"第 {num} 章 审校第 {len(parsed_list)}/{votes} 票："
                                    f"{v2['verdict'] or '格式未识别'}（fail={v2['summary']['fail']}）")
                except Exception:
                    pass

    raw, v2 = _cast_solo()
    if v2.get("unstructured"):
        if _compact_on:
            # 调整四回退：紧凑票没按协议产出 → 长文格式重投一次（max_tokens 1400，
            # 会话轮同步换回长文版——协议段在近场才有效，V1-③ 教训）。仍失败走
            # 下方既有「未审」分支，绝不静默当 PASS。
            ctx.log("warn", f"第 {num} 章 紧凑票未按 JSON 协议产出 → 回退长文格式重投…")
            _long_prompt = build_final_review_prompt(ctx.proj, ctx.cfg, num, prose)
            with _stage_param_override(ctx, PHASE_REVIEW, max_tokens=1400):
                raw, v2 = _cast_solo(
                    text=(prompts.session_turn_text(prompts.FINAL_REVIEW_PROMPT).format(**kw)
                          if use_sess else _long_prompt))
            if v2.get("unstructured"):
                ctx.log("warn", f"第 {num} 章 长文重投后仍无协议段：本章按「未审」处理，不放行 PASS")
        else:
            # 空转票重投一次（带协议重申）。不重投就等于把"模型没按格式答"当成"这章没问题"。
            ctx.log("warn", f"第 {num} 章 审校首票未产出协议段（疑似整章回声）→ 重申格式重投…")
            raw, v2 = _cast_solo(_RETRY_PROTOCOL)
            if v2.get("unstructured"):
                ctx.log("warn", f"第 {num} 章 审校重投后仍无协议段：本章按「未审」处理，不放行 PASS")
    raws.append(raw)
    parsed_list.append(v2)
    if vote_saver:
        try:
            vote_saver(parsed_list)
        except Exception:
            pass
    try:
        ctx.log("info", f"第 {num} 章 审校第 {len(parsed_list)}/{votes} 票："
                        f"{v2['verdict'] or '格式未识别'}（fail={v2['summary']['fail']}）")
    except Exception:
        pass
    # PASS 快速道（gates.review_pass_fast，v0.19 默认开）：首票全维 pass 且零
    # 阻塞 → 免投副本票（省 2/3 审校输出）。与 P5 合并语义兼容：quorum 只对
    # fail 收紧（不足票数的 fail 降级），单票 PASS 在合并函数里本就成立。
    _fast = (bool((ctx.cfg.get("gates") or {}).get("review_pass_fast", True))
             and remaining >= 2
             and not v2.get("unstructured")          # 空转票不是 PASS，别借快速道把审校关掉
             and v2.get("verdict") in ("PASS", "PASS_WITH_NOTES")
             and not (v2.get("summary") or {}).get("fail")
             and not v2.get("blocking"))
    if _fast:
        try:
            ctx.log("info", f"第 {num} 章 PASS 快速道：首票全维通过零阻塞，免投 {remaining - 1} 张副本票")
        except Exception:
            pass
    else:
        _collect(remaining - 1)
    if vote_saver:
        try:
            vote_saver(parsed_list)
        except Exception:
            pass
    merged = merge_review_votes(parsed_list) if len(parsed_list) > 1 else parsed_list[0]
    if merged is not None and parsed_list and all(v.get("unstructured") for v in parsed_list):
        # 全部票都没产出协议段 ⇒ 「未审」，不是「没问题」。verdict 清空交上层按失败处理，
        # 绝不允许留成 PASS（v7_long13 的 11/11 空转就是这样被静默吞掉的）。
        merged = dict(merged)
        merged["unreviewed"] = True
        merged["verdict"] = ""
        merged["unstructured_votes"] = len(parsed_list)
    ctx.review_raw = raws[0] if raws else ""
    # W-6 前置仪器：逐票落指纹（同构率明天才量得出来；不装仪器不许降票）
    _record_vote_fingerprints(ctx.proj, num, raws, parsed_list)
    # A2 双轨裁决：【世界书修正】条目（正文自洽而世界书条目疑过时）→ 登记修正提案
    try:
        n_proposed = memory.propose_worldbook_corrections(ctx.proj, num, merged.get("items", []))
        if n_proposed:
            ctx.log("warn", f"第 {num} 章 审校登记 {n_proposed} 条世界书修正提案"
                            f" → {memory.PROPOSAL_PATH}（人工核对后并入，不自动改世界书）")
    except Exception:
        pass
    return merged


def _author_review_entry(ctx, num: int, prose: str, *,
                         pre_review_prose: str = None, session=None,
                         post_review_turns: int = 0, gr=None,
                         gates_cfg: dict = None) -> tuple:
    """人工审校循环（gates.review_mode=manual）：作者在 G8 门里当审校。

    - 留空 = 放行（verdict AUTHOR_PASS，零审校 LLM 调用）
    - 填阻断问题（每行一条）→ agent 按 REVIEW_FIX 修复 → 作者复验，循环至放行/回退
    - 回退（gate 返回 None）= 保留人工审校开始前的原稿（与自动 G8 同语义）
    返回 (blocking, advisory, verdict, prose)——prose 可能在修复后更新。
    """
    proj = ctx.proj
    gates_cfg = gates_cfg or {}
    gr = gr if gr is not None else gates.GateResult()
    pre = prose if pre_review_prose is None else pre_review_prose
    _wc_items, _wc_blocking, _wc_verdict = gates.word_count_precheck(proj, num, prose, ctx.cfg)
    wc_note = f"（字数提示：{_wc_blocking[0]}）" if _wc_verdict else ""
    manual_rounds = 0
    blocking_review: list = []
    advisory_review: list = []
    verdict_review = "AUTHOR_PASS"
    while True:
        issues = ctx.gate("G8", f"人工审校 第{num}章{wc_note}：输入**阻断级**问题，每行一条；留空 = 通过",
                          chapter=num)
        if issues is None:
            # 作者选择回退：与自动 G8 同语义——保留人工审校开始前的原稿
            if prose != pre:
                _archive_inner_rollback(ctx, proj, num, "G8", prose)
                prose = pre
            if _session_usable(session):
                session.rollback_to(post_review_turns)
            blocking_review, gr.review_blocking = [], []
            ctx.log("warn", f"第 {num} 章 人工审校回退：保留原稿继续")
            break
        lines = [ln.strip(" -·") for ln in str(issues).splitlines() if ln.strip(" -·")]
        if not lines:
            blocking_review, advisory_review, verdict_review = [], [], "AUTHOR_PASS"
            gr.review_blocking = []
            try:
                st.save_review_findings(proj, st.load_state(proj), num, "AUTHOR_PASS", [], [], [])
            except Exception:
                pass
            ctx.log("ok", f"第 {num} 章 人工审校通过（作者放行）")
            break
        if not cfg_mod.slot_connection(ctx.cfg, cfg_mod.SLOT_REVIEW):
            ctx.log("warn", f"第 {num} 章 人工审校填了 {len(lines)} 条问题，但审校槽未绑定连接，无法自动修复")
            blocking_review, gr.review_blocking = lines, lines
            gates.resolve_failed(ctx, f"第 {num} 章人工审校问题无法修复（审校槽未绑定连接）", gr)
            break
        blocking_review = lines
        gr.review_blocking = blocking_review
        manual_rounds += 1
        try:
            st.save_review_findings(
                proj, st.load_state(proj), num, "AUTHOR_ISSUES",
                [{"dim": "D_PLOT", "level": "fail", "text": t, "quote": "",
                  "root_layer": "ROOT_AUTHOR", "line": ""} for t in lines],
                lines, [])
        except Exception:
            pass
        ctx.log("warn", f"第 {num} 章 人工审校 {len(lines)} 条阻断 → AI 修复（第 {manual_rounds} 轮）")
        t_fix = session.turn_count() if _session_usable(session) else 0
        fix_kwargs = dict(chapter_num=num, findings=chr(10).join(lines), prose=prose,
                          project_header=project_header(proj),
                          chapter_header=chapter_header(proj, num))
        rewritten = _rewrite_phase(ctx, session, cfg_mod.SLOT_REVIEW, PHASE_REVIEW_FIX,
                                   prompts.REVIEW_FIX_PROMPT, fix_kwargs, prose=prose,
                                   label=f"人工审校修复 第{manual_rounds}轮")
        # 修复稿健全性守卫（与自动修复环同款）
        looks_like_plan = rewritten.lstrip().startswith("===")
        too_short = len(rewritten.strip()) < max(300, int(len(prose) * 0.5))
        if rewritten.strip() and not looks_like_plan and not too_short:
            prose = rewritten
        else:
            ctx.log("warn", f"第 {num} 章 人工审校修复返回非正文，保留原稿（问题清单仍生效，可回退或继续填）")
        if manual_rounds >= max(gates_cfg.get("review_max_rounds", 1), 3):
            ctx.log("warn", f"第 {num} 章 人工审校修复已达 {manual_rounds} 轮上限，请最终裁决")
    return blocking_review, advisory_review, verdict_review, prose


def _chapter_review(ctx, num: int, prose: str, votes: int = None,
                    done_votes: list = None, vote_saver=None, session=None) -> tuple:
    """v2 6 维最终审核（多轮投票 + 引证验真；用 FINAL_REVIEW_PROMPT）

    Args:
        votes: 投票数；None=取 gates.review_votes（默认 3）；修复环复扫传
               gates.review_votes_recheck（默认 1）控成本

    Returns:
        (blocking, advisory, verdict) 三元组
        - blocking: 阻断级 issue 列表（兼容 v1 解析）
        - advisory: 建议级 issue 列表
        - verdict: PASS / PASS_WITH_NOTES / REJECT / REJECT-HARD / ''（解析失败）

    v1 fallback: 若 LLM 没按 v2 格式输出（含 ===VERDICT=== 段）→ 自动回退 v1 解析
    """
    proj = ctx.proj
    # 字数预检（本地，零 LLM）：短章直接 REJECT，不花审校调用
    wc_items, wc_blocking, wc_verdict = gates.word_count_precheck(proj, num, prose, ctx.cfg)
    if wc_verdict:
        ctx.log("warn", f"第 {num} 章 字数预检未过：{wc_blocking[0]}（跳过审校 LLM）")
        try:
            st.save_review_findings(proj, st.load_state(proj), num,
                                    wc_verdict, wc_items, wc_blocking, [])
        except Exception:
            pass
        return wc_blocking, [], wc_verdict
    if votes is None:
        votes = max(1, int(ctx.cfg.get("gates", {}).get("review_votes", 3)))
    try:
        v2 = review_with_votes(ctx, num, prose, votes,
                           done_votes=done_votes, vote_saver=vote_saver, session=session)
    except Exception as e:
        ctx.log("warn", f"第 {num} 章 6 维审校调用失败（不阻断）：{e}")
        return [], [], ""
    ctx.review_v2 = v2   # 根因溯源复用验真后的 items，不重解析原始输出
    if v2.get("unreviewed"):
        # 审校没按协议产出（网关吞格式/整章回声/旗标改动）——留名字，不许静默当"无问题"
        ctx.log("warn", f"第 {num} 章 6 维审校未产出协议段（{v2.get('unstructured_votes')} 票空转）"
                        f"→ 本章标记需人工，不按审校通过处理")
        try:
            st.mark_chapter_need_human(proj, st.load_state(proj), num)
        except Exception:
            pass
        return [], [], ""
    if v2["verdict"]:
        # 落盘 v2 结果
        try:
            st.save_review_findings(proj, st.load_state(proj), num,
                                    v2["verdict"], v2["items"],
                                    v2["blocking"], v2["advisory"])
        except Exception:
            pass
        return v2["blocking"], v2["advisory"], v2["verdict"]
    # fallback: v1 解析
    blocking, advisory = parse_review_findings(ctx.review_raw or "")
    return blocking, advisory, ""


def parse_review_findings(text: str) -> tuple:
    """v1 解析（===BLOCKING=== / ===ADVISORY=== 两段），返回 (blocking, advisory) 文本列表"""
    blocking, advisory = [], []
    section = None
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("===BLOCKING==="):
            section = "blocking"
            continue
        if line.startswith("===ADVISORY==="):
            section = "advisory"
            continue
        if not line:
            continue
        if line in ("无", "- 无", "（无）", "-无"):
            continue
        item = line.lstrip("-•* ").strip()
        if not item:
            continue
        if section == "blocking":
            blocking.append(item)
        elif section == "advisory":
            advisory.append(item)
    return blocking, advisory


# ---- v2 6 维最终审核解析 ----

_DIM_MAP = {
    "===A_GOLDEN_OPEN===": "A_GOLDEN_OPEN",
    "===B_PAYOFF===": "B_PAYOFF",
    "===C_FINGER===": "C_FINGER",
    "===D_PLOT===": "D_PLOT",
    "===E_CHARACTER===": "E_CHARACTER",
    "===F_HOOK===": "F_HOOK",
}


_HARD_ROOTS = ("ROOT_CORE", "ROOT_GLOBAL_SUMMARY", "ROOT_OUTLINE",
               "ROOT_OUTLINE_UNIT", "ROOT_WORLDBOOK", "ROOT_REGEX")


def compute_verdict(summary: dict, items: list, declared: str = "") -> str:
    """审校判决计算（纯函数；单次审校与多轮投票聚合共用）

    优先级：模型显式声明（===VERDICT===/关键词）→ 计数门禁推断；
    REJECT/REJECT-HARD 再做硬根因升级（设定/大纲/世界书等上游层）。
    """
    verdict = (declared or "").strip().upper()
    if verdict not in ("PASS", "PASS_WITH_NOTES", "REJECT", "REJECT-HARD"):
        verdict = ""
    if not verdict:
        if summary["fail"] == 0 and summary["marginal"] <= 1:
            verdict = "PASS"
        elif summary["fail"] >= 2:
            verdict = "REJECT"
        else:
            # fail=1 或 marginal≥2（含 fail=0/marg=2 中间带，从严落改进档）
            verdict = "PASS_WITH_NOTES"
    if verdict in ("REJECT", "REJECT-HARD"):
        for it in items:
            if it.get("level") == "fail" and it.get("root_layer") in _HARD_ROOTS:
                verdict = "REJECT-HARD"
                break
    return verdict


def verify_review_quotes(prose: str, parsed: dict) -> dict:
    """引证验真（P1）：逐条用代码核验【原文引证】是否真在正文里

    编造/记错的引证（验真失败）= 该条作废 → fail 降 marginal 并加前缀；
    降级后重算 summary/blocking/advisory/verdict（原判决可能建立在假引证上）。
    空引证条目不在此处理（修复环另有回收/降级策略）。返回 mutated parsed。
    """
    changed = False
    for it in parsed.get("items", []):
        q = (it.get("quote") or "").strip()
        if not q:
            continue
        ok, _reason = scan.verify_quote(prose, q)
        it["quote_verified"] = ok
        if not ok and it.get("level") == "fail":
            it["level"] = "marginal"
            it["text"] = "[引证未验真] " + it.get("text", "")
            changed = True
    if changed:
        summary = {"pass": 0, "marginal": 0, "fail": 0}
        blocking, advisory = [], []
        for it in parsed.get("items", []):
            lvl = it.get("level")
            if lvl in summary:
                summary[lvl] += 1
            if lvl == "fail":
                blocking.append(it.get("text", ""))
            elif lvl == "marginal":
                advisory.append(it.get("text", ""))
        parsed["summary"] = summary
        parsed["blocking"] = blocking
        parsed["advisory"] = advisory
        # 原判决基于假引证，丢弃显式声明按计数门禁重算
        parsed["verdict"] = compute_verdict(summary, parsed.get("items", []), "")
    return parsed


# ---- 调整四：紧凑票解析（writing.review_compact，缺省关）----

_QUOTE_REF_RE = re.compile(r"^段(\d{1,4})句(\d{1,4})$")
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；])")


def resolve_quote_ref(prose: str, quote_ref: str) -> str:
    """「段N句M」→ 原文片段（段号口径与 span_edit.annotate 一致：非空行含标题行）。

    定位不到（段/句越界、格式不符）返回空串——由 verify_review_quotes 的既有
    纪律接管（空引证不作废条目，但 fail 失去逐字证据）。"""
    m = _QUOTE_REF_RE.match(str(quote_ref or "").strip())
    if not m:
        return ""
    n, k = int(m.group(1)), int(m.group(2))
    paras = [ln.strip() for ln in (prose or "").split("\n") if ln.strip()]
    if not (1 <= n <= len(paras)):
        return ""
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(paras[n - 1]) if s.strip()]
    if not (1 <= k <= len(sents)):
        return ""
    return sents[k - 1]


_COMPACT_VALID_LEVELS = ("pass", "marginal", "fail")
_COMPACT_ROOTS_OK = ("ROOT_CORE", "ROOT_GLOBAL_SUMMARY", "ROOT_OUTLINE",
                     "ROOT_OUTLINE_UNIT", "ROOT_WORLDBOOK", "ROOT_REGEX", "ROOT_PROSE")


def parse_compact_review_json(raw: str, prose: str) -> dict | None:
    """紧凑票 JSON → 既有 v2 结构（字段映射，验真/聚合/修复环零改动）。

    非 JSON / 六维不全 / 维度名或 score 非法 / 缺 verdict → None（调用方回退
    长文解析并触发长文格式重投——schema 过刚时的软着陆）。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    l, r = text.find("{"), text.rfind("}")
    if l < 0 or r <= l:
        return None
    try:
        data = json.loads(text[l:r + 1])
    except ValueError:
        return None
    dims = data.get("dimensions") if isinstance(data, dict) else None
    if not isinstance(dims, list) or not dims:
        return None
    dim_names = set(_DIM_MAP.values())
    items, blocking, advisory = [], [], []
    summary = {"pass": 0, "marginal": 0, "fail": 0}
    seen = set()
    for d in dims:
        if not isinstance(d, dict):
            return None
        name = str(d.get("dim", "")).strip().upper()
        level = str(d.get("score", "")).strip().lower()
        if name not in dim_names or level not in _COMPACT_VALID_LEVELS or name in seen:
            return None
        seen.add(name)
        root = str(d.get("root", "")).strip().upper()
        text_one = str(d.get("one_line", "")).strip()
        quote = resolve_quote_ref(prose, d.get("quote_ref"))
        items.append({
            "dim": name, "level": level, "text": text_one,
            "quote": quote, "quote_ref": str(d.get("quote_ref", "")).strip(),
            "quote_unresolved": not quote and bool(str(d.get("quote_ref", "")).strip()),
            "root_layer": root if root in _COMPACT_ROOTS_OK
                          else ("ROOT_PROSE" if level == "fail" else ""),
            "line": "",
        })
        if level == "fail":
            blocking.append(text_one)
            summary["fail"] += 1
        elif level == "marginal":
            advisory.append(text_one)
            summary["marginal"] += 1
        else:
            summary["pass"] += 1
    if seen != dim_names:
        return None   # 协议：六维缺一视为评审无效 → 回退长文重投
    declared = str(data.get("verdict", "")).strip().upper()
    if declared not in ("PASS", "PASS_WITH_NOTES", "REJECT", "REJECT-HARD"):
        return None
    confidence = str(data.get("confidence", "")).strip().lower()
    if confidence not in ("high", "medium", "low"):
        confidence = ""
    return {
        "verdict": compute_verdict(summary, items, declared),
        "items": items,
        "blocking": blocking,
        "advisory": advisory,
        "summary": summary,
        "confidence": confidence,
        "compact": True,
    }


def parse_final_review_v2(text: str) -> dict:
    """v2 6 维解析 FINAL_REVIEW_PROMPT 输出。

    Returns:
        {
            "verdict": "PASS" | "PASS_WITH_NOTES" | "REJECT" | "REJECT-HARD" | "",
            "items": [
                {"dim": "A_GOLDEN_OPEN", "level": "pass|marginal|fail", "text": "...",
                 "quote": "...", "root_layer": "ROOT_PROSE|...", "line": "..."}, ...
            ],
            "blocking": [issue_text, ...],   # fail 维度的 text
            "advisory": [issue_text, ...],   # marginal 维度的 text
            "summary": {"pass": N, "marginal": M, "fail": K},
        }
    """
    text = text or ""
    items = []
    blocking = []
    advisory = []
    summary = {"pass": 0, "marginal": 0, "fail": 0}
    verdict = ""

    # 阶段 1：解析 6 维 ===X_xxx=== 段
    cur_dim = None
    cur_level = None
    cur_text_parts = []
    cur_quote = ""
    cur_root = ""

    def _flush():
        nonlocal cur_dim, cur_level, cur_text_parts, cur_quote, cur_root
        if cur_dim and cur_level:
            text_joined = " ".join(cur_text_parts).strip()
            items.append({
                "dim": cur_dim,
                "level": cur_level,
                "text": text_joined,
                "quote": cur_quote,
                "root_layer": cur_root or ("ROOT_PROSE" if cur_level == "fail" else ""),
                "line": "",  # 行号定位（暂未启用）
            })
            if cur_level == "fail":
                blocking.append(text_joined)
                summary["fail"] += 1
            elif cur_level == "marginal":
                advisory.append(text_joined)
                summary["marginal"] += 1
            elif cur_level == "pass":
                summary["pass"] += 1
        cur_dim = None
        cur_level = None
        cur_text_parts = []
        cur_quote = ""
        cur_root = ""

    for line in text.splitlines():
        raw = line.rstrip()
        stripped = raw.strip()
        # 6 维标记行
        matched_dim = None
        for marker, dim_name in _DIM_MAP.items():
            if stripped.startswith(marker):
                matched_dim = dim_name
                break
        if matched_dim:
            _flush()  # 上一维结束
            cur_dim = matched_dim
            rest = stripped
            for marker in _DIM_MAP:
                rest = rest.replace(marker, "").strip()
            # rest 形如 "[pass/marginal/fail] + 1 句理由 + 【原文引证："..."】 + → root: ..."
            # 真机缺陷③根因：prompt 规定 [fail] 括号式，旧实现只认裸词 " fail "，括号式全部漏判
            cur_level = ""
            m_lvl = re.match(r"[\[\(]?\s*(pass|marginal|fail)\b", rest, re.I)
            if m_lvl:
                cur_level = m_lvl.group(1).lower()
                rest = rest[m_lvl.end():].strip()
            cur_text_parts = [rest]
            # 抽引证
            if "【原文引证：" in rest:
                q = rest.split("【原文引证：", 1)[1]
                if "】" in q:
                    cur_quote = q.split("】")[0].strip('"').strip()
            # 抽根因
            if "→ root:" in rest or "→ root " in rest:
                r = re.search(r"→\s*root[:\s]+(ROOT_\w+)", rest)
                if r:
                    cur_root = r.group(1)
            continue
        # ===WORST_QUOTES=== / ===TOTAL=== / ===END=== 触发 flush
        if stripped.startswith("===WORST_QUOTES===") or \
           stripped.startswith("===TOTAL===") or \
           stripped.startswith("===END==="):
            _flush()
            continue
        # 追加到当前维度（多行场景：→ root: ROOT_xxx 在后续行）
        if cur_dim is not None:
            cur_text_parts.append(raw)
            # 顺带扫后续行的根因标记
            if not cur_root:
                m = re.search(r"→\s*root[:\s]+(ROOT_\w+)", raw)
                if m:
                    cur_root = m.group(1)
            # 顺带扫后续行的原文引证（真实评审引证常落在维度标记行之后数行）
            if not cur_quote and "【原文引证：" in raw:
                q = raw.split("【原文引证：", 1)[1]
                if "】" in q:
                    cur_quote = q.split("】")[0].strip('"').strip()
    _flush()  # 末尾

    # 阶段 2：解析 verdict（===VERDICT=== 段 → 正文关键词 → 计数门禁 + 硬伤升级）
    declared = ""
    m = re.search(r"===VERDICT===\s*\n?\s*(\w+)", text)
    if m:
        declared = m.group(1).strip().upper()
    if declared not in ("PASS", "PASS_WITH_NOTES", "REJECT", "REJECT-HARD"):
        declared = ""
        up = text.upper()
        for v in ("REJECT-HARD", "REJECT", "PASS_WITH_NOTES"):
            if v in up:
                declared = v
                break
    verdict = compute_verdict(summary, items, declared)

    # ===CONFIDENCE=== 置信度行（E3.2 CISC：gates.review_confidence_vote 开启时
    # prompt 要求票尾追加；merge_review_votes 据此加权）。缺省空串＝票无置信度。
    confidence = ""
    m_conf = re.search(r"===CONFIDENCE===\s*\n?\s*(high|medium|low)\b", text, re.I)
    if m_conf:
        confidence = m_conf.group(1).lower()

    # 阶段 3：verdict 与 findings 一致性兜底（真机缺陷③）。
    # 模型可能用 markdown 写维度（### A_GOLDEN_OPEN：fail …）导致 ===X=== 协议段
    # 全部缺失、blocking 为空——修复轮与 G8 失去抓手。两级兜底：
    #   a) markdown/自由格式维度行扫描：维度名后跟 fail/marginal → 补解析 items
    #   b) 仍为空 → 从总评段合成一条 blocking（标注「未结构化」，保证不静默丢失）
    if verdict in ("REJECT", "REJECT-HARD") and not blocking:
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("==="):
                continue
            for dim_name in _DIM_MAP.values():
                m = re.search(rf"{dim_name}\s*[:：\-—\]]*\s*\[?(fail|marginal)\]?", s, re.I)
                if m:
                    level = m.group(1).lower()
                    issue_text = s[m.end():].strip(" ：:—-") or f"{dim_name} {level}"
                    items.append({"dim": dim_name, "level": level, "text": issue_text[:200],
                                  "quote": "", "root_layer": "ROOT_PROSE" if level == "fail" else "",
                                  "line": ""})
                    if level == "fail":
                        blocking.append(issue_text[:200])
                        summary["fail"] += 1
                    else:
                        advisory.append(issue_text[:200])
                        summary["marginal"] += 1
                    break
    if verdict in ("REJECT", "REJECT-HARD") and not blocking:
        m = re.search(r"===VERDICT===[^\n]*\n(.{0,400})", text, re.S)
        gist = (m.group(1) if m else text[:300]).strip()
        gist = re.sub(r"\s+", " ", gist)[:200]
        blocking.append(f"[未结构化评审] {gist or '评审否决但未给出结构化问题，请人工复核'}")
        summary["fail"] += 1

    return {
        "verdict": verdict,
        "items": items,
        "blocking": blocking,
        "advisory": advisory,
        "summary": summary,
        "confidence": confidence,
    }


def _save_review_findings(proj: str, num: int, findings: list):
    """审校阻塞问题落盘（append），供人工介入时知道要修什么"""
    try:
        dbg = os.path.join(proj, "pipeline_debug")
        os.makedirs(dbg, exist_ok=True)
        path = os.path.join(dbg, "review_findings.md")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## 第 {num} 章 审校发现（待人工处理）\n")
            for item in findings:
                f.write(f"- {item}\n")
    except Exception:
        pass


TRACKING_DELTA_RECONCILE = 10   # V2：每 10 章一次全量对账（防增量漂移）


def _tracking_delta_on(ctx, num: int) -> bool:
    """V2 增量台账开关：writing.tracking_delta 开且本章不是对账章"""
    return bool(((ctx.cfg or {}).get("writing", {}) or {}).get("tracking_delta", False))         and num % TRACKING_DELTA_RECONCILE != 0


def _update_tracking(ctx, num: int, prose: str, session=None) -> dict:
    if _tracking_delta_on(ctx, num):
        try:
            return _update_tracking_delta(ctx, num, prose, session)
        except Exception:  # noqa: BLE001
            # 可靠性红线（深度研究 §4）：delta 解析/合并失败 → 回退全量重述，
            # 绝不把增量碎片当全文写盘。多花一次调用只发生在失败章。
            logging.getLogger("qianbi.stages").warning(
                "第 %s 章 增量台账失败，回退全量模式", num, exc_info=True)
    return _update_tracking_full(ctx, num, prose, session)


def _update_tracking_full(ctx, num: int, prose: str, session=None) -> dict:
    proj = ctx.proj
    prompt = prompts.TRACKING_UPDATE_PROMPT.format(
        chapter_num=num,
        roster=_roster(proj),
        prose=prose[:6000],
        character_state=project.read_file(project.get_tracking_path(proj, "角色状态"))[:2000],
        foreshadow_table=project.read_file(project.get_tracking_path(proj, "伏笔"))[:2000],
        timeline=project.read_file(project.get_tracking_path(proj, "时间线"))[:1500],
        old_context=project.read_file(project.get_tracking_path(proj, "上下文"))[:1500]
        or "（尚无写作上下文）",
        worldbook=project.worldbook_text(proj, max_chars=2500, num=num) or "（世界书为空）",
        project_header=project_header(proj),
        chapter_header=chapter_header(proj, num),
    )
    ctx.last_prompt = prompt
    if _use_session(ctx, session, cfg_mod.SLOT_HELPER, PHASE_TRACKING):
        _session_seed(session, prose)
        _s4_freeze = bool(((ctx.cfg or {}).get("writing", {}) or {})
                          .get("s4_static_freeze", False)) \
            or bool(((ctx.cfg or {}).get("writing", {}) or {})
                    .get("head_rebuild", False))
        if _s4_freeze and hasattr(session, "open_chapter"):
            # S4-c（卷会话）：{character_state}/{foreshadow_table}/{timeline}/
            # {old_context}/{worldbook} 五节与本章开幕轮/会话历史逐字重复 →
            # 短引用行（TRACKING_SESSION_REF）；{roster} 花名册是追踪的功能性
            # 输入，保留。S1 卷会话/章会话走 else，请求体逐字节不变。
            turn_text = prompts.session_turn_text(prompts.TRACKING_UPDATE_PROMPT).format(
                chapter_num=num,
                roster=_roster(proj), prose=prose,
                character_state=TRACKING_SESSION_REF,
                foreshadow_table=TRACKING_SESSION_REF,
                timeline=TRACKING_SESSION_REF,
                old_context=TRACKING_SESSION_REF,
                worldbook=TRACKING_SESSION_REF,
                project_header=project_header(proj),
                chapter_header=chapter_header(proj, num))
        else:
            turn_text = prompts.session_turn_text(prompts.TRACKING_UPDATE_PROMPT).format(
                chapter_num=num,
                roster=_roster(proj), prose=prose,
                character_state=project.read_file(project.get_tracking_path(proj, "角色状态"))[:2000],
                foreshadow_table=project.read_file(project.get_tracking_path(proj, "伏笔"))[:2000],
                timeline=project.read_file(project.get_tracking_path(proj, "时间线"))[:1500],
                old_context=project.read_file(project.get_tracking_path(proj, "上下文"))[:1500]
                or "（尚无写作上下文）",
                worldbook=project.worldbook_text(proj, max_chars=2500, num=num) or "（世界书为空）",
                project_header=project_header(proj),
                chapter_header=chapter_header(proj, num))
        ctx.last_prompt = turn_text
        result = _session_ask(ctx, session, cfg_mod.SLOT_HELPER, turn_text,
                              phase=PHASE_TRACKING, stream=False)
    else:
        result = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(prompt,
                                                        phase=PHASE_TRACKING))
    updates = parse_tracking_updates(result)
    # 反哺自动档⑤：同一次输出里的新实体/新规则/实体演进/世界观揭示 → 回写世界书（零新增 LLM）
    try:
        entities, rules = memory.parse_entity_rules(result)
        evolutions, reveals = memory.parse_evolution_reveals(result)
        if entities or rules or evolutions or reveals:
            memory.upsert_worldbook_entries(proj, num, entities, rules,
                                            evolutions, reveals)
    except Exception:  # noqa: BLE001
        logging.getLogger("qianbi.stages").exception("追踪反哺回写失败（第 %s 章）", num)
    applied = {}
    for name, content in updates.items():
        path = project.get_tracking_path(proj, name)
        # C3 幽灵数字校验：角色状态更新中的数字必须能在正文/既有状态中找到出处，
        # 否则追加校验提示（不阻断，仅暴露矛盾）
        if name == "角色状态":
            prev_state = project.read_file(path)
            content = _verify_tracking_numbers(prose, prev_state, content)
        if name == "上下文":
            project.write_file(path, f"# 写作上下文\n\n{content}\n")
        else:
            project.write_file(path, content)
        applied[name] = content
    return applied


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_NUM_CTX_RE = re.compile(
    r"(?:余额|剩余|当前|现存|已消耗|已用|还有|仅剩|共|总)\s*[为是：:至]?\s*(\d+(?:\.\d+)?)")


def _verify_tracking_numbers(prose: str, prev_state: str, content: str) -> str:
    """校验角色状态更新中的数字：必须在正文原文或既有状态中出现过，否则标注存疑"""
    prose_nums = set(_NUM_RE.findall(prose or ""))
    prev_nums = set(_NUM_RE.findall(prev_state or ""))
    known = prose_nums | prev_nums
    suspicious = []
    for num in _NUM_CTX_RE.findall(content or ""):
        if num not in known:
            suspicious.append(num)
    if suspicious:
        flag = ("\n\n> ⚠️ 数字校验：以下数值（%s）未在正文原文或既有状态中出现，"
                "疑似推算/编造，请人工核对后修正。" % "、".join(sorted(set(suspicious))))
        content = (content or "") + flag
        logging.getLogger("qianbi.stages").warning(
            "追踪数字校验：角色状态出现幽灵数字 %s（本章 %s）", sorted(set(suspicious)), len(prose_nums))
    return content


def parse_tracking_updates(text: str) -> dict:
    updates = {}
    mapping = {"角色状态": "角色状态", "伏笔": "伏笔", "时间线": "时间线", "上下文": "上下文"}
    parts = re.split(r"===\s*([^=\n]+?)\s*===", text or "")
    for i in range(1, len(parts) - 1, 2):
        key = mapping.get(parts[i].strip())
        if key:
            content = parts[i + 1].strip()
            if content and content != "无变化":
                updates[key] = content
    return updates


def _extract_json_block(text: str) -> dict:
    """从回复中提取第一个平衡的 JSON 对象（```json 围栏或裸对象均可）"""
    import json as _json
    t = text or ""
    fence = t.find("```json")
    if fence >= 0:
        t = t[fence + 7:]
    start = t.find("{")
    if start < 0:
        raise ValueError("无 JSON 对象")
    dec = _json.JSONDecoder()
    obj, _ = dec.raw_decode(t[start:])
    if not isinstance(obj, dict):
        raise ValueError("JSON 非对象")
    return obj


def _cast_checklist(proj: str, num: int, outline: str) -> str:
    """本章出场角色清单（V2.1 完整性自检的输入）：sidecar/花名册中名字出现在
    细纲里的角色 + 提示补检正文新角色"""
    from .tracking_store import load_characters
    chars = load_characters(proj)
    names = list(chars.get("order") or chars.get("characters", {}).keys())
    hit = [n for n in names if n and n in (outline or "")]
    out = "、".join(hit[:12]) if hit else "（花名册角色均未在细纲点名——请按正文实际出场判断）"
    return out + "——逐个自检五字段与状态记录，有变化才出条目；正文新角色走 new。"


def _timeline_recent(proj: str, n: int = 2) -> str:
    """时间线最近 n 行数据行（供补丁器对齐格式，不含全表）"""
    rows = []
    for line in (project.read_file(project.get_tracking_path(proj, "时间线")) or "").splitlines():
        t = line.strip()
        if t.startswith("|") and t.endswith("|") \
                and not set(t.replace("|", "").strip()) <= {"-", ":", " "} \
                and not t.startswith("| 故事内时间"):
            rows.append(t)
    return "\n".join(rows[-n:]) or "（时间线尚空）"


def _update_tracking_delta(ctx, num: int, prose: str, session=None) -> dict:
    """V2.1 增量台账（writing.tracking_delta，缺省关）：JSON 补丁协议。

    LLM 只输出本章变更（键控 upsert + 追加记录行），本地由 tracking_store
    键控合并进 sidecar 并渲染派生 markdown 视图——输出量绑定「本章出场实体数」
    而非章数（根除照抄膨胀：V6 实测 13 章从 1.3k 涨到 8192 截顶）。
    解析失败 → 旧 markdown 增量 → 全量重述（三层回退）。"""
    proj = ctx.proj
    from . import tracking_store
    outline = project.read_file(project.get_outline_path(proj, num))
    kw = dict(
        chapter_num=num,
        prose=prose,
        character_table=tracking_store.character_brief_table(proj),
        cast_checklist=_cast_checklist(proj, num, outline),
        foreshadow_table=tracking_store.render_foreshadow_md(proj)[:1200],
        timeline_recent=_timeline_recent(proj),
        old_context=project.read_file(project.get_tracking_path(proj, "上下文"))[:1200]
        or "（尚无写作上下文）",
        worldbook=project.worldbook_text(proj, max_chars=2500, num=num) or "（世界书为空）",
        roster=_roster(proj),
        project_header=project_header(proj),
        chapter_header=chapter_header(proj, num),
    )
    if _use_session(ctx, session, cfg_mod.SLOT_HELPER, PHASE_TRACKING):
        _session_seed(session, prose)
        turn_text = prompts.session_turn_text(prompts.TRACKING_PATCH_PROMPT).format(**kw)
        # 调整一（writing.instruction_in_head）：输出 schema 与硬规则已在卷级冻结头
        # （通用措辞版），会话轮从协议标记处截断只留材料槽——剥不到则保留全文。
        if bool(((ctx.cfg or {}).get("writing", {}) or {}).get("instruction_in_head", False)):
            _i = turn_text.find(prompts.TRACKING_OUTPUT_MARKER)
            if _i > 0:
                turn_text = (turn_text[:_i].rstrip("\n") + "\n\n"
                             "（输出 JSON schema 与硬规则见系统「追踪补丁协议」"
                             "（卷级冻结）；本步照常执行，仍严格输出唯一一个 json 代码块。）")
            else:
                logging.getLogger("qianbi.stages").warning(
                    "第 %s 章追踪轮未匹配到输出协议标记（模板变了？），本轮保留全文指令", num)
        ctx.last_prompt = turn_text
        result = _session_ask(ctx, session, cfg_mod.SLOT_HELPER, turn_text,
                              phase=PHASE_TRACKING, stream=False)
    else:
        prompt = prompts.TRACKING_PATCH_PROMPT.format(**kw)
        ctx.last_prompt = prompt
        result = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(
            prompt, phase=PHASE_TRACKING))
    patch = _extract_json_block(result)

    # ---- 应用补丁（键控合并 + 派生视图渲染）----
    applied = []
    ch = patch.get("characters") or {}
    changed = tracking_store.apply_character_updates(
        proj, num, ch.get("updates") or [], ch.get("records") or [], ch.get("new") or [])
    if changed:
        project.write_file(project.get_tracking_path(proj, "角色状态"),
                           tracking_store.render_characters_md(proj))
        applied.append("角色状态(%d)" % len(changed))
    fs = (patch.get("foreshadow") or {}).get("upserts") or []
    fs_changed = tracking_store.apply_foreshadow_upserts(proj, fs)
    if fs_changed:
        project.write_file(project.get_tracking_path(proj, "伏笔"),
                           tracking_store.render_foreshadow_md(proj))
        applied.append("伏笔(%d)" % len(fs_changed))
    tl_rows = (patch.get("timeline") or {}).get("rows") or []
    if tl_rows:
        delta_md = ("| 故事内时间 | 章节 | 事件 |\n|---|---|---|\n" + "\n".join(
            "| %s | %s | %s |" % (r.get("故事内时间", ""), r.get("章节", "第%d章" % num),
                                  r.get("事件", "")) for r in tl_rows))
        existing = project.read_file(project.get_tracking_path(proj, "时间线"))
        from .memory import merge_table_rows
        merged, _ch = merge_table_rows(existing, delta_md, key_col=-1)
        project.write_file(project.get_tracking_path(proj, "时间线"), merged)
        applied.append("时间线(%d)" % len(tl_rows))
    ctx_text = str(patch.get("context") or "").strip()
    if ctx_text:
        project.write_file(project.get_tracking_path(proj, "上下文"),
                           f"# 写作上下文\n\n{ctx_text}\n")
        applied.append("上下文")

    # ---- 世界书反哺（JSON 数组适配旧解析器，零新增 LLM）----
    wb = patch.get("worldbook") or {}
    _sec = ""
    if wb.get("new_entities"):
        _sec += "===新实体===\n" + "\n".join("｜".join(str(x) for x in r) for r in wb["new_entities"]) + "\n"
    if wb.get("new_rules"):
        _sec += "===新规则===\n" + "\n".join("｜".join(str(x) for x in r) for r in wb["new_rules"]) + "\n"
    if wb.get("evolutions"):
        _sec += "===实体演进===\n" + "\n".join("｜".join(str(x) for x in r) for r in wb["evolutions"]) + "\n"
    if wb.get("reveals"):
        _sec += "===世界观揭示===\n" + "\n".join("｜".join(str(x) for x in r) for r in wb["reveals"]) + "\n"
    if _sec:
        try:
            entities, rules = memory.parse_entity_rules(_sec)
            evolutions, reveals = memory.parse_evolution_reveals(_sec)
            if entities or rules or evolutions or reveals:
                memory.upsert_worldbook_entries(proj, num, entities, rules,
                                                evolutions, reveals)
        except Exception:  # noqa: BLE001
            logging.getLogger("qianbi.stages").exception("追踪反哺回写失败（第 %s 章）", num)

    ctx.log("info", f"第 {num} 章 增量台账(JSON补丁)：{', '.join(applied) or '零变更'}")
    return {"applied": applied}
