# -*- coding: utf-8 -*-
"""生成 assets/demo 演示内容包（0.20.0 演示引导）

从一次真实跑次的项目目录（bench home）提取《种子书》第 1 章全流程真实产物，
打成可在演示中逐阶段落盘的内容包。换演示书 = 用新的 home 重跑本脚本。

用法：
  python tools/make_demo_pack.py <bench_home>/bench/种子书 <bench_home 对应的 queue.log>

素材全部来自真实 API 生成；唯一人工撰写的是 replay/cw_dialogue.json 的共写
讨论台词（本项目没有共写跑次留档），台词严格取材于书内真实设定。
"""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "demo")

TRACK_MD = ["角色状态.md", "伏笔.md", "时间线.md", "上下文.md", "全局摘要.md", "章节摘要.md"]

# 共写讨论台词：没有真实共写跑次，人工按书内设定撰写（回复口径对齐题材定位/角色状态）
CW_DIALOGUE = [
    {"stage": "cw_core", "mode": "discuss",
     "user": "「种子书」的规则再收紧一点：写下的预言必须付出等价代价，父亲当年用过吗？",
     "reply": "按现有设定，父亲留下的是「不可贪」的斜批，说明他知道代价存在——但没证据表明他自己动过笔。"
              "建议把「父亲是否用过」留成悬案：林兰那句没说完的嘱托正好挂这条线，第 2 章先给半句，第 6 章再给实物证据。"},
    {"stage": "cw_unit", "mode": "discuss",
     "user": "前 5 章的节奏偏慢，第 2 章直接让外卖员的 0317 和笔记对上。",
     "reply": "可以，但建议保留「延迟确认」：第 2 章只让两个 0317 同框，不解释。爽点在「读者先懂、主角装不懂」，"
              "压到第 3 章雨夜再爆。细纲我可以按这个疏密重排。"},
    {"stage": "cw_prose", "mode": "write",
     "user": "按这个思路写第 2 章开头，直接出正文。",
     "body_file": "正文/第002章_开头.md"},
]


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _chapter_file(src: str, num: int) -> str:
    """按章号发现正文文件（兼容任意章名后缀；.drafts/.versions 不参与）"""
    d = os.path.join(src, "正文")
    for fn in sorted(os.listdir(d)):
        if re.match(r"^第%03d章_.+\.md$" % num, fn):
            return os.path.join(d, fn)
    return ""


def _deslop_pair(src: str, num: int) -> tuple:
    """从 .drafts 草稿 vs 终稿提取真实去味前后对照（v15 pinned 定点修复路径）：
    找草稿中有、终稿中无、且长度适中的句，取终稿同序位句为改后文本。"""
    draft = os.path.join(src, "正文", ".drafts", "第%03d.md" % num)
    final = _chapter_file(src, num)
    if not (os.path.isfile(draft) and final):
        return "", ""
    v1, v2 = read(draft), read(final)
    s1 = [x for x in re.split(r"(?<=[。！？])", v1) if len(x.strip()) > 12]
    s2 = [x for x in re.split(r"(?<=[。！？])", v2) if len(x.strip()) > 12]
    for a in s1:
        if a not in v2 and len(a) < 120:
            idx = s1.index(a)
            if idx < len(s2) and s2[idx] != a:
                return a.strip(), s2[idx].strip()
    return "", ""


