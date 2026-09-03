# -*- coding: utf-8 -*-
"""外部文档一键导入：拆解 → 预览映射 → 作者确认后才写盘

GUI 独有模块（放 app 根，不进 dual_sync 的 SHARED_ROOT_FILES：拆解 prompt 与各落点
的写法都服务于导入对话框，TUI 没有这个入口）。

作者提的两条硬约束，这里不是写进 prompt 祈祷模型自觉，而是各有机器兑现：

1. **只拆文档里真实存在的部分**
   - 逐字型落点（核心设定/大纲/细纲/正文）用 verbatim 比率判定：摘录块与原文对
     不上就是模型自己写的，整条判「未验真」，默认不勾选；
   - 改写型落点（世界书条目/正则/伏笔/角色状态）要求模型附 `引证：` 行，引证走
     scan.verify_quote 验真，一条都对不上即「未验真」。
   未验真**允许作者显式勾选强导**，界面把原因写清楚——契约不凌驾于作者。
2. **导入前预览映射**
   `annotate()` 只产预览项，`apply_import()` 只接受被勾选项。中间没有任何一步碰
   项目文件；不勾选即零副作用。

落盘一律用 `## 导入·<来源>` 独立分区或新建文件，绝不覆盖已有内容：导入的东西要
能整块撤掉，不能和作者自己写的混在一起。
"""
import datetime
import os
import re

from . import project

# 单次 LLM 调用的文档预算：再大就拆段。8 段封顶＝24 万字，超出只解析前 24 万字。
CHUNK_CHARS = 30000
MAX_CHUNKS = 8
# verbatim 判定：摘录块里有多大比例能逐字对上原文
VERB_WINDOW = 24
VERB_STEP = 12
VERB_FLOOR = 0.6
# 预览里给作者看的内容摘要长度
PREVIEW_CHARS = 260

_IMPORT_HEADING_MARKS = ("## 原作·", "## 导入·")

SLOTS = [
    {"key": "canon", "name": "原作", "label": "原作概况（同人借用）",
     "path": "设定/世界书.md", "kind": "section", "verify": "verbatim"},
    {"key": "core", "name": "核心设定", "label": "核心设定 / 题材定位",
     "path": "设定/题材定位.md", "kind": "section", "verify": "verbatim"},
    {"key": "worldbook", "name": "世界书", "label": "世界书（实体与规则）",
     "path": "设定/世界书.md", "kind": "entries", "verify": "evidence"},
    {"key": "regex", "name": "正则", "label": "正则契约",
     "path": "设定/正则.md", "kind": "rules", "verify": "evidence"},
    {"key": "divergence", "name": "分歧点", "label": "原作分歧点（落成 must 契约）",
     "path": "设定/正则.md", "kind": "rules", "verify": "evidence"},
    {"key": "outline", "name": "大纲", "label": "全书大纲",
     "path": "大纲/大纲.md", "kind": "section", "verify": "verbatim"},
    {"key": "outline_ch", "name": "细纲", "label": "章级细纲",
     "path": "大纲/细纲_第%03d章.md", "kind": "chapter", "verify": "verbatim"},
    {"key": "prose", "name": "正文", "label": "正文章节",
     "path": "正文/第%03d章.md", "kind": "chapter", "verify": "verbatim"},
    {"key": "foreshadow", "name": "伏笔", "label": "伏笔台账",
     "path": "追踪/伏笔.md", "kind": "foreshadow", "verify": "evidence"},
    {"key": "canon_timeline", "name": "原作进程", "label": "原作进程（时间线）",
     "path": "追踪/时间线.md", "kind": "timeline", "verify": "evidence"},
    {"key": "charstate", "name": "角色状态", "label": "角色状态",
     "path": "追踪/角色状态.md", "kind": "section", "verify": "evidence"},
]
SLOT_BY_NAME = {s["name"]: s for s in SLOTS}
SLOT_BY_KEY = {s["key"]: s for s in SLOTS}

# 导入记录（撤销靠它）：只记「这次写进去了什么」，撤销时才敢动
IMPORT_LOG_PATH = "设定/导入记录.json"

_NO_CONTENT = {"无", "- 无", "（无）", "(无)", "（暂无）", "暂无", "无内容", "（没有）"}
_QUOTE_RE = re.compile(r"^[> \t*-]*引证\s*[：:]\s*(.+)$")
_SECTION_RE = re.compile(r"^===\s*(.+?)\s*===\s*$")
_NUM_RE = re.compile(r"(\d{1,4})")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_PLAIN_CH_TITLE_RE = re.compile(r"^第\s*\d+\s*章[\s:：、._·—-]*(\S.{0,40})$")
_BULLET_RE = re.compile(r"^(?:[-*•·]\s*)+")


# ---------- 读文档（编码兼容）----------

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "utf-16", "big5")
# utf-16 能把任意偶数字节「解」成乱码，所以光看不报错不够，还要判文本性
_TEXTY_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9\s，。、；：！？“”‘’（）《》【】"
                       r"—…·,.:;!?\"'()\[\]<>%+\-/*&#|]")
_TEXTY_FLOOR = 0.75
_SAMPLE = 20000


