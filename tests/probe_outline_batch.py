# -*- coding: utf-8 -*-
"""细纲批次实验：验证批量 prompt 强化 + 解析增强 + 批规模/思考强度组合

用法：python tests/probe_outline_batch.py <start> <end> <effort> [max_tokens]
示例：python tests/probe_outline_batch.py 1 1 max 32768   # 单章 + max 思考
      python tests/probe_outline_batch.py 1 2 high 32768  # 2 章 + high 思考
"""
import os
import sys
import time
import json

sys.path.insert(0, os.getcwd())

KEY = os.environ.get("QIANBI_TEST_KEY", "")
if not KEY:
    cfg_path = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg0 = json.load(f)
        for c in cfg0.get("connections", []):
            if c.get("base_url", "").find("opencode") >= 0 and c.get("api_key"):
                KEY = c["api_key"]
                break
    except Exception:
        pass
BASE = os.environ.get("QIANBI_TEST_BASE", "https://opencode.ai/zen/go/v1")

from app import project, prompts
from app.config import load_config
from app.core import memory
from app.core.stages import (_genre_block, _sanitize_chapter_refs, _unit_contract,
                             _wb_rg_blocks, parse_outlines)

PROJ = os.path.join(os.getcwd(), "tests_output", "改命笔记_官方api")

core_setting = project.read_file(os.path.join(PROJ, "设定", "题材定位.md"))[:2500] or "（未提供）"
volume_outline = project.read_file(os.path.join(PROJ, "大纲", "大纲.md"))[:4000] or "（未提供）"
nearby = []
for n, p in project.list_outlines(PROJ):
    nearby.append(project.read_file(p)[:800])
nearby_text = "\n\n".join(nearby) if nearby else "（无相邻细纲）"

start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
end = int(sys.argv[2]) if len(sys.argv) > 2 else 5
effort = sys.argv[3] if len(sys.argv) > 3 else "max"
max_tokens = int(sys.argv[4]) if len(sys.argv) > 4 else 32768
count = end - start + 1

prompt = prompts.CHAPTER_OUTLINE_PROMPT.format(
    chapter_num=start,
    volume_outline=volume_outline,
    nearby_outlines=nearby_text,
    core_setting_brief=core_setting,
    global_summary=memory.read_global_summary(PROJ) or "（全书尚未开始）",
    recent_summaries=_sanitize_chapter_refs(
        memory.read_recent_summaries(PROJ, start, n=3)) or "（无更前章节摘要）",
    character_states=project.read_file(
        project.get_tracking_path(PROJ, "角色状态"))[:1500] or "（暂无）",
    start_chapter=start,
    end_chapter=end,
    count=count,
    chapter_words=2000,
    chapter_words_max=2200,
    next_chapter=start + 1,
    previous_ending="（无）",
    foreshadows="（无）",
    unit_contract=_unit_contract(PROJ, start),
    genre_block=_genre_block(PROJ, "unit_outline"),
    worldbook_block=_wb_rg_blocks(PROJ, load_config(), start)[0],
    regex_block=_wb_rg_blocks(PROJ, load_config(), start)[1],
    user_directive="（无）",
)

import httpx
print(f"== 实验：第 {start}-{end} 章（{count} 章）effort={effort} max_tokens={max_tokens} ==", flush=True)
t0 = time.monotonic()
try:
    r = httpx.post(f"{BASE}/chat/completions",
                   headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                   json={"model": "deepseek-v4-flash",
                         "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": max_tokens, "temperature": 0.7,
                         "thinking": {"type": "enabled"}, "reasoning_effort": effort},
                   timeout=1500)
    d = r.json()
    msg = (d.get("choices") or [{}])[0].get("message", {})
    content = msg.get("content") or ""
    usage = d.get("usage") or {}
    print(f"HTTP {r.status_code} ({time.monotonic()-t0:.0f}s) content={len(content)} "
          f"finish={(d.get('choices') or [{}])[0].get('finish_reason')} "
          f"usage={json.dumps(usage, ensure_ascii=False)}", flush=True)
    if r.status_code != 200:
        print("body:", str(d)[:500], flush=True)
    else:
        outlines = parse_outlines(content)
        nums = [o[0] for o in outlines]
        print("解析章号:", nums, flush=True)
        if nums:
            print("第1章标题:", outlines[0][1], flush=True)
            print("第1章内容长度:", len(outlines[0][2]), flush=True)
        os.makedirs(".tmp_test", exist_ok=True)
        with open(os.path.join(".tmp_test", f"outline_batch_{start}-{end}_{effort}.md"), "w", encoding="utf-8") as f:
            f.write(content)
        print(f"原始输出已存 .tmp_test/outline_batch_{start}-{end}_{effort}.md", flush=True)
except Exception as e:
    print(f"ERR {type(e).__name__} {e}", flush=True)
print("DONE", flush=True)
