# -*- coding: utf-8 -*-
"""0.20.4 Q2-c 回归：去味卡片制（卡级三查 / 返工→剔除→留痕 / 好卡照常采纳）。"""
import os
import sys

sys.path.insert(0, os.getcwd())

from app.core import stages


class _F:
    level = "blocking"
    message = "AI 句式"

    def __init__(self, start, tic="不是风声"):
        self.start = start
        self.text = tic


def _env(tmp_path, replies):
    """replies: list——第 n 次 ask 返回第 n 条（首轮卡稿/返工轮）。"""
    import app.core.stages as st_mod

    class _Session:
        enabled = True

        def __init__(self):
            self.turns = 2
            self.committed = None
            self.rolled_back = 0
            self.asks = 0

        def turn_count(self):
            return self.turns

        def ask(self, prompt, **kw):
            r = replies[min(self.asks, len(replies) - 1)]
            self.asks += 1
            return kw["postprocess"](r) if kw.get("postprocess") else r

        def commit_turn(self, u, a):
            self.committed = (u, a)
            self.turns += 1

        def rollback_to(self, n):
            self.rolled_back += 1

    class _Client:
        model = "fake"

        def chat(self, *a, **k):
            return ""

    class _Router:
        def client(self, slot):
            return _Client()

    class _Ctx:
        proj = str(tmp_path)
        cfg = {"writing": {}}
        router = _Router()
        last_prompt = ""
        _rewrite_used = 0
        _rewrite_budget_logged = False

        def log(self, *a):
            pass

        def stream_chunk(self, t):
            pass

        def stream_reasoning(self, t):
            pass

        def stream_stage(self, label):
            pass

    return _Ctx(), _Session()


PROSE = ("# 第1章\n"
         "第一段交代地点与天气，值班员在登记簿上写字。\n"
         "第二段，不是风声，而是哭声，敲响了铁皮门。\n"
         "第三段写陈默把钢笔放回窗口，转身离开。")


def test_card_violations_three_checks():
    para_map = {2: [_F(PROSE.index("不是风声"))]}
    para_text = {1: "第一段交代地点与天气，值班员在登记簿上写字。",
                 2: "第二段，不是风声，而是哭声，敲响了铁皮门。",
                 3: "第三段写陈默把钢笔放回窗口，转身离开。"}
    # ① 违规词未消失
    v = stages._card_violations({"para": 2, "text": "第二段，不是风声，而是别的声音，很长很长。"},
                                para_map, para_text)
    assert any("违规词未消失" in r for r in v)
    # ② 防搬运：新段整句搬运第一段（≥16 字窗口命中）
    v2 = stages._card_violations(
        {"para": 2, "text": "第二段，风声停了。第一段交代地点与天气，值班员在登记簿上写字。"},
        para_map, para_text)
    assert any("搬运" in r for r in v2)
    # ③ 段长越带
    v3 = stages._card_violations({"para": 2, "text": "风声。"}, para_map, para_text)
    assert any("段长越带" in r for r in v3)
    # 好卡
    assert stages._card_violations(
        {"para": 2, "text": "第二段，风声里混进了断续的哭声，铁皮门被敲了两下。"},
        para_map, para_text) == []


def test_card_bad_then_rework_success(tmp_path):
    """坏卡 → 返工一次成功 → 采纳返工稿（card_reworked 事件）。"""
    ctx, sess = _env(tmp_path, [
        "⟦P03⟧ 第二段，不是风声，而是哭声，吵个不停吵个不停吵个不停。",  # 首轮：违规词未消失
        "⟦P03⟧ 第二段，风声里混进了断续的哭声，铁皮门被敲了两下。",      # 返工：合格
    ])
    off = PROSE.index("不是风声")
    merged = stages._deslop_pinned_rewrite(ctx, sess, PROSE, [_F(off)], [], 1)
    assert "混进了断续的哭声" in merged and "不是风声" not in merged
    assert sess.rolled_back == 0 and sess.committed is not None
    assert sess.asks == 2   # 首轮 + 返工轮


def test_card_drop_keeps_original_para(tmp_path):
    """坏卡返工仍坏 → 剔除该卡：原段逐字保留，其余不动，合并仍发生（若有好卡）。"""
    ctx, sess = _env(tmp_path, [
        "⟦P03⟧ x",   # 首轮坏
        "⟦P03⟧ y",   # 返工仍坏
    ])
    off = PROSE.index("不是风声")
    out = stages._deslop_pinned_rewrite(ctx, sess, PROSE, [_F(off)], [], 1)
    assert out == ""   # 唯一卡被剔除 → 无合并 → 空串回退整章路径
    assert sess.rolled_back == 1