def _looks_like_text(text: str) -> bool:
    if "\x00" in text[:_SAMPLE]:
        return False
    sample = text[:_SAMPLE]
    if not sample:
        return False
    return len(_TEXTY_RE.findall(sample)) / len(sample) >= _TEXTY_FLOOR


def read_document(path: str) -> tuple:
    """读外部文档 → (text, error)。编码逐个试，且必须通过文本性判定。"""
    if not path or not os.path.isfile(path):
        return "", "文件不存在"
    text = None
    for enc in _ENCODINGS:
        try:
            with open(path, "r", encoding=enc) as f:
                cand = f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as e:
            return "", str(e)
        if _looks_like_text(cand):
            text = cand
            break
    if text is None:
        return "", "看起来不是文本文档（二进制或乱码）——导入只收 txt / md"
    text = clean_text(text)
    if not text.strip():
        return "", "文件内容为空"
    return text, ""


def normalize_path(raw) -> str:
    """QML FileDialog 给的是 file:/// URL，Windows 下还带斜杠盘符"""
    p = str(raw or "")
    if p.startswith("file:"):
        from urllib.parse import unquote, urlparse
        p = unquote(urlparse(p).path)
        if len(p) >= 3 and p[0] == "/" and p[2] == ":":
            p = p[1:]
        p = p.replace("/", os.sep)
    return p


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("　", " ").replace("﻿", "")
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


