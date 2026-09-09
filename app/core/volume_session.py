# -*- coding: utf-8 -*-
"""卷级会话消息栈（S1，成本优化方案 v3 §2）：一卷一个会话，逐章累积跨章历史

ChapterSession（章会话）把「一章」变成一个消息栈，但每章仍从头重建——章头每章
miss 一次、hit 基数永远只有一章。VolumeSession 把边界从「章」推到「卷」：

- system 只含全书冻结前缀（project_header）——**chapter_header 从 system 挪到
  每章开幕轮**（open_chapter）。system 里放任何逐章变化的内容 = 每章全灭缓存；
  挪到追加轮后，章头只 miss 一次、此后永久命中；
- open_chapter(header, first_turn)：把「开幕声明 + 章头 + 本章首个相位轮」合成
  一条追加 user 轮。开幕声明显式标识本章正文（「本章正文以本次回复为准」）——
  session_turn_text 的 {prose} 历史引用在卷栈里跨章后指向「最近一条章正文消息」，
  开幕轮的声明把该语义重新锚定到本章；
- rollback_to/commit_turn/snapshot/ask 语义与 ChapterSession 完全一致
  （继承复用）：成功才固化、失败栈保持原状、闸门回退截断历史；
- 持久化：`项目/会话/卷N_messages.jsonl` append-only（一行一条消息 JSON）。
  save() 逐章调用只追加新行；load() 恢复后消息逐字节一致——服务端前缀缓存
  继续有效（崩溃恢复不需要重放，也不重新 miss）。栈被回退截断后 save() 整文
  重写一次（罕见路径；前缀缓存按位置匹配，截断后前缀仍命中）。

与 ChapterSession 的语义差异（调用方需知的全部）：
  1. restart_with_prose 不再重置栈——卷栈的历史是 1..N-1 章的累积，重置即全丢；
     断点正文经种子并入下一次 ask（与章会话同机制，只是不清栈）；
  2. open_chapter 对同一章重入（G9 重写本章）先截回本章开幕前，再重新开幕——
     被否决的上一轮尝试不留进历史。
"""
import functools
import json
import os
import re

from .chapter_session import ChapterSession

# 开幕声明（本会话语义锚点）：卷栈跨章后 session_turn_text 的 {prose} 引用行
# 写的是「最近一条完整的章正文消息」，开幕轮用它把「本章正文」显式指到本章首轮回复。
OPENING_MARK = ("【第 {num} 章开幕：以下为本章共享上下文与写作指令，"
                "本章正文以本次回复为准】")

_OPENING_NUM_RE = re.compile(r"^【第 (\d+) 章开幕：")

# 卷号→文件名（成本优化方案 v3 §2.4）：项目/会话/卷N_messages.jsonl
_VOLUME_FILE = "卷{vol}_messages.jsonl"
# 接力压缩（长程压缩 §4.3/§6.2）另起的新栈：卷N_cK_messages.jsonl（旧栈留盘作证据）
_VOLUME_FILE_GEN = "卷{vol}_c{gen}_messages.jsonl"


def volume_messages_path(proj: str, volume: int, gen: int = 0) -> str:
    """卷会话消息栈的落盘路径：{proj}/会话/卷{volume}_messages.jsonl。

    gen>0 = 压缩后另起的第 gen 代栈（历史已折叠成交接块，旧栈原样保留可审计）；
    gen=0 保持既有文件名——改造前的栈与断点续跑一律逐字节兼容。"""
    name = (_VOLUME_FILE.format(vol=int(volume)) if int(gen) <= 0
            else _VOLUME_FILE_GEN.format(vol=int(volume), gen=int(gen)))
    return os.path.join(proj, "会话", name)


def opening_marker(chapter_num: int) -> str:
    return OPENING_MARK.format(num=int(chapter_num))


