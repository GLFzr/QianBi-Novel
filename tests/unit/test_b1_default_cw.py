# -*- coding: utf-8 -*-
"""B-1/R17：默认共写档——只作用新装与未表态项目，绝不回填既有档位。

钉五条：
① 出厂 config writing.run_mode == "cw"（用户 2026-09-18 裁决）；
② 老用户盘上显式 "auto" 经 load 后原样保留（merge 只补缺失键）；
③ 项目 state 已表态（mode=auto 或 cw）原样尊重；
④ 未表态（state 无 cw.mode）的新项目读出厂默认 = 新项目默认共写；
⑤ 读档位不落任何 state.cw.mode（无静默回填）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import config as cfg_mod  # noqa: E402
from app.core import state as st  # noqa: E402


def test_factory_default_is_cw():
    assert cfg_mod.DEFAULT_CONFIG["writing"]["run_mode"] == "cw", (
        "出厂默认档漂移——B-1 用户裁决：默认共写")


def test_legacy_explicit_auto_survives_load(tmp_path, monkeypatch):
    """R17 核心：老用户盘上显式 auto 升级后原样保留（不许回填成 cw）。"""
    d = tmp_path / "home" / ".qianbi_novel"
    d.mkdir(parents=True)
    cfg = json.loads(json.dumps(cfg_mod.DEFAULT_CONFIG))
    cfg["writing"]["run_mode"] = "auto"
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(d))
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(d / "config.json"))
    monkeypatch.setattr(cfg_mod, "_LEGACY_DIR", str(tmp_path / "no_legacy"))
    (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out = cfg_mod.load_config()
    assert out["writing"]["run_mode"] == "auto", (
        "老用户显式 auto 被静默改成 cw——R17 违规")


def test_project_explicit_mode_respected(tmp_path):
    """项目已表态（auto/cw）原样尊重，配置默认不覆盖表态。"""
    from app.ui.bridge import Bridge
    proj = tmp_path / "book"
    os.makedirs(proj)
    st_file = proj / "pipeline_state.json"
    st_file.write_text(json.dumps({"cw": {"mode": "auto", "stage": "cw_prose"}}),
                       encoding="utf-8")
    b = Bridge()
    b.proj = str(proj)
    b.cfg = {"writing": {"run_mode": "cw"}}
    assert b._get_cw_mode() == "auto", "项目显式 auto 被出厂默认覆盖（R17 违规）"
    st_file.write_text(json.dumps({"cw": {"mode": "cw", "stage": "cw_prose"}}),
                       encoding="utf-8")
    assert b._get_cw_mode() == "cw"


def test_unexpressed_old_project_stays_auto(tmp_path):
    """R17：从未表态的**旧项目**保持升级前实际行为（自动档），不许静默改 cw。"""
    from app.ui.bridge import Bridge
    proj = tmp_path / "book_old_no_mode"
    os.makedirs(proj)
    (proj / "pipeline_state.json").write_text(
        json.dumps({"stage": "prose", "total_chapters": 5}), encoding="utf-8")   # 无 cw.mode
    b = Bridge()
    b.proj = str(proj)
    b.cfg = {"writing": {"run_mode": "cw"}}   # 即便出厂是 cw
    assert b._get_cw_mode() == "auto", (
        "从未表态的旧项目被静默改成 cw——R17 违规（只许新项目吃默认）")


def test_new_project_created_with_factory_cw(tmp_path, monkeypatch):
    """新项目在**创建时点**显式落出厂档位 cw（留盘，之后不再改写）。"""
    from app.ui.bridge import Bridge
    b = Bridge()
    b.cfg = {"writing": {"run_mode": "cw"}, "connections": [], "slots": {}}
    root = tmp_path / "shelf"
    root.mkdir()
    ok = b.newProject(str(root), "默认档测试", "都市", "番茄", 1, "测试立项", "")
    assert ok is not False
    proj = None
    for d in root.iterdir():
        if d.is_dir():
            proj = d
    assert proj is not None
    state = json.loads((proj / "pipeline_state.json").read_text(encoding="utf-8"))
    assert state["cw"]["mode"] == "cw", (
        f"新项目创建未落出厂共写档：{state.get('cw', {}).get('mode')}")


def test_open_project_never_writes_mode(tmp_path):
    """R17 终检：打开项目 + 读档位，state.cw.mode 不得被写。"""
    from app.ui.bridge import Bridge
    proj = tmp_path / "book_old"
    os.makedirs(proj)
    before = json.dumps({"stage": "prose", "total_chapters": 5})
    (proj / "pipeline_state.json").write_text(before, encoding="utf-8")
    b = Bridge()
    b.proj = str(proj)
    b.cfg = {"writing": {"run_mode": "cw"}}
    b._get_cw_mode()
    b._get_cw_stage_key()
    after = (proj / "pipeline_state.json").read_text(encoding="utf-8")
    assert after == before, "仅读档位就改写了 state 文件（R17 违规）"
