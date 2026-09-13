# -*- coding: utf-8 -*-
"""A14 Pro 总开关（用户裁决 2026-09-13）生效断言单测

裁决：gates.audit_strict_tier 开=允许 Pro 自动升级；关=**绝对零 Pro**——
连接清单里躺着 pro 连接也不许被扫中（清算全量兜底 + flagged 终审两条
自动路径全部留在 flash）。本文件钉死「关态零 Pro」与「开态才可达」。

无真实 API：假客户端替身 + monkeypatch。
"""
import json
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_test_v17_strict_")
os.environ["USERPROFILE"] = _FH
os.environ["HOME"] = _FH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest  # noqa: E402

import app.core.canon_audit as ca  # noqa: E402
from app.core.canon_audit import _strict_conn, audit_chapter  # noqa: E402

VALID = json.dumps({
    "violations": [], "adoptions": [], "ledger_updates": {}, "beat_check": {},
}, ensure_ascii=False)
HARD_HIT = json.dumps({
    "violations": [{"quote": "他推开了西角的铁门", "why": "底册无此门",
                    "canon_ref": "底册无此条", "severity": "硬伤"}],
    "adoptions": [], "ledger_updates": {}, "beat_check": {},
}, ensure_ascii=False)
GARBAGE = "（只思考，无 JSON）"

PRO_CONN = {"id": "t-pro", "name": "严格档", "provider": "custom",
            "base_url": "https://api.deepseek.com", "api_key": "sk",
            "model": "deepseek-v4-pro"}
FLASH_CONN = {"id": "t-flash", "name": "flash", "provider": "custom",
              "base_url": "https://api.deepseek.com", "api_key": "sk",
              "model": "deepseek-v4-flash"}


class FakeClient:
    def __init__(self, base_url="", model="", outputs=None):
        self.base_url, self.model = base_url, model
        self.outputs = list(outputs) if outputs else [VALID]
        self.calls = []

    def chat_stream(self, prompt, temperature=None, phase="", on_chunk=None, **kw):
        self.calls.append((phase, prompt))
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if on_chunk:
            on_chunk(out)
        return out


class _StubLLM:
    """替身 LLMClient：audit 内部 from_connection（pro 升级/终审）的桩"""

    instances = []

    @classmethod
    def from_connection(cls, conn, **kw):
        inst = FakeClient(base_url=conn.get("base_url", ""), model=conn.get("model", ""))
        cls.instances.append(inst)
        return inst


@pytest.fixture(autouse=True)
def _reset_stub():
    _StubLLM.instances = []


def test_switch_off_returns_empty_even_with_pro_connection():
    """关态零 Pro 铁律：cfg 里躺着 pro 连接，_strict_conn 也必须返回空。"""
    cfg = {"gates": {}, "connections": [FLASH_CONN, PRO_CONN]}
    assert _strict_conn(cfg) == {}
    cfg["gates"] = {"audit_strict_tier": False}
    assert _strict_conn(cfg) == {}


def test_switch_on_allows_pro_and_suffix_match():
    cfg = {"gates": {"audit_strict_tier": True}, "connections": [FLASH_CONN, PRO_CONN]}
    assert _strict_conn(cfg).get("model", "").endswith("pro")
    # 开着但没有 pro 连接：优雅回空（不炸）
    cfg2 = {"gates": {"audit_strict_tier": True}, "connections": [FLASH_CONN]}
    assert _strict_conn(cfg2) == {}


def test_bench_mk_cfg_wires_switch_to_pro_mount():
    from scripts.cost_bench import _mk_cfg
    flash = {"key": "sk", "base": "https://api.deepseek.com", "model": "deepseek-flash"}
    assert _mk_cfg(flash)["gates"]["audit_strict_tier"] is False     # 缺省零 Pro
    pro = {"key": "sk", "base": "https://api.deepseek.com", "model": "deepseek-v4-pro"}
    assert _mk_cfg(flash, pro=pro)["gates"]["audit_strict_tier"] is True


def _proj(tmp):
    os.makedirs(os.path.join(tmp, "追踪"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "设定"), exist_ok=True)
    return tmp


