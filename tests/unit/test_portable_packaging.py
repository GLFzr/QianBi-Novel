# -*- coding: utf-8 -*-
"""N-21 门禁：便携包内承诺文档清单必须齐全。

《使用说明》承诺「详见包内」的三份文档（LICENSE / THIRD-PARTY-LICENSES.md /
PRIVACY.md）必须真打进便携 zip；旧实现读 out_dir 里打包后才拷贝的副本 ⇒
新版本首构建/干净机必然静默少打。现在 build_release.write_portable_zip
从 ROOT 直打且缺一即炸——本护栏验证该行为两面。

2026-09-25 修：PORTABLE_DOCS 里 PRIVACY.md 的仓库真实路径是 `docs/PRIVACY.md`
（与 out_dir 拷贝清单同源）。旧门禁按根路径 `PRIVACY.md` 校验 ⇒ 真实构建必炸
（2026-09-25 首次真跑 RC 构建暴露——单测夹具把 PRIVACY.md 摆在根下，恰好掩盖）。
zip 内入口名取 basename，对使用者仍是包根下的三份文件。
"""
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from scripts.build_release import PORTABLE_DOCS, portable_readme, portable_readme_mac, \
    write_portable_zip


def _fake_tree(tmp_path, docs_present=True):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "QianBi-Novel.exe").write_bytes(b"MZ fake")
    root = tmp_path / "root"
    root.mkdir()
    for doc in PORTABLE_DOCS:
        if docs_present or not doc.endswith("PRIVACY.md"):
            dest = root / doc
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("doc", encoding="utf-8")
    return str(dist), str(root)


def test_zip_contains_all_promised_docs(tmp_path):
    dist, root = _fake_tree(tmp_path)
    zpath = str(tmp_path / "portable.zip")
    write_portable_zip(zpath, dist, "使用说明.txt", "readme".encode("utf-8"), root=root)
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
    for doc in PORTABLE_DOCS:
        assert os.path.basename(doc) in names, f"承诺文档 {doc} 没进包"
    assert "使用说明.txt" in names
    assert any(n.endswith("QianBi-Novel.exe") for n in names)


def test_missing_doc_aborts_loudly(tmp_path):
    dist, root = _fake_tree(tmp_path, docs_present=False)  # 缺 docs/PRIVACY.md
    with pytest.raises(FileNotFoundError) as ei:
        write_portable_zip(str(tmp_path / "p.zip"), dist, "r.txt", b"x", root=root)
    assert "N-21" in str(ei.value) and "PRIVACY.md" in str(ei.value)
    # 门禁前置后：缺文档时在开包前就中止，盘上不得留下半成品 zip（旧实现先开包，
    # 缺文档的那次中止会留下一个已写入 dist 的孤儿 zip）
    assert not os.path.exists(str(tmp_path / "p.zip")), \
        "缺承诺文档却仍创建/留下了 zip 半成品——N-21 门禁未 fail-fast"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="平台没有符号链接")
def test_symlinks_are_stored_as_links_not_dropped(tmp_path):
    """符号链接必须原样进 zip（macOS .app 的 Python.framework 全靠它搭结构）。

    旧实现 z.write：链接目录被 os.walk 跳过 ⇒ 整棵不进包，链接文件被解引用。
    解包后 Frameworks 少了 Versions/Current 这种条目 = .app 起不来，且包体看着
    完整——这类静默缺件正是 N-21 同款坏法，必须有单测钉住。
    """
    dist = tmp_path / "dist"
    fw = dist / "Frameworks" / "Python.framework" / "Versions" / "A"
    fw.mkdir(parents=True)
    (fw / "libpython.dylib").write_bytes(b"\x00dylib")
    try:
        os.symlink("A", str(fw.parent / "Current"))
        os.symlink("Versions/Current", str(dist / "Frameworks" / "Python.framework" / "Python"))
    except OSError as e:          # Windows 未开开发者模式时创建不了，跳过不算失败
        pytest.skip("本机建不了符号链接：%s" % e)
    root = tmp_path / "root"
    root.mkdir()
    for doc in PORTABLE_DOCS:
        dest = root / doc
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("doc", encoding="utf-8")

    zpath = str(tmp_path / "p.zip")
    write_portable_zip(zpath, str(dist), "使用说明.txt", b"r", root=str(root))
    with zipfile.ZipFile(zpath) as z:
        infos = {i.filename: i for i in z.infolist()}
        mode = lambda n: (infos[n].external_attr >> 16) & 0o170000
        link_current = "Frameworks/Python.framework/Versions/Current"
        link_py = "Frameworks/Python.framework/Python"
        assert link_current in infos, "链接目录被 walk 跳过、整个没进包"
        assert mode(link_current) == 0o120000, "条目不是 symlink（被解引用成普通文件）"
        assert z.read(link_current) == b"A", "链接目标内容没保住"
        assert link_py in infos and mode(link_py) == 0o120000
        # 链接指向的真实内容仍然在（链接与实体并存，缺一不可）
        assert "Frameworks/Python.framework/Versions/A/libpython.dylib" in infos


