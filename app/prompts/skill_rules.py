# -*- coding: utf-8 -*-
"""lieflat-less-ai-tone 规则装载器（去 AI 味 skill 供应商化，方案 Phase 1）

职责：
  - 从 app/vendor/lieflat-less-ai-tone/SKILL.md（启动时一次性读入缓存）切片出
    规则内核：硬性边界（措辞适配）/ 不改的情况 / 不作为改写理由（负表全量）/
    改写规则 11 条（删除规则 8 的"提示作者"句）/ 最终验收；
  - 丢弃两个交互节：`## 用法`、`## 有风格参考时先读它`（本管线无法满足其前置，
    混进 prompt 会被模型当指令执行）；
  - 渲染两档：full（带 ❌/✅ 示例）与 lean（只保 触发标记/改法/不改 行，裁示例）；
  - 任一预期标题缺失、或渲染文本含花括号（会炸 .format）、或 vendor 文件读不到
    → 整体回退 builtin 并出声告警（不半截拼接）。

合规：上游 MIT（Copyright (c) 2026 shiujan），本项目衍生适配，适配部分同样遵循
MIT。只集成 lieflat-less-ai-tone；不含同系列 lieflat-gongwen / lieflat-charts
（PolyForm Noncommercial，禁商用）。

缓存纪律：进程生命周期内只读一次（init_rules_cache，main.py 启动时调用；测试/探针
走首次访问的懒初始化）。卷级冻结头按字节比对，运行中改 vendor 文件或切 rules_source
= 会话栈整卷作废——需要换源请开新卷（重启应用）。
"""
import logging
import os
import re

logger = logging.getLogger("qianbi.prompts")

VENDOR_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "vendor", "lieflat-less-ai-tone")
SKILL_PATH = os.path.join(VENDOR_DIR, "SKILL.md")

# 预期章节标题（按行首 "## " 后的前缀匹配——上游用全角括号，标题括号内文字不参与匹配；
# 上游 re-vendor 改了标题结构 → 任一缺失即整体回退 builtin）
REQUIRED_SECTIONS = ("硬性边界", "不改的情况", "不作为改写理由", "改写规则", "最终验收")
DROP_SECTIONS = ("用法", "有风格参考时先读它")

# 规则 8 中必须删除的句子（会被模型遵守，把提示语拼进章节正文——clean_llm_output
# 只剥代码围栏，拦不住）。
RULE8_DROP_SENTENCE = "可以在输出后提示作者此处材料稀薄，由作者决定是否补充。"

# 硬性边界首段适配（§4.2）：原白名单边界必须与检出清单/口头禅黑名单/本书正则契约
# 共存，否则 prompt 自相矛盾（一边"清单外别动"，一边 findings 里全是清单外问题）。
BOUNDARY_ORIGINAL_PARA_PREFIX = "本 skill 采用白名单式改写。"
BOUNDARY_ADAPTED_PARA = (
    "本规则集采用白名单式改写。只能处理“改写规则”中明确列出的规范，不能凭一般写作"
    "经验修改其他内容。未命中上述任何规则、且不在本轮检出问题清单 / 口头禅黑名单 / "
    "本书正则契约中的文字，逐字保留。")

# 负表尾注里指向上游文档的链接在应用内不可达，换成纯文字指路
_RESEARCH_LINK = "[RESEARCH.md](./RESEARCH.md)"


_cache = {
    "inited": False,        # 是否已完成初始化（进程内只初始化一次）
    "mode": "builtin",      # "lieflat" | "builtin"（读不到/解析失败回退 builtin）
    "union": None,          # lieflat 生效时的并集静态段全文（内置切片 + skill 后缀）
    "builtin_slice": None,  # 内置静态段（原始模板切片，builtin 模式返回值）
    "skill_suffix": None,   # skill 贡献的追加段
    "reason": "",           # 回退原因（builtin 时告警/文档用）
}

