# -*- coding: utf-8 -*-
"""待修章节汇总 + 一键修复回归：聚合逻辑 / 状态翻转 / 修复环守卫 / prompt 别名防回归"""
import os

from app import prompts
from app.core import state as st
from app.ui import bridge as bmod


# ---- REVIEW_FIX_PROMPT 别名防回归（曾误别名到 REVISION_TARGETS_PROMPT，
#      导致流水线内修复环永远被「修订计划」守卫丢弃，自动修复失效）----

def test_review_fix_prompt_is_real_fix_prompt():
    assert "直接输出修改后的完整正文" in prompts.REVIEW_FIX_PROMPT
    assert "===REVISIONS===" not in prompts.REVIEW_FIX_PROMPT
    # stages.py 修复环用 {chapter_num}/{findings}/{prose}/{project_header}/{chapter_header} 组装，必须可 format
    # （v0.19：细纲/核心设定节选由双层前缀统一承载，不再散装注入）
    out = prompts.REVIEW_FIX_PROMPT.format(chapter_num=3, findings="- x", prose="正文",
                                           project_header="项目基准", chapter_header="章级共享段")
    assert "第 3 章" in out and "- x" in out and "正文" in out
    assert "项目基准" in out and "章级共享段" in out


def test_revision_targets_prompt_still_available():
    assert "===REVISIONS===" in prompts.REVISION_TARGETS_PROMPT


# ---- collect_needs_fix 聚合 ----

def test_collect_needs_fix_pass_only_empty():
    state = {"history": [{"num": 1, "status": "pass"}]}
    assert bmod.collect_needs_fix(state) == []


def test_collect_needs_fix_history_and_findings_merge():
    state = {
        "history": [
            {"num": 1, "title": "甲", "words": 100, "status": "pass"},
            {"num": 2, "title": "乙", "words": 200, "status": "needs_fix"},
        ],
        "review_findings": {
            "2": {"verdict": "REJECT", "blocking": ["x", "y"], "advisory": ["z"], "ts": "T"},
        },
        "chapter_need_human": {"2": "T"},
    }
    r = bmod.collect_needs_fix(state)
    assert len(r) == 1
    e = r[0]
    assert e["num"] == 2 and e["title"] == "乙" and e["blocking"] == 2
    assert e["advisory"] == 1 and e["verdict"] == "REJECT" and e["needHuman"] is True


def test_collect_needs_fix_items_fallback_and_sort():
    # 无 blocking 字段时从 items 的 fail 级兜底；仅 findings（无 history）也入列
    state = {
        "history": [{"num": 5, "title": "戊", "words": 1, "status": "needs_fix"}],
        "review_findings": {
            "3": {"verdict": "REJECT-HARD", "blocking": [], "advisory": [], "ts": "T",
                  "items": [{"dim": "C_FINGER", "level": "fail", "text": "硬伤"},
                            {"dim": "F_HOOK", "level": "marginal", "text": "弱钩"}]},
        },
    }
    r = bmod.collect_needs_fix(state)
    assert [e["num"] for e in r] == [3, 5]
    assert r[0]["blocking"] == 1 and r[0]["verdict"] == "REJECT-HARD"
    assert r[1]["blocking"] == 0   # history 有状态但无登记问题


def test_collect_needs_fix_empty_blocking_skipped():
    state = {"review_findings": {"7": {"verdict": "PASS", "blocking": [], "items": []}}}
    assert bmod.collect_needs_fix(state) == []


# ---- st.update_history_status ----

def test_update_history_status_flips(tmp_path):
    proj = str(tmp_path)
    state = {"history": [{"num": 2, "status": "needs_fix", "title": "乙"}]}
    st.save_state(proj, state)
    s = st.load_state(proj)
    assert st.update_history_status(proj, s, 2, "pass") is True
    assert st.load_state(proj)["history"][0]["status"] == "pass"


def test_update_history_status_missing_noop(tmp_path):
    proj = str(tmp_path)
    state = {"history": [{"num": 1, "status": "pass"}]}
    st.save_state(proj, state)
    s = st.load_state(proj)
    assert st.update_history_status(proj, s, 9, "pass") is False
    assert st.load_state(proj)["history"][0]["status"] == "pass"


# ---- 定向修复助手：最小差异 / 同一性验收 ----

