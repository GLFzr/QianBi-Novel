# -*- coding: utf-8 -*-
"""0.24.0 字数带修复驱动：对低于下限的章跑段落级增厚（Q2-a 同路径），清 [字数] 阻塞。

用法：QIANBI_TEST_KEY=... python tests/word_fix.py
"""
import os
import sys
import time

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
           "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

PROJ = os.path.join(_ROOT, "tests_output", "or_二测_改命笔记")
BASE_URL = os.environ.get("QIANBI_TEST_BASE", "https://opencode.ai/zen/go/v1")
MODEL = os.environ.get("QIANBI_TEST_MODEL", "longcat-2.5-preview-free")
KEY = os.environ.get("QIANBI_TEST_KEY", "").strip()
TARGET = 2000


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    assert KEY, "需要 QIANBI_TEST_KEY"
    from app import config as cfg_mod
    from app import project
    from app.core import versions
    from app import prompts
    from app.core import gates, stages
    from app.core.shared_prefix import project_header
    from app.llm import clean_llm_output
    from app.core.stages import project_header
    from app.core.chapter_session import ChapterSession
    from app.core.volume_session import build_corpus_snapshot
    from app.llm.client import LLMClient

    conn = {"id": "oc", "name": "OpenCode Go free", "provider": "custom",
            "base_url": BASE_URL, "api_key": KEY, "model": MODEL,
            "stream": False, "max_tokens": 32768, "timeout": 900,
            "thinking": "", "reasoning_effort": "high",
            "user_id": "qianbi-wordfix"}
    client = LLMClient.from_connection(conn)

    class _Ctx:
        proj = PROJ
        cfg = {"writing": {}}
        last_prompt = ""
        stopped = False
        _rewrite_used = 0
        _rewrite_budget_logged = False

        def log(self, level, msg):
            log(f"    [{level}] {msg}")

        def stream_chunk(self, t):
            pass

        def stream_reasoning(self, t):
            pass

        def stream_stage(self, label):
            pass

    class _Router:
        def client(self, slot):
            return client

    ctx = _Ctx()
    ctx.router = _Router()
    fixed = skipped = failed = 0
    for n, _t, p in project.list_chapters(PROJ):
        prose = project.read_file(p)
        cc = project.count_chars(prose)
        low_ok, _high, _ = gates.check_word_bounds(prose, TARGET, 0.1)
        if low_ok:
            continue
        gap = max(TARGET - cc, 200)
        log(f"第 {n} 章 {cc} 字（缺口 {gap}）——补尾续写（V7 语义）…")
        kw = dict(chapter_num=n, actual=cc, target=TARGET, gap=gap,
                  ending=prose[-400:],
                  tic_blacklist=stages._tic_blacklist(PROJ),
                  must_block=stages._must_block(PROJ, {"writing": {}}),
                  chapter_header=stages.chapter_header(PROJ, n),
                  project_header=project_header(PROJ))
        prompt = prompts.ENRICH_TAIL_PROMPT.format(**kw)
        try:
            cont = clean_llm_output(client.chat(prompt, phase="word_fix"))
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ 调用失败：{type(e).__name__}: {str(e)[:120]}")
            failed += 1
            continue
        cont = (cont or "").strip()
        if cont and len(cont) >= gap * 0.35:
            merged = prose.rstrip("\n") + "\n\n" + cont
            versions.snapshot(PROJ, n, prose, "字数增厚前备份")
            project.write_file(p, merged)
            new_cc = project.count_chars(merged)
            ok, _, _f = gates.check_word_bounds(merged, TARGET, 0.1)
            log(f"  ✓ 续写 {len(cont)} 字：{cc}→{new_cc}（{'达标' if ok else '仍低于下限'}）")
            fixed += 1
        else:
            log(f"  ✗ 续写过短（{len(cont)} 字 < 阈值 {int(gap*0.35)}），保留原稿")
            failed += 1
    log(f"== 完成：增厚 {fixed} 章 / 失败 {failed} / 跳过（已达标）其余 ==")


if __name__ == "__main__":
    main()
