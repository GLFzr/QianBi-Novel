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
import logging
import os
import re

from .. import config as cfg_mod
from .. import project, prompts, deslop, wb
from ..llm import clean_llm_output
from ..prompts import scene_cards
from . import gates, memory, scan, state as st, versions
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


def preset_param_layers(proj: str) -> dict:
    """预设喂给路由的两层参数覆盖（ModelRouter kwargs）：一次 state 读取取全

    阶段档随「下一章生效」重绑；采样基线与它同源于同一个预设，不单独走第二条链。
    """
    pid = _preset_id(proj)
    return {"stage_params": genre_presets.stage_params(pid),
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


def prev_chapter_pack(proj: str, num: int, tail: int = 800) -> tuple:
    """上一章统一锚点：(结尾文本, 开头文风样本)，取小于本章的最近存在章。

    非线性安全——重写/补写中间章时不再因「磁盘最后一章 != num-1」丢失衔接锚点。
    无更前章或空文返回 ("", "")，占位文案由调用方按场景给。
    """
    prev = project.nearest_chapter_before(proj, num)
    if not prev:
        return "", ""
    text = project.read_file(prev[2]) or ""
    if not text.strip():
        return "", ""
    ending = text[-tail:] if len(text) > tail else text
    body_start = text.find("\n")   # 文风样本跳过标题行
    sample = text[body_start + 1:body_start + 501] if body_start > 0 else text[:500]
    return ending, sample.strip()


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
    text = clean_llm_output(client.chat_stream(
        prompt, on_chunk=on_chunk, on_reasoning=on_reasoning, phase=phase))
    _record_call(ctx, phase, slot, client, prompt)
    return text


# ============ 阶段①：核心设定 ============

def stage_core_setting(ctx) -> str:
    ctx.log("info", "阶段① 生成核心设定…")
    info = project.read_idea_info(ctx.proj)
    if not info["idea"]:
        raise StageError("选题信息缺失（设定/选题信息.md），请先立项")
    ctx.checkpoint()
    prompt = prompts.CORE_SETTING_PROMPT.format(
        book_name=os.path.basename(ctx.proj),
        genre=info["genre"] or "（不限）",
        platform=info["platform"],
        idea=info["idea"],
        emotion="（由你根据题材推荐）",
        total_words=info.get("total_words_wan", 0) or 100,
        genre_block=_genre_block(ctx.proj, "core_setting"),
    )
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
        core_setting=core_setting,
        total_words=total_words_wan,
        chapter_words=chapter_words,
        genre_block=_genre_block(ctx.proj, "outline"),
    )
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
        chapter_num=start,
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
        next_chapter=start + 1,
        previous_ending=previous_ending or "（无）",
        foreshadows=foreshadows or "（无）",
        unit_contract=_unit_contract(ctx.proj, start),
        genre_block=_genre_block(ctx.proj, "unit_outline"),
        worldbook_block=wb_block_text,
        regex_block=rg_block_text,
        user_directive=ctx.consume_gate_idea() or "（无）",
    )
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

def _sanitize_chapter_refs(text: str) -> str:
    """清洗注入上下文的非正文字段里的「第N章」引用（真机硬伤修复）。

    章节号会从细纲标题/章间摘要漏进正文台词（真机实例：角色说出
    「第5章回溯中看到的画面」）。注入 prompt 前剥离行首章标题与句中
    「第N章」标记，剧情指称不受影响。
    """
    if not text:
        return text
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"^#{0,6}\s*第\s*\d+\s*章\s*[：:。]?\s*", "", ln)
        ln = re.sub(r"第\s*\d+\s*章(?=[^\d])", "", ln)
        lines.append(ln)
    return "\n".join(lines).strip()


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


