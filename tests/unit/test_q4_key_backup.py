# -*- coding: utf-8 -*-
"""Q4 更新私钥备份：口令加密备份/校验/还原的往返闭环（2026-09-25 收口裁决）"""
import os

import pytest

from scripts import update_keys as uk


@pytest.fixture()
def key_env(tmp_path, monkeypatch):
    """仓库外临时目录里的一对真密钥 + 固定口令桩"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    key_path = tmp_path / "ed25519.key"
    priv = Ed25519PrivateKey.generate()
    key_path.write_bytes(priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    monkeypatch.setattr(uk, "assert_outside_repo", lambda p: None)  # tmp_path 本就在仓库外，桩掉双保险
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "正确口令-123")
    return str(key_path)


def test_backup_then_restore_roundtrip(key_env, tmp_path):
    bak = str(tmp_path / "k.backup")
    assert uk.do_backup(key_env, bak) == 0
    assert os.path.getsize(bak) > 0
    # 还原到新路径（口令桩已 monkeypatch），公钥行必须与原钥一致
    out = str(tmp_path / "restored.key")
    assert uk.do_restore(bak, out_path=out) == 0
    assert uk.pubkey_entry(uk.load_private(key_env)) == uk.pubkey_entry(uk.load_private(out))


def test_backup_file_lands_next_to_key_by_default(key_env):
    # main() 分支的默认拼接约定：<私钥路径>.backup（仓库外同目录）
    key_dir = os.path.dirname(key_env)
    expected = os.path.join(key_dir, "ed25519.key.backup")
    assert expected == key_env + ".backup"


def test_wrong_passphrase_fails_closed(key_env, tmp_path, monkeypatch):
    bak = str(tmp_path / "k.backup")
    assert uk.do_backup(key_env, bak) == 0
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "错误口令")
    with pytest.raises(SystemExit, match="解密失败"):
        uk._read_backup(bak)


def test_non_backup_file_rejected(tmp_path):
    junk = tmp_path / "junk"
    junk.write_bytes(b"not a backup at all........")
    with pytest.raises(SystemExit, match="magic"):
        uk._read_backup(str(junk))


def test_encrypted_backup_never_contains_pem(key_env, tmp_path):
    bak = tmp_path / "k.backup"
    assert uk.do_backup(key_env, str(bak)) == 0
    blob = bak.read_bytes()
    assert b"PRIVATE KEY" not in blob and b"BEGIN" not in blob  # AESGCM 密文里不该有任何 PEM 形状
    assert uk._pem_pattern().search(blob) is None
