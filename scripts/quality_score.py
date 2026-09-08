# -*- coding: utf-8 -*-
"""质量评测流水线（rubric v2）：对实验章节做双评委盲评 → 聚合 → 回归判定

依据 docs/小说质量评测标准_v2.md 与 tests/quality_rubric/（rubric_v2.json + judge_prompt.md）。
- 每章 2 票独立盲评：维度顺序独立洗牌（消位置偏差）、temperature 0.2、thinking disabled（成本）
- evidence_quote 逐字验真：失败该维计 1 分并记违规
- 聚合：|A-B|<=2 取均值（0.5 粒度）；>2 加第三票取中位数并标 divergent
- 章分 = Σ 权重×得分/10（满分 10）；变体分 = 章分均值
- 回归判定：总分 ≥ 基线-0.5；单章地板（接 P4 时 7.5，默认 7.0）；单维跌幅 ≤1.5
- 用量记真实目录 usage.jsonl（phase=quality_judge，诚实入账）

用法：
  python scripts/quality_score.py                       # 默认五变体
  python scripts/quality_score.py --targets s1_volume   # 指定变体

评委子代理路径（主路径，《测试接手指南_v1.md》§5.5）：
  python scripts/quality_score.py --blind-prepare --targets t1_long20,baseline_e01 --per 10
      # 抽样匿名化 → blind_eval/<qid>/样本-XXX.md + blind_map.json（票面不含变体名）
  python scripts/quality_score.py --blind-aggregate --votes <票目录|票文件...> --baseline <变体>
      # 读评委子代理手写的票 → 逐字验真 + 程序重算加权分 + 按 rubric 聚合 + 回归判定
上面的 API 评委路径保留作尺度对照，已非主路径。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
import time

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BENCH = os.path.join(ROOT, "tests_output", "bench")
RUBRIC = os.path.join(ROOT, "tests", "quality_rubric", "rubric_v2.json")
JUDGE_TPL = os.path.join(ROOT, "tests", "quality_rubric", "judge_prompt.md")
DEFAULT_TARGETS = ("baseline_e01", "e11_span_trim", "e11_span_deslop",
                   "e13_trim_low", "e11_span_reviewfix")
PHASE = "quality_judge"


def _load_key():
    """评委连接优先走**非 DeepSeek 官方控制台**的渠道（百炼托管的同款 flash）——
    盲评是测量仪器，不污染用户 DS 控制台的命中率统计。"""
    from app import config as cfg_mod
    from app import secrets
    cfg = secrets.hydrate(cfg_mod.load_config())
    conns = [c for c in cfg.get("connections", []) if c.get("api_key")]
    flash = next((c for c in conns if c.get("id") == "bailian-flash"), None) or \
        next((c for c in conns if "api.deepseek.com" not in str(c.get("base_url", ""))
              and "flash" in str(c.get("model", ""))), None) or \
        next((c for c in conns if "api.deepseek.com" in str(c.get("base_url", ""))
              and "flash" in str(c.get("model", ""))), None)
    if not flash:
        raise SystemExit("没有可用的 flash 评委连接")
    return flash


def _chapters_of(variant: str) -> list:
    d = os.path.join(BENCH, variant + ".chapters")
    if not os.path.isdir(d):
        raise SystemExit("缺章节目录: " + d)
    out = []
    for fn in sorted(os.listdir(d)):
        m = re.match(r"第(\d+)章.*\.md$", fn)
        if m:
            out.append((int(m.group(1)), os.path.join(d, fn)))
    return out


def _render_rubric_section(rubric: dict, order: list) -> str:
    dims = {d["id"]: d for d in rubric["dimensions"]}
    blocks = []
    for dim_id in order:
        d = dims[dim_id]
        anchors = "\n".join("  - %s分：%s" % (k, v) for k, v in sorted(d["anchors"].items()))
        red = "；".join(d.get("red_flags") or [])
        blocks.append("### %s %s（权重 %d）\n%s\n%s\n[红线——命中该维封顶5分]：%s"
                      % (d["id"], d["name"], d["weight"], anchors,
                         "  - 10分：%s" % d["anchors"]["10"] if "10" not in d["anchors"] else "",
                         red or "（无）"))
    return "\n\n".join(blocks)


def _prev_context(chapters: list, idx: int) -> str:
    if idx == 0:
        return "（本章为第一章，无前情）"
    prev = chapters[idx - 1][1]
    try:
        tail = open(prev, encoding="utf-8").read()[-400:]
    except OSError:
        return "（无前情）"
    return "上一章结尾（最近 400 字）：\n" + tail


def _ask_judge(client, prompt: str) -> dict:
    parts = []
    client.chat_stream(prompt, temperature=0.2, phase=PHASE, on_chunk=parts.append)
    out = "".join(parts).strip()
    if out.startswith("```"):
        lines = out.split("\n")
        out = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    m = re.search(r"\{.*\}", out, re.S)
    return json.loads(m.group(0) if m else out)


def _verify_and_total(vote: dict, rubric: dict, chapter_text: str) -> dict:
    """引文验真 + 程序重算加权总分（不信任模型自报 total）"""
    weights = {d["id"]: d["weight"] for d in rubric["dimensions"]}
    dims = {d["id"]: d for d in rubric["dimensions"]}
    violations = []
    total = 0.0
    wsum = 0.0
    clean = []
    for it in vote.get("dimensions", []):
        dim = str(it.get("dim", "")).strip()
        if dim not in weights:
            continue
        try:
            score = max(1, min(10, int(it.get("score"))))
        except (TypeError, ValueError):
            score = 1
        q = str(it.get("evidence_quote", "")).strip()
        if q and q not in chapter_text:
            violations.append("%s 引文不实" % dim)
            score = 1
        total += weights[dim] * score
        wsum += weights[dim]
        it["score"] = score
        clean.append(it)
    # 缺维按评委违规计 1 分（评分纪律第 2 条的延伸：结构不完整=不可信票）
    for dim_id, w in weights.items():
        if dim_id not in {it["dim"] for it in clean}:
            violations.append("%s 缺维" % dim_id)
            total += w * 1
            wsum += w
    vote["dimensions"] = clean
    vote["weighted_total"] = round(total / wsum, 2) if wsum else 0.0
    vote["violations"] = violations
    return vote


def _arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _blind_prepare(targets: list, per: int, qid: str) -> str:
    """抽样匿名化：评委子代理只见样本号，不见变体与章号（映射只有主代理持有）。

    target 支持 "变体" 或 "变体:起始章"——**续写跑次必须带后者**：
    `<变体>.chapters` 里含种子 home 复制来的旧章（实测两臂 26 份里有 20 份字节相同），
    不筛就会让 A/B 抽到同一篇文本，盲评当场变成"自己比自己"。
    """
    pool = []
    for spec in targets:
        v, _, lo = str(spec).partition(":")
        chs = _chapters_of(v)
        if lo:
            n0 = int(lo)
            chs = [c for c in chs if c[0] >= n0]
            if not chs:
                raise SystemExit("变体 %s 里没有 ≥第%d章 的样本（种子旧章已排除）" % (v, n0))
        if per and len(chs) > per:
            step = (len(chs) - 1) / (per - 1) if per > 1 else 0
            chs = [chs[round(i * step)] for i in range(per)]
        pool.extend((v, num, path) for num, path in chs)
    # 兜底：同内容只留一份，并大声报出来（静默去重会让含重复的包再次蒙混过关）
    seen, uniq, dups = {}, [], []
    for v, num, path in pool:
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if h in seen:
            dups.append("%s#%s ≡ %s#%s" % (v, num, seen[h][0], seen[h][1]))
            continue
        seen[h] = (v, num)
        uniq.append((v, num, path))
    if dups:
        print("⚠️ 抽样里有 %d 份字节相同的样本，已各留一份（续写跑次请加 \"变体:起始章\" 规格）："
              % len(dups))
        for d in dups:
            print("     重复:", d)
    pool = uniq
    random.shuffle(pool)
    out = os.path.join(BENCH, "blind_eval", qid)
    os.makedirs(out, exist_ok=True)
    blind_map = {}
    for i, (v, num, path) in enumerate(pool, 1):
        sid = "样本-%03d.md" % i
        text = open(path, encoding="utf-8").read()
        with open(os.path.join(out, sid), "w", encoding="utf-8") as f:
            f.write(text)
        blind_map[sid] = {"variant": v, "chapter": num}
    mp = os.path.join(BENCH, "blind_eval", qid + ".blind_map.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(blind_map, f, ensure_ascii=False, indent=1)
    print("盲评样本包：%s（%d 份）｜映射（仅主代理读）：%s" % (out, len(pool), mp))
    return out


def _vote_sample_id(vote: dict) -> str:
    sid = str(vote.get("sample") or vote.get("chapter_id") or "")
    return sid if sid.endswith(".md") else sid + ".md"


def _load_blind_votes(paths: list) -> list:
    """票源可以是评委汇总文件（[{sample, dims}, …]）、逐票 JSON，或目录（递归收）。"""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, fns in os.walk(p):
                files += [os.path.join(root, fn) for fn in sorted(fns) if fn.endswith(".json")]
        else:
            files.append(p)
    votes = []
    for fn in files:
        data = json.load(open(fn, encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        for it in items:
            it = dict(it)
            if "dimensions" not in it and "dims" in it:
                it["dimensions"] = it["dims"]
            it["_vote_file"] = fn
            votes.append(it)
    return votes


def _blind_aggregate(vote_paths: list, samples_dir: str, blind_map: dict,
                     rubric: dict, baseline: str, out_dir: str = None,
                     qid: str = "") -> dict:
    """逐字验真 + 程序重算加权分（不信评委自报）→ 按样本聚合 → 变体分 → 回归判定。"""
    dim_ids = [d["id"] for d in rubric["dimensions"]]
    by_sample = {}
    for vote in _load_blind_votes(vote_paths):
        sid = _vote_sample_id(vote)
        path = os.path.join(samples_dir, sid)
        if not os.path.isfile(path):
            print("跳过：找不到样本正文 %s（%s）" % (sid, vote["_vote_file"]))
            continue
        text = open(path, encoding="utf-8").read()
        by_sample.setdefault(sid, []).append(_verify_and_total(vote, rubric, text))

    rows = []
    for sid, vs in sorted(by_sample.items()):
        totals = sorted(v["weighted_total"] for v in vs)
        converged = len(vs) >= 2
        if converged:
            dim_gap = 0
            for d in dim_ids:
                sc = [i["score"] for v in vs for i in v["dimensions"] if i["dim"] == d]
                if len(sc) >= 2:
                    dim_gap = max(dim_gap, max(sc) - min(sc))
            converged = totals[-1] - totals[0] <= 1.0 and dim_gap <= 2
        total = (round(sum(totals) / len(totals), 2) if converged
                 else (totals[len(totals) // 2] if len(totals) % 2
                       else round((totals[len(totals) // 2 - 1] + totals[len(totals) // 2]) / 2, 2)))
        per_dim = {}
        for d in dim_ids:
            sc = [i["score"] for v in vs for i in v["dimensions"] if i["dim"] == d]
            per_dim[d] = round(sum(sc) / len(sc), 2) if sc else 0.0
        bad = ";".join(sorted({x for v in vs for x in v["violations"]}))
        rows.append({"sample": sid, "variant": blind_map.get(sid, {}).get("variant", "?"),
                     "chapter": blind_map.get(sid, {}).get("chapter"),
                     "total": total, "votes": len(vs), "divergent": not converged,
                     "per_dim": per_dim, "violations": bad})
        print("  %s → %-14s 第%s章 %.2f（%d 票%s）%s"
              % (sid, rows[-1]["variant"], rows[-1]["chapter"], total, len(vs),
                 "，分歧取中位" if not converged else "",
                 " 违规:" + bad if bad else ""))

    variants = [r["variant"] for r in rows if r["variant"] != "?"]
    report = {}
    for v in dict.fromkeys([baseline] + variants):
        vr = [r for r in rows if r["variant"] == v]
        if not vr:
            continue
        report[v] = {
            "samples": len(vr),
            "variant_total": round(sum(r["total"] for r in vr) / len(vr), 2),
            "floor": min(r["total"] for r in vr),
            "per_dim_avg": {d: round(sum(r["per_dim"][d] for r in vr) / len(vr), 2)
                             for d in dim_ids},
        }

    base = report.get(baseline, {})
    lines = ["# 质量盲评报告（评委子代理票 · rubric v2 · %s）"
             % time.strftime("%Y-%m-%d %H:%M"), "",
             "票源：%s ｜ 样本包：%s ｜ 基线：%s"
             % ("、".join(os.path.basename(p) for p in vote_paths), samples_dir, baseline), ""]
    for v, r in report.items():
        delta = r["variant_total"] - base.get("variant_total", 0)
        drop, worst = 0.0, ""
        if v != baseline:
            for d in dim_ids:
                dd = base.get("per_dim_avg", {}).get(d, 0) - r["per_dim_avg"].get(d, 0)
                if dd > drop:
                    drop, worst = dd, d
        ok = (v == baseline or (delta >= -0.5 and drop <= 1.5))
        lines.append("| %s | 总分 %.2f (%+.2f) | 地板 %.2f%s | 样本 %d | 最大单维跌幅 %s | 判定：%s |"
                     % (v, r["variant_total"], delta, r["floor"],
                        "（<7.0 观察）" if r["floor"] < 7.0 else "", r["samples"],
                        ("%.1f（%s）" % (drop, worst)) if worst else "—",
                        "基线" if v == baseline else ("✅ 通过" if ok else "❌ 未过")))
    for ln in lines[3:]:
        print(ln)
    out = os.path.join(out_dir or BENCH, "quality_report_blind_%s.md"
                       % (qid or time.strftime("%Y%m%d_%H%M%S")))
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n## 逐样本\n\n| 样本 | 变体 | 章 | 分 | 票 | 分歧 | 违规 |\n"
                  "|---|---|---|---|---|---|---|\n")
        f.write("\n".join("| %s | %s | %s | %.2f | %d | %s | %s |"
                           % (r["sample"], r["variant"], r["chapter"], r["total"], r["votes"],
                              "是" if r["divergent"] else "", r["violations"]) for r in rows) + "\n")
    with open(out.replace(".md", ".json"), "w", encoding="utf-8") as f:
        json.dump({"samples": rows, "variants": report}, f, ensure_ascii=False, indent=1)
    print("→", out)
    return report


_VALUE_FLAGS = {"--targets", "--per", "--qid", "--samples", "--map", "--votes", "--baseline"}
_SWITCH_FLAGS = {"--shuffle", "--blind-prepare", "--blind-aggregate", "-h", "--help"}


def _unknown_args(argv: list) -> list:
    """取值型旗标后面那一个 token 是值，不参与识别。"""
    unknown, prev = [], None
    for a in argv:
        if prev in _VALUE_FLAGS:
            prev = None
            continue
        prev = a
        if a in _VALUE_FLAGS or a in _SWITCH_FLAGS or not a.startswith("-"):
            continue
        unknown.append(a)
    return unknown


def main() -> None:
    # 默认路径会真实调用评委 API 并写入用户真实台账（phase=quality_judge），
    # 所以未识别的参数一律拒执行——不接受"打错旗标就掉进付费路径"。
    if {"-h", "--help"} & set(sys.argv[1:]):
        print(__doc__.strip())
        return
    unknown = _unknown_args(sys.argv[1:])
    if unknown:
        raise SystemExit(
            "未识别的参数：%s\n可用：%s" % (
                " ".join(unknown),
                " ".join(sorted(_VALUE_FLAGS | _SWITCH_FLAGS | {"--help"}))))
    targets = DEFAULT_TARGETS
    shuffle = "--shuffle" in sys.argv
    if "--targets" in sys.argv:
        targets = tuple(sys.argv[sys.argv.index("--targets") + 1].split(","))
    # "变体:起始章" 的规格只对 --blind-prepare 有意义；聚合与 API 评委路径只认变体名
    variants = tuple(str(t).split(":")[0] for t in targets)
    rubric = json.load(open(RUBRIC, encoding="utf-8"))

    if "--blind-prepare" in sys.argv:
        qid = _arg("--qid") or time.strftime("%Y%m%d_%H%M")
        _blind_prepare(list(targets), int(_arg("--per", 0) or 0), qid)
        return
    if "--blind-aggregate" in sys.argv:
        qid = _arg("--qid", "")
        sdir = _arg("--samples") or os.path.join(BENCH, "blind_eval", qid)
        mp = _arg("--map") or next((p for p in (
            os.path.join(BENCH, "blind_eval", qid + ".blind_map.json"),
            os.path.join(sdir, "blind_map.json")) if os.path.isfile(p)), "")
        raw = json.load(open(mp, encoding="utf-8"))
        blind_map = {k: (v if isinstance(v, dict) else {"variant": v})
                     for k, v in raw.items()}
        _blind_aggregate([p for p in _arg("--votes", "").split(",") if p.strip()],
                         sdir, blind_map, rubric, _arg("--baseline", variants[0]),
                         qid=_arg("--qid", ""))
        return
    tpl = open(JUDGE_TPL, encoding="utf-8").read()
    tpl = tpl[tpl.index("你是网文责编"):] if "你是网文责编" in tpl else tpl
    dim_ids = [d["id"] for d in rubric["dimensions"]]
    conn = _load_key()
    print("评委模型：%s ｜ 变体：%s" % (conn.get("model"), ",".join(variants)))

    votes_dir = os.path.join(BENCH, "quality_votes")
    os.makedirs(votes_dir, exist_ok=True)
    from app.llm.client import LLMClient
    report = {}
    for variant in variants:
        chapters = _chapters_of(variant)
        print("\n== %s（%d 章）==" % (variant, len(chapters)))
        variant_rows = []
        for idx, (num, path) in enumerate(chapters):
            text = open(path, encoding="utf-8").read()
            cast = []
            j = 0
            while j < 2 + 1:   # 2 票 + 最多 1 票分歧补投
                seed = random.randrange(10 ** 6)
                # v2.1：定序（共享前缀缓存命中）——位置偏差由锚定纪律+双评委兜底；
                # 方法论对照实验可加 --shuffle 恢复洗牌
                order = list(reversed(dim_ids)) if shuffle else dim_ids[:]
                prompt = ("【chapter_id=%s 第%d章】【judge_id=flash-J%d-seed%d】\n\n"
                          % (variant, num, j + 1, seed)
                          + tpl.replace("{prev_context}", _prev_context(chapters, idx))
                               .replace("{chapter_text}", text)
                               .replace("{rubric_section}", _render_rubric_section(rubric, order))
                               .replace("{chapter_id}", "%s-%02d" % (variant, num))
                               .replace("{judge_id}", "flash-J%d-seed%d" % (j + 1, seed)))
                client = LLMClient.from_connection(conn, max_retries=1, slot="helper",
                                                   stage_params={"thinking": "disabled",
                                                                 "max_tokens": 8192})
                client.user_id = "qianbi-eval"   # DS 控制台明细可单独识别评测流量
                try:
                    vote = _verify_and_total(_ask_judge(client, prompt), rubric, text)
                    vote["seed"] = seed
                    with open(os.path.join(votes_dir, "%s__%03d__J%d.json"
                                           % (variant, num, j + 1)), "w",
                              encoding="utf-8") as f:
                        json.dump(vote, f, ensure_ascii=False, indent=1)
                    cast.append(vote)
                    print("  第%02d章 J%d 加权 %.2f %s" % (num, j + 1, vote["weighted_total"],
                          ("违规:%s" % ";".join(vote["violations"])) if vote["violations"] else ""))
                except Exception as e:  # noqa: BLE001
                    print("  第%02d章 J%d 失败：%s" % (num, j + 1, str(e)[:100]))
                j += 1
                if len(cast) >= 2:
                    if j >= 3:
                        break
                    diff = [abs(cast[0]["weighted_total"] - cast[1]["weighted_total"])]
                    per_dim_max = 0
                    a = {it["dim"]: it["score"] for it in cast[0]["dimensions"]}
                    b = {it["dim"]: it["score"] for it in cast[1]["dimensions"]}
                    for dim in set(a) & set(b):
                        per_dim_max = max(per_dim_max, abs(a[dim] - b[dim]))
                    if diff[0] <= 1.0 and per_dim_max <= 2:
                        break   # 收敛，不投第三票（期望 2.25 票）
            if not cast:
                continue
            totals = sorted(v["weighted_total"] for v in cast)
            ch_total = totals[len(totals) // 2]
            per_dim = {}
            for it in cast[0]["dimensions"]:
                dim = it["dim"]
                scores = [it2["score"] for v in cast
                          for it2 in v["dimensions"] if it2["dim"] == dim]
                per_dim[dim] = round(sum(scores) / len(scores), 2)
            variant_rows.append({"num": num, "total": ch_total, "per_dim": per_dim,
                                 "divergent": len(cast) > 2, "votes": len(cast)})
            print("  第%02d章 章分 %.2f（%d 票%s）" % (num, ch_total, len(cast),
                  "，分歧补投" if len(cast) > 2 else ""))
        report[variant] = {
            "chapters": variant_rows,
            "variant_total": round(sum(r["total"] for r in variant_rows)
                                   / max(1, len(variant_rows)), 2),
            "per_dim_avg": {d: round(sum(r["per_dim"].get(d, 0) for r in variant_rows)
                                     / max(1, len(variant_rows)), 2)
                            for d in dim_ids},
        }
        print("→ %s 变体总分：%.2f" % (variant, report[variant]["variant_total"]))

    # 回归判定（基线 = 第一个变体名，去掉 ":起始章" 规格）
    base_v = variants[0]
    base = report.get(base_v, {})
    print("\n== 回归判定（基线 %s = %.2f）==" % (base_v, base.get("variant_total", 0)))
    lines = ["# 质量盲评报告（rubric v2 · %s）" % time.strftime("%Y-%m-%d %H:%M"), ""]
    for v in variants:
        r = report[v]
        delta = r["variant_total"] - base.get("variant_total", 0)
        floor = min((c["total"] for c in r["chapters"]), default=0)
        worst_dim_drop = 0.0
        worst_dim = ""
        if v != base_v:
            for d in dim_ids:
                drop = base.get("per_dim_avg", {}).get(d, 0) - r["per_dim_avg"].get(d, 0)
                if drop > worst_dim_drop:
                    worst_dim_drop, worst_dim = drop, d
        ok = (v == base_v or (delta >= -0.5 and floor >= 7.0 and worst_dim_drop <= 1.5))
        lines.append("| %s | 总分 %.2f (%+.2f) | 地板 %.2f | 最大单维跌幅 %s | 判定：%s |"
                     % (v, r["variant_total"], delta, floor,
                        ("%.1f（%s）" % (worst_dim_drop, worst_dim)) if worst_dim else "—",
                        "基线" if v == base_v else ("✅ 通过" if ok else "❌ 未过")))
        print(lines[-1])
    out = os.path.join(BENCH, "quality_report_%s.md" % time.strftime("%Y%m%d_%H%M"))
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(out.replace(".md", ".json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("→", out)


if __name__ == "__main__":
    main()