def chapter_microcycle(ctx, num: int, guidance: str = "", ideas: list = None) -> dict:
    """上下文组装→草稿→字数闸门→AI味扫描→去味→定稿落库。返回章节记录"""
    proj = ctx.proj
    chapter_words = _outline_word_target(
        proj, num, ctx.cfg.get("writing", {}).get("chapter_word_target", 3000))
    gates_cfg = ctx.cfg.get("gates", {})
    tolerance = gates_cfg.get("word_tolerance", 0.1)
    max_deslop_rounds = gates_cfg.get("deslop_max_rounds", 2)
    gr = gates.GateResult()
    gr.word_target = chapter_words

    # ---- ① 上下文组装（G4 门：回退=改材料后重新组装读盘，T4.1 内侧门）----
    draft_extra_ideas: list = []
    while True:
        ctx.step(num, st.STEP_ASSEMBLE)
        outline_path = project.get_outline_path(proj, num)
        outline = _sanitize_chapter_refs(project.read_file(outline_path))
        if not outline:
            raise StageError(f"第 {num} 章细纲不存在")

        next_outline = project.read_file(project.get_outline_path(proj, num + 1))
        next_brief = _sanitize_chapter_refs(next_outline[:600]) if next_outline else "（本章为当前最后一章细纲）"
        core_setting = (project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1500]
                        or "（未提供）")
        global_summary = memory.read_global_summary(proj) or "（全书尚未开始或暂无摘要）"
        recent_summaries = _sanitize_chapter_refs(
            memory.read_recent_summaries(proj, num, n=3)) or "（无更近章节摘要）"
        character_states = project.read_file(project.get_tracking_path(proj, "角色状态"))[:3000] or "（暂无）"
        foreshadows = memory.unfished_foreshadows(proj) or "（暂无）"
        timeline = project.read_file(project.get_tracking_path(proj, "时间线"))[:1500] or "（暂无）"
        previous_excerpt = ""
        style_sample = "（本章为第一章，无上一章文风样本）"
        # 统一锚定：取小于本章的最近存在章（非线性安全——重写中间章时仍有衔接锚点）
        prev_text, prev_style = prev_chapter_pack(proj, num, tail=800)
        if prev_text:
            previous_excerpt = prev_text
            if prev_style:
                style_sample = prev_style
        ctx.log("info", f"第 {num} 章 上下文组装完成（核心设定 + 细纲 + 前3章摘要 + 角色状态 + 伏笔 + 文风样本）")
        # 决策门 G4：素材组装后（软门：默认轻提示）
        g4_idea = ctx.gate("G4", f"材料就绪：细纲 + 前3章摘要 + 角色状态 + 伏笔表 + 文风样本（草稿目标 {chapter_words} 字）",
                           chapter=num)
        if g4_idea is None:
            g4_idea = ctx.consume_gate_idea()   # 回退想法就地消费，防串章
            ctx.log("warn", "G4 回退：重新组装（可趁隙修改设定/细纲/追踪文件）")
            continue
        if g4_idea:
            draft_extra_ideas.append(g4_idea)   # 带想法继续 → 注入草稿 user_ideas
        break

    # ---- ② 草稿生成 ----
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
    prompt = prompts.PROSE_WRITING_PROMPT.format(
        chapter_num=num,
        core_setting=core_setting,
        outline=outline,
        next_chapter_brief=next_brief,
        global_summary=global_summary,
        recent_summaries=recent_summaries,
        character_states=character_states,
        foreshadows=foreshadows,
        timeline=timeline,
        previous_excerpt=previous_excerpt or "（本章为第一章）",
        style_sample=style_sample,
        user_guidance=_compose_guidance(guidance, ctx.cfg),
        user_ideas="\n".join(f"- {t}" for t in ((ideas or []) + draft_extra_ideas)) or "（无）",
        word_target=chapter_words,
        tic_blacklist=_tic_blacklist(proj),
        used_setpieces=_used_setpieces(proj),
        genre_block=_genre_block(proj, "prose"),
        worldbook_block=wb_block,
        regex_block=rg_block,
        craft_block=scene_cards.craft_block(num, _total_chapters(proj, chapter_words), outline),
        author_note=_author_note(proj),
    )
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
    enrich_rounds = 0
    while not low_ok and enrich_rounds < max_enrich_rounds:
        enrich_rounds += 1
        ctx.step(num, st.STEP_ENRICH)
        ctx.log("warn", f"第 {num} 章 字数不足（{actual} / 目标 {chapter_words}），自动扩写（第 {enrich_rounds} 轮）…")
        ctx.checkpoint()
        enrich_prompt = prompts.ENRICH_PROMPT.format(chapter_num=num, actual=actual,
                                                     target=chapter_words, prose=prose,
                                                     outline_brief=outline[:600],
                                                     tic_blacklist=_tic_blacklist(proj),
                                                     must_block=_must_block(proj, ctx.cfg))
        ctx.last_prompt = enrich_prompt
        rewritten = _stream(ctx, cfg_mod.SLOT_WRITING, enrich_prompt, label=f"扩写 第{enrich_rounds}轮",
                            phase=PHASE_ENRICH)
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
        trim_prompt = prompts.TRIM_PROMPT.format(chapter_num=num, actual=actual,
                                                 target=chapter_words, cut_pct=cut_pct,
                                                 prose=prose, outline_brief=outline[:600],
                                                 tic_blacklist=_tic_blacklist(proj),
                                                 must_block=_must_block(proj, ctx.cfg))
        ctx.last_prompt = trim_prompt
        prose = _stream(ctx, cfg_mod.SLOT_WRITING, trim_prompt, label="压缩",
                        phase=PHASE_TRIM)
        low_ok, high_ok, actual = gates.check_word_bounds(prose, chapter_words, tolerance)
        if not high_ok and actual < chapter_words * 0.6 and pre_actual <= chapter_words * 1.5:
            # 压缩过度删减（<60%）且原稿未严重超标（≤150%）→ 回退原稿，防章节被压残
            prose, actual = pre_prose, pre_actual
            ctx.log("warn", f"压缩过度删减（{actual} < 60% 目标），已回退原稿（{pre_actual} 字）")
        else:
            ctx.log("ok" if high_ok else "warn",
                    f"压缩后 {actual} 字" + ("，达标" if high_ok else "，仍超标，标记不阻断"))

    # ---- ③ AI 味扫描（本地，零成本）----
    ctx.step(num, st.STEP_SCAN)
    blocking, advisory = gates.scan_deslop(prose)
    gr.blocking_findings, gr.advisory_findings = blocking, advisory
    ctx.log("info", f"第 {num} 章 本地扫描：阻断 {len(blocking)} 处 / 建议 {len(advisory)} 处")

    # ---- ③.5 决策门 G6：扫描完成后（T4.1 内侧门；回退=保留原稿跳过去味）----
    deslop_extra_text = ""
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
    rounds = 0
    while blocking and rounds < max_deslop_rounds:
        rounds += 1
        ctx.step(num, st.STEP_DESLOP)
        ctx.log("warn", f"第 {num} 章 阻断 {len(blocking)} 处 → 去味改写（第 {rounds} 轮）…")
        ctx.checkpoint()
        findings_text = deslop.findings_to_prompt_text(blocking + advisory) + deslop_extra_text
        rewrite_prompt = prompts.DESLOP_REWRITE_PROMPT.format(findings=findings_text, prose=prose,
                                                               outline_brief=outline[:600],
                                                               tic_blacklist=_tic_blacklist(proj),
                                                               must_block=_must_block(proj, ctx.cfg))
        ctx.last_prompt = rewrite_prompt
        rewritten = _stream(ctx, cfg_mod.SLOT_WRITING, rewrite_prompt, label=f"去味改写 第{rounds}轮",
                            phase=PHASE_DESLOP)
        if rewritten.strip():
            prose = rewritten
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
    g7_idea = ctx.gate("G7", f"去味改写完成：{rounds} 轮 · 复扫{'通过' if not blocking else f'仍 {len(blocking)} 处阻断'}"
                             f"（当前 {project.count_chars(prose)} 字，下一步审校）", chapter=num)
    if g7_idea is None:
        g7_idea = ctx.consume_gate_idea()   # 回退想法就地消费，防串章
        ctx.log("warn", "G7 回退：保留去味前原稿继续")
        if rounds and prose != pre_deslop_prose:
            _archive_inner_rollback(ctx, proj, num, "G7", prose)   # 去味稿归档
            prose = pre_deslop_prose                                # 还原原稿
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
    verdict_review, blocking_review, review_ran = "", [], False
    pre_review_prose = prose   # G8 回退还原点
    review_enabled = gates_cfg.get("review_enabled", True)
    if review_enabled and cfg_mod.slot_connection(ctx.cfg, cfg_mod.SLOT_REVIEW):
        review_ran = True
        ctx.stream_stage(f"审校 第{num}章")
        blocking_review, advisory_review, verdict_review = _chapter_review(ctx, num, prose)
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
            fix_prompt = prompts.REVIEW_FIX_PROMPT.format(
                chapter_num=num, findings="\n".join(blocking_review), prose=prose,
                outline_brief=outline[:600], core_setting_brief=core_setting)
            ctx.last_prompt = fix_prompt
            rewritten = _stream(ctx, cfg_mod.SLOT_REVIEW, fix_prompt,
                               label=f"审校修改 第{review_rounds}轮",
                               phase=PHASE_REVIEW_FIX)
            # 修复稿健全性守卫（真机缺陷修复：模型可能返回 ===REVISIONS=== 修订计划
            # 而非改后正文；采纳会把整章替换成指令清单，且空文本复检阻塞更少被误判改善）
            looks_like_plan = rewritten.lstrip().startswith("===")
            too_short = len(rewritten.strip()) < max(300, int(len(prose) * 0.5))
            if not rewritten.strip() or looks_like_plan or too_short:
                ctx.log("warn", f"第 {num} 章 审校修复返回非正文"
                                f"（{'空' if not rewritten.strip() else '修订计划' if looks_like_plan else '长度骤减'}），保留原稿")
                break
            # 回滚保护：修复后复扫，未改善（阻塞不减反增）则保留原稿
            # 复扫只投 review_votes_recheck 票（默认 1）控成本——修复环内不做全量投票
            new_blocking, new_advisory, new_verdict = _chapter_review(
                ctx, num, rewritten,
                votes=max(1, int(gates_cfg.get("review_votes_recheck", 1))))
            if len(new_blocking) < prev_n:
                prose = rewritten
                blocking_review, advisory_review, verdict_review = new_blocking, new_advisory, new_verdict
                gr.review_blocking = new_blocking
            else:
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

    # ---- ④.9 决策门 G8：审校完成后（T4.1 内侧门；回退=保留原稿=还原审校前文本）----
    if review_ran:
        g8_idea = ctx.gate("G8", f"审校完成：verdict {verdict_review or 'PASS'} · 阻塞 {len(blocking_review)} 处"
                                 f"（下一步定稿落库，G9 仍会把关）", chapter=num)
        if g8_idea is None:
            g8_idea = ctx.consume_gate_idea()   # 回退想法就地消费，防串章
            ctx.log("warn", "G8 回退：保留审校前原稿继续")
            if prose != pre_review_prose:
                _archive_inner_rollback(ctx, proj, num, "G8", prose)   # 审校修改稿归档
                prose = pre_review_prose                                # 还原原稿
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
        tracking = _update_tracking(ctx, num, prose)
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
            prose_excerpt=excerpt)
        ctx.last_prompt = summary_prompt
        chapter_summary = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(
            summary_prompt)).splitlines()[0].strip()
        if chapter_summary:
            memory.append_chapter_summary(proj, num, title or f"第{num}章", chapter_summary)
            old_global = memory.read_global_summary(proj)
            ctx.checkpoint()
            global_prompt = prompts.GLOBAL_SUMMARY_PROMPT.format(
                old_summary=old_global or "（全书刚开始）",
                chapter_num=num, chapter_summary=chapter_summary)
            ctx.last_prompt = global_prompt
            new_global = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(
                global_prompt))
            if new_global.strip():
                memory.write_global_summary(proj, new_global)
            ctx.log("ok", f"摘要链已更新（全局摘要 {len(new_global)} 字）")
    except PipelineStopped:
        ctx.log("info", f"第 {num} 章摘要链更新被停止请求中断（不影响已落库正文与记录）")
    except Exception as e:
        ctx.log("warn", f"摘要链更新失败（不阻断）：{e}")

    gr.word_actual = project.count_chars(prose)
    record = {"num": num, "title": title, **gr.to_record()}
    return record


