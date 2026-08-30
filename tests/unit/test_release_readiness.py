# -*- coding: utf-8 -*-
"""商业化封装模块回归（封装计划 T3.x/T4.x）：脱敏 / 遥测 / 更新比较 / 单实例契约"""
from app.secrets import redact_text
from app.telemetry import record, set_enabled
from app.update_check import is_newer


# ---- secrets.redact_text ----

def test_redact_api_key_json():
    t = '{"id": "bailian", "api_key": "sk-verysecret123"}'
    out = redact_text(t)
    assert "verysecret" not in out and "<REDACTED>" in out
    assert '"id": "bailian"' in out   # 无关字段不动


def test_redact_sk_and_bearer():
    out = redact_text("Authorization: Bearer eyJhbGciOiJIUzI1.9x and key=sk-abcdef1234567890")
    assert "eyJhbGciOiJIUzI1" not in out and "abcdef1234567890" not in out


def test_redact_keeps_normal_text():
    t = "第 1 章 草稿完成：2000 字"
    assert redact_text(t) == t


# ---- telemetry（opt-in 默认关）----

def test_telemetry_disabled_by_default_records_nothing(tmp_path, monkeypatch):
    import app.telemetry as tm
    monkeypatch.setattr(tm, "FILE", str(tmp_path / "pending.jsonl"))
    cfg = {"telemetry": {"enabled": False}}
    record(cfg, "app_start", version="0.14.0")
    assert not (tmp_path / "pending.jsonl").exists()


def test_telemetry_enabled_writes_local_jsonl(tmp_path, monkeypatch):
    import app.telemetry as tm
    f = tmp_path / "pending.jsonl"
    monkeypatch.setattr(tm, "FILE", str(f))
    cfg = set_enabled({"telemetry": {"enabled": False}}, True)
    assert cfg["telemetry"]["enabled"] is True
    record(cfg, "chapter_done", version="0.14.0", words=2000)
    text = f.read_text(encoding="utf-8")
    assert "chapter_done" in text and "2000" in text


def test_telemetry_redacts_props(tmp_path, monkeypatch):
    import app.telemetry as tm
    f = tmp_path / "pending.jsonl"
    monkeypatch.setattr(tm, "FILE", str(f))
    cfg = {"telemetry": {"enabled": True}}
    record(cfg, "crash", detail='api_key": "sk-secret12345678"')
    assert "secret12345678" not in f.read_text(encoding="utf-8")


# ---- update_check 版本比较 ----

def test_is_newer_semverish():
    assert is_newer("0.15.0", "0.14.0")
    assert is_newer("0.14", "0.13.9")          # 容忍两段写法
    assert not is_newer("0.14.0", "0.14.0")
    assert not is_newer("0.13", "0.14")
    assert not is_newer("", "0.14")             # 坏清单不误报


# ---- 单实例与崩溃模块可导入且常量稳定 ----

def test_singleinstance_lock_name():
    from app.singleinstance import LOCK_NAME
    assert LOCK_NAME == "QianBiNovel.lock"


def test_crash_dump_global_redacted(tmp_path, monkeypatch):
    import app.crash as cr
    monkeypatch.setattr(cr, "CRASH_DIR", str(tmp_path))
    try:
        raise ValueError('LLM fail api_key": "sk-secret99999999"')
    except ValueError as e:
        path = cr.dump_global(e, "worker-1")
    assert path
    text = open(path, encoding="utf-8").read()
    assert "ValueError" in text and "secret99999999" not in text
    assert "worker-1" in text


def test_save_config_keeps_runtime_key_and_disk_clean(tmp_path, monkeypatch):
    """T3.3 关键回归：落盘脱水不得污染运行时对象（真机 401 事故根因）"""
    import json as _json
    from app import config as cfg_mod
    from app import secrets as secrets_mod
    # 凭据隔离：keyring 指向假服务名，测试绝不触碰真实用户凭据（事故教训 2026-08-29）
    monkeypatch.setattr(secrets_mod, "SERVICE", "QianBiNovel/test-run")
    cfg_file = tmp_path / "config.json"
    raw = cfg_mod.load_config()
    raw["connections"] = [dict(raw["connections"][0])]
    raw["connections"][0]["id"] = "unittest-conn"
    raw["connections"][0]["api_key"] = "sk-test-redact-12345678"
    cfg_file.write_text(_json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(cfg_file))
    cfg = cfg_mod.load_config()
    key_before = cfg["connections"][0]["api_key"]
    assert key_before, "前置：hydrate 后运行时应有 key"
    cfg_mod.save_config(cfg)
    assert cfg["connections"][0]["api_key"] == key_before, "运行时 key 被脱水污染"
    import re
    disk = cfg_file.read_text(encoding="utf-8")
    assert not [k for k in re.findall(r'"api_key": "([^"]*)"', disk) if k], "磁盘配置泄漏明文 key"