def test_format_fix_targets_includes_quote_and_hint():
    targets = [
        {"kind": "review", "dim": "D_PLOT", "text": "数值对不上", "quote": "一百块灵石", "hint": ""},
        {"kind": "deslop", "dim": "not-is-comparison", "text": "不是A是B句式",
         "quote": "这不是恐惧，是战意", "hint": "直接写 B"},
    ]
    out = bmod.format_fix_targets(targets)
    assert "一百块灵石" in out and "维度D_PLOT" in out
    assert "命中原文" in out and "修法: 直接写 B" in out


def test_flagged_para_indices_locates_by_quote():
    prose = "甲段\n乙段目标句丙段\n丁段"
    assert bmod.flagged_para_indices(prose, [{"quote": "目标句"}]) == {1}
    assert bmod.flagged_para_indices(prose, [{"quote": ""}]) == set()


def test_enforce_minimal_diff_restores_unflagged_paragraph():
    prose = "P1\nP2原文未涉问题\nP3问题句\nP4收尾"
    out, restored = bmod.enforce_minimal_diff(
        prose, "P1\nP2被顺手润色了\nP3修复句\nP4收尾", flagged={2})
    assert out == "P1\nP2原文未涉问题\nP3修复句\nP4收尾"
    assert restored == 1


def test_enforce_minimal_diff_reverts_insert_and_delete_outside_flagged():
    prose = "P1\nP2\nP3问题句\nP4"
    out, _ = bmod.enforce_minimal_diff(prose, "P1\n插入的闲笔\nP3修复句", flagged={2})
    paras = out.split("\n")
    assert "P2" in paras and "P4" in paras and "P3修复句" in paras
    assert "插入的闲笔" not in paras


def test_enforce_minimal_diff_keeps_expansion_near_flagged():
    prose = "P1\nP2问题句\nP3"
    out, restored = bmod.enforce_minimal_diff(
        prose, "P1\nP2修复句\n补充的衔接句\nP3", flagged={1})
    assert out == "P1\nP2修复句\n补充的衔接句\nP3"
    assert restored == 0


def test_target_resolved_identity():
    t = {"text": "执事台词与性格不符", "quote": "执事在一旁冷笑"}
    assert bmod.target_resolved(t, "其他正文", ["时间线冲突"]) is True       # 引文消失且无相似复发
    assert bmod.target_resolved(t, "执事在一旁冷笑着说", []) is False          # 引文仍在
    assert bmod.target_resolved(t, "其他正文", ["执事的台词与性格完全不符"]) is False  # 复发


def test_recover_quote_from_text():
    prose = "甲段。\n折寿十天，换一个陌生人活。他低声说。\n丙段。"
    t1 = "规则冲突。【原文引证：\"折寿十天，换一个陌生人活。\"】 → root: ROOT_REGEX"
    assert bmod.recover_quote_from_text(t1, prose) == "折寿十天，换一个陌生人活。"
    t2 = "正文写的是\"折寿十天，换一个陌生人活\"与设定不符"
    assert bmod.recover_quote_from_text(t2, prose) == "折寿十天，换一个陌生人活"
    assert bmod.recover_quote_from_text("引用的句子根本不在正文里", prose) == ""


def test_split_unstructured_findings():
    mega = ("[未结构化评审] REJECT-HARD ===ITEMS=== - [阻塞] C 燃灯无折寿描写 "
            "- [阻塞] D 灯油来源因果空悬 - [建议] D 时间线矛盾 ")
    parts = bmod.split_unstructured_findings(mega)
    assert len(parts) == 3
    assert parts[0].startswith("C 燃灯无折寿描写")
    assert parts[2].startswith("D 时间线矛盾")
    assert bmod.split_unstructured_findings("普通单条问题") == ["普通单条问题"]


def test_parse_final_review_v2_quote_on_continuation_line():
    from app.core import stages
    text = ("===C_FINGER=== fail 折寿规则冲突，与核心设定不符，此处问题跨多行描述，\n"
            "下一行继续补充说明。\n"
            "【原文引证：\"折寿十天，换一个陌生人活。\"】\n"
            "===VERDICT===\nREJECT\n===END===\n")
    v2 = stages.parse_final_review_v2(text)
    fails = [i for i in v2["items"] if i["level"] == "fail"]
    assert fails and fails[0]["quote"] == "折寿十天，换一个陌生人活。"


# ---- ChapterRepairWorker._repair_one（假 LLM，不发请求）----

