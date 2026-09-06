# -*- coding: utf-8 -*-
"""P5 多轮投票：每维多数票、平票从严、阻塞需 ≥2 票、早停"""
import os

from app import project
from app.core import stages


def _vote(verdict, dims):
    """dims: {dim: (level, text, quote, root)} → 构造一票的 v2 解析结构"""
    items, blocking, advisory = [], [], []
    summary = {"pass": 0, "marginal": 0, "fail": 0}
    for d, (lvl, text, quote, root) in dims.items():
        items.append({"dim": d, "level": lvl, "text": text,
                      "quote": quote, "root_layer": root, "line": ""})
        summary[lvl] += 1
        if lvl == "fail":
            blocking.append(text)
        elif lvl == "marginal":
            advisory.append(text)
    return {"verdict": verdict, "items": items, "blocking": blocking,
            "advisory": advisory, "summary": summary}


_P = ("pass", "合标", "", "")
_F = ("fail", "细纲核心事件未演", "他忍了忍", "ROOT_PROSE")
_M = ("marginal", "钩子偏弱", "他睡了", "ROOT_PROSE")


# ---- 每维多数票 ----

def test_majority_fail_kept_with_two_votes():
    v1 = _vote("PASS_WITH_NOTES", {"A_GOLDEN_OPEN": _P, "D_PLOT": _F})
    v2 = _vote("PASS_WITH_NOTES", {"A_GOLDEN_OPEN": _P, "D_PLOT": _F})
    v3 = _vote("PASS", {"A_GOLDEN_OPEN": _P, "D_PLOT": _P})
    m = stages.merge_review_votes([v1, v2, v3])
    assert m["summary"]["fail"] == 1
    assert m["blocking"] and "细纲核心事件未演" in m["blocking"][0]
    assert m["verdict"] == "PASS_WITH_NOTES"      # fail=1 → 改进档
    assert m["vote_count"] == 3
    dim = {it["dim"]: it for it in m["items"]}
    assert dim["D_PLOT"]["level"] == "fail" and dim["D_PLOT"]["votes"] == "2/3"


def test_single_fail_vote_outvoted_by_majority():
    v1 = _vote("PASS_WITH_NOTES", {"D_PLOT": _F})
    v2 = _vote("PASS", {"D_PLOT": _P})
    v3 = _vote("PASS", {"D_PLOT": _P})
    m = stages.merge_review_votes([v1, v2, v3])
    # 1/3 票被多数票覆盖 → 该维 pass，不进阻塞也不进建议
    assert m["summary"] == {"pass": 1, "marginal": 0, "fail": 0}
    assert m["blocking"] == [] and m["advisory"] == []
    assert m["verdict"] == "PASS"


def test_tie_goes_strict():
    v1 = _vote("PASS", {"F_HOOK": _P})
    v2 = _vote("PASS_WITH_NOTES", {"F_HOOK": _M})
    m = stages.merge_review_votes([v1, v2])       # 1:1 平票
    assert m["summary"]["marginal"] == 1          # 从严取 marginal
    # 平票 fail:pass 从严取 fail，但仅 1 票不足阻塞定足数（k=2 需 2 票）→ 降级
    v3 = _vote("PASS_WITH_NOTES", {"F_HOOK": _F})
    v4 = _vote("PASS", {"F_HOOK": _P})
    m2 = stages.merge_review_votes([v3, v4])
    assert m2["summary"]["fail"] == 0 and m2["summary"]["marginal"] == 1
    assert "票数不足降级 1/2" in m2["advisory"][0]
    # 三维各一票（fail/marginal/pass）→ 平票从严取 fail，仍不足票 → 降级
    v5 = _vote("PASS_WITH_NOTES", {"F_HOOK": _F})
    v6 = _vote("PASS_WITH_NOTES", {"F_HOOK": _M})
    v7 = _vote("PASS", {"F_HOOK": _P})
    m3 = stages.merge_review_votes([v5, v6, v7])
    assert m3["summary"]["fail"] == 0 and m3["summary"]["marginal"] == 1


def test_single_vote_quorum_is_one():
    v1 = _vote("PASS_WITH_NOTES", {"D_PLOT": _F})
    m = stages.merge_review_votes([v1])           # k=1（修复环复扫语义）
    assert m["summary"]["fail"] == 1 and m["blocking"]


def test_blocking_items_deduped_across_votes():
    f1 = ("fail", "问题甲", "引证甲", "ROOT_PROSE")
    f2 = ("fail", "问题甲复述", "引证甲", "ROOT_PROSE")   # 同引证 → 去重
    f3 = ("fail", "问题乙", "引证乙", "ROOT_PROSE")
    v1 = _vote("REJECT", {"C_FINGER": f1, "D_PLOT": f3})
    v2 = _vote("REJECT", {"C_FINGER": f2, "D_PLOT": f3})
    m = stages.merge_review_votes([v1, v2])
    c = [it for it in m["items"] if it["dim"] == "C_FINGER"][0]
    assert "问题甲复述" not in c["text"]           # 同引证去重
    d = [it for it in m["items"] if it["dim"] == "D_PLOT"][0]
    assert "问题乙" in d["text"]
    assert m["verdict"] == "REJECT"               # fail=2


