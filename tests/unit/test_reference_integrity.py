# -*- coding: utf-8 -*-
"""WP-17 引用完整性护栏：全仓 md/注释里引用的 docs/*.md 与 tests/*.py 路径必须存在。

事故留档：docs/lieflat-less-ai-tone-integration-plan.md 曾未跟踪入库，而已提交的
app/config.py 注释与 integration-notes.md 都在引用它 ⇒ 干净 clone 指向不存在的
文件。本护栏从仓库自身派生扫描面（walk 所有 .md/.py），不维护手写清单（R11）。
豁免只允许逐条留因（历史计划文档提及的未立项脚本 / 文件名模板占位——改写它们
等于篡改历史记录，豁免比改写诚实），豁免键自身不许腐化。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 已知合法的"非文件"模式：文档里讨论中的路径占位/示例
ALLOWED_PREFIXES = ("tests_output/",)   # 运行期产物目录，不入库

# 显式豁免（逐条留因）
EXEMPT_REFS = {
    "tests/test_chapter_resume.py": "W轮历史计划文档提及，脚本未立项（计划史实）",
    "tests/test_span_merge.py": "成本优化工作指南 v2 提及，脚本未立项（计划史实）",
    "tests/probe_console_model.py": "plan_agent_console v1-v3 历史方案名，探针未按此名落地",
    "tests/probe_console_focus.py": "plan_agent_console v2/v3 历史方案名，探针未按此名落地",
    "tests/probe_reader_dock.py": "plan_agent_console v2/v3 历史方案名，探针未按此名落地",
    "docs/plan_agent_console_v1-v3.md": "区间速写（v1、v2、v3 三份），非单个文件名",
    "docs/2026.9.X_轮次名工作记录.md": "文件名模板占位（seed 文档的命名说明）",
    "docs/YYYY.M.D_轮次名工作记录.md": "文件名模板占位（接手指南的命名说明）",
}


PRUNE_DIRS = (".git", ".venv", "node_modules", "__pycache__", "dist", "build",
              ".tmp_test", ".workbuddy", ".zcode", "tests_output", "tests_output_pd",
              "snapshots_tmp", ".pytest_cache")


def _repo_files():
    for dp, dn, fns in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in PRUNE_DIRS]
        for fn in fns:
            if fn.endswith((".md", ".py")):
                yield os.path.join(dp, fn)


def test_referenced_doc_and_test_paths_exist():
    # 两种"看似本仓路径、实为外链"的形态都跳过：
    # - 链接文本 [docs/x.md](https://…) —— (?!\]\(http
    # - 纯文本 URL 的尾部（https://github.com/…/docs/x.md）—— (?<!/)
    pat = re.compile(r"(?<!/)(?:docs|tests)/[\w\-./\u4e00-\u9fff]+\.(?:md|py)(?!\]\(http)")
    missing = []
    for path in _repo_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in pat.finditer(text):
            ref = m.group(0)
            if ref.startswith(ALLOWED_PREFIXES) or ref in EXEMPT_REFS:
                continue
            target = os.path.join(ROOT, ref.replace("/", os.sep))
            if not os.path.exists(target):
                missing.append(f"{rel} → {ref}")
    # 豁免名单自身不许腐化：豁免的引用必须仍在某处被提及（否则豁免成了死条目）
    assert not missing, (
        "引用完整性违规（干净 clone 会指向不存在的文件）：" + "；".join(sorted(set(missing))))


def test_exempt_refs_not_stale():
    all_text = ""
    for path in _repo_files():
        try:
            all_text += open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
    stale = [ref for ref in EXEMPT_REFS
             if not re.search(re.escape(ref) + r"(?!\]\(http)", all_text)]
    assert not stale, f"豁免名单里有不再被引用的死条目（名单腐化）：{stale}"
