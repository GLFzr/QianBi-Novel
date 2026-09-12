# -*- coding: utf-8 -*-
"""v16 P1 四项修复的生效断言单测（5.1 工单③④ + 5.3 S1b 收窄）

- ① _state_mutate：pipeline_state 单键更新必须保其余键（A1 事故：整文件覆盖抹掉
  genre_preset → 清算 in_session 静默失效——「静默失效类」事故防第三次复发）
- ③ 清算重试同域入会话 + 废轮回滚（回滚后会话栈与本轮调用前逐轮一致）；
  pro 异构（N2 红线）绝不骑会话
- ④ 双通道一致性：_phase_flags（清算模块自查）与 stages.preset_param_layers
  （喂 router 的表）对 canon_audit 相位必须同源同值（含内置 8192 与预设 5000 合流）
- ② 的 payload 断言在 tests/unit/test_llm_payload.py（降级重发显式 disabled）

无真实 API：假客户端/假会话替身 + 真实 presets 管线。
"""
import json
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v16p1_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest  # noqa: E402

import app.core.canon_audit as ca  # noqa: E402
from app.core.canon_audit import audit_chapter  # noqa: E402

VALID = json.dumps({
    "violations": [{"quote": "他推开了西角的铁门", "why": "底册无此门",
                    "canon_ref": "底册无此条", "severity": "硬伤"}],
    "adoptions": [], "ledger_updates": {}, "beat_check": {},
}, ensure_ascii=False)
GARBAGE = "（模型只顾思考，没有输出任何 JSON）"
DEGENERATE = json.dumps({
    "violations": [{"quote": "a", "why": "同一句", "severity": "软伤"},
                   {"quote": "b", "why": "同一句", "severity": "软伤"},
                   {"quote": "c", "why": "同一句", "severity": "软伤"}],
    "adoptions": [], "ledger_updates": {},
}, ensure_ascii=False)

DS = ("https://api.deepseek.com", "deepseek-v4-flash")


class FakeClient:
    """outputs 队列：逐次 chat_stream 弹出（弹尽后重复末项）"""

    def __init__(self, base_url=DS[0], model=DS[1], outputs=None):
        self.base_url, self.model = base_url, model
        self.outputs = list(outputs) if outputs else [VALID]
        self.calls = []

    def chat_stream(self, prompt, temperature=None, phase="", on_chunk=None, **kw):
        self.calls.append(prompt)
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if on_chunk:
            on_chunk(out)
        return out


class FakeSession:
    """outputs 队列：逐次 ask 弹出（弹尽后重复末项）"""

    def __init__(self, client, enabled=True, outputs=None):
        self._client = client
        self.enabled = enabled
        self.outputs = list(outputs) if outputs else [VALID]
        self.turns = 0
        self.asked = []
        self.rollback_log = []

    def ask(self, user_text, *, client=None, phase="", on_chunk=None, **kw):
        self.asked.append((user_text, phase))
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if on_chunk:
            on_chunk(out)
        self.turns += 1
        return out

    def rollback_to(self, n):
        self.rollback_log.append(n)
        self.turns = n

    def turn_count(self):
        return self.turns


def _proj(tmp):
    os.makedirs(os.path.join(tmp, "追踪"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "设定"), exist_ok=True)
    return tmp


class _StubLLM:
    """替身 LLMClient：audit 升 pro 路径的 from_connection 桩"""

    last_instance = None

    @classmethod
    def from_connection(cls, conn, **kw):
        inst = FakeClient(base_url=conn.get("base_url", ""), model=conn.get("model", ""))
        cls.last_instance = inst
        return inst


# ---------- ① _state_mutate 保键 ----------

def test_state_mutate_preserves_other_keys(tmp_path):
    from app.core import state as st
    from scripts.cost_bench import _state_mutate
    proj = str(tmp_path)
    st.save_state(proj, {"genre_preset": "urban_destiny", "stage": st.STAGE_PROSE})
    _state_mutate(proj, stage=st.STAGE_CH_OUTLINE)
    cur = st.load_state(proj)
    assert cur["stage"] == st.STAGE_CH_OUTLINE
    # A1 事故回归钉：单键更新后 genre_preset 必须还在（v15 它被抹掉 → 旗标全灭）
    assert cur["genre_preset"] == "urban_destiny"


