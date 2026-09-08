# -*- coding: utf-8 -*-
"""S4 静态冻结（成本优化方案 v3 §3/S4）单测：指令库入 system + 开幕轮瘦身 + 追踪轮去重

三态矩阵（v3 §5 每步独立 A/B 可回退；S4 挂在卷会话架构下的独立旗标）：
  A. writing.volume_session 关：无会话/章会话原路径——prose 首轮与 tracking 追加轮
     请求体与改造前逐字节一致（① 全字节锁）；
  B. volume_session 开 + s4_static_freeze 关（缺省）：S1 行为——system 仍只含
     project_header，八节章头整体进开幕轮，指令体随首轮重发（字节不变）；
  C. volume_session 开 + s4_static_freeze 开：S4 全量——
     ② system = project_header + 写作指令库（模板化冻结版，逐章变量全部替换），
        开幕轮不含指令体；
     ③ 开幕轮不含三节（上一章结尾/上一章文风样本/最近章节摘要），仍含五节
        （细纲/全局摘要/角色状态/时间线/伏笔）与逐章动态值（S4-b）；
     ④ tracking 卷会话轮五个冗余节换短引用行、花名册保留（S4-c）；
     ⑤ cost_bench 细纲按需生成：缺失才调 stage_chapter_outlines(n, n)，
        --chapters 上限放开到 40（S4-d）。
全部内存假件 + 临时项目目录，禁止任何真实 API（假客户端风格对齐
tests/test_volume_session.py / tests/test_chapter_session.py）。
"""
import inspect
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_SCRIPTS = os.path.join(_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from app import project as pj
from app.core import memory as mem
from app.core import state as st
from app.core.shared_prefix import chapter_header, project_header
from app.core.volume_session import (_LIBRARY_HEADER, prose_instruction_library,
                                     volume_system_text)


# ---------------- 假件（对齐 tests/test_volume_session.py） ----------------

class CycleClient:
    """chapter_microcycle 假客户端：chat_turn=会话轮（逐次记录 messages），
    chat_stream/chat=单轮旁路（清算等）。回复按相位路由，不触网。"""

    def __init__(self, word_target=60):
        self.turn_calls = []      # [(messages, phase), ...]
        self.stream_prompts = []  # 单发旁路（canon_audit）
        self.prose_n = 0
        self.word_target = word_target

    def chat_turn(self, messages, *, on_chunk=None, on_reasoning=None,
                  phase="", temperature=None, abort=None):
        self.turn_calls.append(([dict(m) for m in messages], phase))
        return self._reply(phase)

    def chat_stream(self, prompt, on_chunk=None, on_reasoning=None, phase="",
                    temperature=None, **kw):
        self.stream_prompts.append(prompt)
        return "（清算输出非 JSON）"

    def chat(self, prompt, phase="", **kw):
        return "（无）"

    def _reply(self, phase):
        if phase == "prose":
            self.prose_n += 1
            return _prose_fixture(self.prose_n, self.word_target)
        if phase == "chapter_summary":
            return f"第{self.prose_n}章：少年在巷口拾到玉简。"
        if phase == "global_summary":
            return "少年获得玉简，修行起步。"
        return "（无）"


class CycleCtx:
    """chapter_microcycle 假 ctx：决策门全放行、无轨迹容器；volume_sessions
    对齐 orchestrator.run 持有的按卷缓存（S1 生命周期挂在 ctx 上）。"""

    def __init__(self, proj, cfg, client):
        self.proj = proj
        self.cfg = cfg
        self.router = _FakeRouter(client)
        self.last_prompt = ""
        self.stopped = False
        self.volume_sessions = {}
        self.logs = []

    def log(self, level, msg):
        self.logs.append((level, msg))

    def step(self, num, step_key):
        pass

    def checkpoint(self):
        pass

    def gate(self, key, summary="", chapter=0):
        return ""

    def consume_gate_idea(self):
        return ""

    def stream_stage(self, label):
        pass

    def stream_chunk(self, text):
        pass

    def stream_reasoning(self, text):
        pass


class _FakeRouter:
    def __init__(self, client):
        self._client = client

    def client(self, slot):
        return self._client


def _prose_fixture(num: int, target: int = 60) -> str:
    """构造能过字数闸门与去味扫描的正文替身（count_chars 精确凑到 target）"""
    base = (f"# 第{num}章 开端\n\n雨停了。少年收起纸伞，沿巷口往东走。\n"
            "他数着脚下的青石板，第七块有一道裂缝。")
    pad = target - pj.count_chars(base)
    if pad > 0:
        base += "云" * pad
    return base


def _make_proj(tmp_path):
    proj = str(tmp_path / "测试书")
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"),
                  "## 主要角色表\n- 陈青山：凡人少年，灵根残缺\n")
    pj.write_file(os.path.join(proj, "大纲", "大纲.md"),
                  "## 卷级大纲\n\n### 第一卷：边陲凡尘（约3万字，2章）\n")
    for n in (1, 2, 3):
        pj.write_file(pj.get_outline_path(proj, n),
                      f"### 第 {n} 章：开端{n}\n- 核心事件：少年拾到玉简并反杀探子\n"
                      f"- 承接锚点：上一章结尾\n")
    return proj


