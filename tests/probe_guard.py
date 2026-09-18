# -*- coding: utf-8 -*-
"""探针配置护栏：真 Bridge 探针会打开项目并回写 ~/.qianbi_novel/config.json
（last_project / recent_projects / run_mode），并在 save_config 时把明文 Key 脱水进
Windows 凭据管理器（dehydrate→store_secret→keyring(SERVICE)），污染用户真实环境。

W-04：从「快照 + atexit 还原」升级为「进程隔离为主，快照还原为辅」。
- 主：把 config 落盘目标整体改到本探针专属临时目录（env + 若已导入则改模块级路径）。
  探针被超时 kill、atexit 不跑时，线上 config.json 也从没成为写入目标。
- 辅：仍对真实路径做快照/还原，兜住任何绕过 env 直接写回老路径的代码。
- Keyring 围栏：把 secrets.SERVICE 指到可丢弃命名空间——即便某条路径没走被替换的
  store_secret（或替换时机有窗口），写到的也是测试专用 service 名，用户三条真 Key 不动。
"""
import atexit
import os
import tempfile


def _redirect_config_to_temp() -> str:
    """把 app.config 的落盘目标改到进程专属临时目录；返回真实 config 路径（供快照兜底）。"""
    live = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
    tmp = tempfile.mkdtemp(prefix="qianbi_probe_cfg_")
    os.environ["QIANBI_CONFIG_DIR"] = tmp
    try:
        from app import config as cfg
        cfg.CONFIG_DIR = tmp
        cfg.CONFIG_FILE = os.path.join(tmp, "config.json")
        cfg._LEGACY_DIR = os.path.join(tmp, "_no_legacy")   # 挡 v0.x 迁移从旧目录 copy2 覆盖
    except Exception:  # noqa: BLE001
        pass

    try:
        with open(live, "rb") as f:
            snap = f.read()
    except OSError:
        snap = None

    def _restore():
        try:
            if snap is not None:
                with open(live, "wb") as f:
                    f.write(snap)
            elif os.path.exists(live):
                os.remove(live)
        except OSError:
            pass

    atexit.register(_restore)   # 第二道保险：绕过 env 的写回也会被抹平
    return live


def arm_config_guard() -> str:
    _redirect_config_to_temp()
    _arm_update_guard()
    _arm_secret_guard()
    return os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")


def _arm_secret_guard():
    """探针不碰真凭据管理器

    `dehydrate()` 在每次 save_config 时把明文 Key 写进 Windows 凭据管理器，
    而 deleteConnection 又会按连接 id 删凭据——两条都跑在真 Bridge 探针里，
    动的就是用户真实的 Key。两层围栏：
      ① 把 store/get/delete_secret 换成进程内字典（探针读写自己的沙箱，退出即蒸发）；
      ② 同时把 SERVICE 指到测试专用命名空间——万一某条路径绕开①（或替换有先后窗口），
         写到的也是可丢弃的 service 名，绝不覆盖用户在真实 SERVICE 下的 Key。

    打模块属性就够：hydrate/dehydrate 与 bridge 都是 `secrets.xxx(...)` 这样按名字取，
    不是 `from ... import xxx` 复制了绑定，所以替换对全部调用点生效。
    """
    vault = {}
    try:
        from app import secrets
        secrets.SERVICE = "QianBiNovel/connections.__probe__"
        secrets.available = lambda: True
        secrets.store_secret = lambda cid, key: (vault.__setitem__(cid, key), True)[1]
        secrets.get_secret = lambda cid: vault.get(cid, "")
        secrets.delete_secret = lambda cid: vault.pop(cid, None)
        secrets._VAULT = vault
    except Exception:  # noqa: BLE001
        pass


def _arm_update_guard():
    """探针零网络 + 清单缓存隔离

    自动检查即将默认开。不钉这两条，探针会真发 HTTP；而 `~/.qianbi_novel/updates/`
    里的清单缓存不在 config.json 快照范围内，于是「上次谁跑过什么」会决定这次探针
    看到什么，24h 限流再把执行顺序变成结果。挂在 arm_config_guard 里是让新探针
    没法忘记加。
    """
    os.environ.setdefault("QIANBI_OFFLINE", "1")
    sandbox = tempfile.mkdtemp(prefix="qianbi_probe_updates_")
    try:
        from app import update_check as uc
        uc.updates_dir = lambda: sandbox
    except Exception:  # noqa: BLE001
        pass