def split_chunks(text: str, size: int = CHUNK_CHARS, max_chunks: int = MAX_CHUNKS) -> tuple:
    """长文档切段（优先在空行处断开）→ (chunks, covered_chars)

    超出 size*max_chunks 的部分本轮不解析，covered 让界面如实告诉作者「只解析了
    前 N 字」，不静默丢内容。
    """
    total = len(text)
    if not total:
        return [], 0
    if total <= size:
        return [text], total
    chunks, pos = [], 0
    while len(chunks) < max_chunks and pos < total:
        hard = min(pos + size, total)
        cut = hard
        if hard < total:
            soft = text.rfind("\n\n", pos + size // 2, hard)
            if soft > pos:
                cut = soft
        chunk = text[pos:cut]
        if chunk.strip():
            chunks.append(chunk)
        pos = cut if cut > pos else hard
    return chunks, min(pos, total)


# ---------- prompt ----------

DOC_DECOMPOSE_PROMPT = """你是千笔的「拆解档案管理员」。作者把一份外部文档交进来，你的唯一任务是把里面**真实写过的内容**分门别类摘出来，落进这本书的档案。

## 这本书现状（已有的一律不要重述）
{state_block}

## 待拆解文档（第 {part}／{total} 段）
{document}

## 十一个落点，段名必须一字不差
===原作=== ／ ===核心设定=== ／ ===世界书=== ／ ===正则=== ／ ===分歧点===
===大纲=== ／ ===细纲 第N章=== ／ ===正文 第N章===
===伏笔=== ／ ===原作进程=== ／ ===角色状态===

## 铁律
1. **只摘录，不创作、不改写、不补全、不润色**。文档没写的一个字都不要填——「作者大概还想表达的意思」不是摘录。
2. 某个落点在这段文档里**没有对应内容**，就只写一行：（无）。不要为了凑齐十一段而编。
3. 改写型落点（===原作===／===世界书===／===正则===／===分歧点===／===伏笔===／===原作进程===／===角色状态===）
   每段末尾至少一行 `引证：……`，省略号是**从上面文档逐字复制**的连续片段（10~80 字，去掉空白与
   标点后仍能在原文里找到）。程序会逐条验真；一条都对不上的整段会被判「未验真」，作者要多
   点一次才会写入。
4. `引证：` 行只是给你的凭据，程序会剥掉——除引证行以外的内容才会落盘。
5. 不要输出解释、开场白、结语、代码块围栏。
6. 段落边界可能把一章切成两半：残句照原样摘，不要因为「不像完整一章」就丢掉。

## 各落点写什么、怎么写
- ===原作===：**这份文档是在介绍一部别人的作品**（同人文借用的原作）时才写。第一行必须是
  `书名：《原作书名》｜作者：原作者`（文档里没作者就只写 `书名：《原作书名》`），随后逐字摘录
  原作的世界观概况：力量／规则体系、主要人物关系、原作主线与已发生的结局。
  如果这份文档就是作者本书自己的设定，这一段写（无）。
- ===核心设定===：题材定位、文风要求、卖点、目标读者等**定位性**内容，逐字保留原表述。
- ===世界书===：每行一条 `- **名称**（类别）：描述`。类别限 人物/地名/物品/组织/规则/世界观/其他。
  只收文档里明确介绍过的实体；无名路人、一次性背景板不录。
- ===正则===：每行一条 `- 规则文本｜level：must｜scope：全书`。level 只能是 must 或 should，
  scope 写「全书」或具体范围（如「第2卷」「第1-20章」）。
  **must＝作者要求必须成立的硬约束**，只在文档明说「必须／不得／只能／绝对／禁止」时用；
  语气含糊（尽量／最好／建议）一律 should。
  若约束有可机检的字面判据，写成 `不得出现三连感叹：`!{{3,}}``（反引号内是正则表达式，
  程序会真的拿它拦章节锁定）。没有字面判据的约束不要硬编正则。
- ===分歧点===：本书**与原作出入的地方**——穿越／重生／带记忆／救人／改剧情，以及从哪一章开始分叉。
  每行一条，写成 must 约束：`第N章起：……与原作不再一致，此后……按本书设定成立｜level：must｜scope：第N章后`。
  分歧点必须走这里而不是写进大纲：大纲只是给模型看一眼，must 才会在章节锁定时真的拦住偏离。
  原作概况里没提到本书任何偏离的，写（无）。
- ===大纲===：全书／分卷的主线走向与结构安排，逐字摘录。
- ===细纲 第N章===：第 N 章细纲（情节、冲突、钩子）。文档没给章号、从上下文也定不出来的，写（无）。
- ===正文 第N章===：第 N 章正文原文。**一个字的润色都不要做**，空行分段也照原样。
- ===伏笔===：每行一条 `伏笔内容｜类别｜埋设章节｜计划回收`。类别限 道具谜团/规则契约/数字倒计时/其他。
- ===原作进程===：原作剧情的事件序列（同人用来对齐「原作这时发生了什么」）。
  每行一条 `故事内时间｜原作章节｜事件`。没有明确先后关系的，写（无）。
- ===角色状态===：每行一条 `- 名称：在文档覆盖时点的状态（位置／伤势／持有物／已知信息）`。

只输出上述段落。"""


def state_block(proj: str) -> str:
    """告诉模型这本书已有什么——已有细纲/正文的章号尤其要提醒，免得重复摘"""
    if not proj:
        return "（尚未打开书籍）"
    has = []
    for s in SLOTS:
        if s["kind"] == "chapter":
            continue
        body = project.read_file(os.path.join(proj, s["path"])).strip()
        has.append("%s：%s" % (s["label"], ("已有 %d 字" % len(body)) if body else "空"))
    outs = sorted(n for n, _ in project.list_outlines(proj))
    chs = sorted(project.chapter_nums(proj))

    def rng(xs):
        if not xs:
            return "无"
        if len(xs) == 1:
            return "第%d章" % xs[0]
        return "第%d-%d章（%d 章）" % (xs[0], xs[-1], len(xs))

    return ("档案现状：" + "；".join(has)
            + "；已有细纲 " + rng(outs) + "；已有正文 " + rng(chs))


def build_prompt(doc_chunk: str, part: int, total: int, proj: str = "") -> str:
    return DOC_DECOMPOSE_PROMPT.format(
        state_block=state_block(proj), part=part, total=total, document=doc_chunk)


# ---------- 拆解产物解析 ----------

def _base_name(sec_name: str) -> tuple:
    """段名 → (落点名, 章号或 None)：`细纲 第12章` → ("细纲", 12)

    按名称长度倒序试：`原作` 是 `原作进程` 的前缀，正序会把后者误判成前者。
    """
    m = _NUM_RE.search(sec_name)
    base = re.sub(r"\s+", "", sec_name[:m.start()] if m else sec_name)
    for name in sorted(SLOT_BY_NAME, key=len, reverse=True):
        if base.startswith(name):
            return name, (int(m.group(1)) if m else None)
    return base, None


def _split_sections(text: str) -> list:
    """模型输出 → [(段名, 正文)]；同段落点可出现多次；非段名的标题行算正文"""
    out, cur, buf = [], None, []
    for line in (text or "").splitlines():
        m = _SECTION_RE.match(line.strip())
        if m and SLOT_BY_NAME.get(_base_name(m.group(1))[0]):
            if cur is not None:
                out.append((cur, "\n".join(buf)))
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out.append((cur, "\n".join(buf)))
    return out


def _strip_quotes(body: str) -> tuple:
    """段正文 → (落盘内容, [引证…])；引证行不进文件"""
    keep, quotes = [], []
    for line in (body or "").splitlines():
        m = _QUOTE_RE.match(line.strip())
        if m:
            q = m.group(1).strip().strip("“”\"'「」『』")
            if q:
                quotes.append(q)
            continue
        keep.append(line)
    text = "\n".join(keep).strip("\n")
    if text.strip() in _NO_CONTENT:
        text = ""
    return text, quotes


def _content_lines(body: str) -> list:
    out = []
    for line in (body or "").splitlines():
        s = line.strip()
        if s and s not in _NO_CONTENT:
            out.append(s)
    return out


_SCOPE_FROM_TEXT = re.compile(r"^[\s「『]*(?:自|从)?\s*第\s*(\d{1,4})\s*章\s*(?:起|后|开始)?")


def _as_rule_line(s: str) -> str:
    """规则行统一成 `- 规则：…｜level：…｜scope：…`（regex_rules 认的形状）"""
    body = _BULLET_RE.sub("", s).strip()
    body = re.sub(r"^规则\s*[：:]\s*", "", body)
    if not re.search(r"level\s*[：:]", body, re.I):
        body += "｜level：must"
    if not re.search(r"scope\s*[：:]", body, re.I):
        # 漏写章域时从「第N章起…」的文本里补——分歧点的意义就在它只管某章之后
        m = _SCOPE_FROM_TEXT.match(body)
        body += ("｜scope：第%s章后" % m.group(1)) if m else "｜scope：全书"
    return "- 规则：" + body


_ENTRY_NCD = re.compile(r"^(?:\*\*)?([^*（(：:|｜\n]{1,24})(?:\*\*)?\s*[（(]([^）)]{1,10})[）)]"
                        r"\s*[：:]\s*(.+)$")
_ENTRY_NC = re.compile(r"^(?:\*\*)?([^*：:|｜\n]{1,24})(?:\*\*)?\s*[：:]\s*(.+)$")


def _as_entry_line(s: str) -> str:
    """世界书条目行：`名称（类别）：描述` → `- **名称**（类别）：描述`"""
    body = _BULLET_RE.sub("", s).strip()
    if body.startswith("**"):
        return "- " + body
    m = _ENTRY_NCD.match(body)
    if m:
        return "- **%s**（%s）：%s" % (m.group(1).strip(), m.group(2).strip(),
                                       m.group(3).strip())
    m = _ENTRY_NC.match(body)
    if m:
        return "- **%s**（其他）：%s" % (m.group(1).strip(), m.group(2).strip())
    return "- " + body


def parse_product(text: str) -> list:
    """模型输出 → 原始条目 [{key,label,num,content,quotes}]，同 (key,num) 不去重"""
    items = []
    for sec_name, body in _split_sections(text):
        name, num = _base_name(sec_name)
        slot = SLOT_BY_NAME.get(name)
        if not slot:
            continue
        content, quotes = _strip_quotes(body)
        kind = slot["kind"]
        if kind in ("entries", "rules", "foreshadow", "timeline"):
            lines = _content_lines(content)
            if not lines:
                continue
            if kind == "rules":
                content = "\n".join(_as_rule_line(l) for l in lines)
            elif kind == "entries":
                content = "\n".join(_as_entry_line(l) for l in lines)
            else:
                content = "\n".join(lines)
        else:
            content = clean_text(content)
        if not content.strip():
            continue
        if kind == "chapter" and not num:
            continue      # 章号定不出来就没法落点，宁可不导也不乱建文件
        items.append({"key": slot["key"], "label": slot["label"], "num": num,
                      "content": content, "quotes": quotes,
                      "canon": _canon_name(content) if slot["key"] == "canon" else ""})
    return items


_CANON_RE = re.compile(r"书名\s*[：:]\s*(?:《[^》]+》|\S{1,40})")


def _canon_name(content: str) -> str:
    """从原作概况里取《书名》：模型被要求首行写 `书名：《X》｜作者：Y`"""
    m = _CANON_RE.search(content or "")
    if not m:
        return ""
    v = re.sub(r"^书名\s*[：:]\s*", "", m.group(0)).strip()
    return v.strip("《》").strip()[:40]


def merge_items(groups: list) -> list:
    """多段文档的条目按 (key,num) 合并；重复内容不重复累加"""
    acc, order = {}, []
    for items in groups:
        for it in items:
            k = (it["key"], it["num"])
            if k not in acc:
                acc[k] = dict(it, quotes=list(it["quotes"]))
                order.append(k)
                continue
            cur = acc[k]
            for q in it["quotes"]:
                if q not in cur["quotes"]:
                    cur["quotes"].append(q)
            new = (it["content"] or "").strip()
            if new and new not in cur["content"]:
                cur["content"] = (cur["content"].rstrip() + "\n\n" + new).strip()
    return [acc[k] for k in order]


# ---------- 验真 ----------

def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isalnum())