def _run_microcycle(proj, cfg, client, num):
    from app.core import stages
    ctx = CycleCtx(proj, cfg, client)
    record = stages.chapter_microcycle(ctx, num)
    return ctx, record


def _cfg(**writing):
    base = {"chapter_session": True, "chapter_word_target": 60}
    base.update(writing)
    return {"writing": base, "gates": {"review_enabled": False}}


def _tracking_call(client):
    return next(m for m, ph in client.turn_calls if ph == "tracking")


# ---------------- 期望请求体复算（字节锁的取样基准，跑前取样） ----------------

def _expected_prose_turn(proj, cfg, num):
    """复算 stages 章会话首轮的逐字节请求文本（改造前语义，S1/章会话共用）"""
    from app import prompts
    from app.core import stages
    from app.prompts import scene_cards
    word_target = stages._outline_word_target(
        proj, num, cfg["writing"].get("chapter_word_target", 3000))
    wb_block, rg_block, _meta = stages._wb_rg_blocks(proj, cfg, num)
    outline = stages._sanitize_chapter_refs(pj.read_file(pj.get_outline_path(proj, num)))
    next_outline = pj.read_file(pj.get_outline_path(proj, num + 1))
    next_brief = stages._sanitize_chapter_refs(next_outline[:600]) if next_outline \
        else "（本章为当前最后一章细纲）"
    prose_kw = {
        "chapter_num": num,
        "next_chapter_brief": next_brief,
        "user_guidance": stages._compose_guidance("", cfg),
        "user_ideas": "（无）",
        "word_target": word_target,
        "tic_blacklist": stages._tic_blacklist(proj),
        "used_setpieces": stages._used_setpieces(proj),
        "project_header": project_header(proj),
        "chapter_header": chapter_header(proj, num),
        "style_discipline": prompts.STYLE_DISCIPLINE,
        "worldbook_block": wb_block,
        "regex_block": rg_block,
        "craft_block": scene_cards.craft_block(
            num, stages._total_chapters(proj, word_target), outline),
        "author_note": stages._author_note(proj),
    }
    return prompts.session_turn_text(prompts.PROSE_WRITING_PROMPT).format(**prose_kw)


def _expected_tracking_turn(proj, num):
    """复算 stages 追踪会话轮的逐字节请求文本（改造前语义）。

    第 1 章的取样在跑之前成立：nearest_chapter_before(proj, 1) 恒为 None（章头
    不受本章正文落盘影响），追踪/摘要文件都在 tracking 调用之后才被写。
    """
    from app import prompts
    from app.core import stages
    return prompts.session_turn_text(prompts.TRACKING_UPDATE_PROMPT).format(
        chapter_num=num,
        roster=stages._roster(proj),
        prose="（sentinel 已被历史引用行替换，本值不参与格式化）",
        character_state=pj.read_file(pj.get_tracking_path(proj, "角色状态"))[:2000],
        foreshadow_table=pj.read_file(pj.get_tracking_path(proj, "伏笔"))[:2000],
        timeline=pj.read_file(pj.get_tracking_path(proj, "时间线"))[:1500],
        old_context=pj.read_file(pj.get_tracking_path(proj, "上下文"))[:1500]
        or "（尚无写作上下文）",
        worldbook=pj.worldbook_text(proj, max_chars=2500, num=num) or "（世界书为空）",
        project_header=project_header(proj),
        chapter_header=chapter_header(proj, num))


