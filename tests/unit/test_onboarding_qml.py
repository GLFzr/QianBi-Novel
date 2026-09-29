# -*- coding: utf-8 -*-
"""onboarding M 批 QML 静态装配断言（OB-M3 横幅 / OB-M4 示例书入口 / OB-M2 向导表单）

QML 逻辑不进 pytest 的单元面（无引擎不跑绑定），这里钉「装配契约」：
- 消费的桥面出口真实存在（bridge.py 源码交叉比对，防手滑改名静默断链）；
- objectName / 关键文案在场（探针/演示/走查按名寻址的钉子）；
- 缺省态零噪音（就绪横幅全绿即隐藏、空态入口只在内容包可用时出现）。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

QML_ROOT = os.path.join(ROOT, "app", "ui", "qml")


def _read(rel: str) -> str:
    with open(os.path.join(QML_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _bridge_src() -> str:
    with open(os.path.join(ROOT, "app", "ui", "bridge.py"), encoding="utf-8") as f:
        return f.read()


# ---------- OB-M3：书架就绪横幅 ----------

def test_m3_banner_wiring():
    """横幅消费 connReadySummary（与向导 checklist 同一判定源），缺啥点啥直达"""
    src = _read("BookshelfPanel.qml")
    assert "bridge.connReadySummary" in src, "就绪横幅未接 connReadySummary——与向导判定漂移"
    # 三态 checklist：三槽全列 + 首书一行
    assert 'text: "书架"' in src
    assert "第一本书" in src, "首书态缺席"
    # 直达：连接缺项 → 设置面板；缺书 → 新建对话框
    assert 'mainWindow.activePanel = "settings"' in src
    assert "newProjectDialog.open()" in src
    # 桥面出口真实存在且带 notify（QML 绑定才会在配置变化时刷新）
    bsrc = _bridge_src()
    assert re.search(r"def connReadySummary\(self\)", bsrc)
    assert re.search(r"def _slot_readiness\(self", bsrc)


def test_m3_banner_silent_when_ready():
    """就绪即隐藏（零噪音）：横幅 visible 绑定含「全部就绪则不显示」分支"""
    src = _read("BookshelfPanel.qml")
    assert re.search(r"visible:\s*shelf\.items\.length === 0\s*\|\|\s*"
                     r"bridge\.connReadySummary\.some", src), \
        "横幅 visible 条件不含「空书 ∨ 存在缺项」——全绿时横幅不该出现"


# ---------- OB-M4：零 Key 静态示例书入口 ----------

def test_m4_demo_book_entry_wiring():
    """空态第二入口接 openDemoBook；复制半边与只读守卫真实存在"""
    src = _read("BookshelfPanel.qml")
    assert "bridge.openDemoBook()" in src, "空态缺「打开示例书」入口"
    assert 'objectName: "openDemoBookButton"' in src
    assert "零 Key" in src and "只读" in src, "入口文案必须写明零 Key 与只读（诚实边界）"
    bsrc = _bridge_src()
    assert re.search(r"def openDemoBook\(self\)", bsrc)
    assert re.search(r"def _demo_book_reason\(self\)", bsrc), "只读守卫缺席"
    assert re.search(r"def unpack_book\(", open(os.path.join(
        ROOT, "app", "ui", "demo_pack.py"), encoding="utf-8").read()), "复制半边缺席"


def test_m4_guard_covers_generation_entries():
    """七入口守卫在场（少一处就是一处「示例书能被改」的谎）：流水线/对话/草案/
    确定/去味审校/局部改写/整章重写"""
    bsrc = _bridge_src()
    for fn in ("startPipeline", "submitCwMessage", "generateCwDraft", "confirmCwStage",
               "_start_cw_prose_check", "rewriteSelection", "_rewrite_chapter_common"):
        # 逐函数取源（下一个同级 def 之前）断言守卫在场
        m = re.search(rf"    def {fn}\(.*?(?=\n    def |\n    [A-Z_]+ = )", bsrc, re.S)
        assert m, f"未定位到 {fn}"
        assert "_demo_book_reason()" in m.group(0), f"{fn} 缺示例书只读守卫"
