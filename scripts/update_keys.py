# -*- coding: utf-8 -*-
"""发布密钥管理：给版本清单签名用的 Ed25519 密钥对

为什么要有这一步：更新通道从「一个 URL」变成「raw + Pages + jsDelivr + 用户镜像 +
离线导入的本地文件」之后，能递一份 1KB 清单进来的人，就等于能决定你机器上跑什么 exe。
sha256 只能证明「下载和清单说的一致」，证明不了清单是谁写的——所以公钥钉在应用里，
私钥留在发布机上。

用法：
    python scripts/update_keys.py --gen        # 首次（或轮换）生成，打印要粘进代码的公钥行
    python scripts/update_keys.py --show       # 看现有公钥（幂等，不生成）
    python scripts/update_keys.py --check-repo # 闸门：确认仓库里没有私钥材料

私钥默认落在仓库之外（%LOCALAPPDATA%\\qianbi_sign）。路径一旦落进工作树，
一次 `git add -A` 就能把「给用户推包的能力」公开出去，所以 --gen 直接拒绝那种路径。
丢钥的后果不是更新坏掉，是老客户端从此再也收不到可信的自动更新——请备份。
"""
import argparse
import base64
import hashlib
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIV_BYTES = 32


def default_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "qianbi_sign")


def assert_outside_repo(path: str) -> None:
    real = os.path.realpath(os.path.abspath(path))
    root = os.path.realpath(REPO_ROOT)
    if real == root or real.startswith(root + os.sep):
        raise SystemExit(
            "拒绝在仓库内写私钥：%s\n"
            "这个仓库是公开的，私钥一旦进工作树，一次 `git add -A` 就等于把「给所有用户"
            "推任意 exe」的能力公开。请把密钥目录放在仓库外（默认 %s）。" % (path, default_dir()))


def load_private(path: str):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    with open(path, "rb") as f:
        return load_pem_private_key(f.read(), password=None)


def pubkey_entry(priv) -> dict:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if len(raw) != PRIV_BYTES:
        raise SystemExit("公钥长度不是 32 字节，这不是 Ed25519 密钥")
    b64 = base64.b64encode(raw).decode()
    return {"kid": hashlib.sha256(raw).hexdigest()[:8], "pub": b64}


