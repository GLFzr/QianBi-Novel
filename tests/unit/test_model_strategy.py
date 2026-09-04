# -*- coding: utf-8 -*-
"""模型策略（方案 B）：一键官方全家桶 / 严格审校，连接确保存在、Key 复用、幂等"""
from app import model_strategy as ms


def _cfg():
    return {"connections": [
        {"id": "ds-v4-pro", "name": "DeepSeek 官方", "provider": "deepseek",
         "base_url": "https://api.deepseek.com", "api_key": "sk-official",
         "model": "deepseek-v4-pro"},
        {"id": "custom-x", "name": "旧连接", "provider": "custom",
         "base_url": "https://x.example", "api_key": "k", "model": "m"},
    ], "slots": {"writing": "custom-x", "helper": "custom-x", "review": "custom-x"}}


def test_apply_official_all_rebinds_all_slots():
    cfg = ms.apply_preset(_cfg(), "official_all")
    assert set(cfg["slots"].values()) == {ms.OFFICIAL_FLASH}
    ids = {c["id"] for c in cfg["connections"]}
    assert {ms.OFFICIAL_FLASH, ms.OFFICIAL_PRO} <= ids
    flash = next(c for c in cfg["connections"] if c["id"] == ms.OFFICIAL_FLASH)
    assert flash["model"] == "deepseek-v4-flash"
    assert flash["api_key"] == "sk-official", "官方 Key 应从同账号行复用"


def test_apply_strict_review_upgrades_review_only():
    cfg = ms.apply_preset(_cfg(), "strict_review")
    assert cfg["slots"]["review"] == ms.OFFICIAL_PRO
    assert cfg["slots"]["writing"] == ms.OFFICIAL_FLASH
    assert cfg["slots"]["helper"] == ms.OFFICIAL_FLASH


def test_apply_is_idempotent_and_keeps_user_rows():
    cfg = ms.apply_preset(_cfg(), "official_all")
    once = json_snapshot(cfg)
    cfg = ms.apply_preset(cfg, "official_all")
    assert json_snapshot(cfg) == once
    assert any(c["id"] == "custom-x" for c in cfg["connections"]), "用户自有连接不许动"


def test_key_pulled_from_vault_when_rows_keyless(monkeypatch):
    cfg = _cfg()
    for c in cfg["connections"]:
        c["api_key"] = ""
    monkeypatch.setattr(ms.secrets_mod, "get_secret",
                        lambda cid: "sk-from-vault" if cid == "ds-v4-pro" else "")
    cfg = ms.apply_preset(cfg, "official_all")
    flash = next(c for c in cfg["connections"] if c["id"] == ms.OFFICIAL_FLASH)
    assert flash["api_key"] == "sk-from-vault"


def test_unknown_preset_is_noop():
    cfg = _cfg()
    out = ms.apply_preset(cfg, "不存在")
    assert out["slots"]["writing"] == "custom-x"


def json_snapshot(cfg):
    import json
    return json.dumps({"slots": cfg["slots"],
                       "ids": sorted(c["id"] for c in cfg["connections"])},
                      ensure_ascii=False, sort_keys=True)
