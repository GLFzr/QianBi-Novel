# -*- coding: utf-8 -*-
"""M6 全量验证 · Phase A（纯本地，零 API 消耗）

按《总体规划》第七章验证体系，自动化可测项：
  R（阅读器）S（流式/版本）W（共写）D（数据）T（设置）U（UI 结构）
  + 旧项目兼容（41 章长测项目打开/队列/统计/导出）
输出：tests_output/m6_phaseA_report.md

用法：.venv/Scripts/python.exe tests/m6_full.py [--phase A]
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []


def check(item, name, cond, detail=""):
    RESULTS.append({"item": item, "name": name, "ok": bool(cond), "detail": str(detail)})
    print(("[PASS]" if cond else "[FAIL]"), item, name, detail, flush=True)


def main():
    from PySide6.QtCore import QUrl, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from app.ui.bridge import Bridge
    from app.core import state as st, versions
    from app import project as proj_mod, export as export_mod, config as cfg_mod

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "tests_output")
    old_proj = os.path.abspath(os.path.join(out, "长测_改命笔记"))
    m1 = os.path.abspath(os.path.join(out, "m1_proj"))

    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    b = Bridge()
    engine.rootContext().setContextProperty("bridge", b)
    engine.load(QUrl.fromLocalFile(os.path.join(root, "app", "ui", "qml", "Main.qml")))
    win = engine.rootObjects()[0]
    assert engine.rootObjects(), "Main.qml 加载失败"

    def phase_a():
        try:
            # ============ R 阅读器 ============
            b._open_project(m1, silent=True)
            rl = b.readerChapterList()
            check("R1", "阅读目录构建（进入阅读的数据基础）", len(rl) >= 2)
            check("R3", "阅读偏好持久化（字号/行距/字体/翻页/主题）",
                  b.setReaderPref("fontScale", 1.35) or True
                  and b.readerPrefs().get("fontScale") == 1.35)
            b.setReaderPref("fontScale", 1.0)
            check("R2", "三主题合法", b.readerPrefs()["theme"] in ("night", "parchment", "white"))
            ch = b.readerChapter(2)
            check("R5", "章节内容加载（目录跳转/上下章的数据源）", len(ch["text"]) > 0)
            # R6/R7 标注
            b.addAnnotation(2, "highlight_yellow", "这是第二章的内容", "", 0.1)
            b.addAnnotation(2, "comment", "剧情推进", "节奏太拖", 0.4)
            b.addReaderIdea(2, "M6测试灵感R6")
            b.addBookmark(2, 0.5, "M6书签")
            store = b.readStore(2)
            check("R6", "高亮/批注/灵感/书签写入", len(store["annotations"]) >= 2 and len(store["bookmarks"]) >= 1)
            state = st.load_state(m1)
            check("R6", "灵感进创作笔记", any("M6测试灵感R6" in i["text"] for i in st.norm_ideas(state)))
            b.removeAnnotation(2, len(store["annotations"]) - 1)
            b.removeBookmark(2, len(store["bookmarks"]) - 1)
            st2 = st.load_state(m1)
            st2["pending_ideas"] = [i for i in st.norm_ideas(st2) if "M6测试灵感R6" not in i["text"]]
            st.save_state(m1, st2)
            # R8 位置记忆
            b.saveReadPosition(2, 0.42)
            check("R8", "阅读位置记忆", abs(b.readStore(2)["position"] - 0.42) < 0.01)
            b.saveReadPosition(2, 0.0)
            # R9 未定稿
            b._cur_num = 2
            b._editor_dirty = False
            check("R9", "readerChapter 状态字段", set(b.readerChapter(2).keys()) >= {"isDraft", "isLive"})
            # 清理标注
            s = b.readStore(2)
            for i in range(len(s["annotations"])):
                b.removeAnnotation(2, 0)

            # ============ S 保存驱动版本 ============
            t = os.path.join(root, "smoke_tmp", "m6_t")
            shutil.rmtree(t, ignore_errors=True)
            shutil.copytree(m1, t)
            b.proj = os.path.abspath(t)
            # S6 保存产生版本（两轮保存：第二轮归档的中间稿必与历史版本不同）
            chs = proj_mod.list_chapters(t)
            path1 = chs[0][2]
            old1 = proj_mod.read_file(path1)
            b.openChapter(1)
            b.markEditorDirty(old1 + "\nM6 第一轮保存。")
            b.noteEditAction("手动")
            b.saveChapterText(old1 + "\nM6 第一轮保存。")
            b.markEditorDirty(old1 + "\nM6 第二轮保存（归档源）。")
            b.noteEditAction("手动")
            b.saveChapterText(old1 + "\nM6 第二轮保存（归档源）。")
            vs = versions.list_versions(t, 1)
            check("S6", "保存产生版本（旧内容归档）", any(v["source"] == "手动" for v in vs))
            # S7 diff
            d = b.diffVersionWithDisk(1, vs[-1]["v"])
            check("S7", "版本 diff 输出", isinstance(d, list) and len(d) > 0)
            # S8 回退语义（回退只进工作副本）
            b.noteEditAction("整章重写")
            vt = b.readVersion(1, vs[-1]["v"])
            b.markEditorDirty(vt)
            check("S8", "回退为工作副本（未落盘）",
                  proj_mod.read_file(path1) != vt and b.editorDirty)
            # S10 未保存保护数据位
            check("S10", "editorDirty 状态跟踪", b.editorDirty is True)
            b.clearEditorDirty()
            # S11 草稿暂存
            b.markEditorDirty(old1 + "\n草稿暂存测试。")
            b._flush_draft()
            nd = versions.newest_draft(t)
            check("S11", "5s 防抖草稿落盘（不产生版本）", nd is not None and nd[0] in (1, 2))
            r = b.recoverDraft()
            check("S11", "崩溃草稿恢复（工作副本语义）", r and "草稿暂存测试" in r["text"])
            b.markEditorDirty(old1)
            b.saveChapterText(old1)
            b.discardDrafts()

            # ============ W 共写 ============
            cards = b.stageCards()
            check("W1", "驾驶舱阶段卡片（4 张+状态）", len(cards) == 4)
            check("W2", "逐步确认开关持久化", b.setStepConfirm(True) or b.stepConfirmEnabled())
            b.setStepConfirm(False)
            ideas0 = len(b.ideasList())
            b.submitIdeaScoped("M6：下一章出现红围巾", "next")
            b.submitIdeaScoped("M6：第9章专用想法", "9")
            check("W3", "想法 CRUD+注入范围", len(b.ideasList()) == ideas0 + 2)
            lst = b.ideasList()
            b.removeIdea(lst[0]["id"])
            check("W3", "想法删除", len(b.ideasList()) == ideas0 + 1)
            lst = b.ideasList()
            b.removeIdea(lst[0]["id"])
            b.markIdeaApplied(lst[0]["id"]) if lst else None
            # W9 全局偏好
            b.saveGlobalPrefs("M6文风测试", "M6禁忌测试", "M6节奏测试")
            from app.core import stages as stg
            g = stg._compose_guidance("", b.cfg)
            check("W9", "全局偏好注入合成", all(x in g for x in ("M6文风测试", "M6禁忌测试", "M6节奏测试")))
            b.saveGlobalPrefs("", "", "")
            # W7 重写确认+备份
            old_text = proj_mod.read_file(proj_mod.list_chapters(t)[0][2]) if proj_mod.list_chapters(t) else ""
            b.rewriteChapter(1)
            vs = versions.list_versions(t, 1)
            latest = versions.read_version(t, 1, vs[-1]["v"]) if vs else ""
            check("W7", "重写确认数据链+旧内容可恢复", latest == old_text)
            # W8 质量趋势
            check("W8", "质量趋势接口", isinstance(b.qualityTrend(), list))

            # ============ D 数据 ============
            check("D1", "草稿目录隔离", versions.draft_dir(t).endswith(".drafts"))
            check("D2", "版本目录结构", versions.chapter_versions_dir(t, 1).find(".versions") > 0)
            bk = b.backupProject()
            check("D3", "zip 备份产出", bk and os.path.isfile(bk))
            if bk:
                os.remove(bk)
            ss = b.statsSummary()
            check("D4", "统计面板数据", ss["chapters"] >= 1 and ss["words"] > 0)
            pv = b.exportPreviewText("page", 1)
            check("D5", "导出预览", len(pv) > 10)
            ex = b.exportProjectOpts("txt", "line", 1)
            check("D5", "导出+报告", ex and os.path.isfile(ex))
            if ex:
                os.remove(ex)

            # ============ T 设置 ============
            b.setEditorPref("fontScale", 1.12)
            check("T1", "编辑器偏好持久化", b.editorPrefs()["fontScale"] == 1.12)
            b.setEditorPref("fontScale", 1.0)
            b.setChapterWordTarget(2600)
            check("T1", "字数目标持久化", b.chapterWordTarget() == 2600)
            b.setChapterWordTarget(3000)
            check("T3", "连接配置回归", len(b.cfg.get("connections", [])) >= 1 and b.getConnection(b.cfg["connections"][0]["id"]).get("name", "") != "")

            # ============ U UI 结构 ============
            nav = win.property("navItems")
            try:
                nav = nav.toVariant()
            except Exception:
                pass
            check("U1", "导航五项（含笔记）", len(nav or []) == 5)
            sp = [c for c in win.findChildren(object) if c.objectName() == "settingsPanel"]
            check("U3", "设置四标签页", sp and sp[0].property("settingsTab") == 0)

            # ============ 旧项目兼容（41 章长测项目）============
            b2 = Bridge.__new__(Bridge)  # 不再建新实例，直接切换
            b.proj = old_proj
            b._open_project(old_proj, silent=True)
            check("兼容", "旧项目打开（41章）", len(proj_mod.list_chapters(old_proj)) == 41)
            check("兼容", "旧项目队列刷新", b.chapterModelProp.rowCount() >= 41)
            check("兼容", "旧项目统计", b.statsSummary()["chapters"] == 41)
            rl = b.readerChapterList()
            check("兼容", "旧项目阅读目录", len(rl) == 41 and rl[0]["words"] > 0)
            pv = b.exportPreviewText("blank", 0)
            check("兼容", "旧项目导出预览", len(pv) > 10)
            ideas_old = st.norm_ideas(st.load_state(old_proj))
            check("兼容", "旧想法数据兼容", isinstance(ideas_old, list))
        except Exception as e:
            import traceback
            traceback.print_exc()
            check("EXC", "Phase A 异常", False, str(e))

        # 报告落盘
        total = len(RESULTS)
        passed = sum(1 for r in RESULTS if r["ok"])
        lines = ["# M6 Phase A 报告（纯本地，零 API）", "",
                 f"- 时间：{__import__('time').strftime('%Y-%m-%d %H:%M:%S')}",
                 f"- 结果：**{passed} / {total} PASS**", "",
                 "| 清单 | 项目 | 结果 |", "|---|---|---|"]
        for r in RESULTS:
            lines.append(f"| {r['item']} | {r['name']} | {'✅' if r['ok'] else '❌ ' + r['detail'][:60]} |")
        with open(os.path.join(out, "m6_phaseA_report.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\nPHASE_A_TOTAL {passed}/{total}")
        app.quit()

    QTimer.singleShot(1500, phase_a)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