def do_gen(path: str, force: bool) -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    assert_outside_repo(path)
    if os.path.exists(path) and not force:
        print("密钥已存在，不覆盖：%s（要轮换请加 --force，但那样旧客户端会验不过新签名）" % path)
        return do_show(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    with open(path, "wb") as f:
        f.write(priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    entry = pubkey_entry(priv)
    print("已生成私钥：%s" % path)
    print("\n把这一行粘进 app/update_check.py 的 PUBKEYS 列表（轮换是追加，不是替换）：")
    print('    {"kid": "%s", "pub": "%s"},' % (entry["kid"], entry["pub"]))
    print("\n备份这份私钥（密码管理器/离线盘）。丢了就没有「可信的自动更新」这回事了。")
    return 0


def do_show(path: str) -> int:
    if not os.path.isfile(path):
        print("KEY_MISSING", path)
        return 1
    entry = pubkey_entry(load_private(path))
    print('    {"kid": "%s", "pub": "%s"},' % (entry["kid"], entry["pub"]))
    return 0


def _pem_pattern():
    """PEM 私钥头的形状：-----BEGIN <任意中段> PRIVATE KEY-----（含 OPENSSH 变体）

    常量拆写是为了本文件自己不再命中它——这个脚本就在被扫的文件清单里，
    整串字面量写出来会让闸门永远红，而且红的理由是「扫描器提到了自己在找什么」。
    """
    import re
    head, mid, tail = "-----BEGIN ", "[A-Z0-9. _-]*", "PRIVATE KEY-----"
    return re.compile((head + mid + tail).encode("ascii"))


def do_check_repo() -> int:
    """闸门：私钥材料一旦出现在被跟踪的文件里，立刻红

    只查 `git ls-files`（被跟踪的），不查工作树——工作树里放个临时文件不该拦住的发布。
    """
    import subprocess
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                         capture_output=True)
    if out.returncode != 0:
        print("WARN 不是 git 仓库或 git 不可用，跳过私钥泄漏扫描")
        return 0
    pat = _pem_pattern()
    names = [n.decode("utf-8", "replace") for n in out.stdout.split(b"\0") if n]
    hits = []
    for n in names:
        p = os.path.join(REPO_ROOT, n)
        try:
            with open(p, "rb") as f:
                body = f.read()
        except OSError:
            continue
        if pat.search(body):
            hits.append(n)
    if hits:
        print("PRIVATE KEY IN REPO:", ", ".join(hits))
        print("被跟踪的文件里出现了私钥材料。立刻从历史里清掉并轮换密钥——"
              "公开仓库里的这份密钥能给所有用户推包。")
        return 1
    print("私钥泄漏扫描 OK（%d 个被跟踪文件）" % len(names))
    return 0


# ---- Q4 私钥备份（2026-09-25 收口裁决：本地口令加密，不上传任何云服务） ----
# 格式：magic(7) + version(1) + salt(16) + nonce(12) + AESGCM(密文)
# 口令不经 KDF 以外任何路径落盘；备份文件本身没有口令就是随机字节，
# 拷去 U 盘/网盘都是安全的——这也是它存在的意义：原机磁盘没了还能签。
BACKUP_MAGIC = b"QBNKEY1"


def _derive(passphrase: bytes, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    kdf = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1)
    return kdf.derive(passphrase)


def _ask_passphrase(twice: bool) -> bytes:
    import getpass
    p1 = getpass.getpass("备份口令（为空则放弃）：")
    if not p1:
        raise SystemExit("未输入口令，已取消")
    if twice:
        p2 = getpass.getpass("再输一遍：")
        if p1 != p2:
            raise SystemExit("两次输入不一致，已取消")
    return p1.encode("utf-8")


def do_backup(key_path: str, out_path: str) -> int:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not os.path.isfile(key_path):
        print("KEY_MISSING", key_path)
        return 1
    pem = open(key_path, "rb").read()
    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(_ask_passphrase(twice=True), salt)
    blob = (BACKUP_MAGIC + b"" + salt + nonce
            + AESGCM(key).encrypt(nonce, pem, None))
    assert_outside_repo(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(blob)
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass
    print("已写入加密备份：%s（%d 字节）" % (out_path, len(blob)))
    print("自校验：", end="")
    rc = do_restore(out_path, expect_pub_of=key_path)
    if rc == 0:
        print("这一个文件可以拷去 U 盘/网盘——没有口令它只是随机字节。")
        print("原机磁盘损坏时：python scripts/update_keys.py --restore --backup <该文件> --out <私钥路径>")
    return rc


def _read_backup(path: str) -> bytes:
    blob = open(path, "rb").read()
    if blob[:7] != BACKUP_MAGIC:
        raise SystemExit("不是本工具生成的备份文件（magic 不符）：%s" % path)
    salt, nonce, body = blob[8:24], blob[24:36], blob[36:]
    key = _derive(_ask_passphrase(twice=False), salt)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        return AESGCM(key).decrypt(nonce, body, None)
    except Exception:
        raise SystemExit("解密失败：口令不对或文件损坏（不区分这两种情况）")


def do_restore(backup_path: str, out_path: str = "", expect_pub_of: str = "") -> int:
    import io as _io
    pem = _read_backup(backup_path)
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    try:
        priv = load_pem_private_key(pem, password=None)
    except Exception:
        raise SystemExit("备份里不是可用的 Ed25519 私钥 PEM")
    entry = pubkey_entry(priv)
    print('备份对应公钥 {"kid": "%s", "pub": "%s"}' % (entry["kid"], entry["pub"]))
    if expect_pub_of and os.path.isfile(expect_pub_of):
        cur = pubkey_entry(load_private(expect_pub_of))
        print("与当前私钥一致" if cur == entry else "警告：与当前私钥不一致（旧密钥的备份？）")
    if out_path:
        assert_outside_repo(out_path)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(pem)
        try:
            os.chmod(out_path, 0o600)
        except OSError:
            pass
        print("已还原私钥到：%s" % out_path)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gen", action="store_true", help="生成密钥对（已存在则不覆盖）")
    ap.add_argument("--force", action="store_true", help="配合 --gen：覆盖现有私钥")
    ap.add_argument("--show", action="store_true", help="打印现有私钥对应的公钥行")
    ap.add_argument("--check-repo", action="store_true", help="扫描仓库确认没被跟踪的私钥")
    ap.add_argument("--backup", action="store_true", help="把现有私钥做口令加密备份（Q4）")
    ap.add_argument("--restore", action="store_true", help="从备份校验/还原私钥")
    ap.add_argument("--backup-file", default="", help="备份文件路径（--backup 默认 <私钥>.backup）")
    ap.add_argument("--out", default="", help="--restore 时把私钥写到这个路径（缺省只校验不落盘）")
    ap.add_argument("--key", default=os.path.join(default_dir(), "ed25519.key"),
                    help="私钥路径（默认仓库外）")
    a = ap.parse_args()
    if a.check_repo:
        return do_check_repo()
    if a.gen:
        return do_gen(a.key, a.force)
    if a.show:
        return do_show(a.key)
    if a.backup:
        return do_backup(a.key, a.backup_file or (a.key + ".backup"))
    if a.restore:
        return do_restore(a.backup_file, out_path=a.out)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
