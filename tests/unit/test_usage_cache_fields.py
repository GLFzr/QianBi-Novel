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
