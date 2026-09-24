# -*- coding: utf-8 -*-
"""A-5 门禁：跟踪文件命中 .gitignore 即红。

事故留档：tests_output/ 下 721 个运行产物（AI 生成正文、.usage.jsonl 账单、
console.log）在 .gitignore 屏蔽之前入库，此后一直被跟踪——仓库 58% 是生成物。
本门禁用 git ls-files 与 git check-ignore 批量对账：任何已跟踪文件命中 ignore
规则即红，防止下次再混入。

2026-09-25 修：对账改用 ``-z`` + 字节输入。原先 ``text=True`` 管道在 Windows 把
路径间的换行翻译成 CRLF，喂给 check-ignore 的每个路径尾巴带 CR，凡处在
``examples/*`` 这类通配规则下的跟踪文件全部被误判命中（假红）。
"""
import os
import subprocess

NUL = "\x00"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(*args, stdin=None):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          cwd=ROOT,
                          input=stdin).stdout


def test_no_ignored_paths_tracked():
    tracked = _git("ls-files").splitlines()
    assert tracked, "git ls-files 为空——门禁失去扫描面"
    query = (NUL.join(tracked) + NUL).encode("utf-8")
    r = subprocess.run(["git", "check-ignore", "--stdin", "-z"],
                       input=query, capture_output=True, cwd=ROOT)
    assert r.returncode in (0, 1), r.stderr.decode("utf-8", "replace")
    hit = [q for q in r.stdout.decode("utf-8", "replace").split(NUL) if q]
    assert not hit, (
        f"{len(hit)} 个已跟踪文件命中 .gitignore（生成物混入库，A-5 重演）："
        + "、".join(hit[:20]) + ("…" if len(hit) > 20 else ""))