def chapter_of_opening(text: str) -> int:
    """从 user 轮文本解析章开幕声明里的章号；非开幕轮返回 0。"""
    m = _OPENING_NUM_RE.match(text or "")
    return int(m.group(1)) if m else 0


# 卷号解析（章号 → 卷号）：从 大纲/大纲.md 卷级大纲的章号声明按出现顺序切分。
# 解析不出任何卷声明（旧格式大纲/自由体）时整体回退卷 1——单栈语义，
# 正确性不受影响，只是文件名退化为「卷1」。卷结构解析是启发式的，供 gate 评审。
_VOLUME_HEAD_RE = re.compile(
    r"^#{2,4}\s*第[0-9一二两三四五六七八九十百]+卷[^\n]*", re.M)
# 绝对区间声明「（第14-25章…）」「（第1章-第60章）」→ 25/60 是本卷**末章号**。
# 早于章数式判断：区间里的末章号不是"本卷有几章"，混用会把卷界整体后移
# （t3_long60 实测：真卷界 13/25/37/46/50 被算成 13/38/75/121/171）。
_VOLUME_RANGE_RE = re.compile(
    r"第\s*(\d[\d,]*)\s*章?\s*[-—–~～至到]\s*第?\s*(\d[\d,]*)\s*章")
# 相对章数声明「（约15万字，50章）」→ 本卷 50 章，起点 = 上一卷末章 + 1。
_VOLUME_COUNT_RE = re.compile(r"(\d[\d,]*)\s*章")


def _volume_head_end(line: str, prev_end: int):
    """单条卷级标题 → 本卷末章号（绝对）；无可用声明返回 None。

    章数式的 end = prev_end + count，与「累计求和」逐字节等价（纯章数大纲下
    本函数与改造前返回同样的边界）。"""
    m = _VOLUME_RANGE_RE.search(line)
    if m:
        try:
            start, end = (int(m.group(1).replace(",", "")),
                          int(m.group(2).replace(",", "")))
        except ValueError:
            pass
        else:
            if end >= start > 0:
                return end
    m = _VOLUME_COUNT_RE.search(line)
    if m:
        try:
            count = int(m.group(1).replace(",", ""))
        except ValueError:
            return None
        if count > 0:
            return prev_end + count
    return None


def resolve_volume_number(proj: str, num: int) -> int:
    """章号 → 卷号：优先取大纲卷级「第X-Y章」区间的绝对末章号，退回「N章」累计。"""
    from .. import project
    try:
        text = project.read_file(os.path.join(proj, "大纲", "大纲.md"))
    except Exception:  # noqa: BLE001
        return 1
    if num <= 0:
        return 1
    cum = 0
    idx = 0
    for m in _VOLUME_HEAD_RE.finditer(text or ""):
        end = _volume_head_end(m.group(0), cum)
        if end is None:
            continue
        idx += 1
        cum = end
        if num <= cum:
            return idx
    return max(idx, 1)


# ---- S4-a：写作指令库前置（成本优化方案 v3 §3/S4；仅卷会话 system 使用）----
#
# PROSE_WRITING_PROMPT 的指令体（写作硬约束 0-20/格式契约/输出预算等除双层前缀外
# 的静态部分）原本每章随开幕轮重发 = 每章 ~4-5k tok 全价 miss（S1 实测：prose 首轮
# miss 27.8-33.1k/笔，占全部 miss 的 52%）。改为构造时一次冻结进 system：
#   - 逐章变量（{chapter_num}/{word_target} 等）→「按开幕轮给定的值执行」字样；
#   - 上下文占位符（{worldbook_block}/{regex_block}/{chapter_header}）→
#     「以共享上下文与本章开幕轮为准」；
#   - {style_discipline} 是代码常量（全书恒定）→ 原文内联；
#   - tic_blacklist/craft_block/author_note/下一章预告/用户想法等逐章动态值
#     → 留在每章开幕轮（stages._volume_prose_opening_values）。
# 指令库字节 = 缓存域：任何变更 = 全卷缓存全灭一次，只能随版本发布。
# 静态/动态切分标准：同一本书 20 章内逐字节不变的部分进指令库，会变的留开幕轮。

