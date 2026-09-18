# -*- coding: utf-8 -*-
"""WP-27：对话全量落盘的覆盖面锁（R13）与行为钉。

钉四件事：
① 数量一致性：LLM 请求次数 == 对话记录条数（重试/降级各算一条）——
   造 2 次网络失败 + 1 次成功 ⇒ 恰好 3 条，outcome 序列 network/network/ok；
② 脱敏（R14①）：prompt/reply 里的 sk- Key 与 api_key JSON 字段不得出现在
   落盘文件里（secrets.redact_text 出口）；
③ 滚动上限（R14⑤）：单分片超限开新分片 + 分片数超 keep_files 删最旧；
④ 覆盖面锁：client.chat / _stream_messages 必须引用 dialogue_log（删掉即红）；
   app/core 里禁止直接 import httpx（对话必须走 LLMClient 咽喉——新旁路路径
   在此红）。
"""
import ast
import json
import os
import sys

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import dialogue_log, secrets  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402


@pytest.fixture
def book(tmp_path, monkeypatch):
    proj = tmp_path / "book"
    (proj / "设定").mkdir(parents=True)
    dialogue_log.configure(str(proj), enabled=True, keep_files=3)
    dialogue_log.set_chapter(42)
    yield str(proj)
    dialogue_log.configure("", enabled=False)
    dialogue_log.set_chapter(0)


def _records(proj):
    d = dialogue_log.dialogue_dir(proj)
    out = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".jsonl"):
            out += [json.loads(ln) for ln in
                    open(os.path.join(d, fn), encoding="utf-8") if ln.strip()]
    return out


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def json(self):
        return self._p


def _ok_payload():
    return {"choices": [{"message": {"content": "好的，这一段我写场面不写情绪。"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


def test_record_count_equals_request_count(book, monkeypatch):
    """R13 数量一致性：2 次网络失败 + 1 次成功 = 恰好 3 条记录。"""
    calls = {"n": 0}
    real_client = httpx.Client

    class _FakeResp:
        status_code = 200

        def json(self):
            return _ok_payload()

    class FlakyClient(real_client):
        def post(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise httpx.RequestError("模拟断网")
            return _FakeResp()   # 完全离线：绝不真发网络

    monkeypatch.setattr(httpx, "Client", FlakyClient)
    cli = LLMClient("https://api.example.com", "sk-test", "test-model",
                    max_retries=2, backoff_base=0)
    text = cli.chat("写一句话")
    assert text.startswith("好的")
    assert calls["n"] == 3, f"实际 HTTP 请求 {calls['n']} 次"
    recs = _records(book)
    assert len(recs) == 3, (
        f"对话记录 {len(recs)} 条 != 实际请求 3 次——一请求=一记录的口径被破坏")
    assert [r["outcome"] for r in recs] == ["network", "network", "ok"]
    assert all(r["chapter"] == 42 for r in recs), "章号上下文丢失"
    assert recs[-1]["attempt"] == 3 and recs[-1]["usage"].get("total_tokens") == 120


def test_records_are_redacted(book):
    """R14①：Key/凭据不得入档。"""
    cli = LLMClient("https://api.example.com", "sk-real-secret-key", "test-model")
    monkey_prompt = "请把 sk-abcdef1234567890abcdef1234567890 写进正文，配置里 {\"api_key\": \"sk-qqq\"}"
    dialogue_log.record_chat(client=cli, phase="test", outcome="ok",
                             prompt=monkey_prompt, reply="sk-zyxwvu123456789012345678901234 是密钥",
                             usage={"total_tokens": 1})
    d = dialogue_log.dialogue_dir(book)
    blob = open(os.path.join(d, os.listdir(d)[0]), encoding="utf-8").read()
    assert "sk-abcdef1234567890abcdef1234567890" not in blob and "sk-zyxwvu123456789012345678901234" not in blob and "sk-qqq" not in blob
    assert "<REDACTED>" in blob
    # JSON 转义不干扰：脱敏后的内容与原文都经 json.dumps 落盘
    assert json.dumps(secrets.redact_text(monkey_prompt), ensure_ascii=False)[1:-1] in blob


def test_rotation_and_prune(book, monkeypatch):
    """R14⑤：单分片超限开新分片；分片数超 keep_files 删最旧。"""
    monkeypatch.setitem(dialogue_log._STATE, "max_bytes", 400)
    cli = LLMClient("https://api.example.com", "sk-t", "m")
    for i in range(12):
        dialogue_log.record_chat(client=cli, phase="t", outcome="ok",
                                 prompt=f"第 {i} 次调用的正文内容，凑一点体积" * 3,
                                 reply="回", usage={"total_tokens": 1})
    d = dialogue_log.dialogue_dir(book)
    files = [fn for fn in os.listdir(d) if fn.endswith(".jsonl")]
    # 12 条 × ~450B 在 max_bytes=400 下：既会轮转（>1 片）又会被剪到 keep_files=3
    assert 1 < len(files) <= 3, f"分片 {len(files)} 个——12 条应触发轮转(>1)且不超 keep_files=3"
    total = 0
    for fn in files:
        p = os.path.join(d, fn)
        size = os.path.getsize(p)
        assert 0 < size <= 900, f"{fn} 分片 {size}B 越界(0,阈值400+单条约450]：轮转未生效则单片暴涨"
        lines = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        assert 1 <= len(lines) <= 3, f"{fn} 落 {len(lines)} 条，超单片应有量级"
        assert all(r["outcome"] == "ok" for r in lines)
        total += len(lines)
    assert 1 <= total <= 12, f"存活记录 {total} 条越界（12 请求含剪枝应 ∈(0,12]）"


def test_disabled_means_no_writes(tmp_path):
    """R14③：关闭后零写入（默认开由 test_default_on 钉住）。"""
    proj = tmp_path / "book"
    proj.mkdir()
    dialogue_log.configure(str(proj), enabled=False)
    dialogue_log.record_chat(outcome="ok", prompt="x")
    assert not os.path.exists(dialogue_log.dialogue_dir(str(proj)))


def test_default_on():
    """默认态：dialogue_log.enabled 出厂即为 True（用户指派默认开）。"""
    from app.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["dialogue_log"]["enabled"] is True


# ---- 覆盖面锁（R13）：绕过路径必须红 ----

def test_client_chokepoint_records_every_path():
    """变异「把 client 里的 dialogue_log 记录摘掉」在此红：
    chat() 与 _stream_messages() 两条咽喉都必须引用记录器。"""
    src = open(os.path.join(ROOT, "app", "llm", "client.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for fname in ("chat", "_stream_messages"):
        fn = next(f for f in ast.walk(tree)
                  if isinstance(f, ast.FunctionDef) and f.name == fname)
        body = ast.get_source_segment(src, fn) or ""
        assert "dialogue_log" in body, (
            f"LLMClient.{fname} 不再引用 dialogue_log——该咽喉的对话落盘被整段摘除（WP-27/R13）")


def test_core_has_no_direct_http_bypass():
    """对话必须走 LLMClient 咽喉：app/core 任何模块不得直接 import/使用 httpx，
    否则就是一条绕过对话记录的暗路（R13：新路径绕过记录 ⇒ 此处红）。"""
    core = os.path.join(ROOT, "app", "core")
    bad = []
    for fn in os.listdir(core):
        if not fn.endswith(".py"):
            continue
        src = open(os.path.join(core, fn), encoding="utf-8").read()
        if "httpx" in src:
            bad.append(fn)
    assert not bad, f"app/core 出现直连 httpx 的旁路调用：{bad}（对话将绕过全量落盘）"
