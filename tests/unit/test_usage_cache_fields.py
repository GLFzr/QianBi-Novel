# -*- coding: utf-8 -*-
"""体验轮 P1 可观测性：LLM 用量埋点的缓存命中字段（hit/miss/phase）回归

覆盖四件事：
1. `_record_usage` 读取 DeepSeek 的 prompt_cache_hit_tokens / prompt_cache_miss_tokens
   并随 phase 一起落盘到 usage.jsonl；
2. 假 usage 缺这两个字段（非 DeepSeek 网关）时默认 0，不抛错；
3. `usage.record` 新签名 hit/miss/phase 为可选参数，旧式调用（不传）落 0/空，向后兼容；
4. 内存聚合（_load/_bump/summary）同步累计 hit/miss，且旧格式行（无新列）可读。
"""
import importlib
import json


def _fresh_usage(tmp_path, monkeypatch):
    """重载 app.usage 并把落盘路径指到 tmp_path（避免污染真实 ~/.qianbi_novel）"""
    import app.usage as um
    importlib.reload(um)
    monkeypatch.setattr(um, "FILE", str(tmp_path / "usage.jsonl"))
    return um


def _rows(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def test_record_writes_hit_miss_phase_columns(tmp_path, monkeypatch):
    um = _fresh_usage(tmp_path, monkeypatch)
    um.record({}, "deepseek-v4", "writing", 1000, 200, 1.5, hit=800, miss=200,
              phase="outline")
    (row,) = _rows(tmp_path / "usage.jsonl")
    assert row["in"] == 1000 and row["out"] == 200
    assert row["hit"] == 800
    assert row["miss"] == 200
    assert row["phase"] == "outline"


def test_record_legacy_call_defaults(tmp_path, monkeypatch):
    """旧式调用（不传 hit/miss/phase）落 0/空：jsonl 列仍在，旧消费方不炸"""
    um = _fresh_usage(tmp_path, monkeypatch)
    um.record({}, "m", "s", 10, 5, 0.5)
    (row,) = _rows(tmp_path / "usage.jsonl")
    assert row["hit"] == 0
    assert row["miss"] == 0
    assert row["phase"] == ""


def test_record_usage_reads_deepseek_cache_fields(tmp_path, monkeypatch):
    """_record_usage 从假 usage dict 提取缓存字段并透传 phase"""
    um = _fresh_usage(tmp_path, monkeypatch)
    import app.llm.client as lc
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m", slot="writing")
    usage = {"prompt_tokens": 100, "completion_tokens": 10,
             "prompt_cache_hit_tokens": 64, "prompt_cache_miss_tokens": 36}
    c._record_usage(usage, 1.25, phase="draft")
    (row,) = _rows(tmp_path / "usage.jsonl")
    assert row["model"] == "m" and row["slot"] == "writing"
    assert row["in"] == 100 and row["out"] == 10
    assert row["hit"] == 64 and row["miss"] == 36
    assert row["phase"] == "draft"
    assert c.total_prompt_tokens == 100 and c.total_completion_tokens == 10


def test_record_usage_missing_cache_fields_default_zero(tmp_path, monkeypatch):
    """usage 里没有缓存字段（OpenAI 系网关）→ hit/miss 落 0、phase 落空"""
    um = _fresh_usage(tmp_path, monkeypatch)
    import app.llm.client as lc
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    c._record_usage({"prompt_tokens": 50, "completion_tokens": 5}, 0.5)
    (row,) = _rows(tmp_path / "usage.jsonl")
    assert row["hit"] == 0 and row["miss"] == 0
    assert row["phase"] == ""
    # 空 usage（无 tokens）保持早退，不产生新行
    c._record_usage({}, 0.1)
    assert len(_rows(tmp_path / "usage.jsonl")) == 1


def test_record_usage_falls_back_to_openai_cached_tokens(tmp_path, monkeypatch):
    """中转网关只报 prompt_tokens_details.cached_tokens（无 DS 字段）→
    命中回退该字段，miss = prompt_tokens − 命中（口径与 DS 对齐，
    TokenRhythm 探针实证：713 prompt / cached 512 → hit 512 / miss 201）"""
    um = _fresh_usage(tmp_path, monkeypatch)
    import app.llm.client as lc
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    c._record_usage({"prompt_tokens": 713, "completion_tokens": 45,
                     "prompt_tokens_details": {"cached_tokens": 512}}, 0.8,
                    phase="draft")
    (row,) = _rows(tmp_path / "usage.jsonl")
    assert row["hit"] == 512 and row["miss"] == 201
    assert row["in"] == 713 and row["out"] == 45


def test_record_usage_ds_fields_take_precedence(tmp_path, monkeypatch):
    """DS 字段在时优先用 DS 字段，不做 OpenAI 回退（两个渠道并存不串口径）"""
    um = _fresh_usage(tmp_path, monkeypatch)
    import app.llm.client as lc
    c = lc.LLMClient("http://fake.invalid/v1", "sk", "m")
    c._record_usage({"prompt_tokens": 100, "completion_tokens": 10,
                     "prompt_cache_hit_tokens": 64, "prompt_cache_miss_tokens": 36,
                     "prompt_tokens_details": {"cached_tokens": 128}}, 0.5)
    (row,) = _rows(tmp_path / "usage.jsonl")
    assert row["hit"] == 64 and row["miss"] == 36


def test_summary_aggregates_hit_miss_and_tolerates_legacy_rows(tmp_path, monkeypatch):
    """聚合带 hit/miss；旧格式行（缺新列）按 0 兜底可读"""
    um = _fresh_usage(tmp_path, monkeypatch)
    legacy = {"ts": "2026-01-01 00:00:00", "ymd": "2026-01-01", "model": "old-m",
              "slot": "s", "in": 1000, "out": 100, "latency": 1.0}
    with open(um.FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps(legacy) + "\n")
    um.record({}, "m2", "s2", 100, 10, 0.5, hit=80, miss=20, phase="outline")
    s = um.summary()
    assert s["all"]["in"] == 1100 and s["all"]["out"] == 110
    assert s["all"]["hit"] == 80 and s["all"]["miss"] == 20
    assert s["all"]["by_model"]["m2"]["hit"] == 80
    assert s["all"]["by_model"]["old-m"]["hit"] == 0   # 旧行兜底为 0


def test_opencode_base_sends_session_id():
    """omen-alpha 走 Console Go，缺 x-session-id 直接 400 MissingSessionID（2026-09-08 实测）"""
    from app.llm import client as lc
    h = lc.LLMClient("https://opencode.ai/zen/go/v1", "sk", "omen-alpha",
                     user_id="qianbi-bench-t3")._headers()
    assert h.get("x-session-id") == "qianbi-bench-t3"


def test_session_id_stable_and_user_scoped():
    """会话域要稳定且按跑次分开：按进程随机会把长测缓存域打散，命中直接失真"""
    from app.llm import client as lc
    a = lc.LLMClient("https://opencode.ai/zen/go/v1", "sk", "omen-alpha", user_id="run-x")
    b = lc.LLMClient("https://opencode.ai/zen/go/v1", "sk", "omen-alpha", user_id="run-y")
    assert (a.session_id, b.session_id) == ("run-x", "run-y")
    assert lc.LLMClient("https://opencode.ai/zen/go/v1", "sk", "m").session_id == "qianbi-novel"


def test_other_channels_get_no_extra_header():
    """DS / TokenRhythm 不看这个头——多发一个可能改变它们的路由，故一个字节都不加"""
    from app.llm import client as lc
    for base in ("https://api.deepseek.com/v1", "https://tokenrhythm.studio/v1"):
        h = lc.LLMClient(base, "sk", "deepseek-v4-flash", user_id="qianbi-bench-t1")._headers()
        assert set(h) == {"Content-Type", "Authorization"}, base


def test_usage_row_carries_chapter(tmp_path, monkeypatch):
    """ch：未登记章号落 0（未知），登记后每行带章号；非法值不抛、退回 0"""
    um = _fresh_usage(tmp_path, monkeypatch)
    um.set_chapter(7)
    um.record(None, "m", "s", 100, 10, 0.5, hit=90, miss=10, phase="prose")
    um.set_chapter("8")                       # 字符串章号也要吃得下
    um.record(None, "m", "s", 120, 12, 0.6, phase="review")
    um.set_chapter(None)                      # 未知 → 0，不去猜
    um.record(None, "m", "s", 50, 5, 0.1, phase="outline")
    um.set_chapter("bad")                     # 非法值不抛异常
    um.record(None, "m", "s", 60, 6, 0.2, phase="tracking")
    rows = [json.loads(l) for l in open(um.FILE, encoding="utf-8") if l.strip()]
    assert [r["ch"] for r in rows] == [7, 8, 0, 0]


def test_usage_row_records_actually_sent_params(tmp_path, monkeypatch):
    """sent＝真正随请求下发的参数：剥参与静默丢弃只有这格看得出来；空值不写保旧行形状"""
    um = _fresh_usage(tmp_path, monkeypatch)
    um.record(None, "m", "s", 10, 1, 0.1, phase="prose",
              sent={"thinking": "enabled", "reasoning_effort": "low", "temperature": 0.7})
    um.record(None, "m", "s", 10, 1, 0.1, phase="tracking", sent={})
    rows = [json.loads(l) for l in open(um.FILE, encoding="utf-8") if l.strip()]
    assert rows[0]["sent"] == {"reasoning_effort": "low", "temperature": 0.7, "thinking": "enabled"}
    assert "sent" not in rows[1], "空 sent 不该改变旧行形状"
