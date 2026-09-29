# -*- coding: utf-8 -*-
"""qianbi-mcp 核心实现：JSON-RPC 2.0 + MCP stdio（纯标准库，只读）

协议面（MCP 2024-11-05 基线，stdio 传输=逐行 JSON）：
- initialize        → 自报 protocolVersion / capabilities / serverInfo
- tools/list        → 四个只读账本工具描述
- tools/call        → 读账本，返回 {path, exists, data|raw, warning} 信封
- notifications/*   → 通知不回包（initialized 等，静默吞掉）
- 其余方法          → JSON-RPC error -32601；入参坏 → -32602 / -32600 / -32700

安全边界（E6 铁律）：
- 只读：工具面只有四个 get_*，无任何写路径，无 subprocess，无网络调用；
- 路径锁定：所有读取都经 ensure_under()——目标 realpath 必须（normcase 后）
  落在 --project realpath 之内，且文件名在白名单内，双保险防目录逃逸；
- fail-open：账本缺失/损坏不抛协议错误，如实返回 exists=False / data=None /
  raw 原文 + warning——与账本模块读纪律一致，外部 agent 拿到的是「可判读的
  现状」而不是异常。
"""
from __future__ import annotations

import json
import os
import sys

from app import __version__

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "qianbi-mcp"

TRACKING_DIR = "追踪"


class PathEscape(ValueError):
    """目标路径逃逸出 --project 锁定目录（或文件名不在白名单）——拒绝读取。"""


class _Tool:
    """只读账本工具登记项。file 只接受字面白名单，不接受任何调用方输入。"""

    __slots__ = ("name", "filename", "description")

    def __init__(self, name: str, filename: str, description: str):
        self.name = name
        self.filename = filename
        self.description = description


# 四本账本（P2 已落地 schema，全部 v1）——文件名字面白名单，调用方无法指路
TOOLS = [
    _Tool(
        "get_setting_ledger", "设定账本.json",
        "读取设定名词账本（追踪/设定账本.json，schema version 1）。"
        "entries[] 字段：name/aliases/category/first_chapter/"
        "reader_known_chapter/truth/reveal_planned_ch。只读；文件缺失或损坏时"
        "返回 exists=false 或 data=null 加 warning，不报错。",
    ),
    _Tool(
        "get_reader_belief", "读者认知.json",
        "读取读者认知三段式册（追踪/读者认知.json，schema version 1）。"
        "字段：known[]（读者已知）/suspense[]（活跃悬念）/misconceptions[]"
        "（读者误知）。只读；缺失/损坏 fail-open。",
    ),
    _Tool(
        "get_foreshadow_ledger", "伏笔表.json",
        "读取伏笔账本（追踪/伏笔表.json）：rows[] 三态（未埋/已埋/已回收，含"
        "推进中）+ advances 推进日志。只读；缺失/损坏 fail-open。",
    ),
    _Tool(
        "get_rhythm_ledger", "爽点账本.json",
        "读取爽点节奏账本（追踪/爽点账本.json，schema version 1）。"
        "rows[] 字段：num/beats_declared/beats_delivered/类型/强度。"
        "只读；缺失/损坏 fail-open。",
    ),
]

_TOOL_BY_NAME = {t.name: t for t in TOOLS}

_EMPTY_INPUT_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
    "title": "EmptyArgs",
}


def ensure_under(root: str, target: str) -> str:
    """路径锁定闸：target（realpath 归一后）必须落在 root 目录内。

    root/target 都做 realpath（解析符号链接与 ..）+ normcase（Windows 大小写
    与分隔符差异）后再比对；越界抛 PathEscape。root 自身合法（=root 视作目录
    占位，不用于文件读取场景）。
    """
    real_root = os.path.normcase(os.path.realpath(root))
    real_target = os.path.normcase(os.path.realpath(target))
    if real_target != real_root and not real_target.startswith(
            real_root + os.sep):
        raise PathEscape(
            "路径越界：目标 %s 不在锁定目录 %s 内" % (target, root))
    return real_target