# ============ 审校（v1 一致性检查 + v2 6 维最终审核）============

def review_l0_block(proj: str, num: int, prose: str) -> str:
    """L0 确定性预检组装（流水线/修复复审/共写审校三注入点共用）

    专名/跨章复读/数值账/章末弱钩/题材禁词 → 格式化注入审校 prompt。
    """
    prev = project.nearest_chapter_before(proj, num)
    prev_prose = (project.read_file(prev[2]) if prev else "") or ""
    ledger_text = "\n".join([
        project.worldbook_text(proj, 1500, num=num),
        project.read_file(project.get_tracking_path(proj, "角色状态")) or "",
    ])
    genre = (project.read_idea_info(proj) or {}).get("genre", "") or ""
    forbidden = [] if any(k in genre for k in ("修仙", "仙侠", "玄幻")) else scan.GENERIC_FORBIDDEN
    return scan.format_scan_block(scan.scan_chapter(
        prose, prev_prose, roster=project.worldbook_anchors(proj, 0),
        ledger_text=ledger_text, forbidden_words=forbidden))


def build_final_review_prompt(proj: str, cfg: dict, num: int, prose: str) -> str:
    """组装 6 维终审 prompt（**唯一装配点**：流水线/共写查验/复审共用）

    共写侧原先自带一份同构 .format，两处的 budget/anchors 传参极易漂移；
    收敛后新增注入项只需改这里（回归由 tests/probe_prompt_baseline.py 兜底）。
    """
    wb_block, rg_block, _meta = _wb_rg_blocks(proj, cfg, num)
    return prompts.FINAL_REVIEW_PROMPT.format(
        prose=prose[:6000],
        core_setting=(project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1200]
                      or "（未提供）"),
        global_summary=memory.read_global_summary(proj) or "（尚未开始）",
        character_states=project.read_file(project.get_tracking_path(proj, "角色状态"))[:2000] or "（暂无）",
        foreshadows=memory.unfished_foreshadows(proj) or "（暂无）",
        timeline=project.read_file(project.get_tracking_path(proj, "时间线"))[:1500] or "（暂无）",
        worldbook_block=wb_block,
        regex_block=rg_block,
        genre_review_extra=_genre_review_extra(proj),
        outline=(project.read_file(project.get_outline_path(proj, num))[:1000] or "（未提供）"),
        l0_findings=review_l0_block(proj, num, prose),
    )


