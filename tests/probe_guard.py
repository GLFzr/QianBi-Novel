# -*- coding: utf-8 -*-
"""探针配置护栏：真 Bridge 探针会打开项目并回写 ~/.qianbi_novel/config.json
（last_project / recent_projects），污染用户真实环境。
arm_config_guard() 在进程启动时快照配置，退出时恢复，探针零残留。
"""
import atexit
import os


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
    return path