class _FakeClient:
    def __init__(self, answers):
        self.answers = answers   # [(marker, reply), ...] 按顺序匹配 prompt

    def chat_stream(self, prompt, on_chunk=None, **kw):
        for marker, reply in self.answers:
            if marker in prompt:
                return reply
        return ""


class _FakeRouter:
    def __init__(self, answers):
        self._client = _FakeClient(answers)

    def client(self, slot):
        return self._client


_P1 = ("宗门外门的晨光落在青石台阶上，杂役弟子们的议论声渐渐起来。"
       "陈凡站在比武场中央，握着手中的剑，四周的目光像针一样落在他身上，他一一忍了下来，脸上没有任何表情。"
       "风卷起的落叶擦过他的肩头，他依旧一动不动，视线稳稳落在正前方的比武台边缘。")
_P2 = ("他很清楚接下来的比试对自己意味着什么，输了就要退回杂役院，三年的苦修付诸东流。"
       "他咬紧了心头那口气，告诉自己必须赢下这一场，绝不能让那些等着看他笑话的人如愿。")
_P3 = ("执事在一旁冷笑，说他根本没有胜算，还说杂役弟子想出头千难万难，劝他早点认输下场，"
       "免得在众目睽睽之下丢人现眼，也算给自己留一点体面。")
_P4 = ("风卷起陈凡的衣角，他没有回答，只是默默调整着呼吸，等待着比试正式开始，"
       "手里的剑握得更紧了一些，手心已渗出汗水，心却反而比以往任何时候都更安静。")
PROSE = "# 第2章 乙\n" + _P1 + "\n" + _P2 + "\n" + _P3 + "\n" + _P4

_P1_REWORD = ("晨光洒在宗门外门的青石台阶上，围观的杂役弟子越聚越多，议论声一浪高过一浪。"
              "陈凡依旧站在比武场中央，握着剑，默默承受四面八方的注视，神情沉静得像一块石头。"
              "比武台四周的灯笼在风里轻轻晃动。")
_P2_SLOP = ("这不是恐惧，是战意。他需要这场比试来证明自己，"
            "也必须用这场胜利堵住所有轻视者的嘴，让那些说他没资格站上比武台的人从此闭嘴。")
_P2_CLEAN = ("胸中那份情绪是战意，他需要这场比试来证明自己，"
             "也必须用这场胜利堵住所有轻视者的嘴，让那些说他没资格站上比武台的人从此闭嘴。")
_P3_FIXED = ("执事皱了皱眉，没有再出言讥讽，只低声提醒陈凡在比武场上注意脚下，千万别伤了自己，"
             "说完便退到一旁，不再多看一眼，转身去照看其他比试了。")
_P3_KEPT = "执事在一旁冷笑，说他根本没有胜算，不过他还是让陈凡尽全力出手，免得比完之后留下遗憾。"

assert len(PROSE) >= 300   # 必须过修复稿「长度骤减」守卫


def _mk_proj(tmp_path, prose, rf=None):
    proj = str(tmp_path)
    prose_dir = os.path.join(proj, "正文")
    os.makedirs(prose_dir, exist_ok=True)
    path = os.path.join(prose_dir, "第002章_乙.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prose)
    state = {"history": [{"num": 2, "title": "乙", "words": len(prose), "status": "needs_fix"}]}
    if rf is not None:
        state["review_findings"] = {"2": rf}
    st.save_state(proj, state)
    return proj, path


_FIX_RF = {"verdict": "REJECT", "blocking": ["执事台词与性格不符"], "advisory": [],
           "items": [{"dim": "E_CHARACTER", "level": "fail",
                      "text": "执事台词与性格不符", "quote": "执事在一旁冷笑"}],
           "ts": "T"}

FIX_PROMPT_MARK = "阻塞级一致性问题"       # REVIEW_FIX_PROMPT 特有
REVIEW_PROMPT_MARK = "最终审核 Agent"       # FINAL_REVIEW_PROMPT 特有
PASS_REVIEW = "===VERDICT===\nPASS\n===END==="


def _worker(proj):
    # 低字数目标：测试正文约 330 字，让字数预检放行，本组只测修复环逻辑
    w = bmod.ChapterRepairWorker({"writing": {"chapter_word_target": 200}}, "", [2])
    w.proj = proj
    return w


def test_repair_one_targeted_success(tmp_path, monkeypatch):
    """按引证定向修复：问题段改写、其余段落逐字保留，复审通过 → 状态翻转"""
    fixed = PROSE.replace(_P3, _P3_FIXED)
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        (REVIEW_PROMPT_MARK, PASS_REVIEW),
    ]))
    proj, path = _mk_proj(tmp_path, PROSE, rf=_FIX_RF)
    ok, detail = _worker(proj)._repair_one(2)
    assert ok, detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == fixed
    s = st.load_state(proj)
    assert s["history"][0]["status"] == "pass"
    assert s["review_findings"]["2"]["verdict"] == "PASS"
    assert "repair_attempts" not in s or "2" not in s.get("repair_attempts", {})
    from app.core import versions
    assert versions.list_versions(proj, 2), "修复前备份快照应存在"


