# -*- coding: utf-8 -*-
"""共写档状态机探针（无需 LLM / 无网络）：六阶段推进 / 打回级联矩阵 / reopen 回边 / 档位迁移"""
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())

from app import project
from app.core import state as st
from app.core.co_writing import CoWriting
from app.core import co_dialogue

results = []


def check(name, cond):
    results.append((name, bool(cond)))


def make_proj():
    tmp = tempfile.mkdtemp(prefix="qbn_cw_proj_")
    proj = project.create_project(tmp, "共写探针")
    project.write_idea_info(proj, "悬疑", "番茄", "主角捡到能改命的笔记", 100)
    return proj


def full_products(proj):
    """造出全部六阶段产物（用于打回矩阵）"""
    project.write_file(os.path.join(proj, "设定", "题材定位.md"), "# 题材定位\n\n## 主要角色表\n| 角色 | 定位 |")
    project.write_file(os.path.join(proj, "大纲", "大纲.md"), "# 全书大纲\n\n## 第1章-第30章 开篇单元\n预计总字数：100")
    project.write_file(os.path.join(proj, "设定", "世界书.md"), "## 世界书\n力量体系…")
    project.write_file(os.path.join(proj, "设定", "正则.md"), "## 正则（逻辑约束规则集）\n- 规则：…｜level：must｜scope：全书")
    project.write_file(os.path.join(proj, "大纲", "单元总纲.md"), "## 单元总纲\n- 单元主题：开篇")
    project.write_file(project.get_outline_path(proj, 1), "### 第 1 章：开场\n- 核心事件…")
    project.write_file(project.get_outline_path(proj, 2), "### 第 2 章：摊牌\n- 核心事件…")


# ---- 1. 六阶段推进 ----
proj = make_proj()
cw = CoWriting(proj)
state = cw.load()
st.ensure_cw(state)["mode"] = "cw"
check("初始阶段=cw_project", st.ensure_cw(state).get("stage") == st.STAGE_CW_PROJECT)
order = [st.STAGE_CW_CORE, st.STAGE_CW_OUTLINE, st.STAGE_CW_WORLDBOOK,
         st.STAGE_CW_UNIT, st.STAGE_CW_PROSE]
for expect in order:
    nxt = cw.advance(state)
    check(f"推进到 {expect}", nxt == expect and st.ensure_cw(state).get("stage") == expect)
check("prose 为终态不前", cw.advance(state) == st.STAGE_CW_PROSE
      and st.ensure_cw(state).get("stage") == st.STAGE_CW_PROSE)

# ---- 2. 打回级联矩阵（各阶段逐行验证失效清单 + 归档 + 阶段回退）----
proj2 = make_proj()
full_products(proj2)
cw2 = CoWriting(proj2)
state2 = cw2.load()
st.ensure_cw(state2)["stage"] = st.STAGE_CW_PROSE
st.ensure_cw(state2)["handoff"] = {"cw_core": "h1", "cw_outline": "h2", "cw_worldbook": "h3"}
cw2.save(state2)

def exists(rel):
    return os.path.exists(os.path.join(proj2, rel))

def rollback_case(key, gone, kept, expect_stage):
    s0 = cw2.load()
    st.ensure_cw(s0)["stage"] = st.STAGE_CW_PROSE
    cw2.save(s0)
    s = cw2.load()
    r = cw2.rollback(s, key)
    cw2.save(s)   # 打回结果必须落盘，后续断言读磁盘
    ok = all(not exists(g) for g in gone) and all(exists(k) for k in kept)
    state_t = cw2.load()
    ok = ok and st.ensure_cw(state_t).get("stage") == expect_stage
    roll_dir = os.path.join(proj2, "pipeline_debug", "rollback")
    ok = ok and os.path.isdir(roll_dir) and any(d.startswith(f"cw_{key}_") for d in os.listdir(roll_dir))
    # 归档文件数与失效数一致（抽查最新一次打回）
    latest = sorted([d for d in os.listdir(roll_dir) if d.startswith(f"cw_{key}_")])[-1]
    archived_n = len(os.listdir(os.path.join(roll_dir, latest)))
    check(f"打回 {key} 级联+归档+回退", ok and archived_n == len(gone))
    # 复原产物供下一用例
    full_products(proj2)
    cw2.save(cw2.load())

rollback_case(st.STAGE_CW_CORE,
              gone=["大纲/大纲.md", "设定/世界书.md",
                    "设定/正则.md", "大纲/单元总纲.md", "大纲/细纲_第001章.md", "大纲/细纲_第002章.md"],
              kept=["设定/题材定位.md"], expect_stage=st.STAGE_CW_CORE)