# ---------------- ① flag 关：请求体逐字节不变（锁） ----------------

def test_flag_off_prose_first_turn_and_tracking_turn_byte_identical(tmp_path):
    """①（字节不变锁）：volume_session 关（章会话路径）——system 双层前缀、
    prose 首轮与 tracking 追加轮与改造前逐字节一致"""
    proj = _make_proj(tmp_path)
    cfg = _cfg()
    expected_sys = f"{project_header(proj)}\n\n{chapter_header(proj, 1)}"
    expected_prose = _expected_prose_turn(proj, cfg, 1)
    expected_tracking = _expected_tracking_turn(proj, 1)

    client = CycleClient()
    ctx, record = _run_microcycle(proj, cfg, client, 1)
    assert record["num"] == 1
    assert len(client.turn_calls) >= 2
    sys_msg, first_user = client.turn_calls[0][0][0], client.turn_calls[0][0][1]
    assert sys_msg == {"role": "system", "content": expected_sys}      # 字节锁
    assert first_user["content"] == expected_prose                     # 字节锁
    assert "章开幕" not in first_user["content"]
    tracking_msgs = _tracking_call(client)
    assert tracking_msgs[-1]["content"] == expected_tracking           # 字节锁
    # S4 指令库不出现（构造路径完全未触达）
    assert all("写作指令库" not in m["content"]
               for msgs, _ph in client.turn_calls for m in msgs)
    assert ctx.volume_sessions == {}       # 卷缓存未被触碰


# ---------------- ② S4 关（volume 开 / freeze 关）：S1 字节不变 ----------------

def test_volume_without_s4_keeps_s1_bytes(tmp_path):
    """中间态：volume_session 开 + s4_static_freeze 缺省关 = S1 请求体
    （system 只含前缀、八节章头整体进开幕轮、指令体仍随首轮重发）"""
    proj = _make_proj(tmp_path)
    ph = project_header(proj)
    full_header = chapter_header(proj, 1)
    expected_prose = _expected_prose_turn(proj, _cfg(), 1)
    cfg = _cfg(volume_session=True)        # s4_static_freeze 缺省=关

    client = CycleClient()
    _ctx, _rec = _run_microcycle(proj, cfg, client, 1)
    sys_msg = client.turn_calls[0][0][0]
    opening = client.turn_calls[0][0][1]["content"]
    assert sys_msg == {"role": "system", "content": ph}
    assert full_header in opening                      # 八节章头整体进开幕轮
    assert "写前对账" in opening                       # 指令体仍随首轮重发
    # 首轮文本与章会话路径的 session_turn 同源（剥前缀 + 作用域行）
    assert opening.endswith(expected_prose)


def test_chapter_header_volume_mode_skips_three_sections(tmp_path):
    """S4-b（单元面）：volume_mode=True 跳过三节、保留五节；默认参数字节不变"""
    proj = _make_proj(tmp_path)
    # 造出上一章正文与近章摘要：三节才有内容可跳
    pj.write_file(pj.get_chapter_path(proj, 1, "开端"), _prose_fixture(1))
    mem.append_chapter_summary(proj, 1, "开端", "少年拾到玉简。")
    full = chapter_header(proj, 2)
    slim = chapter_header(proj, 2, volume_mode=True)
    assert chapter_header(proj, 2, volume_mode=False) == full    # 默认字节不变
    for section in ("## 最近章节摘要", "## 上一章结尾（直接衔接用）",
                    "## 上一章开头（文风锚定样本"):
        assert section in full
        assert section not in slim                    # 三节跳过（正文/摘要在卷历史里）
    for section in ("## 本章细纲", "## 角色状态", "## 时间线",
                    "## 待回收/推进伏笔"):
        assert section in slim                        # 五节保留（recitation 防衰减）
    assert slim.endswith("\n") and full.endswith("\n")


# ---------------- ③ S4 开：指令库入 system、开幕轮瘦身（S4-a/S4-b） ----------------

