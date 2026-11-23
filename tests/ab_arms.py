# -*- coding: utf-8 -*-
"""0.20.4 Q1-b 三臂 A/B 定架构实验（同书同细纲，臂间唯一变量=上下文架构）。

臂1 现状：volume_session + compaction(48k)         = Q1-a 后的默认
臂2 fresh：head_rebuild（L4 每章重建+冻结头，跨章历史不入栈）
臂3 旧账：volume_session 无压缩（compaction=false）= 三测劣化复现对照

用法：QIANBI_TEST_KEY=... python tests/ab_arms.py <臂名> <章数上限>
每臂独立项目（or_ab_<臂名>），跑完用 quality_suite blind 层对合并稿盲评。
"""
import os
import sys
import time

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
           "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

ARM_CFG = {
    "compact": {"volume_session": True, "compaction": True,
                "compaction_token_threshold": 48000,
                "s4_static_freeze": True, "tracking_delta": True,
                "review_in_system": True},
    "fresh": {"head_rebuild": True, "book_stream": True,
              "tracking_delta": True, "review_in_system": True},
    "legacy": {"volume_session": True, "compaction": False,
               "s4_static_freeze": True, "tracking_delta": True,
               "review_in_system": True},
}


def main():
    arm = sys.argv[1] if len(sys.argv) > 1 else "compact"
    max_ch = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    assert arm in ARM_CFG, f"未知臂：{arm}"
    key = os.environ.get("QIANBI_TEST_KEY", "").strip()
    assert key, "需要 QIANBI_TEST_KEY"
    import shutil
    proj = os.path.join(_ROOT, "tests_output", f"or_ab_{arm}")
    src = os.path.join(_ROOT, "tests_output", "or_二测_改命笔记")
    if not os.path.isdir(proj):
        shutil.copytree(src, proj)
        # 各臂只保留共写 2 章（第 3 章起自动生成，臂间同起点）
        for fn in os.listdir(os.path.join(proj, "正文")):
            if any(f"第00{n}" in fn for n in range(3, 9)):
                os.remove(os.path.join(proj, "正文", fn))
        for n in range(3, 9):
            vdir = os.path.join(proj, "正文", ".versions", f"第{n}章")
            if os.path.isdir(vdir):
                shutil.rmtree(vdir)
            ap = os.path.join(proj, "正文", ".annotations", f"第{n}章.json")
            if os.path.exists(ap):
                os.remove(ap)
        st_json = os.path.join(proj, "pipeline_state.json")
        state = __import__("json").load(open(st_json, encoding="utf-8"))
        state.setdefault("total_chapters", 12)
        __import__("json").dump(state, open(st_json, "w", encoding="utf-8"),
                                ensure_ascii=False, indent=1)
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv)

    from app.core.orchestrator import Orchestrator
    # 0.20.4 起默认走 OpenCode Go 免费模型（用户限制：仅 space-bunny-free /
    # longcat-2.5-preview-free，禁付费模型）；QIANBI_TEST_KEY 可覆盖为 OpenRouter。
    oc_key = os.environ.get("QIANBI_OC_KEY", "").strip()
    if oc_key:
        conn = {"id": "t", "name": "opencode-go-free", "provider": "custom",
                "base_url": "https://opencode.ai/zen/go/v1", "api_key": oc_key,
                "model": os.environ.get("QIANBI_OC_MODEL", "space-bunny-free"),
                "stream": False, "max_tokens": 16384, "timeout": 900,
                "thinking": "", "reasoning_effort": "high",
                "user_id": "qianbi-ab-" + arm}
    else:
        conn = {"id": "t", "name": "stealth-arm", "provider": "custom",
                "base_url": "https://openrouter.ai/api/v1", "api_key": key,
                "model": "stealth/space-bunny-alpha", "stream": False,
                "max_tokens": 16384, "timeout": 900, "thinking": "",
                "reasoning_effort": ""}
    cfg = {"connections": [conn], "slots": {"writing": "t", "helper": "t", "review": "t"},
           "gates": {"strategy": "mark_continue", "deslop_max_rounds": 2,
                     "word_tolerance": 0.1, "review_enabled": True,
                     "review_max_rounds": 1, "word_enrich_rounds": 1},
           "llm": {"max_retries": 2, "backoff_base": 2.0},
           "dialogue_log": {"enabled": False},
           "writing": dict({"chapter_word_target": 2000, "default_genre": "",
                            "default_platform": "番茄"}, **ARM_CFG[arm])}
    plog = os.path.join(_ROOT, "tests_output", f"_ab_{arm}.log")
    started = time.time()

    def mark(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(plog, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    before = len([f for f in os.listdir(os.path.join(proj, "正文"))
                  if f.endswith(".md")])
    orch = Orchestrator(proj, cfg)
    orch.sig_log.connect(lambda lv, m: mark(f"  {m}"), Qt.DirectConnection)
    orch.sig_auto_paused.connect(lambda r: (mark(f"[budget] {r}"),
                                            orch.resume()), Qt.DirectConnection)
    mark(f"[arm {arm}] cfg={ARM_CFG[arm]}")
    orch.start()
    t0 = time.time()
    while orch.isRunning() and time.time() - t0 < 100 * 60:
        app.processEvents()
        time.sleep(0.2)
        n = len([f for f in os.listdir(os.path.join(proj, "正文"))
                 if f.endswith(".md")])
        if n >= before + max_ch:
            mark(f"[arm {arm}] 达 {max_ch} 章，停止")
            orch.stop()
            break
    mark(f"[arm {arm}] 结束：新增 {len([f for f in os.listdir(os.path.join(proj, '正文')) if f.endswith('.md')]) - before} 章，"
         f"耗时 {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
