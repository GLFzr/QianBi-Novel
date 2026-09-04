# -*- coding: utf-8 -*-
"""给 latest.json 签名 / 验签

签名作用域与客户端**共用同一份实现**（app.update_check.canonical_bytes）：去掉 `sig`
后的全部字段，键序固定、紧凑分隔符、UTF-8。两处各写一份序列化的话，症状是
「发布机签好了，客户端永远验不过」，而且两边都觉得自己没错。

用法：
    python scripts/sign_manifest.py latest.json            # 就地写入 sig 字段
    python scripts/sign_manifest.py --verify latest.json   # 只验不改（闸门用）
"""
import argparse
import base64
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))      # scripts/ 不是包，按目录导入

from app import update_check as uc                        # noqa: E402
import update_keys                                        # noqa: E402


def key_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "qianbi_sign", "ed25519.key")


def do_sign(path: str, priv_file: str) -> int:
    if not os.path.isfile(priv_file):
        print("KEY_MISSING", priv_file)
        print("没有私钥就发不出可信的自动更新：先跑 python scripts/update_keys.py --gen。")
        print("本轮产物仍会出来，但清单未验签 → 客户端只会显示，不会自动安装。")
        return 2
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data.get("version"):
        print("MANIFEST_BAD", path, "没有 version 字段")
        return 1
    priv = update_keys.load_private(priv_file)
    body = {k: v for k, v in data.items() if k != "sig"}
    body["sig"] = base64.b64encode(priv.sign(uc.canonical_bytes(body))).decode()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
        f.write("\n")
    ok, why = uc.verify_manifest(body)
    print("SIGNED", path, "→", why)
    if not ok:
        print("自己签完自己验不过：多半是应用内置公钥与这份私钥不配对。")
        return 1
    return 0


def do_verify(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print("VERIFY FAIL 读不到清单：%s" % e)
        return 1
    ok, why = uc.verify_manifest(data if isinstance(data, dict) else {})
    print(("VERIFY OK   " if ok else "VERIFY FAIL ") + "%s · %s" % (path, why))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", nargs="?", default=os.path.join(REPO_ROOT, "latest.json"))
    ap.add_argument("--verify", action="store_true", help="只验不改")
    ap.add_argument("--key", default=key_path())
    a = ap.parse_args()
    return do_verify(a.path) if a.verify else do_sign(a.path, a.key)


if __name__ == "__main__":
    sys.exit(main())