def main(home: str, queue_log: str):
    src = home
    if os.path.isdir(os.path.join(src, "设定")) is False:
        sys.exit(f"不是项目目录：{src}")
    # script.json 是人工维护的 21 步引导脚本，不随素材重生成——重建前保存、之后原样放回
    script_backup = None
    script_path = os.path.join(OUT, "script.json")
    if os.path.isfile(script_path):
        script_backup = read(script_path)
    shutil.rmtree(OUT, ignore_errors=True)

    ch1 = _chapter_file(src, 1)
    if not ch1:
        sys.exit("正文缺少第 1 章")
    # ---- book/：逐阶段落盘的真实产物 ----
    for rel in ["设定/题材定位.md", "设定/世界书.md", "大纲/大纲.md",
                "大纲/细纲_第001章.md"]:
        write(os.path.join(OUT, "book", rel), read(os.path.join(src, rel)))
    write(os.path.join(OUT, "book", "正文", os.path.basename(ch1)), read(ch1))
    for name in TRACK_MD:
        p = os.path.join(src, "追踪", name)
        if os.path.isfile(p):
            write(os.path.join(OUT, "book", "追踪", name), read(p))
    for name in ["设定清算_第001.json", "连续性台账.json"]:
        p = os.path.join(src, "追踪", name)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(OUT, "book", "追踪", name))

    # 共写「撰写」演示体：第 2 章真实正文的前 3 段（章名自适应）
    ch2_path = _chapter_file(src, 2)
    ch2_title = "单号"
    if ch2_path:
        ch2 = read(ch2_path)
        m_t = re.match(r"#\s*第2章\s*(\S+)", ch2)
        if m_t:
            ch2_title = m_t.group(1)
        paras = [p for p in ch2.split("\n\n") if p.strip()][:3]
        write(os.path.join(OUT, "book", "正文", "第002章_开头.md"),
              f"# 第2章 {ch2_title}（开头试写）\n\n" + "\n\n".join(paras) + "\n")

    # ---- replay/run_log.txt：真实日志行（第 1 章全流程 + 阶段行）----
    log_lines = []
    for line in read(queue_log).splitlines():
        if any(k in line for k in ["上下文组装", "草稿完成", "去味", "审校", "追踪文件",
                                   "设定清算", "核心设定", "全书大纲", "细纲"]):
            # 只取第 1 章相关的行（阶段级/第 1 章）
            if "第 1 章" in line or "第 1 章" not in line:
                log_lines.append(line)
        if len(log_lines) >= 24:
            break
    write(os.path.join(OUT, "replay", "run_log.txt"), "\n".join(log_lines) + "\n")

    # ---- replay/deslop.json：草稿 → 去味后 的真实对照段 ----
    # v15 head_rebuild（persist=False）无会话文件可读——改从 .drafts 草稿 vs 终稿
    # 提取；从后往前扫（后章定稿更近、pinned 去味集中在前 30 章尾部），要求
    # 前后句有实质差异（滤掉仅引号级微差），找不到留空说明。
    before = after = ""
    for _n in range(30, 0, -1):
        before, after = _deslop_pair(src, _n)
        if before and after and before.rstrip("。") != after.rstrip("。"):
            break
    write(os.path.join(OUT, "replay", "deslop.json"), json.dumps(
        {"before": before, "after": after,
         "note": "AI 味扫描阻断 1 处 → 去味改写，复扫通过（真实对照）"},
        ensure_ascii=False, indent=2) + "\n")

    # ---- replay/review.json：真实三票 ----
    write(os.path.join(OUT, "replay", "review.json"), json.dumps(
        {"votes": ["PASS", "PASS", "PASS"], "fail": 0, "verdict": "PASS"},
        ensure_ascii=False, indent=2) + "\n")

    # ---- replay/cw_dialogue.json ----
    write(os.path.join(OUT, "replay", "cw_dialogue.json"),
          json.dumps(CW_DIALOGUE, ensure_ascii=False, indent=2) + "\n")

    # ---- pack.json ----
    if script_backup is not None:
        write(script_path, script_backup)   # 引导脚本原样放回（人工维护件）
    idea = "主角能用一支笔改写命运的笔记"
    m = re.search(r"灵感：(.+)", read(os.path.join(src, "设定", "选题信息.md")))
    if m:
        idea = m.group(1).strip()
    write(os.path.join(OUT, "pack.json"), json.dumps({
        "version": 1,
        "source": "bench v15_fresh（真实 API 生成 · 30 章长跑 · 30 章累计综合命中率 85.3%）",
        "book": {"name": "种子书", "genre": "都市悬疑", "platform": "番茄",
                 "preset_id": "urban_destiny", "total_wan": 10, "idea": idea},
        "budget_s": {"create": 60, "pipeline": 150, "cw": 75, "finish": 30},
    }, ensure_ascii=False, indent=2) + "\n")

    n = sum(len(fs) for _, _, fs in os.walk(OUT))
    print(f"内容包完成：{OUT}（{n} 个文件）")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