def test_votes_identical():
    v1 = _vote("PASS", {"A_GOLDEN_OPEN": _P, "F_HOOK": _M})
    v2 = _vote("PASS", {"A_GOLDEN_OPEN": _P, "F_HOOK": _M})
    v3 = _vote("PASS", {"A_GOLDEN_OPEN": _P, "F_HOOK": _P})
    assert stages._votes_identical(v1, v2)
    assert not stages._votes_identical(v1, v3)
    v4 = _vote("PASS_WITH_NOTES", {"A_GOLDEN_OPEN": _P, "F_HOOK": _M})
    assert not stages._votes_identical(v1, v4)    # 判决不同


# ---- 早停（真调用路径，FakeRouter）----

class _FakeClient:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = 0

    def chat_stream(self, prompt, on_chunk=None, temperature=None, **kw):
        self.calls += 1
        return self.scripts.pop(0)


class _FakeRouter:
    def __init__(self, client):
        self._c = client

    def client(self, slot):
        return self._c


class _FakeCtx:
    def __init__(self, proj, client, votes=3):
        self.proj = proj
        self.cfg = {"gates": {"review_votes": votes, "review_temperature": 0.2},
                    "writing": {"regex_semantics": "logic"}}
        self.router = _FakeRouter(client)
        self.last_prompt = ""
        self.review_raw = None
        self.review_v2 = None
        self.logs = []

    def stream_chunk(self, t):
        pass

    def log(self, level, msg):
        self.logs.append((level, msg))


def _report(dim_line):
    return (f"===A_GOLDEN_OPEN=== pass 合标\n{dim_line}\n"
            f"===C_FINGER=== pass\n===E_CHARACTER=== pass\n===F_HOOK=== pass\n"
            f"===WORST_QUOTES===\n- [D] \"他忍了忍，决定改日再说\"\n===TOTAL===\n"
            f"- fail 项数：1\n- marginal 项数：0\n- 总评：PASS_WITH_NOTES\n===END===\n"
            f"===VERDICT===\nPASS_WITH_NOTES\n===END===")


_FAIL_LINE = '===D_PLOT=== fail 未演【原文引证："他忍了忍，决定改日再说"】 → root: ROOT_PROSE'


def test_first_vote_solo_then_replicas_parallel(tmp_path):
    """v0.19 投票调度：首票单发（写前缀缓存）→ 其余票并行重采样。

    旧「前两票并行 + 早停」已移除：v4 thinking 下 temperature 无效、票间必不同构，
    早停名存实亡；首票单发让并行票全量命中前缀缓存，墙钟与旧两阶段制相同。
    """
    proj = str(tmp_path)
    project.write_file(os.path.join(proj, "大纲", "细纲_第002章.md"), "核心事件：反击")
    prose = "他忍了忍，决定改日再说。" * 50
    same = _report(_FAIL_LINE)
    client = _FakeClient([same, same, same])
    ctx = _FakeCtx(proj, client, votes=3)
    merged = stages.review_with_votes(ctx, 2, prose, votes=3)
    assert client.calls == 3                      # 三票全投（早停已移除）
    assert merged["summary"]["fail"] == 1
    assert any("审校第 1/3 票" in msg for _lvl, msg in ctx.logs)


def test_three_votes_run_when_divergent(tmp_path):
    proj = str(tmp_path)
    prose = "他忍了忍，决定改日再说。" * 50
    fail = _report(_FAIL_LINE)
    passd = _report("===D_PLOT=== pass 合标")
    client = _FakeClient([fail, passd, fail])
    ctx = _FakeCtx(proj, client, votes=3)
    merged = stages.review_with_votes(ctx, 2, prose, votes=3)
    assert client.calls == 3
    assert merged["summary"]["fail"] == 1 and merged["blocking"]   # 2/3 票保留阻塞


def test_pass_fast_path_skips_replicas(tmp_path):
    """gates.review_pass_fast：首票全维 pass 零阻塞 → 免投副本票（v0.18.5 实验变量）"""
    proj = str(tmp_path)
    project.write_file(os.path.join(proj, "大纲", "细纲_第002章.md"), "核心事件：反击")
    prose = "他忍了忍，决定改日再说。" * 50
    ok = _report("===D_PLOT=== pass 合标")
    client = _FakeClient([ok, ok, ok])
    ctx = _FakeCtx(proj, client, votes=3)
    ctx.cfg["gates"]["review_pass_fast"] = True
    merged = stages.review_with_votes(ctx, 2, prose, votes=3)
    assert client.calls == 1                      # 只投了首票
    assert client.scripts                         # 剩余两票没被消费
    assert merged["verdict"] in ("PASS", "PASS_WITH_NOTES")


def test_pass_fast_path_off_explicitly(tmp_path):
    """review_pass_fast=False 显式关闭：三票照投（v0.19 起默认开，关闭需显式配置）"""
    proj = str(tmp_path)
    project.write_file(os.path.join(proj, "大纲", "细纲_第002章.md"), "核心事件：反击")
    prose = "他忍了忍，决定改日再说。" * 50
    ok = _report("===D_PLOT=== pass 合标")
    client = _FakeClient([ok, ok, ok])
    ctx = _FakeCtx(proj, client, votes=3)
    ctx.cfg["gates"]["review_pass_fast"] = False
    stages.review_with_votes(ctx, 2, prose, votes=3)
    assert client.calls == 3                      # 显式关：三票照投