def verbatim_ratio(source: str, block: str) -> float:
    """摘录块有多大比例能逐字对上原文（1.0＝整块照抄，≈0＝模型自己写的）"""
    src, txt = _norm(source), _norm(block)
    if not txt:
        return 0.0
    if len(txt) < VERB_WINDOW:
        return 1.0 if txt in src else 0.0
    hits = wins = 0
    i = 0
    while i + VERB_WINDOW <= len(txt):
        wins += 1
        if txt[i:i + VERB_WINDOW] in src:
            hits += 1
        i += VERB_STEP
    return hits / wins if wins else 0.0


def _canon_guard_rule(canon: str) -> str:
    return ("- 规则：原作《%s》已确立的人物性格、称谓与既成事实不得改写；"
            "除本书分歧点外一律遵循原作｜level：must｜scope：全书" % canon)


def annotate(items: list, source: str, proj: str) -> list:
    """补上落点路径、验真结论与默认勾选态 → 预览项（不写盘）"""
    from .core.scan import verify_quote
    plans = []
    canon = next((it.get("canon") for it in items if it.get("canon")), "")
    for it in items:
        slot = SLOT_BY_KEY[it["key"]]
        num = it["num"]
        rel = _chapter_target(proj, slot["key"], num, it["content"]) \
            if slot["kind"] == "chapter" else slot["path"]
        ok = sum(1 for q in it["quotes"] if verify_quote(source, q)[0])
        total = len(it["quotes"])
        verb = (verbatim_ratio(source, it["content"])
                if slot["verify"] == "verbatim" else None)
        if verb is not None and verb < VERB_FLOOR:
            trust, reason = False, "与原文逐字比对仅 %d%%，疑似改写而非摘录" % round(verb * 100)
        elif total and not ok:
            trust, reason = False, "%d 条引证在原文里都找不到" % total
        else:
            trust, reason = True, ""
        plans.append({
            "key": it["key"], "label": slot["label"], "num": num or 0,
            "target": rel.replace("/", os.sep), "targetSlash": rel,
            "content": it["content"], "chars": project.count_chars(it["content"]),
            "quotesTotal": total, "quotesOk": ok,
            "verbatim": round(verb * 100) if verb is not None else -1,
            "trust": trust, "checked": trust, "reason": reason,
            "canon": it.get("canon") or canon, "suggested": False,
            "exists": bool(project.read_file(os.path.join(proj, rel)).strip()),
            "preview": it["content"][:PREVIEW_CHARS].replace("\n", " ⏎ "),
        })
    if canon:
        rule = _canon_guard_rule(canon)
        slot = SLOT_BY_KEY["regex"]
        plans.append({
            "key": "regex", "label": slot["label"], "num": 0,
            "target": slot["path"].replace("/", os.sep), "targetSlash": slot["path"],
            "content": rule, "chars": project.count_chars(rule),
            "quotesTotal": 0, "quotesOk": 0, "verbatim": -1,
            "trust": True, "checked": True, "reason": "",
            "canon": canon, "suggested": True,
            "exists": False, "preview": rule,
        })
    return sorted(plans, key=lambda p: (p["key"], p["num"], 0 if p["suggested"] else 1))


