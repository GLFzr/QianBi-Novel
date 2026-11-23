# -*- coding: utf-8 -*-
"""qianbi-mcp：千笔账本只读 MCP server（E6，0.20.3）

把 P2 已落地的四本追踪账本以 MCP（Model Context Protocol）stdio server 形态
暴露给外部 agent 宿主（Claude Code / Codex / ZCode 等）——「GUI 给作者、MCP 给
agent」的引擎双形态（0.20.3 报告 E6 行 / t7 §2.3）。

- 纯标准库实现 JSON-RPC 2.0 + MCP stdio 传输（逐行 JSON，一请求一行一响应），
  零第三方依赖、零网络：只实现 initialize / tools/list / tools/call 三方法。
- 只读工具四个：get_setting_ledger / get_reader_belief / get_foreshadow_ledger /
  get_rhythm_ledger——各自返回对应账本 JSON 全文 + 绝对路径。
- 安全边界：只读（无任何写工具）、路径锁定（账本文件必须落在 --project 目录内，
  realpath + normcase 双重校验，越界拒绝）、stdio 本地进程（不做远程托管）。
- fail-open：账本缺失/损坏不报协议错误，按存在性+告警文本如实返回（与账本模块
  的 fail-open 读纪律一致，t7 §2.6「工具不可用返回显式错误」的只读版）。

启动：`python -m app.mcp_server --project <项目路径>`（项目路径=书目录，
内含 追踪/ sidecar 区）。

schema 版本纪律（t7 §2.6）：serverInfo 自报 qianbi 版本；账本 schema 当前均为
version 1，工具描述里显式标注——旧 server 读新账本靠 fail-open 兜底不误读。
"""
from app.mcp_server.server import (PROTOCOL_VERSION, SERVER_NAME, PathEscape,
                                   QianbiMcpServer, ensure_under, serve)

__all__ = ["PROTOCOL_VERSION", "SERVER_NAME", "PathEscape", "QianbiMcpServer",
           "ensure_under", "serve"]
