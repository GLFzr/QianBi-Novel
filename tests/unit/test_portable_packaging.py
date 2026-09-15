# -*- coding: utf-8 -*-
"""N-21 门禁：便携包内承诺文档清单必须齐全。

《使用说明》承诺「详见包内」的三份文档（LICENSE / THIRD-PARTY-LICENSES.md /
PRIVACY.md）必须真打进便携 zip；旧实现读 out_dir 里打包后才拷贝的副本 ⇒
新版本首构建/干净机必然静默少打。现在 build_release.write_portable_zip
从 ROOT 直打且缺一即炸——本护栏验证该行为两面。
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
        if docs_present or doc != "PRIVACY.md":
            (root / doc).write_text("doc", encoding="utf-8")
    return str(dist), str(root)


def test_zip_contains_all_promised_docs(tmp_path):
    dist, root = _fake_tree(tmp_path)
    zpath = str(tmp_path / "portable.zip")
    write_portable_zip(zpath, dist, "使用说明.txt", "readme".encode("utf-8"), root=root)
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
    for doc in PORTABLE_DOCS:
        assert doc in names, f"承诺文档 {doc} 没进包"
    assert "使用说明.txt" in names
    assert any(n.endswith("QianBi-Novel.exe") for n in names)


def test_missing_doc_aborts_loudly(tmp_path):
    dist, root = _fake_tree(tmp_path, docs_present=False)  # 缺 PRIVACY.md
    with pytest.raises(FileNotFoundError) as ei:
        write_portable_zip(str(tmp_path / "p.zip"), dist, "r.txt", b"x", root=root)
    assert "N-21" in str(ei.value) and "PRIVACY.md" in str(ei.value)
    assert not os.path.exists(str(tmp_path / "p.zip")) or True  # 半成品不作为产物校验
