# -*- coding: utf-8 -*-
"""项目文件结构管理

{书名}/
├── 设定/       (世界观/角色/势力/关系.md/题材定位.md)
├── 大纲/       (大纲.md/卷纲_第X卷.md/细纲_第XXX章.md)
├── 正文/       (第XXX章_章名.md)
└── 追踪/       (伏笔.md/时间线.md/角色状态.md/上下文.md)
"""
import os
import re
import tempfile

PROJECT_DIRS = ["设定", "大纲", "正文", "追踪"]
SETTING_SUBDIRS = ["世界观", "角色", "势力"]

TRACKING_TEMPLATES = {
    "追踪/伏笔.md": "# 伏笔追踪\n\n> 状态：未埋 / 已埋 / 已回收\n\n| 伏笔 | 埋设章节 | 状态 | 计划回收 | 备注 |\n|------|----------|------|----------|------|\n",
    "追踪/时间线.md": "# 故事时间线\n\n| 故事内时间 | 章节 | 事件 |\n|------------|------|------|\n",
    "追踪/角色状态.md": "# 角色状态追踪\n\n> 每章写完后更新主要角色的状态变化。\n",
    "追踪/上下文.md": "# 写作上下文\n\n> 当前进度与最近决策速记。\n\n当前进度：尚未开始\n",
    "追踪/全局摘要.md": "# 全局摘要\n\n> 每章定稿后滚动更新，是全书记忆的锚点。\n\n（尚未开始）\n",
    "追踪/章节摘要.md": "# 章节摘要链\n\n> 每章一句话摘要，按章号追加。\n",
}


def create_project(root_dir: str, book_name: str) -> str:
    """创建新项目，返回项目路径"""
    proj = os.path.join(root_dir, book_name)
    os.makedirs(proj, exist_ok=False)
    for d in PROJECT_DIRS:
        os.makedirs(os.path.join(proj, d), exist_ok=True)
    for d in SETTING_SUBDIRS:
        os.makedirs(os.path.join(proj, "设定", d), exist_ok=True)
    for rel, content in TRACKING_TEMPLATES.items():
        path = os.path.join(proj, rel.replace("/", os.sep))
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
    return proj


def is_project(path: str) -> bool:
    """判断目录是否为写作项目"""
    if not os.path.isdir(path):
        return False
    return all(os.path.isdir(os.path.join(path, d)) for d in ["设定", "大纲", "正文", "追踪"])


def read_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def chapter_filename(num: int, title: str = "") -> str:
    """生成章节文件名"""
    title = re.sub(r'[\\/:*?"<>|]', "", title).strip()
    if title:
        return f"第{num:03d}章_{title}.md"
    return f"第{num:03d}章.md"


def outline_filename(num: int) -> str:
    return f"细纲_第{num:03d}章.md"


def list_chapters(proj: str) -> list:
    """列出正文章节 [(num, filename, full_path)]"""
    prose_dir = os.path.join(proj, "正文")
    result = []
    if not os.path.isdir(prose_dir):
        return result
    for name in sorted(os.listdir(prose_dir)):
        m = re.match(r"第(\d+)章", name)
        if m and name.endswith(".md"):
            result.append((int(m.group(1)), name, os.path.join(prose_dir, name)))
    return result


def list_outlines(proj: str) -> list:
    """列出细纲 [(num, full_path)]"""
    outline_dir = os.path.join(proj, "大纲")
    result = []
    if not os.path.isdir(outline_dir):
        return result
    for name in sorted(os.listdir(outline_dir)):
        m = re.match(r"细纲_第(\d+)章", name)
        if m and name.endswith(".md"):
            result.append((int(m.group(1)), os.path.join(outline_dir, name)))
    return result


def next_chapter_num(proj: str) -> int:
    chapters = list_chapters(proj)
    if not chapters:
        return 1
    return max(c[0] for c in chapters) + 1


def get_chapter_path(proj: str, num: int, title: str = "") -> str:
    return os.path.join(proj, "正文", chapter_filename(num, title))


def get_outline_path(proj: str, num: int) -> str:
    return os.path.join(proj, "大纲", outline_filename(num))


def get_tracking_path(proj: str, name: str) -> str:
    """name: 伏笔/时间线/角色状态/上下文"""
    return os.path.join(proj, "追踪", f"{name}.md")


def project_progress(proj: str) -> dict:
    """项目进度摘要"""
    chapters = list_chapters(proj)
    outlines = list_outlines(proj)
    total_words = 0
    for _, _, p in chapters:
        total_words += len(read_file(p))
    return {
        "chapters_written": len(chapters),
        "outlines_ready": len(outlines),
        "total_words": total_words,
        "last_chapter": chapters[-1][0] if chapters else 0,
    }


def count_chars(text: str) -> int:
    """统计中文字数（去除空白与 markdown 标记的近似值）"""
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"[#>*`\-\[\]()]", "", t)
    return len(t)


# ---------- 千笔一文：选题信息 / 摘要链 / 计划章数 ----------

def ensure_tracking_files(proj: str):
    """老项目补齐新增的追踪文件（全局摘要/章节摘要）"""
    for rel, content in TRACKING_TEMPLATES.items():
        path = os.path.join(proj, rel.replace("/", os.sep))
        if not os.path.exists(path):
            write_file(path, content)


def read_idea_info(proj: str) -> dict:
    """读取 设定/选题信息.md → {genre, platform, idea, total_words_wan}"""
    doc = read_file(os.path.join(proj, "设定", "选题信息.md"))
    info = {"genre": "", "platform": "番茄", "idea": "", "total_words_wan": 0}
    m = re.search(r"题材：(.+)", doc)
    if m:
        info["genre"] = m.group(1).strip()
    m = re.search(r"平台：(.+)", doc)
    if m:
        info["platform"] = m.group(1).strip()
    m = re.search(r"灵感：(.+)", doc, re.S)
    if m:
        info["idea"] = m.group(1).strip()
    m = re.search(r"预计总字数：(\d+)", doc)
    if m:
        info["total_words_wan"] = int(m.group(1))
    return info


