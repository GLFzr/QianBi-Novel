# -*- coding: utf-8 -*-
"""失败现场 dump：流水线异常时把现场（阶段/章号/最后 prompt/日志尾部）写到项目目录

位置：{项目}/pipeline_debug/failure_时间戳.md
目的：无人值守运行失败后，不用重新跑就能排查"当时模型收到了什么"。
"""
import datetime
import os
import traceback


def dump_failure(proj: str, stage_key: str, chapter_num: int,
                 last_prompt: str, error: BaseException,
                 log_tail: list = None, step_key: str = "") -> str:
    """写入失败现场文件，返回文件路径"""
    try:
        debug_dir = os.path.join(proj, "pipeline_debug")
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(debug_dir, f"failure_{ts}.md")
        lines = [
            "# 流水线失败现场",
            "",
            f"- 时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 阶段：{stage_key or '（未知）'}",
            f"- 章节：第 {chapter_num} 章" if chapter_num else "- 章节：（未到正文阶段）",
            f"- 微循环步骤：{step_key or '（无）'}",
            "",
            "## 异常",
            "",
            "```",
            traceback.format_exc() if hasattr(error, "__traceback__") and error.__traceback__ else str(error),
            "```",
            "",
        ]
        if last_prompt:
            lines += ["## 最后一次 LLM 请求 prompt", "", "```", last_prompt[:12000], "```", ""]
        if log_tail:
            lines += ["## 日志尾部", "", "```"] + list(log_tail) + ["```", ""]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path
    except Exception:
        return ""