def _chapter_target(proj: str, key: str, num, content: str) -> str:
    """章级落点路径。**章号已在盘上就返回既有文件路径**——按标题新建会让同一章
    并存两个文件（第012章_旧名.md / 第012章_新名.md），list_chapters 读出两条。"""
    num = int(num)
    if key == "prose":
        for n, name, p in project.list_chapters(proj):
            if n == num:
                return "正文/" + name
        return ("正文/" + project.chapter_filename(num, _chapter_title(content))).replace(os.sep, "/")
    for n, p in project.list_outlines(proj):
        if n == num:
            return "大纲/" + os.path.basename(p)
    return "大纲/" + project.outline_filename(num)


def _chapter_title(content: str) -> str:
    """从摘录内容里取章题（文件名后缀）：`# 第12章 赎票` 与 `第12章 赎票` 都认"""
    for line in (content or "").splitlines():
        s = line.strip()
        m = _H1_RE.match(s) or _PLAIN_CH_TITLE_RE.match(s)
        if m:
            return re.sub(r"^第\s*\d+\s*章[\s:：、._·—-]*", "", m.group(1)).strip()[:40]
    return ""


def missing_slots(plans: list) -> list:
    """文档里没有的落点——如实列出来，作者才知道 Agent 没替他编东西"""
    seen = {p["key"] for p in plans}
    return [{"key": s["key"], "label": s["label"]} for s in SLOTS if s["key"] not in seen]


# ---------- 落盘 ----------

def _import_heading(source_label: str, canon_title: str = "") -> str:
    """世界书分区标题。同人的借用世界观**必须以原作名标识**——作者翻档案时要能一眼
    看出哪一段不是自己写的；没有原作名才退回用文件名。"""
    name = (canon_title or source_label or "外部文档").strip()
    mark = "## 原作·" if canon_title else "## 导入·"
    return "%s%s（%s）" % (mark, name[:60], datetime.date.today().isoformat())


def _block_heading(ln: str) -> bool:
    s = (ln or "").lstrip()
    return any(s.startswith(m) for m in _IMPORT_HEADING_MARKS)


def _append_section(path: str, heading: str, content: str) -> dict:
    """追加一个独立分区。同一段内容已在文件里就不再堆第二份。"""
    doc = project.read_file(path)
    body = content.strip()
    if _norm(body) and _norm(body) in _norm(doc):
        return {"added": 0, "skipped": 1, "sha": ""}
    project.write_file(path, (doc.rstrip() + "\n\n" if doc.strip() else "")
                       + heading + "\n\n" + body + "\n")
    return {"added": 1, "skipped": 0, "sha": _sha(body)}


def _import_blocks(lines: list) -> list:
    """[(起始行, 结束行)] —— 文中每个导入/原作分区的行区间（末块延伸到文件尾）"""
    marks = [i for i, ln in enumerate(lines) if _block_heading(ln)]
    out = []
    for j, i in enumerate(marks):
        end = marks[j + 1] if j + 1 < len(marks) else len(lines)
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1
        out.append((i, end))
    return out


def _remove_blocks(path: str, heading: str) -> int:
    """删掉标题完全匹配的分区（含其后直到下一个同级标题前的所有行）"""
    lines = project.read_file(path).splitlines()
    hits = [i for i, ln in enumerate(lines) if ln.strip() == heading.strip()]
    if not hits:
        return 0
    keep = [True] * len(lines)
    for i in hits:
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break
        for k in range(i, end):
            keep[k] = False
    project.write_file(path, "\n".join(l for l, k in zip(lines, keep) if k).rstrip() + "\n")
    return len(hits)