def test_s4_on_system_carries_frozen_library(tmp_path):
    """②：flag 开——system = 前缀 + 指令库（模板化冻结版）；开幕轮不含指令体"""
    proj = _make_proj(tmp_path)
    ph = project_header(proj)
    lib_sys = volume_system_text(proj)
    assert lib_sys.startswith(ph + "\n\n" + _LIBRARY_HEADER + "\n")
    # 指令库 = PROSE 静态指令体（硬约束/格式契约/输出格式俱全）
    assert "写前对账" in lib_sys
    assert "## 法证级细节冻结" in lib_sys
    assert "## 去 AI 味红线" in lib_sys
    assert "## 输出格式" in lib_sys
    assert "4. 对话推进剧情或揭示性格" in lib_sys        # style_discipline 原文内联
    # 模板化冻结：逐章变量与上下文占位符全部替换
    for leftover in ("{chapter_num}", "{word_target}", "{worldbook_block}",
                     "{regex_block}", "{next_chapter_brief}", "{user_guidance}",
                     "{user_ideas}", "{used_setpieces}", "{craft_block}",
                     "{tic_blacklist}", "{author_note}", "{style_discipline}",
                     "{chapter_header}"):
        assert leftover not in lib_sys
    assert "按开幕轮给定的值" in lib_sys or "开幕轮给定" in lib_sys
    assert "以本章开幕轮" in lib_sys
    assert prose_instruction_library() in lib_sys       # 冻结体可独立复取

    header_vm = chapter_header(proj, 1, volume_mode=True)
    client = CycleClient()
    _ctx, record = _run_microcycle(proj, _cfg(volume_session=True,
                                              s4_static_freeze=True), client, 1)
    assert record["num"] == 1
    sys_msg = client.turn_calls[0][0][0]
    opening = client.turn_calls[0][0][1]["content"]
    assert sys_msg == {"role": "system", "content": lib_sys}     # 逐字节一致
    assert opening.startswith("【第 1 章开幕：")
    # 开幕轮：共享上下文 + 动态值 + 指令库执行指针，指令体一字不重发
    assert header_vm in opening
    assert "按写作指令库执行本章写作" in opening
    for frozen in ("写前对账", "## 法证级细节冻结", "## 去 AI 味红线", "## 输出格式"):
        assert frozen not in opening
    # S4-b：三节不再逐字重发（正文与摘要就在会话历史里）
    assert "## 最近章节摘要" not in opening
    assert "## 上一章结尾（直接衔接用）" not in opening
    assert "## 上一章开头（文风锚定样本" not in opening
    # 后续相位轮 system 不变、无开幕声明（前缀复用）
    for msgs, _ph in client.turn_calls[1:]:
        assert msgs[0] == {"role": "system", "content": lib_sys}
        assert "以下为本章共享上下文" not in msgs[-1]["content"]   # 无开幕声明


def test_s4_on_opening_keeps_five_sections_and_dynamic_values(tmp_path):
    """③：开幕轮仍含五节（细纲/全局摘要/角色状态/时间线/伏笔）+ 逐章动态值"""
    from app.core import stages
    proj = _make_proj(tmp_path)
    mem.write_global_summary(proj, "少年获得玉简，修行起步。")   # 预置：五节齐全
    next_brief = stages._sanitize_chapter_refs(
        pj.read_file(pj.get_outline_path(proj, 2))[:600])
    header_vm = chapter_header(proj, 1, volume_mode=True)
    for section in ("## 本章细纲", "## 全局摘要", "## 角色状态", "## 时间线",
                    "## 待回收/推进伏笔"):
        assert section in header_vm                  # 夹具自检：五节确在 volume 章头

    client = CycleClient()
    _ctx, _rec = _run_microcycle(proj, _cfg(volume_session=True,
                                            s4_static_freeze=True), client, 1)
    opening = client.turn_calls[0][0][1]["content"]
    assert header_vm in opening
    for section in ("## 本章细纲", "## 全局摘要", "## 角色状态", "## 时间线",
                    "## 待回收/推进伏笔"):
        assert section in opening                    # 五节保留（recitation 防衰减）
    # 逐章动态值（与指令库的引用行逐名对应）
    assert "- 本章章号：第 1 章" in opening
    assert "- 字数目标：60 字" in opening
    assert "- 下一章预告：" in opening and next_brief in opening
    assert "- 名场面不复用清单：" in opening
    assert "- 本章工艺路线：" in opening
    assert "- 作者按：" in opening
    assert "- 口头禅黑名单：" in opening


