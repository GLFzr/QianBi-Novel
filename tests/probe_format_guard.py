# -*- coding: utf-8 -*-
"""探针侧模板装配护栏（§7.3：N-14 修复件）。

背景：writing.py 模板新增 ``{project_header}`` 槽后，4 支手搓 ``.format()`` 的探针
集体 KeyError（台账 N-14，#62「探针比被测代码年轻」同型）。本护栏把「模板槽位 ↔
探针 kwargs」的对账显式化：**模板新增/改名槽位时，探针当场给出可读的槽位名报错，
而不是 KeyError traceback**——下次再隐形就炸。

用法：
    from probe_format_guard import format_or_die
    prompt = format_or_die(prompts.PROSE_WRITING_PROMPT, chapter_num=1, ...)
"""
import string


def template_fields(template: str) -> set:
    """模板里的全部槽位名（konstant 前缀字段与格式规约一并解析）"""
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def format_or_die(template: str, **kwargs) -> str:
    """槽位全覆盖断言 + format。缺槽时报出缺哪些槽，不再抛裸 KeyError"""
    missing = template_fields(template) - set(kwargs)
    if missing:
        raise AssertionError(
            "探针 kwargs 未覆盖模板槽位 %s（模板新增槽后探针必须跟上——N-14 护栏）"
            % sorted(missing))
    return template.format(**kwargs)
