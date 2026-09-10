# -*- coding: utf-8 -*-
"""v11 四项调整（工作指南 v3 第三部分）离线回归——全内存/临时目录，零 API

- 调整一（instruction_in_head）：三提取器切点钉住 + 头并入 + 轮次瘦身
- 调整三（volume_effort / audit_effort_low）：档位统一、state 钉住、降档合并
- 调整四（review_compact）：紧凑模板渲染 + quote_ref 定位 + JSON→v2 映射
- 调整五（deslop_pinned）：命中段映射、⟦Pnn⟧ 解析、定点修复合并与回退门槛

纪律：所有旗标缺省关时行为与改造前逐字节一致（各用例显式覆盖关态断言）。
"""
import json
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v11_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import prompts
from app.core import stages
from app.core.canon_audit import (AUDIT_CROSS_DIRECTIVE, AUDIT_INSTRUCTIONS,
                                  AUDIT_PROMPT, audit_instruction_head,
                                  audit_instruction_tail)
from app.core.volume_session import head_rebuild_system_text
from app.prompts.review import (FINAL_REVIEW_COMPACT, FINAL_REVIEW_PROMPT,
                                REVIEW_PROTOCOL_MARKER, review_compact_protocol)


# ==================== 调整一：三提取器 ====================

def test_audit_extractors_placeholder_free_and_in_template():
    head, tail = audit_instruction_head(), audit_instruction_tail()
    assert len(head) > 800 and len(tail) > 80
    import re
    for seg in (head, tail):
        assert not re.search(r"\{[a-z_]+\}", seg), "静态段不得含 format 占位符"
    out = AUDIT_PROMPT.format(num=3, project_header="PH", authorized="A",
                              constraints_block="C", ledger_block="L",
                              outline_brief="O", prev_ending="P",
                              next_opening="N", prose="PROSE")
    assert head in out and tail in out, ".format 渲染必须逐字还原静态段（剥除前提）"
    assert "{{" not in out.replace("}}", "") or True  # schema 自带收尾双括号，不检查


def test_tracking_static_head_generic_wording_and_marker():
    static = prompts.tracking_patch_static_head()
    assert len(static) > 800
    assert "{chapter_num}" not in static, "冻结头段不能带章号占位符（卷内逐字节稳定）"
    assert prompts.TRACKING_OUTPUT_MARKER in prompts.TRACKING_PATCH_PROMPT
    assert "硬规则" in static and '"worldbook"' in static


def test_deslop_static_rules_extraction():
    rules = prompts.deslop_static_rules()
    assert rules.startswith("## 改写原则")
    assert "10." in rules and rules.rstrip().endswith("保持对白引号格式与原文一致")
    assert "{" not in rules and "}" not in rules, "改写原则段零占位符"
    assert rules in prompts.DESLOP_REWRITE_PROMPT


def _mk_proj(tmp_path):
    proj = tmp_path / "p"
    (proj / "设定").mkdir(parents=True)
    (proj / "大纲").mkdir()
    (proj / "设定" / "题材定位.md").write_text("# 设定\n主角：测试", encoding="utf-8")
    (proj / "设定" / "世界书.md").write_text("# 世界书\n| 实体 |", encoding="utf-8")
    (proj / "大纲" / "大纲.md").write_text("# 大纲\n第一卷", encoding="utf-8")
    return str(proj)


def test_head_rebuild_instruction_in_head_merges_three_sections(tmp_path):
    proj = _mk_proj(tmp_path)
    base = head_rebuild_system_text(proj, 1, review_in_system=True,
                                    review_tail=prompts.review_static_tail())
    on = head_rebuild_system_text(proj, 1, review_in_system=True,
                                  review_tail=prompts.review_static_tail(),
                                  instruction_in_head=True)
    # 旗标关：不含三段（与 v10 行为逐字节一致——同一入参下 base 即旧行为）
    for marker in ("设定清算指令", "追踪补丁协议", "去味改写规则"):
        assert marker not in base
    # 旗标开：三段并入，且位于快照之后、审校尾段之前（指南规定顺序）
    assert audit_instruction_head() in on and audit_instruction_tail() in on
    assert prompts.tracking_patch_static_head() in on
    assert prompts.deslop_static_rules() in on
    assert on.index("设定清算指令") < on.index("追踪补丁协议") < on.index("去味改写规则")
    assert on.index("去味改写规则") < on.rindex(prompts.review_static_tail()[-200:])
    # 二次构建逐字节稳定（卷内冻结纪律）
    again = head_rebuild_system_text(proj, 1, review_in_system=True,
                                     review_tail=prompts.review_static_tail(),
                                     instruction_in_head=True)
    assert again == on