def _audit(proj, cfg, solo_outputs, monkeypatch):
    """跑 audit_chapter：预扫客户端 = flash 假客户端（outputs 按序），pro 走桩。
    LLMClient 桩经 monkeypatch 替换（用例结束自动还原，不跨测试泄漏）。"""
    solo = FakeClient(model="deepseek-v4-flash", outputs=solo_outputs)
    monkeypatch.setattr(ca, "LLMClient", _StubLLM)
    rep = audit_chapter(proj, 1, "他推开了西角的铁门，门后有风。", cfg,
                        router=None, session=None)
    return rep, solo


def test_switch_off_never_touches_pro_on_fallback(tmp_path, monkeypatch):
    """关态 + 预扫两轮全废 + cfg 带 pro 连接：升级被跳过，全部调用留在 flash。"""
    proj = _proj(str(tmp_path))
    cfg = {"gates": {}, "writing": {}, "connections": [FLASH_CONN, PRO_CONN]}
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False:
                        FakeClient(model="deepseek-v4-flash", outputs=[GARBAGE, GARBAGE]))
    rep, solo = _audit(proj, cfg, [GARBAGE, GARBAGE], monkeypatch)
    assert _StubLLM.instances == []            # 零 pro 客户端被构造
    assert rep["failed"] is True               # 两轮全废照实报失败（不冒充干净）
    assert all(ph == "canon_audit" for ph, _p in solo.calls)


def test_switch_on_upgrades_to_pro_on_fallback(tmp_path, monkeypatch):
    """开态 + 同场景：第二轮升级 pro 兜底，桩被构造且模型是 pro。"""
    proj = _proj(str(tmp_path))
    cfg = {"gates": {"audit_strict_tier": True}, "writing": {},
           "connections": [FLASH_CONN, PRO_CONN]}
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False:
                        FakeClient(model="deepseek-v4-flash", outputs=[GARBAGE, GARBAGE]))
    rep, _solo = _audit(proj, cfg, [GARBAGE, GARBAGE], monkeypatch)
    assert len(_StubLLM.instances) == 1 and _StubLLM.instances[0].model.endswith("pro")
    assert rep["failed"] is False              # pro 兜底轮采到有效结果


def test_switch_off_skips_flagged_review(tmp_path, monkeypatch):
    """关态 + 预扫报硬伤：flagged 终审不发生（采信预扫），零 pro 客户端。"""
    proj = _proj(str(tmp_path))
    cfg = {"gates": {}, "writing": {}, "connections": [FLASH_CONN, PRO_CONN]}
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False:
                        FakeClient(model="deepseek-v4-flash", outputs=[HARD_HIT]))
    rep, _solo = _audit(proj, cfg, [HARD_HIT], monkeypatch)
    assert _StubLLM.instances == []            # pro 终审没有被构造
    assert rep["cascade"]["pro_review"] is False
    assert rep["violations"] and rep["violations"][0]["severity"] == "硬伤"  # 采信预扫


def test_switch_on_runs_flagged_review(tmp_path, monkeypatch):
    """开态 + 同场景：pro flagged 终审发生（cascade.pro_review=True）。"""
    proj = _proj(str(tmp_path))
    cfg = {"gates": {"audit_strict_tier": True}, "writing": {},
           "connections": [FLASH_CONN, PRO_CONN]}
    monkeypatch.setattr(ca, "_client_for", lambda cfg, router=None, strict=False:
                        FakeClient(model="deepseek-v4-flash", outputs=[HARD_HIT]))
    rep, _solo = _audit(proj, cfg, [HARD_HIT], monkeypatch)
    assert len(_StubLLM.instances) == 1 and _StubLLM.instances[0].model.endswith("pro")
    assert rep["cascade"]["pro_review"] is True


def test_flag_absent_is_off_when_no_gates_key():
    """cfg 连 gates 键都没有（老工程/最小配置）：缺省=关=零 Pro。"""
    assert _strict_conn({"connections": [PRO_CONN]}) == {}