# ---------------- ④ S4 开：tracking 卷会话轮冗余去重（S4-c） ----------------

def test_s4_on_tracking_turn_uses_reference_line(tmp_path):
    """④：tracking 卷会话轮五节换短引用行；花名册保留、正文走历史引用"""
    from app.core import stages
    proj = _make_proj(tmp_path)
    client = CycleClient()
    _ctx, _rec = _run_microcycle(proj, _cfg(volume_session=True,
                                            s4_static_freeze=True), client, 1)
    body = _tracking_call(client)[-1]["content"]
    assert stages.TRACKING_SESSION_REF in body
    assert body.count(stages.TRACKING_SESSION_REF) == 5   # 五节各一
    assert "陈青山" in body                                # 花名册（功能性输入）保留
    assert "最近一条完整的章正文消息" in body                # {prose} 历史引用仍在
    # 冗余节全文不再重发（各追踪文件模板首行/独有句为判别物）
    assert "角色状态追踪" not in body
    assert "当前进度与最近决策速记" not in body
    assert "本书尚未生成世界书" not in body


def test_s4_off_tracking_turn_keeps_full_sections(tmp_path):
    """对照组：freeze 关（章会话路径）——追踪轮仍注入五个追踪文件全文"""
    from app.core import stages
    proj = _make_proj(tmp_path)
    client = CycleClient()
    _ctx, _rec = _run_microcycle(proj, _cfg(), client, 1)
    body = _tracking_call(client)[-1]["content"]
    assert "角色状态追踪" in body
    assert "当前进度与最近决策速记" in body
    assert "本书尚未生成世界书" in body
    assert stages.TRACKING_SESSION_REF not in body


# ---------------- ⑤ S4-d：cost_bench 长卷能力 ----------------

def test_ensure_outline_generates_missing_only(tmp_path, monkeypatch):
    """⑤：细纲缺失 → 现场调 stage_chapter_outlines(orch, n, n)；已备 → 零调用"""
    import cost_bench as cb
    from app.core import stages
    proj = str(tmp_path)
    os.makedirs(os.path.join(proj, "大纲"), exist_ok=True)
    calls = []

    def fake_stage_outlines(orch, start, end):
        calls.append((orch, start, end))
        pj.write_file(pj.get_outline_path(proj, start),
                      f"### 第 {start} 章：现场生成\n- 核心事件：补齐\n")
        return []

    monkeypatch.setattr(stages, "stage_chapter_outlines", fake_stage_outlines)
    orch = object()
    assert cb._ensure_outline(proj, 7, orch) is True
    assert calls == [(orch, 7, 7)]                       # 逐章现场生成（n..n）
    assert st.load_state(proj).get("stage") == st.STAGE_CH_OUTLINE
    assert cb._ensure_outline(proj, 7, orch) is False    # 已有细纲：零调用
    assert cb._ensure_outline(proj, 8, orch) is True     # 下一章缺 → 再生成
    assert calls == [(orch, 7, 7), (orch, 8, 8)]
    assert os.path.isfile(pj.get_outline_path(proj, 7))


def test_cmd_run_wires_ensure_outline_before_microcycle():
    """⑤（调用时机）：cmd_run 章循环里细纲补齐在微循环之前"""
    import cost_bench as cb
    src = inspect.getsource(cb.cmd_run)
    assert "_ensure_outline(proj, n, orch)" in src
    assert src.index("_ensure_outline(proj, n, orch)") < src.index("chapter_microcycle(")


def test_chapters_flag_capped_at_40(monkeypatch):
    """⑤：--chapters 上限放开到 MAX_CHAPTERS=40（含下限 1 兜底）"""
    import cost_bench as cb
    rec = []
    monkeypatch.setattr(cb, "cmd_run",
                        lambda variant, chapters, *a, **k: rec.append(chapters))
    for raw, expect in ((0, 1), (3, 3), (41, 40), (99, 40)):
        monkeypatch.setattr(sys, "argv",
                            ["cost_bench.py", "--variant", "t",
                             "--chapters", str(raw)])
        cb.main()
        assert rec[-1] == expect
    monkeypatch.setattr(sys, "argv", ["cost_bench.py", "--variant", "t"])
    cb.main()
    assert rec[-1] == 3                                  # 默认不变


# ---------------- runner（直接 python 运行同 pytest 语义） ----------------

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