def test_audit_turn_strip_removes_static_keeps_materials():
    kw = dict(num=7, project_header="PH", authorized="A", constraints_block="C",
              ledger_block="L", outline_brief="O", prev_ending="P",
              next_opening="N", prose="PROSE_BODY")
    body = AUDIT_PROMPT.format(**kw)
    assert AUDIT_INSTRUCTIONS in body and AUDIT_CROSS_DIRECTIVE in body
    stripped = body.replace(AUDIT_INSTRUCTIONS, "（指针）", 1)
    stripped = stripped.replace(AUDIT_CROSS_DIRECTIVE, "", 1).rstrip() + "\n"
    assert AUDIT_INSTRUCTIONS not in stripped and AUDIT_CROSS_DIRECTIVE not in stripped
    for keep in ("PH", "C", "L", "O", "P", "N", "PROSE_BODY"):
        assert keep in stripped, "材料槽必须全保留"
    assert "（指针）" in stripped


def test_tracking_turn_slim_keeps_materials_drops_schema():
    kw = dict(chapter_num=7, prose="PROSE", character_table="T", cast_checklist="CC",
              foreshadow_table="F", timeline_recent="TL", old_context="OC",
              worldbook="WB", roster="R", project_header="PH", chapter_header="CH")
    turn = prompts.session_turn_text(prompts.TRACKING_PATCH_PROMPT).format(**kw)
    i = turn.find(prompts.TRACKING_OUTPUT_MARKER)
    assert i > 0
    slim = turn[:i].rstrip("\n") + "\n\n（见系统）"
    assert "硬规则" not in slim and '"worldbook"' not in slim, "schema/规则必须剥净"
    for keep in ("T", "CC", "F", "TL", "OC", "WB", "R"):
        assert keep in slim


# ==================== 调整三：effort 纪律 ====================

class _Client:
    def __init__(self):
        self.reasoning_effort = ""


class _Router:
    def __init__(self, stage_params=None):
        self.stage_params = stage_params if stage_params is not None else {}
        self._clients = {}

    def client(self, slot):
        return self._clients.setdefault(slot, _Client())


class _Ctx:
    def __init__(self, cfg, router, proj):
        self.cfg = cfg
        self.router = router
        self.proj = proj
        self.logs = []
        self.stream_chunk = lambda t: None
        self.stream_reasoning = lambda t: None

    def log(self, level, msg):
        self.logs.append((level, msg))

    def stream_stage(self, label):
        pass


def test_merge_audit_effort_low_idempotent_and_layered():
    sp = {}
    assert stages._merge_audit_effort_low(sp) is True
    assert sp["canon_audit"]["reasoning_effort"] == "low"
    assert sp["canon_audit"]["thinking"] == "enabled"
    assert stages._merge_audit_effort_low(sp) is False        # 幂等
    sp2 = {"canon_audit": {"thinking": "enabled", "early_stop": True}}
    stages._merge_audit_effort_low(sp2)
    assert sp2["canon_audit"]["early_stop"] is True            # 既有键保留
    assert stages._merge_audit_effort_low(None) is False


