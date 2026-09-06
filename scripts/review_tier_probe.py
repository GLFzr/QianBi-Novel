# -*- coding: utf-8 -*-
"""审校三档埋雷测试（v0.18.6）：固定输入 + 已知缺陷（标准答案）→ 召回率/引文真实性/成本

设计：
- 在种子书第 2 章草稿上埋 4 颗雷，每颗落在 FINAL_REVIEW_PROMPT 六维的**明文硬规则**上：
  A 开章纯铺陈（维A：前500字零冲突零异象必 fail）
  C 金手指越界（维C：对已发生事实落墨生效=设定白名单外必 fail）
  D 幻影引用（维D：凭空出现"认识的人"必 fail）
  F 禁用章尾预告（去AI味红线+维F："他不知道的是……"）
- 每颗雷有唯一标记文本；审校 items 的 quote/text 命中标记即视为"抓到"。
- 干净原章作对照（假阳性检查）。
- 三档：high（现默认）/ low / disabled，各 1 票（去投票噪声）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import logging
logging.basicConfig(level=logging.WARNING)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REAL_HOME = os.path.expanduser("~")
BENCH = os.path.join(ROOT, "tests_output", "bench")
HOME = os.path.join(BENCH, "review_tier_home")
BASE = os.path.join(BENCH, "bench_base")
BOOK = "种子书"
NUM = 2

# ---------- 埋雷 ----------

A_MARK = "晾衣绳上的水滴了七天，墙皮鼓起三块白斑"
C_MARK = "让父亲在昨夜的高速上活下来"
C_MARK2 = "墨迹在纸上洇开，像被谁吸了进去"
D_MARK = "老周"
F_MARK = "他不知道的是"


def _defective(orig: str) -> str:
    lines = orig.split("\n")
    title = lines[0]
    body = "\n".join(lines[1:]).strip()
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    # 雷 A：开章两段换成纯天气铺陈（覆盖原汤渍钩子段与骑车段）
    a_para = (f"{A_MARK}。雨不大，但一直下。楼下便利店的灯牌坏了半边，"
              "晚上看过去只剩一个「便」字在雨里发白。陈默撑着伞走出巷口，"
              "路面上的水洼一个连着一个，倒映着灰白的天。")
    a_para2 = ("公交站牌下挤满了人。有人在打电话，有人在刷手机，"
               "雨棚的铁皮被雨点敲得叮叮响。他站在队尾，看着一辆辆车进站又出站，"
               "溅起的水花打湿了裤脚。这一天和这个梅雨季的任何一天都没有区别。")
    # 雷 C：结尾改为对已发生事实落墨且生效（违反「近24小时内即将发生」+「已闭合事件拒绝落墨」）
    c_para = ("他忽然想到一种可能。他翻开种子书，翻到空白页，笔尖抵住纸面，"
              f"写下：{C_MARK}。{C_MARK2}，一行小字浮现出来：已受理。"
              "他盯着那行字，呼吸停了半拍——本子接了。")
    # 雷 F：章尾禁用预告句
    f_para = f"{F_MARK}，这一夜，有一双眼睛正从街对面的黑暗里，安静地数着他房间的灯亮了几个小时。"
    # 雷 D：在中段插入幻影引用（老周从未在本书任何前文出现）
    d_para = ("他把纸箱推到墙边，想起{zh}昨天在楼道里说过的话：这种催租短信，"
              "拖着就好，房东比你还怕房子空着。".format(zh=D_MARK))
    new_body = "\n\n".join([a_para, a_para2] + paras[2:-1] + [d_para, c_para, f_para])
    return title + "\n\n" + new_body + "\n"


def _load_key():
    from app import config as cfg_mod
    from app import secrets
    cfg = secrets.hydrate(cfg_mod.load_config())
    for c in cfg.get("connections", []):
        if c.get("id") == "cap-flash" and c.get("api_key"):
            return c
    for c in cfg.get("connections", []):
        if c.get("api_key") and "api.deepseek.com" in str(c.get("base_url", "")):
            return c
    raise SystemExit("无可用 Key")


def _usage_file():
    from app import config as cfg_mod
    return os.path.join(cfg_mod.CONFIG_DIR, "usage", "usage.jsonl")


def _last_usage_row() -> dict:
    p = _usage_file()
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        rows = [l for l in f if l.strip()]
    return json.loads(rows[-1]) if rows else {}


def main():
    from app import project
    from app.core import state as st
    from app.llm.client import LLMClient
    from app.core import stages

    if os.path.isdir(HOME):
        shutil.rmtree(HOME)
    os.makedirs(HOME)
    os.environ["USERPROFILE"] = HOME
    os.environ["HOME"] = HOME
    proj = os.path.join(HOME, "bench", BOOK)
    shutil.copytree(BASE, proj)

    conn = _load_key()
    cfg = {"writing": {"regex_semantics": "logic"},
           "gates": {"review_temperature": 0.2}}
    orig = project.read_file(os.path.join(proj, "正文", ".drafts", "第%03d.md" % NUM))
    defective = _defective(orig)
    project.write_file(os.path.join(proj, "正文", ".drafts", "第%03d_defective.md" % NUM), defective)
    print("埋雷完成：%s / %s / %s / %s" % (A_MARK[:12], C_MARK[:12], D_MARK, F_MARK), flush=True)

    TIERS = [("high", {"thinking": "enabled", "reasoning_effort": "high"}),
             ("low", {"thinking": "enabled", "reasoning_effort": "low"}),
             ("disabled", {"thinking": "disabled"})]
    MARKS = [("A开章", A_MARK), ("C金手指", C_MARK), ("D幻影", D_MARK), ("F章尾", F_MARK)]
    results = []
    VOTES = 2   # 每组合 2 票：看单档稳定性（独立采样）
    raw_dir = os.path.join(BENCH, "review_tier_raw")
    os.makedirs(raw_dir, exist_ok=True)
    for kind, prose in (("defective", defective), ("clean", orig)):
        for tier, ov in TIERS:
            for vote in range(VOTES):
                client = LLMClient.from_connection(conn, max_retries=1, slot="review")
                client._overrides = lambda ph, _o=ov: dict(_o)
                prompt = stages.build_final_review_prompt(proj, cfg, NUM, prose)
                t0 = time.monotonic()
                raw = client.chat_stream(prompt, temperature=0.2, phase="review")
                lat = time.monotonic() - t0
                with open(os.path.join(raw_dir, "%s_%s_v%d.txt" % (kind, tier, vote)),
                          "w", encoding="utf-8") as f:
                    f.write(raw)
                v2 = stages.verify_review_quotes(prose, stages.parse_final_review_v2(raw))
                items = v2.get("items") or []
                n_q = sum(1 for i in items if i.get("quote"))
                n_qv = sum(1 for i in items if i.get("quote") and i.get("quote_verified"))
                fails = [i.get("dim") for i in items if i.get("level") == "fail"]
                blob = json.dumps(items, ensure_ascii=False)
                caught = [name for name, mark in MARKS if mark in blob]
                u = _last_usage_row()
                results.append({"kind": kind, "tier": tier, "vote": vote,
                                "verdict": v2.get("verdict"),
                                "n_items": len(items), "n_fail": len(fails), "fails": fails,
                                "quote_real": "%d/%d" % (n_qv, n_q), "caught": caught,
                                "lat": round(lat, 1),
                                "out": u.get("out"), "reasoning": u.get("reasoning")})
                print("[%s/%s/#%d] verdict=%s items=%d fail=%s 引文=%s 抓到=%s lat=%ss out=%s"
                      % (kind, tier, vote, v2.get("verdict"), len(items), fails,
                         "%d/%d" % (n_qv, n_q), caught, round(lat, 1), u.get("out")), flush=True)

    out = os.path.join(BENCH, "review_tier_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("结果已存：%s" % out)


if __name__ == "__main__":
    main()
