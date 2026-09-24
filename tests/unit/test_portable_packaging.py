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

from scripts.build_release import PORTABLE_DOCS, write_portable_zip


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


def test_portable_docs_paths_exist_in_real_repo():
    # 真仓对账：PORTABLE_DOCS 的每一条都必须真实存在——防夹具再度掩盖路径漂移
    # （2026-09-25 RC 构建事故：门禁写根路径、文件在 docs/ 下，夹具恰好吻合假路径）
    for doc in PORTABLE_DOCS:
        assert os.path.isfile(os.path.join(ROOT, doc)), f"{doc} 在真实仓库中不存在"