def _build_final_review_prompt(ctx, num: int, prose: str) -> str:
    """ctx 薄封装（流水线调用）"""
    return build_final_review_prompt(ctx.proj, ctx.cfg, num, prose)


_LEVEL_STRICT = {"fail": 2, "marginal": 1, "pass": 0}


def merge_review_votes(parsed_list: list) -> dict:
    """多轮独立审校结果聚合（P5）：每维多数票，平票从严。

    - fail（阻塞）需 ≥2 票（不足票数的 fail 维降 marginal 并进 advisory）；k=1 时 quorum=1
    - 每维合并为一条代表条目（阻塞项跨票去重合并）
    - summary/verdict 全部重算（丢弃单票声明的判决）
    """
    k = len(parsed_list)
    quorum = 2 if k >= 2 else 1
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
        counts = {}
        for lvl in levels:
            counts[lvl] = counts.get(lvl, 0) + 1
        top = max(counts.values())
        cands = [lvl for lvl, c in counts.items() if c == top]
        merged_lvl = max(cands, key=lambda x: _LEVEL_STRICT[x])   # 平票从严
        cand_items = dim_items[d]
        if merged_lvl == "fail":
            fail_votes = counts.get("fail", 0)
            fail_items = [it for it in cand_items if it.get("level") == "fail"]
            if fail_votes >= quorum:
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
                        "line": "", "votes": f"{fail_votes}/{k}"}
                items.append(item)
                blocking.append(item["text"])
                summary["fail"] += 1
            else:
                rep = fail_items[0] if fail_items else cand_items[0]
                item = {"dim": d, "level": "marginal",
                        "text": f"[票数不足降级 {fail_votes}/{k}] " + rep.get("text", ""),
                        "quote": rep.get("quote", ""),
                        "root_layer": rep.get("root_layer", ""),
                        "line": "", "votes": f"{fail_votes}/{k}"}
                items.append(item)
                advisory.append(item["text"])
                summary["marginal"] += 1
        elif merged_lvl == "marginal":
            marg_items = [it for it in cand_items if it.get("level") == "marginal"]
            rep = marg_items[0] if marg_items else cand_items[0]
            item = {"dim": d, "level": "marginal", "text": rep.get("text", ""),
                    "quote": rep.get("quote", ""),
                    "root_layer": rep.get("root_layer", ""), "line": "",
                    "votes": f"{counts.get('marginal', 0)}/{k}"}
            items.append(item)
            advisory.append(item["text"])
            summary["marginal"] += 1
        else:
            summary["pass"] += 1
    verdict = compute_verdict(summary, items, "")   # 丢弃单票声明，按聚合计数重算
    return {"verdict": verdict, "items": items, "blocking": blocking,
            "advisory": advisory, "summary": summary, "vote_count": k}