def _entry_name(line: str) -> str:
    body = _BULLET_RE.sub("", (line or "").strip())
    m = re.match(r"^(?:\*\*)?([^*（(：:|｜\s]{1,24})", body)
    return m.group(1) if m else ""


def _append_entries(path: str, heading: str, lines: list) -> dict:
    """世界书条目并进已有的导入分区；全文同名的条目跳过（那不是新东西）

    判重口径与 memory.upsert_worldbook_entries 一致：归一化后看名字是否已在世界书
    全文出现过。不能用 wb.roster_names——它的行名正则要求专名后紧跟冒号，
    `- **当铺**（地点）：…` 这种带括注的规范条目恰好抓不到。
    """
    doc = project.read_file(path)
    known = _norm(doc)
    added, skipped = [], 0
    for ln in lines:
        key = _norm(_entry_name(ln))
        if key and key in known:
            skipped += 1
            continue
        known += key
        added.append(ln)
    if not added:
        return {"added": 0, "skipped": skipped, "wrote": [], "block": None}
    file_lines = doc.splitlines()
    blocks = _import_blocks(file_lines)
    if not blocks:
        r = _append_section(path, heading, "\n".join(added))
        if not r["added"]:
            return {"added": 0, "skipped": skipped + len(added), "wrote": [], "block": None}
        return {"added": len(added), "skipped": skipped, "wrote": [],
                "block": {"heading": heading, "sha": r["sha"]}}
    at = blocks[-1][1]
    while at - 1 > blocks[-1][0] and not file_lines[at - 1].strip():
        at -= 1
    file_lines[at:at] = [""] if at < len(file_lines) else []
    file_lines[at:at] = added
    project.write_file(path, "\n".join(file_lines) + "\n")
    return {"added": len(added), "skipped": skipped, "wrote": added, "block": None}


def _append_rules(proj: str, path: str, lines: list) -> dict:
    doc = project.read_file(path).rstrip()
    # regex_rules 的 rule 文本保留 `规则：` 前缀（_regex_rule_line 就那样写），
    # 探针必须用同一口径，否则永远比不中、重复导入静默累加
    existing = {_norm(r["rule"]) for r in project.regex_rules(proj)}
    added, skipped = [], 0
    for ln in lines:
        probe = _norm(re.split(r"[｜|]", _BULLET_RE.sub("", ln), maxsplit=1)[0])
        if probe and probe in existing:
            skipped += 1
            continue
        existing.add(probe)
        added.append(ln)
    if not added:
        return {"added": 0, "skipped": skipped, "wrote": [], "block": None}
    project.write_file(path, (doc + "\n" if doc else "") + "\n".join(added) + "\n")
    return {"added": len(added), "skipped": skipped, "wrote": added, "block": None}


def _table_row(ln: str) -> list:
    s = ln.strip()
    if not s.startswith("|"):
        return None
    return [c.strip() for c in s.strip("|").split("|")]


def _find_table(lines: list, heads: tuple) -> tuple:
    """(表头行号, 表尾行号, 列名)；表尾＝从表头往下**连续**的表格块最后一行"""
    for i, ln in enumerate(lines):
        cells = _table_row(ln)
        if cells and cells[0] in heads:
            last = i
            for j in range(i + 1, len(lines)):
                if _table_row(lines[j]) is None:
                    break
                last = j
            return i, last, cells
    return -1, -1, []


# 模型给的字段序是固定的，但各本书的表头列序/列数不一样（4 列老表 / 6 列反哺表），
# 必须按**列名**落位而不是按位置灌
_TABLE_SPECS = {
    "foreshadow": {
        "heads": ("伏笔", "伏笔内容"),
        "fields": ("伏笔", "类别", "埋设章节", "计划回收"),
        "synonyms": {"伏笔": ("伏笔", "内容", "悬念"), "类别": ("类别", "类型"),
                     "埋设章节": ("埋设", "章节"), "计划回收": ("回收",),
                     "状态": ("状态", "现状"), "备注": ("备注", "说明")},
        "defaults": {"状态": "未回收", "备注": "导入"},
        "key": "伏笔", "fallback": "## 导入伏笔",
    },
    "timeline": {
        "heads": ("故事内时间", "时间", "原作进程"),
        "fields": ("故事内时间", "章节", "事件"),
        "synonyms": {"故事内时间": ("时间", "纪年"), "章节": ("章节", "章"),
                     "事件": ("事件", "情节", "描述")},
        "defaults": {},
        "key": "事件", "fallback": "## 导入原作进程",
    },
}


def _column_map(cols: list, spec: dict) -> dict:
    """表头列名 → {模型字段: 列下标}；同一列被多个别名命中时取先声明的字段"""
    used, mapping = set(), {}
    for field in spec["fields"] + tuple(spec["defaults"]):
        for name in spec["synonyms"].get(field, (field,)):
            hit = next((j for j, c in enumerate(cols) if name in c and j not in used), None)
            if hit is not None:
                mapping[field] = hit
                used.add(hit)
                break
    return mapping


