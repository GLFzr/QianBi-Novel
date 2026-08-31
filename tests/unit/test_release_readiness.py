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


# ---- Token 用量统计（插件）----

def test_usage_record_and_summary(tmp_path, monkeypatch):
    import importlib
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))
    cfg = {}
    um.record(cfg, "deepseek-v4-flash", "writing", 1000, 2000, 1.5)
    um.record(cfg, "deepseek-v4-flash", "review", 500, 100, 0.5)
    um.record(cfg, "deepseek-v4-pro", "writing", 300, 900, 0.8)
    s = um.summary(cfg)
    assert s["today"]["in"] == 1800 and s["today"]["out"] == 3000
    assert s["today"]["calls"] == 3
    assert s["today"]["by_slot"]["writing"]["in"] == 1300
    assert s["month"] == s["all"]          # 新装环境今日=本月=全部
    # 成本：flash 1/2 元每百万 → (1000+500)/1e6*1 + (2000+100)/1e6*2 + pro 2/8
    assert s["today"]["cost"] == round(0.0015 + 0.0042 + 0.0006 + 0.0072, 2)   # summary 四舍五入到分


def test_usage_persists_across_reload(tmp_path, monkeypatch):
    import importlib
    import app.usage as um
    f = tmp_path / "usage.jsonl"
    monkeypatch.setattr(um, "FILE", str(f))
    um.record({}, "m1", "writing", 100, 200)
    importlib.reload(um)                    # 模拟重启：重载模块重读文件
    monkeypatch.setattr(um, "FILE", str(f))
    s = um.summary({})
    assert s["all"]["calls"] == 1 and s["all"]["in"] == 100


def test_usage_ignores_zero_usage(tmp_path, monkeypatch):
    import importlib
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))
    um.record({}, "m", "writing", 0, 0)
    assert not (tmp_path / "usage.jsonl").exists()   # 零用量不落盘
    assert um.summary({})["all"]["calls"] == 0


def test_usage_cross_day_month_split(tmp_path, monkeypatch):
    """历史 jsonl 含跨月记录：today / month / all 三档切分正确"""
    import importlib
    import json as _json
    import app.usage as um
    importlib.reload(um)
    f = tmp_path / "usage.jsonl"
    rows = [
        {"ymd": "2026-07-31", "model": "m-flash", "slot": "writing", "in": 100, "out": 200},
        {"ymd": "2026-08-27", "model": "m-flash", "slot": "writing", "in": 300, "out": 400},
        {"ymd": "2026-08-28", "model": "m-pro", "slot": "review", "in": 500, "out": 600},
    ]
    f.write_text("\n".join(_json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(um, "FILE", str(f))
    monkeypatch.setattr(um, "_today", lambda: "2026-08-28")
    s = um.summary({})
    assert s["today"]["in"] == 500 and s["today"]["calls"] == 1
    assert s["month"]["in"] == 800 and s["month"]["calls"] == 2   # 08-27+08-28，不含 7 月
    assert s["all"]["in"] == 900 and s["all"]["calls"] == 3


def test_usage_memory_day_rollover(tmp_path, monkeypatch):
    """进程存活期间跨天：内存按天分桶自动切分"""
    import importlib
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))
    day = {"v": "2026-08-27"}
    monkeypatch.setattr(um, "_today", lambda: day["v"])
    um.record({}, "m", "writing", 100, 100)
    day["v"] = "2026-08-28"
    um.record({}, "m", "writing", 50, 50)
    s = um.summary({})
    assert s["today"]["in"] == 50 and s["today"]["calls"] == 1
    assert s["all"]["in"] == 150 and s["all"]["calls"] == 2


def test_client_chat_records_usage(tmp_path, monkeypatch):
    """埋点（chat 路径）：响应 usage → jsonl 落盘，model/slot/in/out 正确"""
    import importlib
    import json as _json
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 80}}

    class _HttpClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            return _Resp()

    import app.llm.client as lc
    monkeypatch.setattr(lc.httpx, "Client", _HttpClient)
    c = lc.LLMClient("http://fake.invalid/v1", "sk-test", "m-flash", slot="writing")
    assert c.chat("hi") == "ok"
    assert c.total_prompt_tokens == 120 and c.total_completion_tokens == 80
    rec = _json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8").strip())
    assert rec["model"] == "m-flash" and rec["slot"] == "writing"
    assert rec["in"] == 120 and rec["out"] == 80


def test_client_stream_records_usage(tmp_path, monkeypatch):
    """埋点（stream 路径）：末 chunk（include_usage）usage → jsonl 落盘"""
    import importlib
    import json as _json
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))

    lines = [
        'data: {"choices": [{"delta": {"content": "hel"}}]}',
        'data: {"choices": [{"delta": {"content": "lo"}}]}',
        'data: {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 20}}',
        'data: [DONE]',
    ]

    class _StreamResp:
        status_code = 200

        def iter_lines(self):
            return iter(lines)

    class _StreamCtx:
        def __enter__(self):
            return _StreamResp()

        def __exit__(self, *a):
            return False

    class _HttpClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, json=None, headers=None):
            return _StreamCtx()

    import app.llm.client as lc
    monkeypatch.setattr(lc.httpx, "Client", _HttpClient)
    c = lc.LLMClient("http://fake.invalid/v1", "sk-test", "m-flash", slot="draft")
    assert c.chat_stream("hi") == "hello"
    rec = _json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8").strip())
    assert rec["slot"] == "draft" and rec["in"] == 40 and rec["out"] == 20