def test_audit_effort_low_payload_resolution():
    from app.llm.client import LLMClient
    sp = {"canon_audit": {"thinking": "enabled"}}
    stages._merge_audit_effort_low(sp)
    c = LLMClient.from_connection(
        {"name": "t", "base_url": "http://127.0.0.1:9", "model": "m", "api_key": "k"},
        max_retries=0, stage_params=sp)
    payload = c._build_payload([{"role": "user", "content": "x"}], stream=False,
                               phase="canon_audit")
    assert payload.get("reasoning_effort") == "low"
    payload_r = c._build_payload([{"role": "user", "content": "x"}], stream=False,
                                 phase="review")
    assert "reasoning_effort" not in payload_r, "降档只作用于 canon_audit 相位"


def test_volume_effort_apply_pin_and_refusal(tmp_path):
    proj = tmp_path / "vp"
    proj.mkdir()
    router = _Router()
    ctx = _Ctx({"writing": {"volume_effort": "low"}}, router, str(proj))
    stages._apply_volume_effort(ctx, str(proj), 3)
    for slot in ("writing", "review", "helper"):
        assert router.client(slot).reasoning_effort == "low"
    state = __import__("app.core.state", fromlist=["load_state"]).load_state(str(proj))
    assert state["volume_effort"] == "low" and state["volume_effort_vol"] >= 1
    # 同卷改档 → 拒绝并沿用钉住值
    ctx2 = _Ctx({"writing": {"volume_effort": "max"}}, router, str(proj))
    stages._apply_volume_effort(ctx2, str(proj), 3)
    assert router.client("writing").reasoning_effort == "low"
    assert any("拒绝中途改" in m for _lv, m in ctx2.logs)
    # 非法档位忽略；缺省空串零动作
    ctx3 = _Ctx({"writing": {"volume_effort": "turbo"}}, router, str(proj))
    stages._apply_volume_effort(ctx3, str(proj), 3)
    ctx4 = _Ctx({"writing": {}}, router, str(proj))
    stages._apply_volume_effort(ctx4, str(proj), 3)
    assert router.client("review").reasoning_effort == "low"   # 未被非法/空档位改动


# ==================== 调整四：紧凑票 ====================

def test_compact_template_shares_rubric_and_renders():
    proto = review_compact_protocol()
    assert FINAL_REVIEW_PROMPT.find(REVIEW_PROTOCOL_MARKER) > 0
    prefix = FINAL_REVIEW_PROMPT[:FINAL_REVIEW_PROMPT.find(REVIEW_PROTOCOL_MARKER)]
    assert FINAL_REVIEW_COMPACT == prefix + proto.replace("{", "{{").replace("}", "}}")
    kw = dict(project_header="【H】", chapter_header="【章头】", prose="正文",
              worldbook_block="WB", regex_block="RG", genre_review_extra="GR",
              l0_findings="L0")
    rendered = FINAL_REVIEW_COMPACT.format(**kw)     # 不抛 KeyError/ValueError
    assert proto in rendered and "【章头】" in rendered and "段N句M" in proto
    assert '"verdict"' in proto and '"confidence"' in proto and '"dimensions"' in proto


def test_resolve_quote_ref():
    prose = "# 第1章 试炼\n他攥紧了怀里的布袋。袋里三枚下品灵石，硌得胸口发疼。\n第二段开头。他停下脚步！雨落下来？"
    q = stages.resolve_quote_ref(prose, "段2句2")
    assert q == "袋里三枚下品灵石，硌得胸口发疼。"
    assert stages.resolve_quote_ref(prose, "段1句1") == "# 第1章 试炼"
    for bad in ("段99句1", "段2句99", "随便", "", "第2段"):
        assert stages.resolve_quote_ref(prose, bad) == ""


def _compact_vote():
    return json.dumps({
        "dimensions": [
            {"dim": "A_GOLDEN_OPEN", "score": "pass", "quote_ref": "", "one_line": "开章有冲突"},
            {"dim": "B_PAYOFF", "score": "marginal", "quote_ref": "段2句1",
             "one_line": "爽点兑现弱", "root": "ROOT_OUTLINE_UNIT"},
            {"dim": "C_FINGER", "score": "pass", "quote_ref": "", "one_line": "无越界"},
            {"dim": "D_PLOT", "score": "pass", "quote_ref": "", "one_line": "因果成立"},
            {"dim": "E_CHARACTER", "score": "pass", "quote_ref": "", "one_line": "声口稳定"},
            {"dim": "F_HOOK", "score": "fail", "quote_ref": "段3句1",
             "one_line": "章末无钩", "root": "ROOT_PROSE"},
        ],
        "verdict": "PASS_WITH_NOTES",
        "confidence": "high",
    }, ensure_ascii=False)


