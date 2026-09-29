# -*- coding: utf-8 -*-
"""`python -m app.mcp_server --project <项目路径>` 入口。

stdio 传输下 stdout 是协议通道：本模块在启动前把 stdin/stdout 重配置为
UTF-8（Windows 控制台默认 gbk 会毁掉中文账本内容），日志只走 stderr。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from app.mcp_server.server import serve


def _reconfigure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout):
        reconf = getattr(stream, "reconfigure", None)
        if reconf is None:
            continue
        try:
            reconf(encoding="utf-8")
        except (ValueError, OSError):  # 已有缓冲数据等场景——尽力而为
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.mcp_server",
        description="qianbi-mcp：千笔账本只读 MCP stdio server（四账本工具，"
                    "路径锁定 --project 目录内）")
    parser.add_argument("--project", required=True,
                        help="书项目目录（内含 追踪/ sidecar 区），只读锁定")
    parser.add_argument("--info", action="store_true",
                        help="打印 server 元信息（JSON，stderr）后退出")
    args = parser.parse_args(argv)

    meta = json.dumps(
        {"server": "qianbi-mcp", "protocol": "2024-11-05", "readonly": True},
        ensure_ascii=True)
    if args.info:
        print(meta, file=sys.stderr)
        return 0

    if not os.path.isdir(args.project):
        parser.error("--project 不是存在目录：%s" % args.project)
        return 2  # pragma: no cover - parser.error 直接退出

    _reconfigure_utf8()
    serve(args.project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