def _votes_identical(a: dict, b: dict) -> bool:
    """两票是否完全一致（早停判据：维度等级全同且判决相同）"""
    if (a.get("verdict") or "") != (b.get("verdict") or ""):
        return False
    la = {it.get("dim"): it.get("level") for it in a.get("items", [])}
    lb = {it.get("dim"): it.get("level") for it in b.get("items", [])}
    return la == lb


def review_with_votes(ctx, num: int, prose: str, votes: int) -> dict:
    """k 次独立审校投票（P5）：温度治理 + 引证验真后按维聚合。

    第 1、2 票完全一致 → 早停省 1/3 成本。返回聚合后的 v2 结构；
    ctx.review_raw 记录第 1 票原始输出（根因溯源复用）。
    """
    votes = max(1, int(votes))
    gates_cfg = ctx.cfg.get("gates", {})
    temp = gates_cfg.get("review_temperature", 0.2)
    prompt = _build_final_review_prompt(ctx, num, prose)
    ctx.last_prompt = prompt
    client = ctx.router.client(cfg_mod.SLOT_REVIEW)
    parsed_list, raws = [], []
    for i in range(votes):
        raw = clean_llm_output(client.chat_stream(
            prompt, on_chunk=ctx.stream_chunk, temperature=temp, phase=PHASE_REVIEW))
        raws.append(raw)
        v2 = verify_review_quotes(prose, parse_final_review_v2(raw))
        if not v2["verdict"]:   # v1 兜底
            fb, fa = parse_review_findings(raw)
            v2["blocking"] = v2["blocking"] or fb
            v2["advisory"] = v2["advisory"] or fa
        parsed_list.append(v2)
        if i == 1 and votes > 2 and _votes_identical(parsed_list[0], v2):
            try:
                ctx.log("info", f"第 {num} 章 审校投票 1/2 完全一致 → 早停（省第 3 票）")
            except Exception:
                pass
            break
        if i < votes - 1:
            try:
                ctx.log("info", f"第 {num} 章 审校第 {i + 1}/{votes} 票："
                                f"{v2['verdict'] or '格式未识别'}（fail={v2['summary']['fail']}）")
            except Exception:
                pass
    merged = merge_review_votes(parsed_list) if len(parsed_list) > 1 else parsed_list[0]
    ctx.review_raw = raws[0]
    # A2 双轨裁决：【世界书修正】条目（正文自洽而世界书条目疑过时）→ 登记修正提案
    try:
        n_proposed = memory.propose_worldbook_corrections(ctx.proj, num, merged.get("items", []))
        if n_proposed:
            ctx.log("warn", f"第 {num} 章 审校登记 {n_proposed} 条世界书修正提案"
                            f" → {memory.PROPOSAL_PATH}（人工核对后并入，不自动改世界书）")
    except Exception:
        pass
    return merged


def _chapter_review(ctx, num: int, prose: str, votes: int = None) -> tuple:
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
        v2 = review_with_votes(ctx, num, prose, votes)
    except Exception as e:
        ctx.log("warn", f"第 {num} 章 6 维审校调用失败（不阻断）：{e}")
        return [], [], ""
    ctx.review_v2 = v2   # 根因溯源复用验真后的 items，不重解析原始输出
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


def _update_tracking(ctx, num: int, prose: str) -> dict:
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
    )
    ctx.last_prompt = prompt
    result = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(prompt))
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