class QianbiMcpServer:
    """无状态协议分发器 + 项目账本只读访问器。"""

    def __init__(self, project_dir: str):
        if not os.path.isdir(project_dir):
            raise NotADirectoryError(
                "--project 不是存在目录：%s" % project_dir)
        # 锁定目录在构造时一次性 realpath 定桩；之后所有读取都过 ensure_under
        self.project_dir = os.path.realpath(project_dir)

    # ---------------- 账本只读 ----------------

    def read_ledger(self, tool: _Tool) -> dict:
        """读一本账本，fail-open 信封：{path, exists, data, raw, warning}。

        - 正常：data=解析后的 JSON 全文；raw 不带（省一倍体积）；
        - 损坏：data=None，raw=文件原文，warning 带解析错误；
        - 缺失：exists=False，warning 提示（账本模块惰性播种，缺失=空账本常态）。
        """
        if tool.filename not in {t.filename for t in TOOLS}:
            raise PathEscape("文件不在只读白名单：%s" % tool.filename)
        path = ensure_under(
            self.project_dir,
            os.path.join(self.project_dir, TRACKING_DIR, tool.filename))
        envelope = {"path": path, "exists": False, "data": None, "raw": None}
        if not os.path.isfile(path):
            envelope["warning"] = "账本文件不存在（空账本常态，写入侧惰性播种）"
            return envelope
        envelope["exists"] = True
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            envelope["warning"] = "账本读取失败：%s" % exc
            return envelope
        try:
            envelope["data"] = json.loads(text)
        except ValueError as exc:
            envelope["raw"] = text
            envelope["warning"] = "账本 JSON 损坏（fail-open 返回原文）：%s" % exc
        return envelope

    # ---------------- MCP 工具面 ----------------

    def _tool_descriptors(self) -> list:
        return [{
            "name": t.name,
            "description": t.description,
            "inputSchema": dict(_EMPTY_INPUT_SCHEMA),
        } for t in TOOLS]

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        tool = _TOOL_BY_NAME.get(name) if isinstance(name, str) else None
        if tool is None:
            raise KeyError("未知工具：%r（只读工具面：%s）"
                           % (name, ", ".join(sorted(_TOOL_BY_NAME))))
        envelope = self.read_ledger(tool)
        payload = json.dumps(
            {"tool": tool.name, "path": envelope["path"],
             "exists": envelope["exists"], "data": envelope["data"],
             "raw": envelope["raw"], "warning": envelope.get("warning")},
            ensure_ascii=False, indent=2)
        return {"content": [{"type": "text", "text": payload}],
                "isError": False}

    # ---------------- JSON-RPC 分发 ----------------

    def dispatch(self, msg: object):
        """处理一条已解析的 JSON-RPC 请求；通知返回 None（不回包）。"""
        if not isinstance(msg, dict):
            return _error(None, -32600, "Invalid Request")
        method = msg.get("method")
        req_id = msg.get("id")
        if not isinstance(method, str) or not method:
            return _error(req_id, -32600, "Invalid Request: method 缺失")
        if method.startswith("notifications/"):
            return None  # 通知不回包（initialized 等，静默）
        handlers = {
            "initialize": self._on_initialize,
            "tools/list": self._on_tools_list,
            "tools/call": self._on_tools_call,
        }
        handler = handlers.get(method)
        if handler is None:
            return _error(req_id, -32601, "Method not found: %s" % method)
        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(req_id, -32602, "Invalid params: 须为 object")
        try:
            result = handler(params)
        except KeyError as exc:
            return _error(req_id, -32602, str(exc.args[0] if exc.args else exc))
        except PathEscape as exc:
            return _error(req_id, -32602, "拒绝读取：%s" % exc)
        return _ok(req_id, result)

    def _on_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        }

    def _on_tools_list(self, params: dict) -> dict:
        return {"tools": self._tool_descriptors()}

    def _on_tools_call(self, params: dict) -> dict:
        return self._call_tool(params)


# ---------------- JSON-RPC 信封 ----------------

def _ok(req_id, result: object) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


# ---------------- stdio 主循环 ----------------

def serve(project_dir: str, stdin=None, stdout=None) -> QianbiMcpServer:
    """逐行读取 JSON-RPC 请求、逐行写响应；返回 server 供测试断言状态。

    - 一行一请求一响应（MCP stdio 逐行 JSON 口径）；
    - 空行跳过；坏 JSON 行回 -32700 不中断服务；
    - 通知不产生输出；日志一律走 stderr（由 __main__ 负责，本函数不打印）。
    """
    server = QianbiMcpServer(project_dir)
    fin = stdin if stdin is not None else sys.stdin
    fout = stdout if stdout is not None else sys.stdout
    for raw in fin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError as exc:
            resp = _error(None, -32700, "Parse error: %s" % exc)
        else:
            resp = server.dispatch(msg)
            if resp is None:
                continue
        fout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        fout.flush()
    return server
