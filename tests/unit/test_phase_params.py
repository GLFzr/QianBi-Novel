# -*- coding: utf-8 -*-
"""体验轮 B1'：内置机械相位表——机械相位关思考，genre 显式配置优先"""
from app.core import stages


def test_builtin_table_contents():
    assert stages.BUILTIN_PHASE_PARAMS["tracking"]["thinking"] == "disabled"
    assert stages.BUILTIN_PHASE_PARAMS["deslop"]["thinking"] == "disabled"
    assert stages.BUILTIN_PHASE_PARAMS["canon_audit"]["thinking"] == "enabled"
    # v0.19 级联：预扫 low（干净采信/有硬伤升 pro 复核），pro 终审显式 high 由级联传
    assert stages.BUILTIN_PHASE_PARAMS["canon_audit"]["reasoning_effort"] == "low"


def test_builtin_merges_without_overriding_genre(tmp_path, monkeypatch):
    """genre 显式配置的键优先；内置表只补缺（键级 setdefault）"""
    import json
    d = tmp_path / "presets"
    d.mkdir()
    pf = d / "p1.json"
    pf.write_text(json.dumps({"id": "p1", "version": 2,
                              "stage_params": {"prose": {"temperature": 0.9},
                                               "tracking": {"thinking": "enabled"}}},
                             ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(stages.genre_presets, "user_dir", lambda: str(d))
    monkeypatch.setattr(stages, "_preset_id", lambda proj: "p1" if proj else "")
    layers = stages.preset_param_layers("书")
    sp = layers["stage_params"]
    assert sp["prose"] == {"temperature": 0.9}
    assert sp["tracking"]["thinking"] == "enabled", "genre 显式配置优先"
    assert sp["tracking"].get("max_tokens") == 8192, "genre 未设的键由内置补缺"
    assert "deslop" in sp, "genre 未配置的机械相位由内置表兜底"


def test_builtin_applies_to_empty_preset():
    layers = stages.preset_param_layers("")
    for ph, kv in stages.BUILTIN_PHASE_PARAMS.items():
        assert layers["stage_params"].get(ph) == kv