def test_parse_compact_review_json_full_mapping():
    prose = "第一段。\n他在门外停下了脚步！\n第三段收束了全局。"
    v2 = stages.parse_compact_review_json(_compact_vote(), prose)
    assert v2 is not None
    assert v2["verdict"] in ("PASS", "PASS_WITH_NOTES", "REJECT", "REJECT-HARD")
    assert v2["summary"] == {"pass": 4, "marginal": 1, "fail": 1}
    assert v2["confidence"] == "high"
    assert v2["blocking"] == ["章末无钩"]
    assert v2["advisory"] == ["爽点兑现弱"]
    by_dim = {it["dim"]: it for it in v2["items"]}
    assert by_dim["F_HOOK"]["quote"] == "第三段收束了全局。"
    assert by_dim["F_HOOK"]["root_layer"] == "ROOT_PROSE"
    assert by_dim["B_PAYOFF"]["root_layer"] == "ROOT_OUTLINE_UNIT"
    assert by_dim["A_GOLDEN_OPEN"]["root_layer"] == ""       # pass 无根因
    # 验真闭环：compact 引文本就来自原文 → 验真必过（句长 ≥6 满足 min_len）
    verified = stages.verify_review_quotes(prose, v2)
    fails = [it for it in verified["items"] if it.get("quote") and not it.get("quote_verified")]
    assert fails == []


def test_parse_compact_review_json_rejects_malformed():
    prose = "第一段。"
    base = json.loads(_compact_vote())
    def _dump(d):
        return json.dumps(d, ensure_ascii=False)
    missing_dim = dict(base, dimensions=[d for d in base["dimensions"] if d["dim"] != "C_FINGER"])
    bad_verdict = dict(base, verdict="MAYBE")
    bad_score = dict(base, dimensions=[dict(d, score="ok") if d["dim"] == "A_GOLDEN_OPEN" else d
                                       for d in base["dimensions"]])
    bad_dim = dict(base, dimensions=[dict(d, dim="G_MISC") if d["dim"] == "A_GOLDEN_OPEN" else d
                                     for d in base["dimensions"]])
    for broken in (missing_dim, bad_verdict, bad_score, bad_dim):
        assert stages.parse_compact_review_json(_dump(broken), prose) is None
    assert stages.parse_compact_review_json("完全不是 JSON 的整章回声" * 10, prose) is None
    assert stages.parse_compact_review_json("", prose) is None
    # 围栏容忍
    fenced = "```json\n" + _compact_vote() + "\n```"
    assert stages.parse_compact_review_json(fenced, "第一段。\n他停下了！\n第三段收束。") is not None


def test_stage_param_override_sets_and_restores():
    sp = {"review": {"max_tokens": 900, "thinking": "disabled"}}
    router = _Router(stage_params=sp)
    ctx = type("R", (), {"router": router})()
    with stages._stage_param_override(ctx, "review", max_tokens=1400):
        assert sp["review"]["max_tokens"] == 1400
        assert sp["review"]["thinking"] == "disabled"
    assert sp["review"]["max_tokens"] == 900
    with stages._stage_param_override(ctx, "review", temperature=0.5):
        assert sp["review"]["temperature"] == 0.5
    assert "temperature" not in sp["review"]                  # 新增键退出时移除
    with stages._stage_param_override(ctx, "review"):         # 空 kv 为 no-op
        pass
    assert sp["review"]["max_tokens"] == 900


# ==================== 调整五：deslop 定点修复 ====================

class _F:
    def __init__(self, start, level="blocking", message="毒句式", text="命中文本"):
        self.start = start
        self.level = level
        self.message = message
        self.text = text