def init_rules_cache(cfg: dict = None) -> dict:
    """应用启动时调用一次（main.py）；测试/探针未调用时由首次访问懒初始化。

    cfg 缺省时读 app.config.load_config()。之后进程内不再重读 vendor 文件——
    卷级冻结头按字节比对，中途换文件/换源 = 会话栈整卷作废。
    """
    if cfg is None:
        from .. import config as cfg_mod
        cfg = cfg_mod.load_config()
    deslop_cfg = (cfg or {}).get("deslop", {}) or {}
    source = deslop_cfg.get("rules_source", "lieflat")
    render = deslop_cfg.get("rules_render", "lean")

    _cache["inited"] = True
    _cache["union"] = None
    _cache["skill_suffix"] = None
    _cache["reason"] = ""

    from . import writing as writing_mod
    _cache["builtin_slice"] = writing_mod.builtin_deslop_static_rules()

    if source != "lieflat":
        _cache["mode"] = "builtin"
        _cache["reason"] = f"配置 rules_source={source}，使用内置规则"
        logger.info("去 AI 味规则源：builtin（配置指定）")
        return dict(_cache)

    try:
        with open(SKILL_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        suffix_full = _render_skill(raw, "full")
        suffix_lean = _render_skill(raw, render if render in ("full", "lean") else "lean")
        suffix = suffix_lean if render != "full" else suffix_full
        if not suffix:
            raise ValueError("渲染结果为空")
        if "{" in suffix or "}" in suffix:
            raise ValueError("渲染文本含花括号（会破坏模板 .format）")
        # 并集 = 内置静态段 + skill 后缀；两者均无占位符，标记切片契约保持
        _cache["mode"] = "lieflat"
        _cache["skill_suffix"] = suffix
        _cache["union"] = _cache["builtin_slice"].rstrip("\n") + "\n\n" + suffix
        logger.info("去 AI 味规则源：lieflat（commit 27d2923，%s 档，追加 %d 字）",
                    "full" if render == "full" else "lean", len(suffix))
    except Exception as e:  # noqa: BLE001
        _cache["mode"] = "builtin"
        _cache["union"] = None
        _cache["skill_suffix"] = None
        _cache["reason"] = f"vendor 规则装载失败，回退内置规则：{e}"
        logger.warning("lieflat-less-ai-tone 装载失败，deslop 规则回退 builtin：%s", e)
    return dict(_cache)


def _ensure_init() -> None:
    if not _cache["inited"]:
        try:
            init_rules_cache()
        except Exception as e:  # noqa: BLE001
            _cache["inited"] = True
            _cache["mode"] = "builtin"
            logger.warning("去 AI 味规则源懒初始化失败，回退 builtin：%s", e)


def active_mode() -> str:
    _ensure_init()
    return _cache["mode"]


def builtin_slice() -> str:
    _ensure_init()
    return _cache["builtin_slice"] or ""


def union_text() -> str:
    """lieflat 生效时的并集静态段；builtin 模式返回空串（调用方回退内置切片）。"""
    _ensure_init()
    return _cache["union"] or ""


def skill_suffix_text() -> str:
    _ensure_init()
    return _cache["skill_suffix"] or ""


def fallback_reason() -> str:
    _ensure_init()
    return _cache["reason"]


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            return text[end + 4:].lstrip("\n")
    return text


def _split_h2_sections(text: str) -> list:
    """按行首 `## ` 切片，返回 [(标题行, 标题key, 正文)]；`###` 及以下随所属 H2。"""
    sections = []
    cur_title = None
    cur_key = ""
    cur_lines = []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, cur_key, "\n".join(cur_lines).strip("\n")))
            cur_title = line[3:].strip()
            cur_key = cur_title
            for sym in ("（", "("):
                cur_key = cur_key.split(sym)[0]
            cur_lines = []
        else:
            if cur_title is not None:
                cur_lines.append(line)
            # frontmatter 之后的文档主标题（# 去 AI 味）与引言：尚未遇到 H2，丢弃引言
    if cur_title is not None:
        sections.append((cur_title, cur_key, "\n".join(cur_lines).strip("\n")))
    return sections


def _render_skill(raw: str, mode: str) -> str:
    """切片 + 适配 + 渲染。任一预期标题缺失 → 返回 ""（调用方回退 builtin）。"""
    body = _strip_frontmatter(raw)
    sections = {key: (title, content)
                for title, key, content in _split_h2_sections(body)}
    missing = [k for k in REQUIRED_SECTIONS if k not in sections]
    if missing:
        raise ValueError(f"预期章节标题缺失：{missing}（上游结构变了？整体回退）")

    # 丢弃交互节：存在也不进渲染产物（断言测试锁死：见 test_skill_rules.py）
    out = []
    out.append("## 去 AI 味规则补充（lieflat-less-ai-tone，MIT 衍生适配；"
               "与上方改写原则共同生效）")

    # —— 硬性边界（措辞适配）——
    title, content = sections["硬性边界"]
    lines = content.splitlines()
    adapted = []
    replaced = False
    for ln in lines:
        if not replaced and ln.strip().startswith(BOUNDARY_ORIGINAL_PARA_PREFIX):
            adapted.append(BOUNDARY_ADAPTED_PARA)
            replaced = True
        else:
            adapted.append(ln)
    if not replaced:
        raise ValueError("硬性边界首段未命中，边界适配失败（整体回退）")
    out.append(f"### {title}\n" + "\n".join(adapted).strip("\n"))

    # —— 不改的情况（原文取用）——
    title, content = sections["不改的情况"]
    out.append(f"### {title}\n{content.strip(chr(10))}")

    # —— 不作为改写理由（负表全量，硬约束）——
    title, content = sections["不作为改写理由"]
    content = content.replace(_RESEARCH_LINK, "上游 RESEARCH.md")
    out.append(f"### {title}\n{content.strip(chr(10))}")

    # —— 改写规则 11 条（选段取用=全部保留在文本层；删规则 8"提示作者"句）——
    title, content = sections["改写规则"]
    if RULE8_DROP_SENTENCE not in content:
        raise ValueError("规则 8 的「提示作者」句未命中（上游措辞变了？整体回退）")
    content = content.replace(RULE8_DROP_SENTENCE, "")
    if mode == "lean":
        content = _lean_rules(content)
    out.append(f"### {title}（原文 11 条全量保留在文本层；论述文条目预期召回低）\n{content.strip(chr(10))}")

    # —— 最终验收（原文取用）——
    title, content = sections["最终验收"]
    out.append(f"### {title}（输出前逐项自查）\n{content.strip(chr(10))}")

    return "\n\n".join(out).strip("\n")


def _lean_rules(rules_text: str) -> str:
    """lean 档：裁掉 ❌/✅ 示例块（`>` 行）与因此产生的连续空行，规则正文全保。

    故意不按"触发标记/改法"前缀行过滤——规则 1（翻案腔句式清单）、规则 9（起手式
    词表）的触发实体在正文叙述里，机械前缀过滤会把规则本身裁没；示例块才是体积
    大头（约六成），裁它已达成 token 目标。
    """
    out = []
    blank = 0
    for ln in rules_text.splitlines():
        if ln.strip().startswith(">"):
            continue
        if not ln.strip():
            blank += 1
            if blank >= 2:
                continue
        else:
            blank = 0
        out.append(ln)
    return chr(10).join(out).strip(chr(10))