_LIBRARY_HEADER = "## 写作指令库（全书冻结·所有章节通用）"

# （原始模板逐字子串 → 冻结文本）：顺序即执行顺序。命中处均为模板原文，
# PROSE_WRITING_PROMPT 变更后必须同步本表（缺失即构造期抛错，不静默漂移）。
_LIBRARY_REPLACEMENTS = (
    ("你是网络小说叙事写手。请根据以上共享上下文写作第 {chapter_num} 章正文。",
     "你是网络小说叙事写手。按本指令库执行本章写作：章号以开幕轮给定的值为准，"
     "共享上下文（细纲/状态/伏笔/上一章锚点）以本章开幕轮为准。"),
    ("{worldbook_block}",
     "（世界书事实基准以系统「世界书·常驻条目」与本章开幕轮给定的激活块为准）"),
    ("{regex_block}",
     "（正则约束以系统「正则契约」节与本章开幕轮给定的规则块为准）"),
    ("（无则按 {word_target} 字）", "（无则按开幕轮给定的本章字数目标执行）"),
    ("1. 字数目标：{word_target} 字（允许 ±10%）",
     "1. 字数目标：以开幕轮给定的本章字数目标为准（允许 ±10%）"),
    ("**最后自检：全文长度必须落在 {word_target} 字 ±10% 内",
     "**最后自检：全文长度必须落在开幕轮给定的本章字数目标 ±10% 内"),
    ("{next_chapter_brief}", "（以本章开幕轮给定的「下一章预告」为准）"),
    ("{user_guidance}", "（以本章开幕轮给定的「用户补充指导」为准）"),
    ("{user_ideas}", "（以本章开幕轮给定的「用户创作想法」为准）"),
    ("{used_setpieces}", "（以本章开幕轮给定的「名场面不复用清单」为准）"),
    ("{craft_block}", "（以本章开幕轮给定的「本章工艺路线」为准）"),
    ("{tic_blacklist}", "（以本章开幕轮给定的「口头禅黑名单」为准）"),
    ("{author_note}", "（以本章开幕轮给定的「作者按」为准）"),
    ("第一行输出章名：# 第{chapter_num}章 {{章名}}",
     "第一行输出章名：# 第N章 {章名}（N 为开幕轮给定的章号）"),
)


@functools.lru_cache(maxsize=1)
def prose_instruction_library() -> str:
    """PROSE 指令体的模板化冻结版（全书冻结·所有章节通用，S4-a）。

    在原始模板串上做定点替换（不 .format——{{章名}} 转义与占位符语义不参与）；
    模板漂移（找不到待冻结片段）或残留 {xxx} 逐章占位符一律抛错——指令库混入
    逐章变量 = 每章全灭缓存，必须在构造期爆掉而不是静默上屏。
    """
    from ..prompts.co_writing import STYLE_DISCIPLINE
    from ..prompts.writing import PROSE_WRITING_PROMPT
    body = PROSE_WRITING_PROMPT.split("{chapter_header}\n\n", 1)[1] \
        if "{chapter_header}\n\n" in PROSE_WRITING_PROMPT else PROSE_WRITING_PROMPT
    lib = body.replace("{style_discipline}", STYLE_DISCIPLINE)
    for old, new in _LIBRARY_REPLACEMENTS:
        if old not in lib:
            raise ValueError("写作指令库模板漂移：找不到待冻结片段「%s…」——"
                             "PROSE_WRITING_PROMPT 变更后须同步 _LIBRARY_REPLACEMENTS"
                             % old[:24])
        lib = lib.replace(old, new)
    leftover = sorted({m for m in re.findall(r"\{[a-z_][a-z_0-9]*\}", lib)})
    if leftover:
        raise ValueError("写作指令库残留逐章占位符：%s（冻结版不得含 {xxx} 变量）"
                         % leftover)
    return lib


