# -*- coding: utf-8 -*-
"""去 AI 味规则共享缓存（B2c 拆环枢纽）

skill_rules（vendor 规则装载器）与 writing（DESLOP_REWRITE_PROMPT 模板宿主）
原本互相 import：skill_rules.init_rules_cache 要 writing.builtin_deslop_static_rules()
切内置规则段；writing.deslop_static_rules 要 skill_rules._cache 里的并集文本。
本模块把这份共享状态（缓存字典 + 两个能力钩子）下沉为无 app 内依赖的枢纽：

  - ``_cache``                 规则缓存（进程内单例；两经手方读写的同一对象）
  - ``set_builtin_slice_provider``  writing 注册——切出内置静态规则段
  - ``set_init_hook``          skill_rules 注册——vendor 规则装载（含切片/渲染）
  - ``ensure_init``            懒初始化入口（带 builtin 回退兜底）

本模块不许 import 任何 app 内其他模块——它是被两侧依赖的一方，不是依赖方。
"""
import logging

logger = logging.getLogger("qianbi.prompts")

_cache = {
    "inited": False,        # 是否已完成初始化（进程内只初始化一次）
    "mode": "builtin",      # "lieflat" | "builtin"（读不到/解析失败回退 builtin）
    "union": None,          # lieflat 生效时的并集静态段全文（内置切片 + skill 后缀）
    "builtin_slice": None,  # 内置静态段（原始模板切片，builtin 模式返回值）
    "skill_suffix": None,   # skill 贡献的追加段
    "reason": "",           # 回退原因（builtin 时告警/文档用）
}

# 能力钩子（由 writing / skill_rules 在各自模块导入时注册，避免互引）
_builtin_slice_provider = None   # () -> str：内置静态规则段（原始模板切片）
_init_hook = None                # (cfg: dict | None) -> dict：vendor 规则装载


def set_builtin_slice_provider(fn) -> None:
    """writing 注册：提供 builtin 静态规则段切片（零占位符）"""
    global _builtin_slice_provider
    _builtin_slice_provider = fn


def set_init_hook(fn) -> None:
    """skill_rules 注册：vendor 规则装载入口（init_rules_cache）"""
    global _init_hook
    _init_hook = fn


def builtin_slice_text() -> str:
    """内置静态规则段；钩子未注册（异常态）时返回空串并告警"""
    if _builtin_slice_provider is None:
        logger.warning("deslop_rules：builtin 切片钩子未注册（writing 未导入？），返回空切片")
        return ""
    return _builtin_slice_provider() or ""


def ensure_init() -> None:
    """懒初始化（首次访问时调 skill_rules 注册的装载钩子；失败回退 builtin）"""
    if _cache["inited"]:
        return
    if _init_hook is None:
        _cache["inited"] = True
        _cache["mode"] = "builtin"
        _cache["reason"] = "装载钩子未注册（skill_rules 未导入？）"
        return
    try:
        _init_hook()
    except Exception as e:  # noqa: BLE001
        _cache["inited"] = True
        _cache["mode"] = "builtin"
        logger.warning("去 AI 味规则源懒初始化失败，回退 builtin：%s", e)