def _append_table(path: str, lines: list, kind: str) -> dict:
    """按现有表头的列名对齐追加；判重列同名的行跳过；找不到表则整段作普通文本追加"""
    spec = _TABLE_SPECS[kind]
    doc = project.read_file(path)
    file_lines = doc.splitlines()
    head, last, cols = _find_table(file_lines, spec["heads"])
    if not cols:
        r = _append_section(path, spec["fallback"], "\n".join(lines))
        return {"added": r["added"], "skipped": len(lines) - r["added"], "wrote": [],
                "block": {"heading": spec["fallback"], "sha": r["sha"]} if r["added"] else None}
    cmap = _column_map(cols, spec)
    key_col = cmap.get(spec["key"], 0)
    known = set()
    for i in range(head + 1, last + 1):
        if "---" in file_lines[i]:
            continue
        row = _table_row(file_lines[i])
        if row and len(row) > key_col:
            known.add(_norm(row[key_col]))
    rows, skipped = [], 0
    for ln in lines:
        parts = [p.strip().replace("|", "｜") for p in re.split(r"[｜|]", ln)]
        if not parts or not parts[0]:
            continue
        cells = [""] * len(cols)
        for j, field in enumerate(spec["fields"]):
            col = cmap.get(field)
            if col is not None and j < len(parts) and parts[j]:
                cells[col] = parts[j]
        for field, col in cmap.items():
            if field in spec["defaults"] and not cells[col]:
                cells[col] = spec["defaults"][field]
        probe = _norm(cells[key_col] if len(cells) > key_col else parts[0])
        if probe and probe in known:
            skipped += 1
            continue
        known.add(probe)
        rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return {"added": 0, "skipped": skipped, "wrote": [], "block": None}
    at = last + 1
    while at < len(file_lines) and file_lines[at].strip() == "":
        at += 1
    file_lines[at:at] = rows
    project.write_file(path, "\n".join(file_lines) + "\n")
    return {"added": len(rows), "skipped": skipped, "wrote": rows, "block": None}


CONST_MARK = "[常驻]"


def _mark_const(line: str) -> str:
    """给原作条目加常驻标记：世界书超预算按档裁剪时，借来的世界观不能第一批被裁掉

    诚实边界：`wb` 只在**裁剪路径**上剥标记；「全文不超预算 → 逐字返回原文件」这条
    快速路径不剥，标记会原样出现在注入文本里。那条路径下所有条目本来都进得来，
    标记不影响取舍，只是多四个字符——比起原作设定被静默裁掉，这个代价可以接受。
    """
    s = line.rstrip()
    return s if CONST_MARK in s else s + " " + CONST_MARK


def apply_import(proj: str, plans: list, source_label: str = "",
                 canon_title: str = "") -> dict:
    """只写被勾选的预览项 → {written, skipped, batch, report}"""
    if not proj:
        return {"written": [], "skipped": [], "batch": "", "report": "未打开书籍"}
    canon_title = canon_title or next(
        (p.get("canon") for p in plans if p.get("canon")), "")
    heading = _import_heading(source_label)
    # 只有世界书里那一段是「借来的世界观」，要用原作名标识；核心设定/大纲/角色状态
    # 是作者自己的东西，仍按文件名归档，否则会把原创误标成原作
    wb_heading = _import_heading(source_label, canon_title) \
        if canon_title else heading
    written, skipped = [], []
    record = {"lines": [], "blocks": [], "files": []}
    for p in plans:
        if not p.get("checked"):
            continue
        slot = SLOT_BY_KEY.get(p["key"])
        if not slot:
            skipped.append((p.get("label") or p["key"], "未知落点"))
            continue
        rel = p.get("targetSlash") or slot["path"]
        path = os.path.join(proj, rel)
        kind = slot["kind"]
        if kind == "chapter":
            if project.read_file(path).strip():
                skipped.append(("%s 第%d章" % (p["label"], p["num"]), "目标已存在，未覆盖"))
                continue
            body = p["content"].strip() + "\n"
            project.write_file(path, body)
            record["files"].append({"path": rel, "sha": _sha(body)})
            written.append("%s 第%d章 → %s" % (p["label"], p["num"], p["target"]))
            continue
        lines = [l for l in p["content"].splitlines() if l.strip()]
        if not lines:
            skipped.append((p["label"], "内容为空"))
            continue
        if kind == "entries":
            if canon_title:
                lines = [_mark_const(l) for l in lines]
            r = _append_entries(path, wb_heading, lines)
        elif kind == "rules":
            r = _append_rules(proj, path, lines)
        elif kind in ("foreshadow", "timeline"):
            r = _append_table(path, lines, kind)
        else:
            use = wb_heading if p["key"] in ("canon", "worldbook") else heading
            r = _append_section(path, use, p["content"])
            r["skipped"] = 1 - r["added"]
            r["wrote"] = []
            r["block"] = {"heading": use, "sha": r["sha"]} if r["added"] else None
        if r.get("wrote"):
            record["lines"].append({"path": rel, "texts": r["wrote"]})
        if r.get("block"):
            record["blocks"].append({"path": rel, **r["block"]})
        if kind == "section":
            note = ("追加 %d 字" % p["chars"]) if r["added"] else "内容已在文件中，未重复追加"
        else:
            note = "新增 %d 项" % r["added"]
            if r["skipped"]:
                note += "，重复/同名跳过 %d 项" % r["skipped"]
        if r["added"]:
            written.append("%s → %s（%s）" % (p["label"], slot["label"], note))
        else:
            skipped.append((p["label"], note))
    batch = ""
    if written or record["lines"] or record["blocks"] or record["files"]:
        batch = _record_batch(proj, source_label, canon_title, written, record)
    parts = ["已导入 %d 项：" % len(written) + "；".join(written) if written
             else "没有导入任何内容"]
    if skipped:
        parts.append("跳过 %d 项：" % len(skipped)
                     + "；".join("%s（%s）" % s for s in skipped))
    if batch:
        parts.append("本批编号 %s（可在契约页整批撤销）" % batch)
    return {"written": written, "skipped": skipped, "batch": batch,
            "report": "。".join(parts)}