def test_state_mutate_then_phase_flags_see_preset(tmp_path):
    """修复①的端到端语义：mutate 写入 genre_preset 后，_phase_flags 必须立刻读到
    预设旗标（v15 里这一环断了，S2 分支零日志静默跳过）。"""
    from app import presets as gp
    from app.core import state as st
    from scripts.cost_bench import _state_mutate
    proj = _proj(str(tmp_path))
    pid = "t_v16_p1_mutate"
    gp.save_preset({"id": pid, "name": "t", "version": 2,
                    "stage_params": {"canon_audit": {"in_session": True}}})
    _state_mutate(proj, genre_preset=pid)
    assert st.load_state(proj)["genre_preset"] == pid
    flags = ca._phase_flags({}, proj)
    assert flags.get("in_session") is True


# ---------- ③ 重试同域骑会话 + 废轮回滚 ----------

def test_retry_rides_session_and_rolls_back_failed_round(tmp_path, monkeypatch):
    """旗标关（等价 A1 抹除场景）但会话可用：重试轮骑会话，废轮回滚后
    turn_count 复位（上下文与首试一致），次轮会话轮采到有效结果。"""
    proj = _proj(str(tmp_path))
    solo = FakeClient(outputs=[VALID])                 # 单发不被动用（全程骑会话）
    sess = FakeSession(solo, outputs=[GARBAGE, VALID])  # 会话轮：废 → 有效
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                        router=None, session=sess)
    assert len(sess.asked) == 2                        # 两轮重试都骑了会话
    body, phase = sess.asked[0]
    assert phase == "canon_audit"
    assert body.startswith("（作用域")                 # SCOPE_LINE 打头（会话轮口径）
    assert sess.rollback_log and sess.rollback_log[0] == 0   # 废轮回滚到调用前
    assert solo.calls == []                            # 没有走独立单发
    assert rep["cascade"]["in_session"] is False       # 不是 S2，是重试通道
    assert rep["violations"][0]["severity"] == "硬伤"  # 最终采到有效结果
    assert rep["failed"] is False


def test_s2_failed_fallback_stays_standalone(tmp_path, monkeypatch):
    """F1 路径多样性不变量：S2 预扫试过并废轮 → 回退轮保持独立单发
    （S1b 的「重试入会话」只覆盖 S2 未启用的场景）。"""
    proj = _proj(str(tmp_path))
    from app import presets as gp
    from app.core import state as st
    pid = "t_v16_p1_s2on"
    gp.save_preset({"id": pid, "name": "t", "version": 2,
                    "stage_params": {"canon_audit": {"in_session": True}}})
    st.save_state(proj, {"genre_preset": pid})
    solo = FakeClient(outputs=[VALID])
    sess = FakeSession(solo, outputs=[DEGENERATE])
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                        router=None, session=sess)
    assert len(sess.asked) == 1                        # 只有 S2 预扫那一轮进会话
    assert len(solo.calls) == 1                        # 回退轮走了独立单发
    assert rep["cascade"]["in_session"] is False
    assert rep["violations"][0]["severity"] == "硬伤"  # 独立单发采到有效结果


def test_retry_with_pro_upgrade_stays_standalone(tmp_path, monkeypatch):
    """N2 红线：会话基座 flash、升级后 client 是 pro（异构）——次轮重试绝不骑会话。"""
    proj = _proj(str(tmp_path))
    solo = FakeClient(outputs=[GARBAGE, GARBAGE])     # flash 两轮全废
    sess = FakeSession(solo, outputs=[DEGENERATE])
    pro = FakeClient(base_url="https://api.deepseek.com", model="deepseek-v4-pro",
                     outputs=[VALID])
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    monkeypatch.setattr(ca, "_strict_conn",
                        lambda cfg: {"base_url": pro.base_url, "api_key": "sk",
                                     "model": pro.model})
    monkeypatch.setattr(ca, "LLMClient", _StubLLM)
    _StubLLM.last_instance = None
    cfg = {"gates": {}, "writing": {},
           "connections": [{"base_url": pro.base_url, "api_key": "sk",
                            "model": pro.model}]}
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", cfg,
                        router=None, session=sess)
    assert len(sess.asked) == 1                       # 只有 flash 首轮骑会话
    assert len(sess.rollback_log) == 1                # 废轮已回滚
    assert _StubLLM.last_instance is not None and pro.calls == []  # 桩接住升级请求
    stub_calls = _StubLLM.last_instance.calls
    assert len(stub_calls) == 1                       # pro 终审走独立单发
    assert rep["violations"][0]["severity"] == "硬伤"