def write_idea_info(proj: str, genre: str, platform: str, idea: str, total_words_wan: int = 0):
    doc = f"# 选题信息\n\n- 题材：{genre}\n- 平台：{platform}\n"
    if total_words_wan:
        doc += f"- 预计总字数：{total_words_wan} 万字\n"
    doc += f"- 灵感：{idea}\n"
    write_file(os.path.join(proj, "设定", "选题信息.md"), doc)


# ---------- 世界书与正则（共写档产物 · M2：默认「逻辑约束规则集」）----------

WORLDBOOK_PATH = "设定/世界书.md"
REGEX_PATH = "设定/正则.md"


def worldbook_text(proj: str, max_chars: int = 2000) -> str:
    """世界书全文（注入 prompt 用，空串回退占位）"""
    doc = read_file(os.path.join(proj, WORLDBOOK_PATH))
    if not doc.strip():
        return "（本书尚未生成世界书——按核心设定写作，后续在世界书阶段补充）"
    if len(doc) > max_chars:
        return doc[:max_chars] + "…（截断）"
    return doc


def regex_rules(proj: str, semantics: str = "logic") -> list:
    """「正则」抽象接口（方案 §4.1）：返回 [{rule, level: must/should, scope}]

    - 默认 semantics="logic"（逻辑约束规则集）：解析 设定/正则.md 的
      `- 规则：…｜level：must/should｜scope：…` 条目
    - semantics="regex"（字面正则样本，备选）：只取行内反引号包裹的 pattern 作 rule
    - 文件缺失/为空 → 空列表（组装方负责占位回退）
    """
    doc = read_file(os.path.join(proj, REGEX_PATH))
    if not doc.strip():
        return []
    rules = []
    for line in doc.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.lstrip("-•* ").strip()
        if not line:
            continue
        if semantics == "regex":
            m = re.search(r"`([^`]+)`", line)
            rule = m.group(1) if m else line
            rules.append({"rule": rule[:300], "level": "must", "scope": "样本"})
            continue
        level, scope = "should", "全书"
        m = re.search(r"level\s*[:：]\s*(must|should)", line)
        if m:
            level = m.group(1)
        m = re.search(r"scope\s*[:：]\s*([^｜|]+)", line)
        if m:
            scope = m.group(1).strip()
        rules.append({"rule": line[:300], "level": level, "scope": scope[:60]})
    return rules


def regex_block(proj: str, semantics: str = "logic", max_chars: int = 1500) -> str:
    """组装注入 prompt 的正则块（空串回退占位，不抛 KeyError）"""
    rules = regex_rules(proj, semantics)
    if not rules:
        return "（本书尚未生成正则约束规则集）"
    lines = [f"- {r['rule']}（level: {r['level']} · scope: {r['scope']}）" for r in rules]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "…（截断）"
    return text


def split_worldbook_product(product: str) -> tuple:
    """共写世界书总结产物 → (世界书正文, 正则段)

    「## 正则」小节独立成 设定/正则.md；未拆出独立正则段时返回 (全文, "")。
    """
    m = re.search(r"##\s*正则.*?(?=\n##\s|\Z)", product or "", re.S)
    if not m:
        return (product or "").strip(), ""
    return product[:m.start()].rstrip(), m.group(0).strip()


# ---------- 章节终稿锁定（M4 · 锁读写全部下沉 project.py，worker 与 UI 同进程读取）----------

def _annotation_path(proj: str, num: int) -> str:
    return os.path.join(proj, "正文", ".annotations", f"第{num}章.json")


def _read_annotation(proj: str, num: int) -> dict:
    """读取章节标注仓（annotations/bookmarks/position/locked），缺省补全"""
    import json
    data = {"annotations": [], "bookmarks": [], "position": 0.0, "locked": False}
    try:
        with open(_annotation_path(proj, num), "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            data.update(raw)
    except (OSError, ValueError):
        pass
    data.setdefault("annotations", [])
    data.setdefault("bookmarks", [])
    data.setdefault("position", 0.0)
    data.setdefault("locked", False)
    return data


def _write_annotation(proj: str, num: int, data: dict):
    import json
    d = os.path.join(proj, "正文", ".annotations")
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _annotation_path(proj, num))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def is_chapter_locked(proj: str, num: int) -> bool:
    """终稿锁定判定（只读；文件缺失=未锁，旧项目容错）"""
    if not num:
        return False
    return bool(_read_annotation(proj, num).get("locked"))


def set_chapter_locked(proj: str, num: int, locked: bool):
    """设置锁定标记（保留标注/书签/位置字段；锁定=内容不再改动）"""
    if not num:
        return
    data = _read_annotation(proj, num)
    data["locked"] = bool(locked)
    _write_annotation(proj, num, data)


def attempt_unlock(proj: str, num: int) -> bool:
    """显式解锁：唯一放行通道（解锁前终稿仍留 .versions/ 版本历史）"""
    if not num:
        return False
    if not is_chapter_locked(proj, num):
        return False
    set_chapter_locked(proj, num, False)
    return True


def planned_chapters(proj: str, chapter_word_target: int = 3000) -> int:
    """计划总章数：预计总字数 ÷ 每章目标字数；未设置返回 0（不限）"""
    wan = read_idea_info(proj).get("total_words_wan", 0)
    if not wan or not chapter_word_target:
        return 0
    return max(1, int(wan * 10000 / chapter_word_target))