# ---------- 导入清单与整批撤销 ----------

def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _load_log(proj: str) -> list:
    import json
    raw = project.read_file(os.path.join(proj, IMPORT_LOG_PATH))
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return data.get("batches", []) if isinstance(data, dict) else []


def _save_log(proj: str, batches: list):
    import json
    project.write_file(os.path.join(proj, IMPORT_LOG_PATH),
                       json.dumps({"batches": batches[-40:]}, ensure_ascii=False, indent=1))


def _record_batch(proj: str, source_label: str, canon_title: str,
                  written: list, record: dict) -> str:
    now = datetime.datetime.now()
    batch = {"id": now.strftime("%Y%m%d-%H%M%S"), "ts": now.isoformat(timespec="seconds"),
             "label": source_label, "canon": canon_title, "items": len(written)}
    batch.update(record)
    batches = _load_log(proj)
    batches.append(batch)
    _save_log(proj, batches)
    return batch["id"]


def import_batches(proj: str) -> list:
    """历史导入批次（新→旧），供界面列撤销入口"""
    out = []
    for b in reversed(_load_log(proj)):
        out.append({"id": b.get("id", ""), "label": b.get("label") or "外部文档",
                    "canon": b.get("canon") or "", "ts": (b.get("ts") or "")[:10],
                    "items": b.get("items", 0),
                    "undo": len(b.get("lines", [])) + len(b.get("blocks", []))
                            + len(b.get("files", []))})
    return out


def _remove_texts(path: str, texts: list) -> int:
    """按整行精确匹配删除（每条只删第一次出现）；作者改过的行匹配不上即不动"""
    lines = project.read_file(path).splitlines()
    drop = set()
    for t in texts:
        want = t.strip()
        for i, ln in enumerate(lines):
            if i not in drop and ln.strip() == want:
                drop.add(i)
                break
    if not drop:
        return 0
    project.write_file(path, "\n".join(l for i, l in enumerate(lines) if i not in drop).rstrip() + "\n")
    return len(drop)


def revert_import(proj: str, batch_id: str) -> dict:
    """按清单回滚一个导入批次

    只认三种确定性事实：这次写进去的整行、这次新建的分区标题、这次新建的文件。
    文件内容被后续编辑过（哈希不符）就不删，行被作者改过（整行匹配不上）就不删——
    撤销的是导入，不是撤销作者。
    """
    batches = _load_log(proj)
    batch = next((b for b in batches if b.get("id") == batch_id), None)
    if not batch:
        return {"ok": False, "report": "找不到批次 %s 的导入记录" % batch_id}
    removed, kept = [], []
    for entry in batch.get("lines", []):
        path = os.path.join(proj, entry["path"].replace("/", os.sep))
        n = _remove_texts(path, entry.get("texts", []))
        left = len(entry.get("texts", [])) - n
        removed.append("%s 删 %d 行" % (entry["path"], n))
        if left > 0:
            kept.append("%s 有 %d 行已被改动，保留" % (entry["path"], left))
    for entry in batch.get("blocks", []):
        path = os.path.join(proj, entry["path"].replace("/", os.sep))
        lines = project.read_file(path).splitlines()
        hit = [i for i, ln in enumerate(lines) if ln.strip() == entry["heading"].strip()]
        if not hit:
            continue
        i = hit[0]
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break
        body = "\n".join(lines[i + 1:end]).strip()
        if entry.get("sha") and _sha(body) != entry["sha"]:
            kept.append("%s 的导入分区已被改动，整块保留" % entry["path"])
            continue
        _remove_blocks(path, entry["heading"])
        removed.append("%s 删分区「%s」" % (entry["path"], entry["heading"][:28]))
    for entry in batch.get("files", []):
        path = os.path.join(proj, entry["path"].replace("/", os.sep))
        if not os.path.isfile(path):
            continue
        if _sha(project.read_file(path)) != entry.get("sha"):
            kept.append("%s 导入后被编辑过，保留" % entry["path"])
            continue
        os.remove(path)
        removed.append("删除 %s" % entry["path"])
    batches = [b for b in batches if b.get("id") != batch_id]
    _save_log(proj, batches)
    report = "已撤销 %s：" % batch_id + "；".join(removed) if removed \
        else "批次 %s 没有可确定性回滚的内容" % batch_id
    if kept:
        report += "。保留 " + "；".join(kept)
    return {"ok": bool(removed), "report": report}