def test_retry_without_session_untouched(tmp_path, monkeypatch):
    """无会话（session=None）：行为与改造前一致——两轮独立单发。"""
    proj = _proj(str(tmp_path))
    solo = FakeClient(outputs=[GARBAGE, VALID])
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False: solo)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", {"gates": {}, "writing": {}},
                        router=None, session=None)
    assert len(solo.calls) == 2
    assert rep["violations"][0]["severity"] == "硬伤"


# ---------- ④ 双通道一致性（防第三次静默失效） ----------

def test_phase_flags_and_router_layers_agree_on_canon_audit(tmp_path):
    """_phase_flags（清算自查）与 preset_param_layers（router 档表）必须同源同值：
    预设 5000 压过内置 8192，两条链合流结果一致；in_session 只在预设链出现时两链同见。"""
    from app import presets as gp
    from app.core import state as st
    from app.core.stages import BUILTIN_PHASE_PARAMS, preset_param_layers
    proj = _proj(str(tmp_path))
    pid = "t_v16_p1_dual"
    gp.save_preset({"id": pid, "name": "t", "version": 2,
                    "stage_params": {"canon_audit": {"in_session": True,
                                                     "max_tokens": 5000}}})
    st.save_state(proj, {"genre_preset": pid})
    flags = ca._phase_flags({}, proj)
    layers = preset_param_layers(proj)["stage_params"]["canon_audit"]
    # 合流结果：预设显式键压过内置（5000 压 8192）；内置只对预设没写的键补缺——
    # 两链必须给出同一份档（最强断言：整档逐键相等）
    assert flags["max_tokens"] == 5000 and layers["max_tokens"] == 5000
    assert flags["in_session"] is True and layers["in_session"] is True
    for k, v in BUILTIN_PHASE_PARAMS["canon_audit"].items():
        if k in ("in_session", "max_tokens"):   # 预设显式键：上面已单独断言压过内置
            continue
        assert flags.get(k) == v and layers.get(k) == v, "内置键 %s 两链不一致" % k
    assert flags == layers


def test_phase_flags_and_router_layers_agree_without_preset(tmp_path):
    """无 canon_audit 预设项：两链都落到内置机械相位表（同源缺省）。"""
    from app import presets as gp
    from app.core import state as st
    from app.core.stages import BUILTIN_PHASE_PARAMS, preset_param_layers
    proj = _proj(str(tmp_path))
    pid = "t_v16_p1_dual2"
    gp.save_preset({"id": pid, "name": "t", "version": 2,
                    "stage_params": {"outline": {"length_budget": 1200}}})
    st.save_state(proj, {"genre_preset": pid})
    flags = ca._phase_flags({}, proj)
    layers = preset_param_layers(proj)["stage_params"]["canon_audit"]
    assert flags == layers == dict(BUILTIN_PHASE_PARAMS["canon_audit"])


def test_phase_flags_default_off_when_state_wiped(tmp_path):
    """事故语义钉：state 无 genre_preset（被整文件覆盖后的形态）→ 旗标缺省关闭。
    修复①保证 bench 不再产出这种 state；此测试钉的是 fail-safe 方向（缺省关）。"""
    proj = _proj(str(tmp_path))
    flags = ca._phase_flags({}, proj)
    assert "in_session" not in flags
    assert flags["max_tokens"] == 8192 and flags["thinking"] == "enabled"