def volume_system_text(proj: str) -> str:
    """卷会话 system（S4-a）：全书冻结前缀 + 写作指令库（模板化冻结版）。

    仅卷会话模式使用；章节会话/单轮路径的 system 仍为双层前缀原样（字节不变）。
    指令库入 system 后，S1 时代旧卷栈（system 只含前缀）的 load 校验必然失配
    → 按全新栈继续——缓存域切换本就该全灭一次，属预期行为。
    """
    from .shared_prefix import project_header
    return f"{project_header(proj)}\n\n{_LIBRARY_HEADER}\n{prose_instruction_library()}"


class VolumeSession(ChapterSession):
    """卷会话消息栈：一卷一个会话，章边界=开幕轮（ChapterSession 语义超集）。

    - system = 全书冻结前缀 + PROSE 指令库（S4-a volume_system_text：模板化
      冻结版，逐章变量改「按开幕轮给定的值执行」）；章头进每章开幕轮；
    - open_chapter() 声明章边界；随后第一次 ask() 把开幕轮原子固化
      （成功才入栈——与 ChapterSession 的失败安全同纪律）；
    - save()/load()：jsonl append-only 落盘 / 逐字节恢复。
    """

    def __init__(self, client, system_text: str, *, volume: int = 1,
                 proj: str = "", enabled: bool = True, gen: int = 0):
        super().__init__(client, system_text, enabled=enabled)
        self._volume = int(volume)
        self._gen = int(gen)
        self._proj = proj
        self._path = volume_messages_path(proj, self._volume, self._gen) if proj else ""
        self._saved_len = 0          # 已落盘的前导消息条数（append-only 游标）
        self._pending_opening = None  # open_chapter 合成的开幕轮：随下一次 ask 固化
        self._current_chapter = 0     # 栈中最后一条开幕轮的章号（0=尚无）
        self._chapter_start_turns = 0  # 本章开幕前的轮数（同章重入时截断基准）

    # ---- 卷身份 ----

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def gen(self) -> int:
        """会话栈代次：0=原始栈，>0=第 gen 次接力压缩后另起的栈（长程压缩 §4.3）。"""
        return self._gen

    @property
    def current_chapter(self) -> int:
        """栈中最后一条开幕轮的章号（0=栈内还没有任何章开幕）。"""
        return self._current_chapter

    @property
    def messages_path(self) -> str:
        return self._path

    # ---- 章开幕（S1 的字节级关键改动：章头从 system 挪到这里）----

    def _opening_text(self, chapter_header_text: str, first_turn_text: str,
                      chapter_num: int, preface: str = "") -> str:
        mark = (opening_marker(chapter_num) if chapter_num
                else "【新章开幕：以下为本章共享上下文与写作指令，本章正文以本次回复为准】")
        parts = [mark]
        # 接力压缩的交接块插在章头之前（卷终状态在前、本章上下文在后）；
        # 空串时本节完全不存在 → 与压缩改造前逐字节一致。
        if (preface or "").strip():
            parts.append(preface)
        if (chapter_header_text or "").strip():
            parts.append(chapter_header_text)
        parts.append(first_turn_text)
        return "\n\n".join(p for p in parts if p)

    def open_chapter(self, chapter_header_text: str, first_turn_text: str,
                     chapter_num: int = 0, preface: str = "") -> str:
        """声明章边界：章头 + 本章首个相位轮合成开幕 user 轮（不重置栈）。

        返回合成后的开幕轮全文（调用方可据此设置 last_prompt）。开幕轮在随后的
        第一次 ask() 成功时原子固化——合成阶段不推栈，失败/中止不留半截轮次。
        同一章重入（G9 重写本章后重跑）先截回本章开幕前的轮数，被否决的上一轮
        尝试（草稿/审校/修复轮）不留在历史里。

        preface = 接力压缩的卷终交接块（长程压缩 §4.3 项 2）：插在开幕声明与章头
        之间，只在该卷新栈的首个开幕轮给一次，之后随历史一起永久命中。
        缺省空串 = 本节不存在，请求体与压缩改造前逐字节一致。
        """
        if chapter_num and self._current_chapter == chapter_num:
            self.rollback_to(self._chapter_start_turns)
        self._pending_opening = self._opening_text(
            chapter_header_text, first_turn_text, chapter_num, preface)
        self._pending_prose = None   # 开幕轮与正文种子互斥：开幕轮自带本章首个相位轮
        self._current_chapter = int(chapter_num or 0)
        self._chapter_start_turns = self._turns
        return self._pending_opening

    def seed_prose(self, prose: str, chapter_num: int = 0) -> None:
        """断点续跑：卷栈缺本章历史时把盘上草稿播种进下一次 ask（不清栈）。

        卷会话崩溃在中途时，盘上 jsonl 只落到上一章末尾（save 逐章调用）——
        本章的开幕轮与正文都不在栈里，若不播种，「最近一条章正文消息」会指向
        上一章。播种语义与 ChapterSession.restart_with_prose 一致（正文前缀拼
        进下一次 ask），区别只在不清掉 1..N-1 章历史。
        """
        if chapter_num and self._current_chapter == chapter_num:
            self.rollback_to(self._chapter_start_turns)   # 本章旧尝试不留双份
        self._pending_prose = prose
        self._pending_opening = None
        self._current_chapter = int(chapter_num or self._current_chapter)
        self._chapter_start_turns = self._turns

    # ---- 轮次固化（覆盖：开幕轮/种子并入下一轮；其余语义与章会话一致）----

    def ask(self, user_text: str, *, on_chunk=None, on_reasoning=None,
            phase: str = "", temperature=None, abort=None,
            client=None, postprocess=None) -> str:
        """追加 user 轮并同步等待回复；回复固化为 assistant 轮后返回原文。

        若 open_chapter()/seed_prose() 留下了待固化内容，本轮 user 内容为：
        开幕轮全文（open_chapter）＞「## 本章正文」种子前缀+user_text
        （seed_prose/restart_with_prose）＞ user_text 原文。失败不固化任何轮，
        待固化内容保留（重试仍带）——与 ChapterSession 异常安全语义一致。
        """
        if not self._enabled:
            raise RuntimeError("VolumeSession 未启用（配置关闭或客户端不支持多轮）："
                               "调用方应回退单轮 chat_stream")
        content = user_text
        if self._pending_opening is not None:
            content = self._pending_opening
        elif self._pending_prose is not None:
            content = f"## 本章正文\n{self._pending_prose}\n\n{user_text}"
        reply = (client or self._client).chat_turn(
            self._messages + [{"role": "user", "content": content}],
            on_chunk=on_chunk, on_reasoning=on_reasoning, phase=phase,
            temperature=temperature, abort=abort)
        if postprocess:
            reply = postprocess(reply)
        self._messages.append({"role": "user", "content": content})
        self._messages.append({"role": "assistant", "content": reply})
        self._pending_prose = None
        self._pending_opening = None
        self._turns += 1
        return reply

    def restart_with_prose(self, prose: str) -> None:
        """断点续跑播种（卷栈语义）：**不重置栈**——1..N-1 章历史是卷会话的
        全部价值，重置即全丢；正文经种子并入下一次 ask（_session_seed 走这里）。"""
        self._pending_prose = prose
        self._pending_opening = None

    def rollback_to(self, turn_count_before: int) -> None:
        """截断回栈到「第 N 轮固化后」的状态（语义与 ChapterSession 一致）。

        卷栈差异：截断可能跨越章边界（回退到上一章某轮），本章开幕状态随之
        作废（current_chapter 归零由回退目标处的开幕轮恢复语义承担）；截断落盘
        游标之下时立即整文重写持久层，防崩溃恢复把已否决的轮次读回来。
        """
        super().rollback_to(turn_count_before)
        if self._current_chapter and turn_count_before <= self._chapter_start_turns:
            # 回退到本章开幕（或更早）：本章开幕状态一并作废
            self._current_chapter = 0
            self._chapter_start_turns = turn_count_before
        try:
            self.save()   # 截到游标之下 = 盘上历史已被否决，立即重写（罕见路径）
        except Exception:  # noqa: BLE001
            pass

    # ---- 持久化（append-only；逐字节 round-trip）----

    def _serialize(self, m: dict) -> str:
        return json.dumps(m, ensure_ascii=False)

    def save(self) -> str:
        """把未落盘的尾部消息追加进 jsonl；返回落盘路径（未配置 proj 返回空串）。

        append-only：正常路径只追加新行，历史行逐字节不动（save 两次=文件不变）。
        栈被回退截断到已落盘游标之下时整文重写一次（截断后的前缀仍逐字节一致，
        服务端前缀缓存按位置匹配不受影响）。
        """
        if not self._path:
            return ""
        n = len(self._messages)
        if n == self._saved_len:
            return self._path
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        if n < self._saved_len:
            data = "\n".join(self._serialize(m) for m in self._messages) + "\n"
            with open(self._path, "w", encoding="utf-8", newline="\n") as f:
                f.write(data)
        else:
            with open(self._path, "a", encoding="utf-8", newline="\n") as f:
                for m in self._messages[self._saved_len:]:
                    f.write(self._serialize(m) + "\n")
        self._saved_len = n
        return self._path

    def load(self, path: str) -> bool:
        """从 jsonl 恢复消息栈；成功返回 True（此后消息与落盘时逐字节一致）。

        文件缺失/损坏/首条 system 与当前全书前缀不一致（设定/正则/世界书在两次
        运行之间改过——旧栈缓存域已死）时返回 False，栈保持构造时的全新状态。
        恢复内容含章节边界：current_chapter / 章开幕轮数一并还原，断点续跑的
        「本章缺历史才播种」判断因此成立。
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
        except OSError:
            return False
        msgs = []
        for ln in lines:
            try:
                m = json.loads(ln)
            except ValueError:
                return False
            if not (isinstance(m, dict) and isinstance(m.get("role"), str)
                    and isinstance(m.get("content"), str)):
                return False
            msgs.append({"role": m["role"], "content": m["content"]})
        if not msgs or msgs[0]["role"] != "system" \
                or msgs[0]["content"] != self._system_text:
            return False
        self._messages = msgs
        self._saved_len = len(msgs)
        self._turns = (len(msgs) - 1) // 2
        self._pending_prose = None
        self._pending_opening = None
        self._current_chapter = 0
        self._chapter_start_turns = 0
        for i, m in enumerate(msgs):
            if m["role"] != "user":
                continue
            chap = chapter_of_opening(m["content"])
            if chap:
                self._current_chapter = chap
                self._chapter_start_turns = max((i - 1) // 2, 0)
        return True

    # snapshot() / commit_turn() / turn_count() / enabled / system_text
    # 直接继承 ChapterSession（深拷贝与固化语义逐字一致）。
    #
    # 兼容注记：_rewrite_phase 的 span 路径用 snapshot()+commit_turn() 合成修订轮，
    # 对卷栈同样成立——历史里「最近一条章正文消息」仍指向最新正文。


def new_volume_session(client, system_text: str, *, proj: str, num: int,
                       enabled: bool = True) -> VolumeSession:
    """按章号解析卷号并构造 VolumeSession（便捷入口，卷号解析失败回退卷 1）。"""
    return VolumeSession(client, system_text,
                         volume=resolve_volume_number(proj, num), proj=proj,
                         enabled=enabled)
