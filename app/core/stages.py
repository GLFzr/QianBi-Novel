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
import os
import re

from .. import config as cfg_mod
from .. import project, prompts, deslop
from ..llm import clean_llm_output
from . import gates, memory, state as st, versions


class StageError(Exception):
    pass


class PipelineStopped(Exception):
    """用户停止流水线时抛出"""
    pass


def _stream(ctx, slot: str, prompt: str, label: str = "") -> str:
    """流式 LLM 调用：增量实时转发到 UI（ctx.stream_chunk），返回完整文本

    label 非空时先通知 UI 阶段切换（清空流式区并显示阶段标签），
    实现"人和 AI 一起读"的全程流式创作视图。
    """
    if label:
        ctx.stream_stage(label)
    def on_chunk(c):
        ctx.stream_chunk(c)
    def on_reasoning(r):
        ctx.stream_reasoning(r)
    return clean_llm_output(ctx.router.client(slot).chat_stream(
        prompt, on_chunk=on_chunk, on_reasoning=on_reasoning))


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
    )
    ctx.last_prompt = prompt
    result = _stream(ctx, cfg_mod.SLOT_WRITING, prompt, label="核心设定")
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
    )
    ctx.last_prompt = prompt
    result = _stream(ctx, cfg_mod.SLOT_WRITING, prompt, label="全书大纲")
    if not result:
        raise StageError("全书大纲生成失败：模型返回为空")
    project.write_file(os.path.join(ctx.proj, "大纲", "大纲.md"), result)
    ctx.log("ok", f"全书大纲已生成（按 {total_words_wan} 万字规划）")
    return result


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

    outlines = _generate_outline_batch(ctx, todo, chapter_words,
                                       core_setting, volume_outline, nearby_text)
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
                            nearby_text: str) -> list:
    """一次调用生成一批细纲；解析失败或调用失败 → 拆半递归；单章失败跳过

    todo: 待生成章号列表（有序）。返回 [(num, title, content)]，失败章不在其中。
    """
    if not todo:
        return []
    start, end = todo[0], todo[-1]
    ctx.checkpoint()
    prompt = prompts.CHAPTER_OUTLINE_PROMPT.format(
        chapter_num=start,
        volume_outline=volume_outline,
        nearby_outlines=nearby_text,
        core_setting_brief=core_setting[:2500],
        start_chapter=start,
        end_chapter=end,
        count=end - start + 1,
        chapter_words=chapter_words,
        chapter_words_max=int(chapter_words * 1.1),
        next_chapter=start + 1,
    )
    ctx.last_prompt = prompt  # 失败现场 dump 用
    try:
        result = _stream(ctx, cfg_mod.SLOT_HELPER, prompt, label="细纲")
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
                                       core_setting, volume_outline, nearby_text)
        right = _generate_outline_batch(ctx, todo[mid:], chapter_words,
                                        core_setting, volume_outline, nearby_text)
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

