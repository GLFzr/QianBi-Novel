# -*- coding: utf-8 -*-
"""API key 安全存储：Windows 凭据管理器（keyring）+ 配置脱敏

- config.json 不再落明文 api_key：保存时抽出 key 入凭据管理器，json 中只留 key_ref 指纹
- 读取时透明回填（load_config→hydrate），所有下游消费方（router/client）零改动
- keyring 不可用时降级保留明文（功能优先，log 一次警告）
- redact_text：崩溃 dump/遥测/日志的统一脱敏出口
"""
import logging
import re

logger = logging.getLogger("qianbi.secrets")

SERVICE = "QianBiNovel/connections"
_KEY_REF = "keyring"

try:
    import keyring as _keyring
    # 触发一次后端探测；不可用环境（部分 Linux/精简系统）降级
    _keyring.get_keyring()
    _AVAILABLE = True
except Exception as e:  # noqa: BLE001
    _keyring = None
    _AVAILABLE = False
    logger.warning("keyring 不可用（%s），API key 将回退明文存储", e)


def available() -> bool:
    return _AVAILABLE


def store_secret(conn_id: str, key: str) -> bool:
    if not (_AVAILABLE and conn_id and key):
        return False
    try:
        _keyring.set_password(SERVICE, conn_id, key)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("keyring 写入失败（%s），回退明文", e)
        return False


def get_secret(conn_id: str) -> str:
    if not (_AVAILABLE and conn_id):
        return ""
    try:
        return _keyring.get_password(SERVICE, conn_id) or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("keyring 读取失败（%s）", e)
        return ""


def delete_secret(conn_id: str):
    if not (_AVAILABLE and conn_id):
        return
    try:
        _keyring.delete_password(SERVICE, conn_id)
    except Exception:  # noqa: BLE001
        pass


# 行丢过 key_ref（退役换血/旧版迁移弄丢指针）而凭据库里仍有同 id Key 的，领养回来。
# 每个 id 每进程只探一次：load_config 是热路径，不能每次界面动作都跑一遍凭据库。
_ADOPT_CHECKED: set = set()


def hydrate(cfg: dict) -> dict:
    """load_config 出口：把 key_ref 指向的凭据回填到内存中的 api_key 字段"""
    for conn in cfg.get("connections", []):
        if conn.get("api_key"):
            continue
        cid = conn.get("id", "")
        if conn.get("key_ref") == _KEY_REF:
            conn["api_key"] = get_secret(cid)
        elif _AVAILABLE and cid and cid not in _ADOPT_CHECKED:
            # key_ref 没了 ≠ Key 没了：查一次凭据库，有同 id 的就领养并接回指针
            _ADOPT_CHECKED.add(cid)
            found = get_secret(cid)
            if found:
                conn["api_key"] = found
                conn["key_ref"] = _KEY_REF
    return cfg


def dehydrate(cfg: dict) -> dict:
    """save_config 入口：抽出明文 key 入凭据管理器，json 只留 key_ref"""
    for conn in cfg.get("connections", []):
        key = conn.get("api_key") or ""
        if key and store_secret(conn.get("id", ""), key):
            conn["api_key"] = ""
            conn["key_ref"] = _KEY_REF
        elif not key and conn.get("key_ref") == _KEY_REF:
            # 明文已空且指向 keyring：保持指针（hydrate 会回填）
            pass
    return cfg


# 脱敏模式：json 键值对 / sk- 开头令牌 / Bearer
_RE_JSON_KEY = re.compile(r"\"api_key\"\s*[:=]\s*\"[^\"]{4,}\"")
_RE_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_RE_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._-]{8,}")


def redact_text(text: str) -> str:
    """崩溃 dump/遥测/日志的统一脱敏出口"""
    if not text:
        return text
    text = _RE_JSON_KEY.sub('"api_key": "<REDACTED>"', text)
    text = _RE_SK.sub("sk-<REDACTED>", text)
    text = _RE_BEARER.sub("Bearer <REDACTED>", text)
    return text
