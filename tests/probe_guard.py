# -*- coding: utf-8 -*-
"""探针配置护栏：真 Bridge 探针会打开项目并回写 ~/.qianbi_novel/config.json
（last_project / recent_projects），污染用户真实环境。
arm_config_guard() 在进程启动时快照配置，退出时恢复，探针零残留。
"""
import atexit
import os
import tempfile


def arm_config_guard() -> str:
    path = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "config.json")
    try:
        with open(path, "rb") as f:
            snap = f.read()
    except OSError:
        snap = None

    def _restore():
        try:
            if snap is not None:
                with open(path, "wb") as f:
                    f.write(snap)
            elif os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    atexit.register(_restore)
    _arm_update_guard()
    return path


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