def chapter_microcycle(ctx, num: int, guidance: str = "", ideas: list = None) -> dict:
    """上下文组装→草稿→字数闸门→AI味扫描→去味→定稿落库。返回章节记录"""
    proj = ctx.proj
    chapter_words = ctx.cfg.get("writing", {}).get("chapter_word_target", 3000)
    gates_cfg = ctx.cfg.get("gates", {})
    tolerance = gates_cfg.get("word_tolerance", 0.1)
    max_deslop_rounds = gates_cfg.get("deslop_max_rounds", 2)
    gr = gates.GateResult()
    gr.word_target = chapter_words

    # ---- ① 上下文组装 ----
    ctx.step(num, st.STEP_ASSEMBLE)
    outline_path = project.get_outline_path(proj, num)
    outline = project.read_file(outline_path)
    if not outline:
        raise StageError(f"第 {num} 章细纲不存在")

    next_outline = project.read_file(project.get_outline_path(proj, num + 1))
    next_brief = next_outline[:600] if next_outline else "（本章为当前最后一章细纲）"
    core_setting = (project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1500]
                    or "（未提供）")
    global_summary = memory.read_global_summary(proj) or "（全书尚未开始或暂无摘要）"
    recent_summaries = memory.read_recent_summaries(proj, num, n=3) or "（无更近章节摘要）"
    character_states = project.read_file(project.get_tracking_path(proj, "角色状态"))[:3000] or "（暂无）"
    foreshadows = memory.unfished_foreshadows(proj) or "（暂无）"
    previous_excerpt = ""
    chapters = project.list_chapters(proj)
    if chapters:
        last = chapters[-1]
        if last[0] == num - 1:
            prev_text = project.read_file(last[2])
            previous_excerpt = prev_text[-800:] if len(prev_text) > 800 else prev_text
    ctx.log("info", f"第 {num} 章 上下文组装完成（核心设定 + 细纲 + 前3章摘要 + 角色状态 + 伏笔）")

    # ---- ② 草稿生成 ----
    ctx.step(num, st.STEP_DRAFT)
    ctx.checkpoint()
    prompt = prompts.PROSE_WRITING_PROMPT.format(
        chapter_num=num,
        core_setting=core_setting,
        outline=outline,
        next_chapter_brief=next_brief,
        global_summary=global_summary,
        recent_summaries=recent_summaries,
        character_states=character_states,
        foreshadows=foreshadows,
        previous_excerpt=previous_excerpt or "（本章为第一章）",
        user_guidance=guidance or "无特殊指导",
        user_ideas="\n".join(f"- {t}" for t in (ideas or [])) or "（无）",
        word_target=chapter_words,
    )
    ctx.last_prompt = prompt
    prose = _stream(ctx, cfg_mod.SLOT_WRITING, prompt, label=f"草稿 第{num}章")
    if not prose.strip():
        raise StageError(f"第 {num} 章草稿生成失败：模型返回为空")
    actual = project.count_chars(prose)
    ctx.log("ok", f"第 {num} 章 草稿完成：{actual} 字（目标 {chapter_words}）")

    # ---- 字数闸门：不足自动扩写一次 ----
    word_ok, actual = gates.check_words(prose, chapter_words, tolerance)
    if not word_ok:
        ctx.step(num, st.STEP_ENRICH)
        ctx.log("warn", f"第 {num} 章 字数不足（{actual}），自动扩写…")
        ctx.checkpoint()
        enrich_prompt = prompts.ENRICH_PROMPT.format(chapter_num=num, actual=actual,
                                                     target=chapter_words, prose=prose)
        ctx.last_prompt = enrich_prompt
        prose = _stream(ctx, cfg_mod.SLOT_WRITING, enrich_prompt, label="扩写")
        word_ok, actual = gates.check_words(prose, chapter_words, tolerance)
        ctx.log("ok" if word_ok else "warn",
                f"扩写后 {actual} 字" + ("，达标" if word_ok else "，仍不足，标记不阻断"))

    # ---- ③ AI 味扫描（本地，零成本）----
    ctx.step(num, st.STEP_SCAN)
    blocking, advisory = gates.scan_deslop(prose)
    gr.blocking_findings, gr.advisory_findings = blocking, advisory
    ctx.log("info", f"第 {num} 章 本地扫描：阻断 {len(blocking)} 处 / 建议 {len(advisory)} 处")

    # ---- ④ 去味改写（仅阻断级触发，最多 max_deslop_rounds 轮）----
    rounds = 0
    while blocking and rounds < max_deslop_rounds:
        rounds += 1
        ctx.step(num, st.STEP_DESLOP)
        ctx.log("warn", f"第 {num} 章 阻断 {len(blocking)} 处 → 去味改写（第 {rounds} 轮）…")
        ctx.checkpoint()
        findings_text = deslop.findings_to_prompt_text(blocking + advisory)
        rewrite_prompt = prompts.DESLOP_REWRITE_PROMPT.format(findings=findings_text, prose=prose)
        ctx.last_prompt = rewrite_prompt
        rewritten = _stream(ctx, cfg_mod.SLOT_WRITING, rewrite_prompt, label=f"去味改写 第{rounds}轮")
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

    # ---- ④.5 审校（一致性检查，可开关；用审校槽）----
    review_enabled = gates_cfg.get("review_enabled", True)
    if review_enabled and cfg_mod.slot_connection(ctx.cfg, cfg_mod.SLOT_REVIEW):
        ctx.stream_stage(f"审校 第{num}章")
        blocking_review, advisory_review = _chapter_review(ctx, num, prose)
        gr.review_blocking = blocking_review
        review_rounds = 0
        while blocking_review and review_rounds < gates_cfg.get("review_max_rounds", 1):
            review_rounds += 1
            prev_n = len(blocking_review)
            ctx.step(num, st.STEP_REVIEW)
            ctx.log("warn", f"第 {num} 章 审校发现 {prev_n} 处阻塞 → 修改（第 {review_rounds} 轮）…")
            ctx.checkpoint()
            fix_prompt = prompts.REVIEW_FIX_PROMPT.format(
                chapter_num=num, findings="\n".join(blocking_review), prose=prose)
            ctx.last_prompt = fix_prompt
            rewritten = _stream(ctx, cfg_mod.SLOT_REVIEW, fix_prompt, label=f"审校修改 第{review_rounds}轮")
            if not rewritten.strip():
                ctx.log("warn", f"第 {num} 章 审校修复返回为空，保留原稿")
                break
            # 回滚保护：修复后复扫，未改善（阻塞不减反增）则保留原稿，防止越修越糟
            new_blocking, new_advisory = _chapter_review(ctx, num, rewritten)
            if len(new_blocking) < prev_n:
                prose = rewritten
                blocking_review, advisory_review = new_blocking, new_advisory
                gr.review_blocking = new_blocking
            else:
                ctx.log("warn", f"第 {num} 章 审校修复未改善（{prev_n}→{len(new_blocking)} 处），保留原稿")
                blocking_review = new_blocking
                gr.review_blocking = new_blocking
                break
        gr.review_rounds_used = review_rounds
        if blocking_review:
            ctx.log("warn", f"第 {num} 章 审校 {review_rounds} 轮后仍有 {len(blocking_review)} 处阻塞")
            gates.resolve_failed(ctx, f"第 {num} 章审校未通过（{len(blocking_review)} 处阻塞）", gr)
            _save_review_findings(proj, num, blocking_review)
        elif review_rounds:
            ctx.log("ok", f"第 {num} 章 审校通过（复检 {review_rounds} 轮）")
        else:
            ctx.log("ok", f"第 {num} 章 审校通过（无阻塞问题）")
    else:
        ctx.log("info", "审校已跳过（未启用或审校槽未绑定连接）")

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
        summary_prompt = prompts.CHAPTER_SUMMARY_PROMPT.format(
            chapter_num=num, title=title or f"第{num}章",
            prose_excerpt=prose[:2500])
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


