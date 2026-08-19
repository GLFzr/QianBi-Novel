# -*- coding: utf-8 -*-
"""章节终稿锁定探针（M4 · 无需 LLM / 无网络）：
project 层锁守卫（is/set/attempt_unlock + 标注仓兼容 + 版本历史保留）+ bridge 语义
（确认锁定/编辑器只读数据源/保存拒绝/显式解锁/档位迁移保持）
"""
import os
import sys
import tempfile

_FH = tempfile.mkdtemp(prefix="qbn_lock_home_")
os.environ["USERPROFILE"] = _FH

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QCoreApplication
app = QCoreApplication(sys.argv)

from app import project
from app.core import state as st, versions
from app.ui.bridge import Bridge

results = []


def check(name, cond):
    results.append((name, bool(cond)))


tmp = tempfile.mkdtemp(prefix="qbn_lock_proj_")
proj = project.create_project(tmp, "锁定探针")
chapter_path = project.get_chapter_path(proj, 1, "开场")
project.write_file(chapter_path, "# 第1章 开场\n\n正文内容。")
project.write_file(project.get_outline_path(proj, 1), "### 第 1 章：开场\n- 核心事件…")

# ---- ① project 层锁守卫 ----
check("初始未锁", project.is_chapter_locked(proj, 1) is False)
project.set_chapter_locked(proj, 1, True)
check("锁定后 is_locked", project.is_chapter_locked(proj, 1) is True)
ann = os.path.join(proj, "正文", ".annotations", "第1章.json")
check("标注仓含 locked", os.path.exists(ann) and "locked" in open(ann, encoding="utf-8").read())
# 标注仓兼容：先写批注再锁定，批注字段保留
import json
data = json.load(open(ann, encoding="utf-8"))
data["annotations"] = [{"kind": "comment", "quote": "x", "note": "n", "pos": 0.1}]
json.dump(data, open(ann, "w", encoding="utf-8"), ensure_ascii=False)
project.set_chapter_locked(proj, 1, True)
data2 = json.load(open(ann, encoding="utf-8"))
check("锁定保留批注字段", len(data2.get("annotations", [])) == 1 and data2.get("locked") is True)

# ---- ② attempt_unlock 唯一放行 ----
check("attempt_unlock 放行", project.attempt_unlock(proj, 1) is True
      and project.is_chapter_locked(proj, 1) is False)
check("未锁 attempt 返回 False", project.attempt_unlock(proj, 1) is False)

# ---- ③ 版本历史保留（锁定不删版本） ----
versions.snapshot(proj, 1, "旧内容", versions.SOURCE_FINALIZE)
vs_before = [v["v"] for v in versions.list_versions(proj, 1)]
project.set_chapter_locked(proj, 1, True)
project.attempt_unlock(proj, 1)
vs_after = [v["v"] for v in versions.list_versions(proj, 1)]
check("锁定/解锁不动版本历史", vs_before == vs_after and vs_before)

# ---- ④ bridge 语义：确认锁定 → 保存拒绝 → 解锁放行 ----
b = Bridge()
b.openProject(proj)
b.openChapter(1)
check("bridge 初始未锁", b.chapterLocked is False)
b.confirmChapterLocked()
check("confirmChapterLocked 锁定", b.chapterLocked is True)
b.saveChapterText("# 第1章 开场\n\n被篡改的内容。")
check("锁定章保存被拒", "被篡改" not in project.read_file(chapter_path))
b.unlockChapter()
check("unlockChapter 解锁", b.chapterLocked is False)
b.saveChapterText("# 第1章 开场\n\n修改后的内容。")
check("解锁后保存放行", "修改后的内容" in project.read_file(chapter_path))

# ---- ⑤ 档位迁移保持锁定（不降级）----
project.set_chapter_locked(proj, 1, True)
b.setCwMode(True)
check("进共写档锁定保持", project.is_chapter_locked(proj, 1) is True)
b.setCwMode(False)
check("回自动档锁定保持", project.is_chapter_locked(proj, 1) is True)
project.attempt_unlock(proj, 1)

# ---- ⑥ 自动档定稿不产 locked（快照不触碰锁字段）----
project.set_chapter_locked(proj, 1, True)
versions.snapshot(proj, 1, "新内容", versions.SOURCE_FINALIZE)
check("快照不触碰锁定", project.is_chapter_locked(proj, 1) is True)
project.attempt_unlock(proj, 1)

print("=== 章节锁定探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