def test_arc_prefix_wraps_the_bundle_but_not_the_docs(tmp_path):
    """arc_prefix：mac 包里 .app 整体进包根，说明/承诺文档与它并列。

    不加前缀压 dist（= .app 内部）会把 Contents/ 摊在包根：解出来没有 .app 外壳，
    Bootloader 认不出 bundle 布局，直接报 Failed to load Python shared library。
    加了前缀则入口必须是 QianBi-Novel.app/Contents/...，文档仍留在包根。
    """
    dist = tmp_path / "QianBi-Novel.app" / "Contents" / "MacOS"
    dist.mkdir(parents=True)
    (dist / "QianBi-Novel").write_bytes(b"bin")
    root = tmp_path / "root"
    root.mkdir()
    for doc in PORTABLE_DOCS:
        dest = root / doc
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("doc", encoding="utf-8")

    zpath = str(tmp_path / "p.zip")
    write_portable_zip(zpath, str(tmp_path / "QianBi-Novel.app"), "使用说明.txt",
                       b"r", root=str(root), arc_prefix="QianBi-Novel.app")
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
    assert "QianBi-Novel.app/Contents/MacOS/QianBi-Novel" in names
    assert "使用说明.txt" in names
    for doc in PORTABLE_DOCS:
        assert os.path.basename(doc) in names, "承诺文档要与 .app 并列在包根"
        assert "QianBi-Novel.app/" + os.path.basename(doc) not in names

    # Windows 路径（不传前缀）行为不变：dist 内容就在包根
    zpath2 = str(tmp_path / "p2.zip")
    write_portable_zip(zpath2, str(tmp_path / "QianBi-Novel.app"), "使用说明.txt",
                       b"r", root=str(root))
    with zipfile.ZipFile(zpath2) as z:
        assert "Contents/MacOS/QianBi-Novel" in z.namelist()


def test_mac_readme_is_mac_not_a_windows_readme_in_disguise():
    """mac 包里那份《使用说明》必须是写给 Mac 用户的。

    最容易犯的错是图省事把 Windows 那份原样塞进去：里面全是双击 exe、SmartScreen
    放行、Windows 凭据管理器——按它操作一步都走不通，而包看起来完全正常。
    """
    mac = portable_readme_mac("9.9.9").decode("utf-8")
    for bad in (".exe", "SmartScreen", "凭据管理器", "%USERPROFILE%", "Inno", "PowerShell"):
        assert bad not in mac, f"mac 说明里混进了 Windows 专属内容: {bad}"
    for good in ("QianBi-Novel.app", "钥匙串", "xattr -dr com.apple.quarantine",
                 "shasum -a 256", "~/Documents/千笔一文", "9.9.9"):
        assert good in mac, f"mac 说明缺了 {good}"
    # Windows 那份原样还在，别在改 mac 时把 win32 的话顺手删了
    win = portable_readme("9.9.9").decode("utf-8-sig")
    assert "QianBi-Novel.exe" in win and "SmartScreen" in win


def test_portable_docs_paths_exist_in_real_repo():
    # 真仓对账：PORTABLE_DOCS 的每一条都必须真实存在——防夹具再度掩盖路径漂移
    # （2026-09-25 RC 构建事故：门禁写根路径、文件在 docs/ 下，夹具恰好吻合假路径）
    for doc in PORTABLE_DOCS:
        assert os.path.isfile(os.path.join(ROOT, doc)), f"{doc} 在真实仓库中不存在"