# ============ 审校（一致性检查）============

def _chapter_review(ctx, num: int, prose: str) -> tuple:
    """调用审校槽做一致性检查，返回 (blocking_list, advisory_list)"""
    proj = ctx.proj
    prompt = prompts.REVIEW_PROMPT.format(
        chapter_num=num,
        prose=prose[:6000],
        core_setting=(project.read_file(os.path.join(proj, "设定", "题材定位.md"))[:1200]
                      or "（未提供）"),
        global_summary=memory.read_global_summary(proj) or "（尚未开始）",
        character_states=project.read_file(project.get_tracking_path(proj, "角色状态"))[:2000] or "（暂无）",
        foreshadows=memory.unfished_foreshadows(proj) or "（暂无）",
        timeline=project.read_file(project.get_tracking_path(proj, "时间线"))[:1500] or "（暂无）",
    )
    ctx.last_prompt = prompt
    try:
        result = clean_llm_output(ctx.router.client(cfg_mod.SLOT_REVIEW)
                                  .chat_stream(prompt, on_chunk=ctx.stream_chunk))
    except Exception as e:
        ctx.log("warn", f"第 {num} 章 审校调用失败（不阻断）：{e}")
        return [], []
    return parse_review_findings(result)


def parse_review_findings(text: str) -> tuple:
    """解析审校输出（===BLOCKING=== / ===ADVISORY=== 两段），返回 (blocking, advisory) 文本列表"""
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
        prose=prose[:6000],
        character_state=project.read_file(project.get_tracking_path(proj, "角色状态"))[:2000],
        foreshadow_table=project.read_file(project.get_tracking_path(proj, "伏笔"))[:2000],
        timeline=project.read_file(project.get_tracking_path(proj, "时间线"))[:1500],
    )
    ctx.last_prompt = prompt
    result = clean_llm_output(ctx.router.client(cfg_mod.SLOT_HELPER).chat(prompt))
    updates = parse_tracking_updates(result)
    applied = {}
    for name, content in updates.items():
        path = project.get_tracking_path(proj, name)
        if name == "上下文":
            project.write_file(path, f"# 写作上下文\n\n{content}\n")
        else:
            project.write_file(path, content)
        applied[name] = content
    return applied


def parse_tracking_updates(text: str) -> dict:
    updates = {}
    mapping = {"角色状态": "角色状态", "伏笔": "伏笔", "时间线": "时间线", "上下文": "上下文"}
    parts = re.split(r"===(角色状态|伏笔|时间线|上下文)===", text)
    for i in range(1, len(parts) - 1, 2):
        key = mapping.get(parts[i])
        if key:
            content = parts[i + 1].strip()
            if content and content != "无变化":
                updates[key] = content
    return updates