def test_repair_one_rolls_back_offtarget_rewrite(tmp_path, monkeypatch):
    """模型顺手润色了未涉问题的段落 → 机械还原，最终稿只含问题段改动"""
    fixed = PROSE.replace(_P3, _P3_FIXED).replace(_P1, _P1_REWORD)
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        (REVIEW_PROMPT_MARK, PASS_REVIEW),
    ]))
    proj, path = _mk_proj(tmp_path, PROSE, rf=_FIX_RF)
    ok, detail = _worker(proj)._repair_one(2)
    assert ok, detail
    assert "回滚" in detail
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert content == PROSE.replace(_P3, _P3_FIXED)   # _P1 被还原为原文


def test_repair_one_rejects_when_quote_still_present(tmp_path, monkeypatch):
    """同一性验收：改写后引文仍在 = 原问题未修复 → 原稿保留"""
    fixed = PROSE.replace(_P3, _P3_KEPT)
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        (REVIEW_PROMPT_MARK,
         "===E_CHARACTER=== fail 执事台词仍与既有性格不符【原文引证：\"执事在一旁冷笑\"】\n"
         "===VERDICT===\nREJECT\n===END==="),
    ]))
    proj, path = _mk_proj(tmp_path, PROSE, rf=_FIX_RF)
    ok, detail = _worker(proj)._repair_one(2)
    assert not ok and "未被修复" in detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == PROSE
    s = st.load_state(proj)
    assert s["history"][0]["status"] == "needs_fix"
    assert s["repair_attempts"]["2"]["count"] == 1


def test_repair_one_deslop_findings_are_targets(tmp_path, monkeypatch):
    """deslop blocking 命中（无登记审校问题）也进修复目标，复扫含本地正则"""
    prose = PROSE.replace(_P2, _P2_SLOP)
    fixed = prose.replace(_P2_SLOP, _P2_CLEAN)
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        (REVIEW_PROMPT_MARK, PASS_REVIEW),
    ]))
    proj, path = _mk_proj(tmp_path, prose,
                          rf={"verdict": "PASS", "blocking": [], "advisory": [],
                              "items": [], "ts": "T"})
    ok, detail = _worker(proj)._repair_one(2)
    assert ok, detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == fixed
    assert st.load_state(proj)["history"][0]["status"] == "pass"


def test_repair_one_deslop_still_hit_after_fix_rejected(tmp_path, monkeypatch):
    """模型改了问题段但毒句式仍在 → 同一性验收 + 本地正则复扫均不通过 → 不采纳"""
    prose = PROSE.replace(_P2, _P2_SLOP)
    p2_kept = ("这不是恐惧，是战意，他反复这样提醒自己。"
               "他需要这场比试来证明自己，也必须用这场胜利堵住所有轻视者的嘴。")
    fixed = prose.replace(_P2_SLOP, p2_kept)   # 引文「不是恐惧，是战意」仍在段内
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        (REVIEW_PROMPT_MARK, PASS_REVIEW),
    ]))
    proj, path = _mk_proj(tmp_path, prose,
                          rf={"verdict": "PASS", "blocking": [], "advisory": [],
                              "items": [], "ts": "T"})
    ok, detail = _worker(proj)._repair_one(2)
    assert not ok and "未被修复" in detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == prose


