# -*- coding: utf-8 -*-
"""v13 输出侧治理离线回归——v12 教训：miss 131k+out 34.8k，90% 缺口在输出与写延迟

- pace_boundaries：边界细粒度＞全局＞缺省的时长解析
- audit 会话轮材料引用化：corpus_head 门控下 slim prompt 的引用行与门控关断
- flagged 上限：_cap_flagged 截断与溢出计数
- outline_in_session：会话内细纲生成落盘 + 解析失败回退

全内存/临时目录，零 API。"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v13_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core import stages
from app.core.canon_audit import (AUDIT_PROMPT, EARLY_STOP_DIRECTIVE,
                                  REVIEW_FLAGGED_CAP, _cap_flagged)


# ==================== pace_boundaries ====================

def test_pace_seconds_priority():
    # 边界值 ＞ 全局 ＞ 缺省
    cfgw = {"pace_boundaries": {"deslop_review": 45}, "session_pace_seconds": 30}
    assert stages._pace_seconds(cfgw, "deslop_review", 0) == 45
    assert stages._pace_seconds(cfgw, "review_audit", 0) == 30
    assert stages._pace_seconds(cfgw, "", 7) == 30
    # 无全局有边界：其他边界回退缺省
    cfgw2 = {"pace_boundaries": {"deslop_review": 45}}
    assert stages._pace_seconds(cfgw2, "review_audit", 0) == 0
    # 全空＝关
    assert stages._pace_seconds({}, "", 0) == 0
    # 非法值忽略（回退链继续）
    cfgw3 = {"pace_boundaries": {"deslop_review": "x"}, "session_pace_seconds": "y"}
    assert stages._pace_seconds(cfgw3, "deslop_review", 9) == 9
    assert stages._pace_seconds({"session_pace_seconds": -5}, "", 0) == 0


def test_pace_boundaries_existing_presets_unchanged():
    """session_pace_seconds=45 的既有预设（v9-v12）语义不变：任意边界都取 45"""
    cfgw = {"session_pace_seconds": 45}
    for b in ("prose_tail", "deslop_review", "review_audit", ""):
        assert stages._pace_seconds(cfgw, b, 0) == 45


# ==================== audit 会话轮材料引用化 ====================

def _fmt(diffs: dict) -> str:
    base = dict(num=3, names="x", project_header="PH", authorized="A",
                constraints_block="C", ledger_block="L", outline_brief="O",
                prev_ending="P", next_opening="N", prose="PROSE")
    base.update(diffs)
    return AUDIT_PROMPT.format(**base)


def test_audit_slim_prompt_reference_lines_and_gate():
    slim = _fmt({
        "authorized": "【＝系统「设定底册（卷首冻结）」的授权自创清单（历史已载）——"
                      "直接对照执行；正文新出场者仍须逐条收录进 adoptions】",
        "constraints_block": "【＝系统「设定底册（卷首冻结）」的核心设定约束条款"
                             "（金手指限制/消耗/反噬/触发条件与全局红线，历史已载）——"
                             "直接对照执行，违反即 violations】",
        "outline_brief": "【＝系统「本卷细纲快照（卷首冻结）」中第 3 章细纲（历史已载）——"
                         "拍点契约照常执行，缺失/漂移/自造记入 violations】",
        "prev_ending": "【＝系统「已锁章节原文（卷首冻结）」中上一章结尾（历史已载）】",
        "next_opening": "【＝系统「已锁章节原文（卷首冻结）」中下一章开头（历史已载；无则为空）】",
    })
    for keep in ("PH", "L", "PROSE"):   # 前缀/台账/正文仍实注入
        assert keep in slim
    slim_materials = sum(slim.count(m) for m in ("历史已载",))
    assert slim_materials >= 5
    assert "历史已载" not in _fmt({})    # 全量 prompt 无引用行（门控关断=旧行为）


def test_early_stop_directive_static():
    assert EARLY_STOP_DIRECTIVE.startswith("\n## 对账纪律")
    assert "不要输出分诊清单" in EARLY_STOP_DIRECTIVE


# ==================== flagged 上限 ====================

def test_cap_flagged():
    items = [{"i": i} for i in range(12)]
    capped, overflow = _cap_flagged(items)
    assert len(capped) == REVIEW_FLAGGED_CAP == 8 and overflow == 4
    assert capped[0] == {"i": 0} and capped[-1] == {"i": 7}
    few = [{"i": 1}, {"i": 2}]
    assert _cap_flagged(few) == (few, 0)
    assert _cap_flagged([]) == ([], 0)


# ==================== outline_in_session ====================

class _Session:
    enabled = True

    def __init__(self, reply):
        self.reply = reply
        self.asked = []

    def turn_count(self):
        return 0

    def ask(self, prompt, **kw):
        self.asked.append(prompt)
        return kw["postprocess"](self.reply) if kw.get("postprocess") else self.reply

    def snapshot(self):
        return []

    def rollback_to(self, n):
        pass


class _Router2:
    def client(self, slot):
        return type("C", (), {"reasoning_effort": "", "last_aborted": False,
                              "last_sampling": {}, "last_degraded": False,
                              "model": "m"})()


class _Ctx:
    def __init__(self, cfg, proj):
        self.cfg = cfg
        self.proj = proj
        self.router = _Router2()
        self.logs = []
        self.stream_chunk = lambda t: None
        self.stream_reasoning = lambda t: None
        self._ideas = []

    def log(self, level, msg):
        self.logs.append((level, msg))

    def stream_stage(self, label):
        pass

    def checkpoint(self):
        pass

    def consume_gate_idea(self):
        return self._ideas.pop(0) if self._ideas else None

    def gate(self, *a, **k):
        return None


def _mk_proj(tmp_path):
    proj = tmp_path / "p13"
    (proj / "设定").mkdir(parents=True)
    (proj / "大纲").mkdir()
    (proj / "正文").mkdir()
    (proj / "追踪").mkdir()
    (proj / "设定" / "题材定位.md").write_text(
        "# 设定\n主角：测试\n### 金手指约束条款\n- 每日 3 次\n### 授权自创清单\n- 测试堂",
        encoding="utf-8")
    (proj / "设定" / "世界书.md").write_text("# 世界书\n| 实体 |", encoding="utf-8")
    (proj / "大纲" / "大纲.md").write_text("### 第4卷 试炼（第1-40章）\n- 卷契约：活下来",
                                          encoding="utf-8")
    return str(proj)


def test_outline_in_session_generates_and_writes(tmp_path):
    proj = _mk_proj(tmp_path)
    ctx = _Ctx({"writing": {}}, proj)
    sess = _Session("===第30章===\n## 第30章 测试钩子\n- 章名：测试钩子\n"
                    "- 核心事件：主角识破骗局并反杀（≥250字）\n"
                    "- 承接锚点：上一章的账期\n- 章末钩子：门被敲响\n"
                    "- 预算合计：约 1900—2100 字\n")
    ok = stages._ensure_outline_in_session(ctx, sess, 30)
    assert ok is True
    written = open(os.path.join(proj, "大纲", "细纲_第030章.md"), encoding="utf-8").read()
    assert "测试钩子" in written and "预算合计" in written
    # 会话轮不重复注入全书前缀（骑冻结头的字节前提）
    assert sess.asked and "作用域" in sess.asked[0]


def test_outline_in_session_parse_failure_returns_false(tmp_path):
    proj = _mk_proj(tmp_path)
    ctx = _Ctx({"writing": {}}, proj)
    sess = _Session("完全无法解析的自由文本，没有 ===第N章=== 分隔符。")
    ok = stages._ensure_outline_in_session(ctx, sess, 31)
    assert ok is False
    assert not os.path.exists(os.path.join(proj, "大纲", "细纲_第031章.md"))