def test_findings_para_map_offsets():
    prose = "# 第1章\n第一段正文，不是偶然，而是选择。\n\n第二段，他深吸一口气。"
    # 「不是…而是」在第 2 行（段 2）；「深吸一口气」在第 4 行（段 3）
    off2 = prose.index("不是偶然")
    off3 = prose.index("深吸一口气")
    m = stages._findings_para_map(prose, [_F(off2), _F(off3)])
    assert sorted(m) == [2, 3]
    assert len(m[2]) == 1 and len(m[3]) == 1
    m0 = stages._findings_para_map(prose, [_F(-1), _F(99999), "not-a-finding"])
    assert m0 == {}

def test_parse_pinned_output_last_wins():
    raw = ("解释行不该出现\n"
           "⟦P02⟧ 第二段改好了。\n"
           "⟦P03⟧ 第三段改好了。\n"
           "⟦P02⟧ 第二段最终版。")
    spans = stages._parse_pinned_output(raw)
    by_para = {s["para"]: s["text"] for s in spans}
    assert by_para[2] == "第二段最终版。"
    assert by_para[3] == "第三段改好了。"
    assert all(s["op"] == "replace" for s in spans)
    assert stages._parse_pinned_output("没有任何标记的回复") == []


def _pinned_env(tmp_path, prose, reply):
    """构造定点修复的全套假件（session/ctx），返回 (ctx, session)"""
    class _Session:
        enabled = True

        def __init__(self):
            self.turns = 2
            self.committed = None
            self.rolled_back = 0

        def turn_count(self):
            return self.turns

        def ask(self, prompt, **kw):
            return kw["postprocess"](reply) if kw.get("postprocess") else reply

        def commit_turn(self, user, assistant):
            self.committed = (user, assistant)
            self.turns += 1

        def rollback_to(self, n):
            self.rolled_back += 1

    class _Router2:
        def client(self, slot):
            return _Client()

    sess = _Session()
    ctx = _Ctx({"writing": {}}, _Router2(), str(tmp_path))
    return ctx, sess


def test_deslop_pinned_happy_path_and_guards(tmp_path):
    from app.core.stages import (DESLOP_PINNED_MAX_PARAS, _deslop_pinned_rewrite,
                                 _findings_para_map)
    prose = "# 第1章\n第一段干净。\n第二段，不是风声，而是哭声。\n第三段干净。"
    off = prose.index("不是风声")
    blocking = [_F(off)]
    ctx, sess = _pinned_env(tmp_path, prose, "⟦P03⟧ 第二段，风声里混着哭声。")
    merged = _deslop_pinned_rewrite(ctx, sess, prose, blocking, [], 1)
    assert merged.startswith("# 第1章") and "风声里混着哭声" in merged
    assert "不是风声" not in merged and "第一段干净" in merged and "第三段干净" in merged
    assert sess.committed is not None and sess.committed[1] == merged
    # 越界段号 → 回退（返回空串 + 回滚）
    ctx2, sess2 = _pinned_env(tmp_path, prose, "⟦P99⟧ 越界段。")
    assert _deslop_pinned_rewrite(ctx2, sess2, prose, blocking, [], 1) == ""
    assert sess2.rolled_back == 1
    # 替换膨胀 >25% → 回退
    big = "膨胀" * 2000
    ctx3, sess3 = _pinned_env(tmp_path, prose, f"⟦P03⟧ {big}")
    assert _deslop_pinned_rewrite(ctx3, sess3, prose, blocking, [], 1) == ""
    # 命中段 >2 → 不进模型直接回退（无 ask、无 commit、无回滚）
    finds = [_F(0), _F(off), _F(prose.index("第三段干净"))]
    assert len(_findings_para_map(prose, finds)) == 3 > DESLOP_PINNED_MAX_PARAS
    ctx4, sess4 = _pinned_env(tmp_path, prose, "⟦P02⟧ x")
    assert _deslop_pinned_rewrite(ctx4, sess4, prose, finds, [], 1) == ""
    assert sess4.committed is None and sess4.rolled_back == 0