rollback_case(st.STAGE_CW_OUTLINE,
              gone=["大纲/细纲_第001章.md", "大纲/细纲_第002章.md", "大纲/单元总纲.md"],
              kept=["设定/题材定位.md", "大纲/大纲.md", "设定/世界书.md", "设定/正则.md"],
              expect_stage=st.STAGE_CW_OUTLINE)
rollback_case(st.STAGE_CW_WORLDBOOK,
              gone=["大纲/细纲_第001章.md", "大纲/细纲_第002章.md", "大纲/单元总纲.md"],
              kept=["设定/世界书.md", "设定/正则.md"],
              expect_stage=st.STAGE_CW_WORLDBOOK)
rollback_case(st.STAGE_CW_UNIT,
              gone=["大纲/细纲_第001章.md", "大纲/细纲_第002章.md"],
              kept=["大纲/单元总纲.md"],
              expect_stage=st.STAGE_CW_UNIT)
check("打回清除下游交接块", all(not st.ensure_cw(cw2.load()).get("handoff", {}).get(k)
                              for k in st.CW_STAGE_ORDER))

# ---- 3. reopen 世界书回边（软切不级联）----
proj3 = make_proj()
full_products(proj3)
cw3 = CoWriting(proj3)
state3 = cw3.load()
st.ensure_cw(state3)["stage"] = st.STAGE_CW_UNIT
cw3.save(state3)
check("cw_unit 可回看世界书", cw3.can_reopen(state3))
check("reopen 软切到世界书", cw3.reopen(state3) == st.STAGE_CW_WORLDBOOK
      and st.ensure_cw(state3).get("reopening") == st.STAGE_CW_UNIT)
check("reopen 不级联删除", exists3 := os.path.exists(os.path.join(proj3, "大纲", "细纲_第001章.md"))
      and os.path.exists(os.path.join(proj3, "大纲", "单元总纲.md")))
check("reopen 重确定返回原阶段", cw3.confirm_reopen_return(state3) == st.STAGE_CW_UNIT
      and st.ensure_cw(state3).get("reopening") == "")
check("prose 阶段也可回看", (st.ensure_cw(state3).__setitem__("stage", st.STAGE_CW_PROSE) or True)
      and cw3.can_reopen(state3))

# ---- 4. 档位迁移与粘性 ----
proj4 = make_proj()
project.write_file(os.path.join(proj4, "设定", "题材定位.md"), "# 题材定位\n## 主要角色表\n| 角色 |")
cw4 = CoWriting(proj4)
state4 = cw4.load()
cw4.migrate_mode(state4, True)
check("进共写档按产物推断阶段", st.ensure_cw(state4).get("stage") == st.STAGE_CW_OUTLINE)
cw4.migrate_mode(state4, False)
check("切回自动档粘性保留", st.ensure_cw(state4).get("mode") == "auto")

# ---- 5. 转写管理 + 交接块 ----
proj5 = make_proj()
cw5 = CoWriting(proj5)
state5 = cw5.load()
for i in range(30):
    co_dialogue.transcript_append(state5, st.STAGE_CW_CORE, "user" if i % 2 == 0 else "agent", f"第{i}轮讨论内容" + "字" * 200)
tail = co_dialogue.transcript_text(state5, st.STAGE_CW_CORE)
check("转写截断 ≤4000 字", len(tail) <= 4000 and "第29轮" in tail)
product, handoff = co_dialogue.build_handoff(st.STAGE_CW_CORE,
    "## 题材定位\n悬疑。\n\n→ 下阶段交接\n- 关键事实：金手指=改命笔记\n- 开放问题：代价未定")
check("build_handoff 拆分", "题材定位" in product and "改命笔记" in handoff)
co_dialogue.store_handoff(state5, st.STAGE_CW_CORE, handoff)
check("下一阶段只读交接块", "改命笔记" in co_dialogue.prev_handoff(state5, st.STAGE_CW_OUTLINE))
p2, h2 = co_dialogue.build_handoff(st.STAGE_CW_OUTLINE, "没有交接小节的产物全文")
check("缺交接小节容错", p2 == "没有交接小节的产物全文" and h2 == "")

print("=== 共写档状态机探针 ===")
ok = True
for name, passed in results:
    print(("PASS" if passed else "FAIL"), name)
    ok = ok and passed
print("TOTAL", f"{sum(1 for _, p in results if p)} / {len(results)}")
sys.exit(0 if ok else 1)