def test_repair_one_quoteless_blocking_degraded_path(tmp_path, monkeypatch):
    """登记问题完全无引证（旧数据/解析降级）→ 放宽最小差异不死锁，验收仍由同一性把关"""
    rf = {"verdict": "REJECT", "blocking": ["燃灯场景缺少代价描写，违反正则约束"],
          "advisory": [], "items": [], "ts": "T"}
    fixed = PROSE.replace(_P4, _P4 + "他咬着牙，补上了一句关于折寿代价的内心独白。")
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, fixed),
        (REVIEW_PROMPT_MARK, PASS_REVIEW),
    ]))
    proj, path = _mk_proj(tmp_path, PROSE, rf=rf)
    ok, detail = _worker(proj)._repair_one(2)
    assert ok, detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == fixed   # 无引证可定位时，改动不被最小差异还原
    assert st.load_state(proj)["history"][0]["status"] == "pass"


def test_repair_one_no_targets_fresh_review_pass(tmp_path, monkeypatch):
    """完全无登记问题且新鲜复审通过 → 直接翻转状态"""
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (REVIEW_PROMPT_MARK, PASS_REVIEW),
    ]))
    proj, path = _mk_proj(tmp_path, PROSE)
    ok, detail = _worker(proj)._repair_one(2)
    assert ok and "复审通过" in detail
    assert st.load_state(proj)["history"][0]["status"] == "pass"


def test_repair_one_rejects_revision_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, "===REVISIONS===\n- [第3段] → 改法"),
    ]))
    proj, path = _mk_proj(tmp_path, PROSE, rf=_FIX_RF)
    ok, detail = _worker(proj)._repair_one(2)
    assert not ok and "非正文" in detail
    with open(path, encoding="utf-8") as f:
        assert f.read() == PROSE   # 原稿保留
    assert st.load_state(proj)["history"][0]["status"] == "needs_fix"


def test_repair_one_stale_findings_trigger_fresh_review(tmp_path, monkeypatch):
    """登记引证已不在正文（人工修过）→ 视为过期作废 → 走新鲜复审而不是空跑修复模型"""
    rf = {"verdict": "REJECT", "blocking": ["执事台词与性格不符"], "advisory": [],
          "items": [{"dim": "E_CHARACTER", "level": "fail", "text": "执事台词与性格不符",
                     "quote": "早已被人工删掉的旧句子"}], "ts": "T"}
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (REVIEW_PROMPT_MARK, PASS_REVIEW),
    ]))
    proj, path = _mk_proj(tmp_path, PROSE, rf=rf)
    ok, detail = _worker(proj)._repair_one(2)
    assert ok and "复审通过" in detail
    assert st.load_state(proj)["history"][0]["status"] == "pass"


def test_repair_one_three_failed_rounds_marks_need_human(tmp_path, monkeypatch):
    """模型始终未改动问题段落 → 连续 3 轮不收敛 → 升级人工介入"""
    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: _FakeRouter([
        (FIX_PROMPT_MARK, PROSE),   # 原样返回，无任何有效改动
    ]))
    proj, path = _mk_proj(tmp_path, PROSE, rf=_FIX_RF)
    w = _worker(proj)
    for i in (1, 2):
        ok, detail = w._repair_one(2)
        assert not ok and "修复无效" in detail
        assert "转人工" not in detail
    ok, detail = w._repair_one(2)
    assert not ok and "转人工" in detail
    s = st.load_state(proj)
    assert "2" in (s.get("chapter_need_human") or {})
    with open(path, encoding="utf-8") as f:
        assert f.read() == PROSE


def test_repair_one_short_chapter_rejected_without_llm(tmp_path, monkeypatch):
    """字数预检 REJECT：新鲜复审被本地短路（不调 LLM），[字数] 被过滤出修复目标，
    无目标分支不得静默标 pass——返回失败且带字数原因，状态保持 needs_fix"""
    calls = []

    class _SpyClient:
        def chat_stream(self, prompt, on_chunk=None, **kw):
            calls.append(prompt)
            return "===VERDICT===\nPASS\n===END==="

    monkeypatch.setattr(bmod, "ModelRouter", lambda cfg, **kw: type(
        "R", (), {"client": lambda self, slot: _SpyClient()})())
    proj, path = _mk_proj(tmp_path, PROSE)
    w = bmod.ChapterRepairWorker({"writing": {"chapter_word_target": 3000}}, "", [2])
    w.proj = proj
    ok, detail = w._repair_one(2)
    assert not ok and "字数" in detail
    assert calls == []                      # 预检短路：审校槽零调用
    s = st.load_state(proj)
    assert s["history"][0]["status"] == "needs_fix"
    assert s["review_findings"]["2"]["verdict"] == "REJECT"
    assert any(str(b).startswith("[字数]") for b in s["review_findings"]["2"]["blocking"])
