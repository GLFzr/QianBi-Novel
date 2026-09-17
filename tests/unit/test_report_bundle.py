# -*- coding: utf-8 -*-
"""WP-28：报障包测试——最要紧的一条是「假 Key 塞进配置后不得出现在包里」。

覆盖：包内文件清单齐全（版本/配置摘要/对话/日志）；Key 与家目录路径脱敏；
体积护栏（日志尾部截断、对话分片限量）。
"""
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app import dialogue_log, report_bundle  # noqa: E402

FAKE_KEY = "sk-fake-key-1234567890abcdef"


def _make_world(tmp_path, monkeypatch):
    proj = tmp_path / "book"
    (proj / "设定").mkdir(parents=True)
    logs = tmp_path / "logs"
    logs.mkdir()
    # 程序日志：塞一份含「看起来像机器路径」的内容
    (logs / "qianbi.log").write_text(
        "2026-09-17 INFO LLM ok model=test\n"
        f"2026-09-17 WARNING 工作目录 {os.path.expanduser('~')}\\\\book\n",
        encoding="utf-8")
    # 对话记录：一条含假 Key 的调用
    dialogue_log.configure(str(proj), enabled=True, keep_files=5)
    from app.llm.client import LLMClient
    cli = LLMClient("https://api.example.com", FAKE_KEY, "test-model")
    dialogue_log.record_chat(client=cli, phase="draft", outcome="ok",
                             prompt="写一章", reply="好的。", usage={"total_tokens": 9})
    cfg = {"slots": {"writing": "ds-official-flash"},
           "connections": [{"name": "测试连接", "provider": "deepseek",
                            "api_key": FAKE_KEY, "base_url": "https://api.example.com",
                            "model": "deepseek-v4-flash"}],
           "dialogue_log": {"enabled": True, "keep_files": 40},
           "gates": {"review_max_rounds": 3}}
    return str(proj), str(logs), cfg


def test_bundle_contents_and_fake_key_never_leaks(tmp_path, monkeypatch):
    proj, logs, cfg = _make_world(tmp_path, monkeypatch)
    out_dir = tmp_path / "out"
    path = report_bundle.create_bundle(proj, str(out_dir), cfg, logs,
                                       keep_dialogue=5, max_log_bytes=1024)
    assert os.path.isfile(path) and path.endswith(".zip")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        blob = "".join(z.read(n).decode("utf-8", "replace") for n in names)
    # 清单齐全：版本 / 配置摘要 / 对话 / 日志
    assert any(n.startswith("版本") for n in names), f"缺版本文件：{names}"
    assert any("配置摘要" in n for n in names), f"缺配置摘要：{names}"
    assert any(n.startswith("对话记录/") and n.endswith(".jsonl") for n in names), f"缺对话：{names}"
    assert any(n.startswith("日志/") for n in names), f"缺日志：{names}"
    # 最要紧的一条：假 Key 不得出现在包里的任何位置
    assert FAKE_KEY not in blob, "假 Key 泄漏进报障包——脱敏出口被绕过（WP-28 核心）"
    assert "sk-fake-key" not in blob
    # 家目录路径脱敏（R14：机器路径不入包）
    assert os.path.expanduser("~") not in blob


def test_bundle_size_guards(tmp_path, monkeypatch):
    """体积护栏：日志只取尾部（max_log_bytes），对话只取最近 keep_dialogue 个分片"""
    proj, logs, cfg = _make_world(tmp_path, monkeypatch)
    # 造 6 个对话分片（> keep_dialogue=2）与大日志
    dialogue_log.configure(proj, enabled=True, keep_files=20)
    dialogue_log._STATE["max_bytes"] = 1   # 强制每次新分片
    for i in range(6):
        dialogue_log.record_chat(outcome="ok", prompt=f"call-{i}", reply="r")
    big = tmp_path / "logs" / "qianbi.log"
    big.write_text("x" * 5000, encoding="utf-8")
    out_dir = tmp_path / "out"
    path = report_bundle.create_bundle(proj, str(out_dir), cfg, logs,
                                       keep_dialogue=2, max_log_bytes=100)
    with zipfile.ZipFile(path) as z:
        dlg = [n for n in z.namelist() if n.startswith("对话记录/")]
        log_data = [z.read(n) for n in z.namelist() if n.startswith("日志/") and n.endswith(".log")]
    assert len(dlg) <= 2, f"对话分片 {len(dlg)} 个超过 keep_dialogue=2"
    assert log_data and len(log_data[0]) < 5000, "日志未做尾部截断"
    assert "截断".encode("utf-8") in log_data[0], "截断标记缺失"
