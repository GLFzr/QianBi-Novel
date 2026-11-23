# -*- coding: utf-8 -*-
"""E6 qianbi-mcp 只读 server 单测（0.20.3）

覆盖：
- 协议握手（initialize 返回 protocolVersion/capabilities/serverInfo）
- tools/list 恰好四工具（描述+inputSchema 齐备）
- tools/call 对临时项目夹具返回真实 JSON 全文+路径
- 路径逃逸拒绝（..、反斜杠、符号链接、白名单外文件名）
- 损坏/缺失账本 fail-open（isError=False + warning，不抛协议错误）
- 逐行 stdio 主循环（通知静默、坏行 -32700 不中断）
- `python -m app.mcp_server` 子进程全链路握手
"""
import io
import json
import os
import subprocess
import sys

import pytest

from app import __version__
from app.mcp_server import (PROTOCOL_VERSION, SERVER_NAME, PathEscape,
                            QianbiMcpServer, ensure_under, serve)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

LEDGERS = {
    "get_setting_ledger": "设定账本.json",
    "get_reader_belief": "读者认知.json",
    "get_foreshadow_ledger": "伏笔表.json",
    "get_rhythm_ledger": "爽点账本.json",
}

def _normcase(p):
    return os.path.normcase(os.path.normpath(p))


# 按真实 P2 schema 造的最小夹具
FIXTURE_LEDGERS = {
    "设定账本.json": {
        "version": 1,
        "entries": [{"name": "青云剑", "aliases": ["青冥"],
                     "category": "法宝", "first_chapter": 1,
                     "reader_known_chapter": 3, "truth": "上古残剑",
                     "reveal_planned_ch": 12}],
    },
    "读者认知.json": {
        "version": 1,
        "known": [{"content": "主角佩剑", "kind": "setting",
                   "created_ch": 1, "last_mention_ch": 4}],
        "suspense": [{"content": "剑上裂纹来历", "truth": "封印松动",
                      "planted_ch": 2, "due_ch": 10, "resolved_ch": None,
                      "last_mention_ch": 5}],
        "misconceptions": [{"name": "青云剑", "belief": "凡铁",
                            "truth": "上古残剑", "payoff_planned_ch": 12,
                            "created_ch": 1, "resolved_ch": None}],
    },
    "伏笔表.json": {
        "rows": [{"name": "裂纹", "state": "已埋", "plant_ch": 2}],
        "advances": [],
    },
    "爽点账本.json": {
        "version": 1,
        "rows": [{"num": 3, "beats_declared": ["DL"], "beats_delivered": ["DL"],
                  "类型": "打脸", "强度": 3}],
    },
}


@pytest.fixture
def proj(tmp_path):
    """带四本账本的项目夹具（书目录 + 追踪/ sidecar 区）。"""
    tracking = tmp_path / "追踪"
    tracking.mkdir()
    for fname, data in FIXTURE_LEDGERS.items():
        (tracking / fname).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(tmp_path)


@pytest.fixture
def server(proj):
    return QianbiMcpServer(proj)


