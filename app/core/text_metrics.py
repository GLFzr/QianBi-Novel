# -*- coding: utf-8 -*-
"""文本计量基础函数（B2d 拆环下沉）

``han_tokens`` 原在 app/core/history_compaction.py，被 volume_session 反向
引用（lines_size 估算栈体积），形成 history_compaction↔volume_session 环。
计量口径属无状态基础能力，下沉本模块：两侧改为直接 import，环消。

口径不许动：中文字符数 × 0.6（同 scripts/header_audit.py 的 est_metrics；
非中文字符不计）。**不是** DSH 的 4 字符/token 启发式——那个口径系统性低估
CJK，会把长卷的压缩触发点推晚。
"""
import re

TOKENS_PER_HAN = 0.6           # 仓库既有口径：1 汉字 ≈ 0.6 token（scripts/header_audit.py）
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def han_tokens(text: str) -> int:
    """字符 → token 的仓库既有口径：中文字符数 × 0.6（同 scripts/header_audit.py
    的 est_metrics；非中文字符不计）。"""
    return int(len(_HAN_RE.findall(text or "")) * TOKENS_PER_HAN + 0.5)
