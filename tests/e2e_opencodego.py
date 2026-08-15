# -*- coding: utf-8 -*-
"""端到端真实试写：DeepSeek 官方 API + 完整流水线（设定→大纲→细纲→3章微循环→完本）

【测试约定】本项目测试一律只用 deepseek-v4-flash（+ thinking disabled 防推理截断）。
途径切换：设环境变量 QIANBI_TEST_BASE / QIANBI_TEST_KEY（默认官方 api.deepseek.com，
Key 从 ~/.qianbi_novel/config.json 读取）。
- 配置注入内存（不写 ~/.qianbi_novel/config.json，不污染用户配置）
- 跑完 3 章自动停止，输出结果汇总
- 运行：.venv/Scripts/python.exe tests/e2e_opencodego.py
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())

# ---- 测试连接（约定：deepseek-v4-flash）----
MODEL = "deepseek-v4-flash"
BASE = os.environ.get("QIANBI_TEST_BASE", "https://api.deepseek.com")
KEY = os.environ.get("QIANBI_TEST_KEY", "")
if not KEY:
    cfg_path = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg0 = json.load(f)
        for c in cfg0.get("connections", []):
            if c.get("base_url", "").find("deepseek.com") >= 0 and c.get("api_key"):
                KEY = c["api_key"]
                break
    except Exception:
        pass
assert KEY, "未找到测试 API Key（设 QIANBI_TEST_KEY 或 ~/.qianbi_novel/config.json）"
CHAPTERS_TO_WRITE = 3   # 写完几章后自动停止
CHAPTER_WORDS = 2000    # 每章目标字数（测试用 2000，比默认 3000 快）

from PySide6.QtGui import QGuiApplication
app = QGuiApplication(sys.argv)

from app import project
from app.core.orchestrator import Orchestrator
from app.core import state as st

cfg = {
    "connections": [
        {"id": "t-write", "name": f"{MODEL}（写作槽）", "provider": "custom",
         "base_url": BASE, "api_key": KEY, "model": MODEL,
         "temperature": 0.7, "max_tokens": 16384, "timeout": 300,
         "thinking": "disabled"},
        {"id": "t-helper", "name": f"{MODEL}（辅助槽）", "provider": "custom",
         "base_url": BASE, "api_key": KEY, "model": MODEL,
         "temperature": 0.7, "max_tokens": 16384, "timeout": 300,
         "thinking": "disabled"},
    ],
    "slots": {"writing": "t-write", "helper": "t-helper", "review": "t-helper"},
    "gates": {"strategy": "mark_continue", "deslop_max_rounds": 2,
              "word_tolerance": 0.1, "review_enabled": True, "review_max_rounds": 1},
    "llm": {"max_retries": 2, "backoff_base": 2.0},
    "writing": {"chapter_word_target": CHAPTER_WORDS, "default_genre": "",
                "default_platform": "番茄"},
    "last_project": "",
    "recent_projects": [],
}

root = os.path.join(os.getcwd(), "tests_output")
os.makedirs(root, exist_ok=True)
PROGRESS_LOG = os.path.join(root, "e2e_progress.log")


def mark(msg):
    """进度落盘：进程被杀也能看到死在哪一步"""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


proj = project.create_project(root, "改命笔记_官方api")
project.write_idea_info(proj, "都市悬疑脑洞", "番茄", "主角捡到一本能改写现实的笔记，每次使用都会付出未知代价", 0)
mark(f"[e2e] 项目已创建: {proj}（途径：{BASE} · {MODEL} · thinking=disabled）")

logs = []
records = []
fail = {"msg": ""}


def on_log(level, msg):
    logs.append(f"[{level}] {msg}")
    mark(f"  {msg}")


def on_chapter_done(record):
    records.append(record)
    mark(f"[e2e] 第 {record['num']} 章定稿: {record['words']} 字, "
         f"去味阻断 {record.get('deslop_blocking', 0)}, "
         f"审校阻塞 {record.get('review_blocking', 0)}, 状态 {record['status']}")
    if len(records) >= CHAPTERS_TO_WRITE:
        orch.stop()
        mark("[e2e] 已写完 3 章，请求停止…")


def on_finished(reason):
    mark(f"[e2e] 流水线结束: {reason}")


def on_failed(msg):
    fail["msg"] = msg
    mark(f"[e2e] 流水线失败: {msg}")


orch = Orchestrator(proj, cfg)
orch.sig_log.connect(on_log)
orch.sig_chapter_done.connect(on_chapter_done)
orch.sig_finished.connect(on_finished)
orch.sig_failed.connect(on_failed)

t0 = time.monotonic()
mark("[e2e] 流水线启动（写 3 章 @2000 字，deepseek-v4-flash + thinking disabled）…")
orch.start()

TIMEOUT = 50 * 60  # 50 分钟上限
last_beat = time.monotonic()
while orch.isRunning() and time.monotonic() - t0 < TIMEOUT:
    app.processEvents()
    time.sleep(0.2)
    if time.monotonic() - last_beat > 30:
        last_beat = time.monotonic()
        mark(f"[beat] 存活 {time.monotonic() - t0:.0f}s，章数 {len(records)}")

app.processEvents()
mark(f"[e2e] 总耗时 {time.monotonic() - t0:.0f}s")

# ===== 结果汇总 =====
print("\n========== 结果汇总 ==========", flush=True)
if fail["msg"]:
    print("失败原因:", fail["msg"], flush=True)
    dbg = os.path.join(proj, "pipeline_debug")
    if os.path.isdir(dbg):
        for f in sorted(os.listdir(dbg)):
            print(f"--- pipeline_debug/{f} ---", flush=True)
            print(project.read_file(os.path.join(dbg, f))[:2000], flush=True)
    sys.exit(1)

chapters = project.list_chapters(proj)
print(f"正文章节: {len(chapters)} 章", flush=True)
for n, name, path in chapters:
    print(f"  {name}: {project.count_chars(project.read_file(path))} 字", flush=True)

outlines = project.list_outlines(proj)
print(f"细纲: {len(outlines)} 章", flush=True)
print(f"设定/题材定位.md: {len(project.read_file(os.path.join(proj, '设定', '题材定位.md')))} 字", flush=True)
print(f"大纲/大纲.md: {len(project.read_file(os.path.join(proj, '大纲', '大纲.md')))} 字", flush=True)

state = st.load_state(proj)
print(f"\npipeline_state: stage={state['stage']} current_chapter={state['current_chapter']}", flush=True)
print(f"history 记录: {len(state['history'])} 条", flush=True)
for h in state["history"]:
    print(f"  第{h['num']}章: {h['words']}字 去味阻断{h['deslop_blocking']} 审校阻塞{h.get('review_blocking', 0)} {h['status']}", flush=True)

print(f"\ntokens 累计: {orch.router.total_tokens()}", flush=True)
print(f"成本估算: ¥{orch.router.estimate_cost():.2f}（OpenCode Go 为订阅制，仅供参考）", flush=True)

print("\n追踪文件状态:", flush=True)
for name in ["伏笔", "时间线", "角色状态", "上下文", "全局摘要", "章节摘要"]:
    p = os.path.join(proj, "追踪", f"{name}.md")
    content = project.read_file(p)
    print(f"  {name}.md: {len(content)} 字", flush=True)

print("\nE2E_DONE", flush=True)
app.quit()
sys.exit(0)