def _rpc(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _call(server, tool, arguments=None):
    resp = server.dispatch(_rpc("tools/call",
                                {"name": tool, "arguments": arguments or {}}))
    assert "result" in resp, resp
    result = resp["result"]
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    return json.loads(result["content"][0]["text"])


# ---------------- 握手 ----------------

class TestInitialize:
    def test_handshake(self, server):
        resp = server.dispatch(_rpc(
            "initialize",
            {"protocolVersion": "2024-11-05",
             "capabilities": {}, "clientInfo": {"name": "test"}}))
        assert "error" not in resp
        result = resp["result"]
        assert result["protocolVersion"] == PROTOCOL_VERSION
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == SERVER_NAME == "qianbi-mcp"
        assert result["serverInfo"]["version"] == __version__

    def test_unknown_method_error_32601(self, server):
        resp = server.dispatch(_rpc("resources/list", {}))
        assert resp["error"]["code"] == -32601

    def test_notification_silent(self, server):
        assert server.dispatch({"jsonrpc": "2.0", "method":
                                "notifications/initialized"}) is None

    def test_invalid_request_shapes(self, server):
        assert server.dispatch("not-a-dict")["error"]["code"] == -32600
        assert server.dispatch({"jsonrpc": "2.0", "id": 2})[
            "error"]["code"] == -32600
        assert server.dispatch(_rpc("initialize", "bad-params"))[
            "error"]["code"] == -32602


# ---------------- tools/list ----------------

class TestToolsList:
    def test_exactly_four_readonly_tools(self, server):
        resp = server.dispatch(_rpc("tools/list", {}))
        tools = resp["result"]["tools"]
        assert {t["name"] for t in tools} == set(LEDGERS)
        assert len(tools) == 4
        for t in tools:
            assert t["description"].strip()
            assert t["inputSchema"]["type"] == "object"
            # 只读边界写进工具描述，宿主侧可审计
            assert "只读" in t["description"]

    def test_no_write_tools_by_construction(self):
        from app.mcp_server import server as server_mod
        for t in server_mod.TOOLS:
            assert t.name.startswith("get_")
            assert "\\" not in t.filename and "/" not in t.filename


# ---------------- tools/call 对真实夹具 ----------------

class TestToolsCall:
    def test_all_four_return_real_json_and_path(self, server, proj):
        for tool, fname in LEDGERS.items():
            envelope = _call(server, tool)
            assert envelope["tool"] == tool
            assert envelope["exists"] is True
            assert envelope["warning"] is None
            # server 返回 realpath 定桩后的路径（盘符大小写归一），normcase 比对
            assert _normcase(envelope["path"]) == _normcase(os.path.join(
                str(proj), "追踪", fname))
            # data = 账本 JSON 全文（解析态），逐字等于夹具
            assert envelope["data"] == FIXTURE_LEDGERS[fname]

    def test_payload_text_contains_path_line(self, server, proj):
        resp = server.dispatch(_rpc("tools/call",
                                    {"name": "get_setting_ledger"}))
        text = resp["result"]["content"][0]["text"]
        assert _normcase("设定账本.json") in _normcase(text)
        assert "青云剑" in text  # JSON 全文内容在场

    def test_unknown_tool_is_jsonrpc_error(self, server):
        resp = server.dispatch(_rpc("tools/call",
                                    {"name": "write_ledger", "arguments": {}}))
        assert resp["error"]["code"] == -32602
        assert "write_ledger" in resp["error"]["message"]

    def test_arguments_cannot_redirect_path(self, server, proj):
        """调用方塞任何路径参数都无法越界——工具根本不读入参。"""
        sneaky = {"path": os.path.join(proj, "..", "secret.json"),
                  "file": "伏笔表.json", "project": os.path.pardir}
        envelope = _call(server, "get_setting_ledger", sneaky)
        assert _normcase(envelope["path"]) == _normcase(os.path.join(
            str(proj), "追踪", "设定账本.json"))


# ---------------- 路径锁定 ----------------

class TestPathLock:
    def test_ensure_under_rejects_dotdot(self, proj):
        with pytest.raises(PathEscape):
            ensure_under(proj, os.path.join(proj, os.pardir, "outside.json"))

    def test_ensure_under_rejects_backslash_escape(self, proj):
        with pytest.raises(PathEscape):
            ensure_under(proj, os.path.join(proj, "..\\outside.json"))

    def test_ensure_under_accepts_inside(self, proj):
        inside = os.path.join(proj, "追踪", "设定账本.json")
        assert ensure_under(proj, inside)

    def test_ensure_under_rejects_symlink_out(self, tmp_path, proj):
        if not hasattr(os, "symlink"):  # pragma: no cover
            pytest.skip("os.symlink 不可用")
        outside = tmp_path / "outside_root" / "逃逸.json"
        outside.parent.mkdir()
        outside.write_text("{}", encoding="utf-8")
        link = tmp_path / "追踪链接"
        try:
            os.symlink(str(outside.parent), str(link))
        except OSError:  # pragma: no cover - Windows 无特权场景
            pytest.skip("符号链接创建受限")
        with pytest.raises(PathEscape):
            ensure_under(proj, str(link / "逃逸.json"))

    def test_resolver_whitelist_rejects_foreign_name(self, server):
        with pytest.raises(PathEscape):
            server.read_ledger(type("T", (), {
                "name": "x", "filename": "正文.md",
                "description": ""})())

    def test_nonexistent_project_refused(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            QianbiMcpServer(str(tmp_path / "不存在"))


# ---------------- fail-open ----------------

class TestFailOpen:
    def test_corrupt_json_fail_open(self, server, proj):
        bad = os.path.join(proj, "追踪", "设定账本.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"version": 1, "entries": [截断')
        envelope = _call(server, "get_setting_ledger")
        assert envelope["exists"] is True
        assert envelope["data"] is None
        assert envelope["raw"] == '{"version": 1, "entries": [截断'
        assert "损坏" in envelope["warning"]

    def test_missing_ledger_fail_open(self, tmp_path):
        (tmp_path / "追踪").mkdir()
        server = QianbiMcpServer(str(tmp_path))
        envelope = _call(server, "get_reader_belief")
        assert envelope["exists"] is False
        assert envelope["data"] is None
        assert "不存在" in envelope["warning"]

    def test_empty_file_fail_open(self, server, proj):
        with open(os.path.join(proj, "追踪", "爽点账本.json"),
                  "w", encoding="utf-8") as f:
            f.write("")
        envelope = _call(server, "get_rhythm_ledger")
        assert envelope["exists"] is True
        assert envelope["data"] is None
        assert envelope["warning"]


# ---------------- stdio 逐行主循环 ----------------

class TestServeLineProtocol:
    def _run(self, server, lines):
        fin = io.StringIO("".join(line + "\n" for line in lines))
        fout = io.StringIO()
        serve(server.project_dir, stdin=fin, stdout=fout)
        return [json.loads(x) for x in fout.getvalue().splitlines()]

    def test_request_response_lines(self, proj):
        fin = io.StringIO("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in [
            _rpc("initialize", {}, req_id=1),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _rpc("tools/list", {}, req_id=2),
            _rpc("tools/call", {"name": "get_foreshadow_ledger"}, req_id=3),
        ]))
        fout = io.StringIO()
        serve(proj, stdin=fin, stdout=fout)
        out = [json.loads(x) for x in fout.getvalue().splitlines()]
        # 通知静默：三条响应，序号 1/2/3
        assert [r["id"] for r in out] == [1, 2, 3]
        assert out[0]["result"]["serverInfo"]["name"] == SERVER_NAME
        assert len(out[1]["result"]["tools"]) == 4
        payload = json.loads(out[2]["result"]["content"][0]["text"])
        assert payload["path"].endswith("伏笔表.json")
        assert payload["data"]["rows"][0]["name"] == "裂纹"

    def test_blank_and_corrupt_lines_survive(self, proj):
        fin = io.StringIO("\n  \n{broken json\n" + json.dumps(
            _rpc("tools/list", {}, req_id=9)) + "\n")
        fout = io.StringIO()
        serve(proj, stdin=fin, stdout=fout)
        out = [json.loads(x) for x in fout.getvalue().splitlines()]
        assert len(out) == 2
        assert out[0]["id"] is None and out[0]["error"]["code"] == -32700
        assert out[1]["id"] == 9 and "tools" in out[1]["result"]


# ---------------- 子进程全链路 ----------------

class TestSubprocessEntry:
    def test_module_entry_handshake(self, proj):
        requests = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in [
            _rpc("initialize", {}, req_id=1),
            _rpc("tools/call", {"name": "get_rhythm_ledger"}, req_id=2),
        ])
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "app.mcp_server", "--project", proj],
            input=requests, capture_output=True, text=True,
            encoding="utf-8", cwd=REPO_ROOT, env=env, timeout=60)
        assert proc.returncode == 0, proc.stderr
        lines = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
        assert [r["id"] for r in lines] == [1, 2]
        assert lines[0]["result"]["serverInfo"]["version"] == __version__
        payload = json.loads(lines[1]["result"]["content"][0]["text"])
        assert payload["data"]["rows"][0]["num"] == 3

    def test_module_entry_requires_existing_project(self):
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "app.mcp_server", "--project",
             os.path.join(REPO_ROOT, "no_such_project_dir")],
            capture_output=True, text=True, encoding="utf-8",
            cwd=REPO_ROOT, env=env, timeout=60)
        assert proc.returncode == 2
        assert "--project" in (proc.stderr or "")
