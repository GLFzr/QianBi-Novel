# -*- coding: utf-8 -*-
"""C23 must 机器复扫闭环（卡7）：改写验收双复扫 + 3-gram 防复用 + 卡6S guard 出口

- 采纳前双复扫：deslop 规则复扫（原有）+ mustscan.violation_keys must 契约指纹复扫
  ——改写稿「新引入」must 违规 = 本轮改写更糟 → 拒绝采纳、回退本轮、烧掉轮次并入
  max_deslop_rounds 熔断。
- 无带 pattern 的 must 规则 → 双复扫整体跳过：行为与 prompt 字节零变化。
- 3-gram 防复用：被拒改写稿相对原稿新增的高频 3-gram（≥3 次）追加进下一轮去味
  prompt 的 tic_blacklist（会话级不落盘）。
- G7 回退对账断言：还原原稿语义下 must_after ⊆ must_before 恒成立。

LLM 用相位队列假件（test_microcycle_steps 同思路）；除假 client 外全真身。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import project as pj
from app.core import state as st
from app.core import stages

_BASE = "草稿内容这是一段完整的测试正文。"          # 16 字/句，零 must 违规
# 含 not-is 阻断句（deslop 必须改写）但零 must 违规（无「!」）的初稿
_DRAFT_BLOCKING = ("## 第1章 开端\n\n" + _BASE * 39
                   + "这不是巧合，而是命运的伏笔。")
_DRAFT_CLEAN = "## 第1章 开端\n\n" + _BASE * 40     # 去味达标稿（无阻断、无 must 违规）
_MUST_RULES_MD = ("# 规则集\n"
                  "- 禁止三连感叹：`!{3,}`｜level：must｜scope：全书\n")

import json


class _PhaseQueueClient:
    """按相位出队的假 client；记录每相位的 prompt 字节（防复用注入的字节断言用）"""

    def __init__(self, responses=None):
        self.responses = {k: list(v) for k, v in (responses or {}).items()}
        self.calls = []
        self.prompts = {}

    def _next(self, phase, prompt=""):
        self.calls.append(phase)
        if phase in ("deslop",):
            self.prompts.setdefault(phase, []).append(prompt)
        q = self.responses.get(phase)
        if not q:
            return ""
        return q.pop(0) if len(q) > 1 else q[0]

    def chat_stream(self, prompt, on_chunk=None, phase="", **kw):
        return self._next(phase, prompt)

    def chat(self, prompt, **kw):
        return self._next("chat", prompt)


class _FakeRouter:
    def __init__(self, client):
        self._c = client

    def client(self, slot):
        return self._c


class _PinCtx:
    """微循环假 ctx；gate_none_key 指定的门回 None（G7 回退路径测试用）"""

    def __init__(self, proj, cfg, client):
        self.proj = proj
        self.cfg = cfg
        self.router = _FakeRouter(client)
        self.logs = []
        self.last_prompt = ""
        self.review_raw = ""
        self.paused = []
        self.timeline = []
        self.gate_none_key = ""

    def gate(self, key, summary="", chapter=0):
        return None if key == self.gate_none_key else ""

    def consume_gate_idea(self):
        return ""

    def checkpoint(self):
        pass

    def step(self, num, key):
        self.timeline.append((num, key))

    def log(self, level, msg):
        self.logs.append(f"{level}|{msg}")

    def stream_chunk(self, text):
        pass

    def stream_stage(self, label):
        pass

    def auto_pause(self, reason):
        self.paused.append(reason)


def _mk_proj(tmp_path, name="复扫书", rules_md=_MUST_RULES_MD):
    proj = str(tmp_path / name)
    for d in ("设定", "大纲", "正文", "追踪"):
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    pj.ensure_tracking_files(proj)
    pj.write_file(os.path.join(proj, "设定", "题材定位.md"), "## 主要角色表\n- 陈青山：凡人少年\n")
    pj.write_file(pj.get_outline_path(proj, 1), "### 开端\n- 核心事件：少年拾到玉简")
    if rules_md is not None:
        pj.write_file(os.path.join(proj, pj.REGEX_PATH), rules_md)
    return proj


def _cfg(target=600, **gates_extra):
    gates = {"review_enabled": False, "deslop_max_rounds": 2, "word_enrich_rounds": 1}
    gates.update(gates_extra)
    return {"gates": gates,
            "writing": {"chapter_word_target": target},
            "llm": {"max_retries": 0}}


def _events(proj):
    path = os.path.join(proj, "追踪", "session_events.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


# ---------- 1. 改写稿引入 forbid → 回退 + 轮次递增 + guard 出口计数 ----------

def test_rewrite_not_adopted_on_new_must_breach(tmp_path):
    proj = _mk_proj(tmp_path)
    bad_rewrite = _DRAFT_BLOCKING + "\n\n他大喊!!!声音在巷子里回荡。"   # 新引入 `!{3,}` 命中
    client = _PhaseQueueClient({"prose": [_DRAFT_BLOCKING], "deslop": [bad_rewrite]})
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    # 两轮改写稿都被复扫拒绝（假件对 deslop 恒回同一坏稿），轮次全部烧进熔断
    assert client.calls.count("deslop") == 2, f"两轮都应拒绝后重试：{client.calls}"
    assert any("must 新增违规" in lg for lg in ctx.logs), "复扫日志必须含「must 新增违规」"
    assert any(lg.startswith("warn|") and "拒绝采纳" in lg for lg in ctx.logs)
    # 改写稿被回退：定稿正文保持改写前原稿（无「!!!」）
    chapters = pj.list_chapters(proj)
    final = pj.read_file(chapters[0][2])
    assert "!!!" not in final and "这不是巧合" in final, "定稿必须是改写前原稿"
    # 阻断未消 → resolve_failed（needs_fix），状态不被误标 pass
    assert record.get("status") == "needs_fix" and record.get("deslop_blocking") == 1
    # 卡6S guard 出口：累计新增 must 违规数（2 轮 × 1 条）与字数保持率随章落盘
    guard = (record.get("metrics") or {}).get("guard") or {}
    assert guard.get("new_must_violations") == 2, f"guard 出口计数漂移：{guard}"
    assert guard.get("chars_kept_ratio") == 1.0
    # trim_over 式事件账
    evs = [e for e in _events(proj) if e.get("event") == "rewrite_retry"]
    assert len(evs) == 2 and evs[0]["new_must"] == 1


# ---------- 2. 改写稿不新增 must 违规 → 照常采纳（复扫不误伤） ----------

def test_rewrite_adopted_when_no_new_must_breach(tmp_path):
    proj = _mk_proj(tmp_path)
    client = _PhaseQueueClient({"prose": [_DRAFT_BLOCKING], "deslop": [_DRAFT_CLEAN]})
    ctx = _PinCtx(proj, _cfg(), client)
    record = stages.chapter_microcycle(ctx, 1)

    assert client.calls.count("deslop") == 1
    assert not any("must 新增违规" in lg for lg in ctx.logs)
    assert any("去味完成，复扫通过" in lg for lg in ctx.logs)
    assert record.get("status") == "pass"
    chapters = pj.list_chapters(proj)
    assert "这不是巧合" not in pj.read_file(chapters[0][2]), "达标改写稿必须被采纳"
    assert ((record.get("metrics") or {}).get("guard") or {}).get("new_must_violations") == 0


# ---------- 3. 无带 pattern 的 must 规则 → 双复扫跳过，行为零变化 ----------

def test_no_must_rules_zero_overhead(tmp_path):
    for name, rules in [("无规则书", None),
                        ("自然语规则书", "# 规则集\n- 规则：改命必须索回代价｜level：must\n")]:
        proj = _mk_proj(tmp_path, name, rules_md=rules)
        client = _PhaseQueueClient({"prose": [_DRAFT_BLOCKING], "deslop": [_DRAFT_CLEAN]})
        ctx = _PinCtx(proj, _cfg(), client)
        record = stages.chapter_microcycle(ctx, 1)

        assert client.calls.count("deslop") == 1, name
        assert not any("must 新增违规" in lg for lg in ctx.logs), name
        assert record.get("status") == "pass", name
        # C23 对无 pattern 规则的书零新增 prompt 字节（防复用行只在拒绝后出现）
        dp = client.prompts.get("deslop", [""])[0]
        assert "改写防复用" not in dp, name


# ---------- 4. 3-gram 防复用：被拒稿的高频新片段进下一轮 prompt ----------

def test_trigram_blacklist_fed_to_next_round(tmp_path):
    proj = _mk_proj(tmp_path)
    tic = "那道身影"
    bad_rewrite = (_DRAFT_BLOCKING + " " + f"他看见{tic}。{tic}停在门口。{tic}转身走了。"
                   + "!!!")   # 高频新 3-gram + must 违规，双料被拒
    client = _PhaseQueueClient({"prose": [_DRAFT_BLOCKING], "deslop": [bad_rewrite]})
    ctx = _PinCtx(proj, _cfg(), client)
    stages.chapter_microcycle(ctx, 1)

    dps = client.prompts.get("deslop", [])
    assert len(dps) == 2
    assert "改写防复用" not in dps[0], "首轮 prompt 不带防复用行（尚无被拒稿）"
    assert "改写防复用" in dps[1], "被拒稿的新增高频 3-gram 必须进下一轮 tic_blacklist"
    assert "那道身" in dps[1] and "道身影" in dps[1], "3-gram 粒度入黑名单"


# ---------- 5. _high_freq_new_trigrams 直证 ----------

def test_high_freq_new_trigrams_helper():
    original = "他推门进去。屋里很暗，桌上有一盏灯。"
    rewritten = ("他看见那道身影。那道身影停在门口。那道身影转身走了。"
                 "屋里很暗，桌上有一盏灯。")
    out = stages._high_freq_new_trigrams(original, rewritten, min_count=3)
    assert any("那道" in g for g in out), out
    # 复用原稿已有片段不算新增（净增口径）
    assert stages._high_freq_new_trigrams(original, original + "那道身影。", min_count=3) == []
    assert stages._high_freq_new_trigrams(original, original, min_count=3) == []


# ---------- 6. G7 回退对账断言：还原原稿后 must 子集关系恒成立 ----------

def test_g7_rollback_reconciliation_ok(tmp_path):
    proj = _mk_proj(tmp_path)
    client = _PhaseQueueClient({"prose": [_DRAFT_BLOCKING], "deslop": [_DRAFT_CLEAN]})
    ctx = _PinCtx(proj, _cfg(), client)
    ctx.gate_none_key = "G7"   # 仅 G7 门回 None → 走回退还原分支
    record = stages.chapter_microcycle(ctx, 1)

    assert any("G7 回退" in lg for lg in ctx.logs)
    assert not any("G7 对账异常" in lg for lg in ctx.logs), "还原原稿后对账必须恒过"
    chapters = pj.list_chapters(proj)
    final = pj.read_file(chapters[0][2])
    assert "这不是巧合" in final and "!!!" not in final, "G7 回退后定稿=去味前原稿"
    assert record.get("status") == "pass", "人工裁决保留原稿 = 本步通过"
    assert not st.is_chapter_need_human(st.load_state(proj), 1)
