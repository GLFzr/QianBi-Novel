# -*- coding: utf-8 -*-
"""原作世界书导入探针（同人档 · 新建项目链路）

真 Bridge 真跑 `newProject(..., worldbookFile=...)`——从建目录到落盘全程走一遍，
不 mock 任何一层。盯的都是「用户以为导进去了」会翻车的地方：
① 酒馆世界书 JSON → 世界书.md 条目，wb.parse 认得出、触发标记不丢；
② 纯文本 → 原作世界书.md 存档，绝不混进 世界书.md（不进 prompt）；
③ 空参数（不导入）老路径零变化；
④ 导入文件不存在 → 项目照常创建，只用 toast 报错。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probe_guard import arm_config_guard      # noqa: E402

arm_config_guard()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtGui import QGuiApplication     # noqa: E402

from app import project                       # noqa: E402
from app.ui.bridge import Bridge              # noqa: E402

results = []
toasts = []


def check(name, ok, extra=""):
    results.append((name, bool(ok), extra))


app = QGuiApplication(sys.argv[:1])
b = Bridge()
b.toast.connect(lambda lv, msg: toasts.append((lv, str(msg))))

tmp = tempfile.mkdtemp(prefix="qianbi_wb_import_")
ST_BOOK = {"entries": {
    "0": {"uid": 0, "key": ["灯盟"], "comment": "灯盟", "constant": False,
          "disable": False, "content": "控制当铺的联盟。"},
    "1": {"uid": 1, "key": [], "comment": "玛娜潮汐", "constant": True,
          "disable": False, "content": "魔力每七天一次涨潮。"},
}}

# ---- ① 世界书 JSON 随新项目导入 ----
st_file = os.path.join(tmp, "worldbook.json")
with open(st_file, "w", encoding="utf-8") as f:
    json.dump(ST_BOOK, f, ensure_ascii=False)
loc1 = os.path.join(tmp, "shelf1")
os.makedirs(loc1)
toasts.clear()
ok = b.newProject(loc1, "同人书甲", "同人", "番茄", 30, "千笔同人测试", "", st_file)
check("JSON 导入：项目创建成功", ok)
proj1 = os.path.join(loc1, "同人书甲")
check("JSON 导入：项目目录成型", project.is_project(proj1))
check("JSON 导入：toast 报告条目数",
      any("2 条" in m for _lv, m in toasts), str(toasts[:2]))
wb_doc = project.read_file(os.path.join(proj1, project.WORLDBOOK_PATH))
entries = project.wb.parse(wb_doc)
names = [e.name for e in entries]
check("JSON 导入：条目被 wb.parse 认出", {"灯盟", "玛娜潮汐"} <= set(names), str(names))
check("JSON 导入：常驻标记保留",
      any(e.meta["constant"] for e in entries))
check("JSON 导入：关键词标记保留",
      any("灯盟" in e.meta["keywords"] for e in entries))

# ---- ② 纯文本随新项目导入 ----
txt_file = os.path.join(tmp, "原作设定.txt")
with open(txt_file, "w", encoding="utf-8") as f:
    f.write("青云宗：正道第一大派。")
loc2 = os.path.join(tmp, "shelf2")
os.makedirs(loc2)
toasts.clear()
ok = b.newProject(loc2, "同人书乙", "同人", "番茄", 30, "", "", txt_file)
proj2 = os.path.join(loc2, "同人书乙")
check("文本导入：世界书.md 保持为空",
      not project.read_file(os.path.join(proj2, project.WORLDBOOK_PATH)).strip())
archived = project.read_file(os.path.join(proj2, project.WORLDBOOK_SOURCE_PATH))
check("文本导入：原作世界书.md 存档", "青云宗" in archived, archived[:80])
check("文本导入：toast 指明存档位置", any("原作世界书.md" in m for _lv, m in toasts))

# ---- ③ 不传世界书：老路径零变化 ----
loc3 = os.path.join(tmp, "shelf3")
os.makedirs(loc3)
ok = b.newProject(loc3, "普通书", "都市", "番茄", 50, "", "", "")
proj3 = os.path.join(loc3, "普通书")
check("无导入：项目照常创建", ok and project.is_project(proj3))
check("无导入：不产生世界书文件",
      not os.path.exists(os.path.join(proj3, project.WORLDBOOK_PATH))
      and not os.path.exists(os.path.join(proj3, project.WORLDBOOK_SOURCE_PATH)))

# ---- ④ 文件不存在：项目照建，toast 报错 ----
loc4 = os.path.join(tmp, "shelf4")
os.makedirs(loc4)
toasts.clear()
ok = b.newProject(loc4, "书丁", "都市", "番茄", 50, "", "", os.path.join(tmp, "没有.json"))
check("坏路径：项目照常创建", ok and project.is_project(os.path.join(loc4, "书丁")))
check("坏路径：toast 报导入失败", any("导入失败" in m for _lv, m in toasts), str(toasts[:2]))

# ---- 清理 ----
import shutil
shutil.rmtree(tmp, ignore_errors=True)

failed = [r for r in results if not r[1]]
for name, ok_, extra in results:
    print(("PASS" if ok_ else "FAIL"), name, ("| " + extra[:120] if extra and not ok_ else ""))
print("TOTAL %d / %d" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
