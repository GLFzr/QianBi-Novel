# -*- coding: utf-8 -*-
"""0.23.0 质量深测执行器（Phase 5，预注册：docs/0.23.0_质量深测计划.md）

用法（工作区根目录）：
    ./.venv/Scripts/python.exe tests/quality_suite.py <cmd>
cmd ∈ baseline | machine | semantic | blind | ab | all

- M 层：14 项 deslop 指标 + 45 规则命中密度 + 跨章 3-gram 复现率，千笔 7 章
  vs 真人基线（7 部连载长篇本地语料采样，聚合统计，书名不出报告）。
- S 层：设定清算（canon_audit）产物采集 + stealth 独立复审计 1 章 + 钩子/爽点兑现审计。
- B 层：10 维匿名盲评（本地评委 ×2 发取均值 + stealth 独立评委 ×1 发）。
- A 层：同细纲（第3章）双模型同题对比（qwen vs stealth）+ 盲评排名。
"""
import json
import os
import random
import re
import sys
import time

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
           "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

OUT = os.path.join(_ROOT, "tests_output")
PROJ = os.path.join(OUT, "or_二测_改命笔记")
CORPUS = "G:/ai/酒馆/网文拆解/语料"          # 真人语料（本地合法留存；只做聚合统计）
LOCAL_KEY_FILE = "G:/ai/launcher-webui/state/api.key"
URL_LOCAL = "http://127.0.0.1:2027/v1"
MODEL_LOCAL = "qwen3.8-27b"
URL_REMOTE = "https://openrouter.ai/api/v1"
MODEL_REMOTE = "stealth/space-bunny-alpha"
SAMPLE_PER_BOOK = 30


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _key_local():
    return open(LOCAL_KEY_FILE, encoding="utf-8").read().strip()


def _key_remote():
    k = os.environ.get("QIANBI_TEST_KEY", "").strip()
    if k:
        return k
    # 一测隔离配置（gitignored）里的 OpenRouter 连接
    cfgp = os.path.join(OUT, "_phase1_cfg", "config.json")
    if os.path.exists(cfgp):
        cfg = json.load(open(cfgp, encoding="utf-8"))
        for c in cfg.get("connections", []):
            if "openrouter" in str(c.get("base_url", "")):
                return c.get("api_key", "")
    return ""


def _local_alive():
    import httpx
    try:
        return httpx.get("http://127.0.0.1:2027/health", timeout=3).status_code == 200
    except Exception:  # noqa: BLE001
        return False


_LOCAL_DOWN = None   # 进程内只探测一次


def _client(remote=False):
    from app.llm.client import LLMClient
    global _LOCAL_DOWN
    if not remote and _LOCAL_DOWN is None:
        _LOCAL_DOWN = not _local_alive()
        if _LOCAL_DOWN:
            log("本地 llama.cpp 不可达——评委/审计全部回退 stealth（独立评委，无自评偏置）")
    if (not remote and _LOCAL_DOWN) or remote:
        if not _key_remote():
            raise RuntimeError("需要远端评委但无 QIANBI_TEST_KEY")
        return LLMClient.from_connection(
            {"base_url": URL_REMOTE, "api_key": _key_remote(),
             "model": MODEL_REMOTE, "stream": False,
             "max_tokens": 16384, "timeout": 900})
    return LLMClient.from_connection(
        {"base_url": URL_LOCAL, "api_key": _key_local(),
         "model": MODEL_LOCAL, "stream": False,
         "max_tokens": 4096, "timeout": 600})


def _ask(client, prompt, phase, temperature=0.2):
    from app.llm import clean_llm_output
    return clean_llm_output(client.chat(prompt, phase=phase,
                                        temperature=temperature))


def _json_block(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------- 文本与指标 ----------

def _norm(text):
    return re.sub(r"[^\u4e00-\u9fff]", "", text or "")


def _trigrams(text):
    t = _norm(text)
    return {t[i:i + 3] for i in range(len(t) - 2)} if len(t) >= 3 else set()


def _flatten_metrics(m, prefix=""):
    out = {}
    for k, v in m.items():
        if isinstance(v, dict):
            out.update(_flatten_metrics(v, prefix + k + "."))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[prefix + k] = v
    return out


def _measure(text, prev_text=""):
    """单章同口径度量：14 组指标（递归取数值叶）+ 45 规则密度 + 与上一章的 3-gram 复现率"""
    from app.core import deslop_metrics, gates
    blocking, advisory = gates.scan_deslop(text)
    findings = list(blocking) + list(advisory)
    m = deslop_metrics.compute_metrics(text, findings)
    n = project_count(text)
    row = {
        "chars": n,
        "rule_blocking": len(blocking),
        "rule_advisory": len(advisory),
        "rule_density_kt": round((len(blocking) + len(advisory)) / max(n, 1) * 1000, 2),
        "metrics": _flatten_metrics(m),
    }
    if prev_text:
        cur, prev = _trigrams(text), _trigrams(prev_text)
        row["trigram_carry"] = round(len(cur & prev) / max(len(cur), 1), 4) if cur else 0.0
    return row


def project_count(text):
    from app import project
    return project.count_chars(text)


def _chapters_of(book_dir):
    ch = os.path.join(book_dir, "chapters")
    if not os.path.isdir(ch):
        return []
    return sorted(os.path.join(ch, f) for f in os.listdir(ch) if f.endswith(".txt"))


# ---------- M 层 ----------

def cmd_baseline():
    books = [d for d in sorted(os.listdir(CORPUS))
             if os.path.isdir(os.path.join(CORPUS, d, "chapters"))]
    log(f"基线语料：{len(books)} 部 × 每部抽 {SAMPLE_PER_BOOK} 章")
    rng = random.Random(20230930)
    rows = []
    for b in books:
        files = _chapters_of(os.path.join(CORPUS, b))
        if len(files) < SAMPLE_PER_BOOK + 1:
            continue
        picks = sorted(rng.sample(range(1, len(files)), SAMPLE_PER_BOOK))
        for idx in picks:
            try:
                text = open(files[idx], encoding="utf-8", errors="ignore").read()
                prev = open(files[idx - 1], encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if project_count(text) < 800:
                continue
            rows.append(_measure(text, prev))
        log(f"  {b}: 累计 {len(rows)} 章")
    agg = _aggregate(rows)
    out = {"n_chapters": len(rows), "n_books": len(books), "aggregate": agg,
           "note": "真人基线（7 部连载长篇本地语料采样聚合；书名不入报告）"}
    json.dump(out, open(os.path.join(OUT, "_quality_baseline.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"基线落盘：{len(rows)} 章；规则密度中位 {agg['rule_density_kt']}，"
        f"3-gram 复现均值 {agg.get('trigram_carry')}")


def _aggregate(rows):
    keys = set()
    for r in rows:
        keys.update(r["metrics"].keys())
    agg = {"rule_density_kt": _median([r["rule_density_kt"] for r in rows]),
           "trigram_carry": round(_median([r["trigram_carry"] for r in rows
                                           if "trigram_carry" in r]), 4)}
    for k in sorted(keys):
        vals = [r["metrics"][k] for r in rows if k in r["metrics"]]
        agg[k] = _median(vals)
    return agg


def _median(vals):
    vals = sorted(vals)
    n = len(vals)
    if not n:
        return None
    return round(vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2, 4)


def cmd_machine():
    from app import project
    base = json.load(open(os.path.join(OUT, "_quality_baseline.json"),
                          encoding="utf-8"))["aggregate"]
    chapters = project.list_chapters(PROJ)
    rows = []
    prev = ""
    for n, _t, p in chapters:
        text = project.read_file(p)
        row = _measure(text, prev)
        row["chapter"] = n
        rows.append(row)
        prev = text
    agg = _aggregate(rows)
    cover = all(len(r["metrics"]) >= 20 for r in rows)
    ratio_density = (round(agg["rule_density_kt"] / base["rule_density_kt"], 2)
                     if base["rule_density_kt"] else None)
    ratio_carry = (round(agg["trigram_carry"] / base["trigram_carry"], 2)
                   if base.get("trigram_carry") else None)
    m2_ok = ratio_density is not None and 0.5 <= ratio_density <= 2.0
    m3_ok = ratio_carry is not None and ratio_carry <= 1.5
    ratios = {k: (round(agg[k] / base[k], 2) if base.get(k) not in (None, 0) and agg.get(k) is not None else None)
              for k in agg if k in base and isinstance(base[k], (int, float))}
    out = {"chapters": rows, "aggregate": agg, "baseline_aggregate": base,
           "M1_coverage_100": cover,
           "M2_ratio": ratio_density, "M2_ok": m2_ok,
           "M3_ratio": ratio_carry, "M3_ok": m3_ok,
           "metric_ratios_vs_baseline": ratios}
    json.dump(out, open(os.path.join(OUT, "_quality_machine.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"M1 覆盖率100%={cover} | M2 规则密度比值={ratio_density} 达标={m2_ok} | "
        f"M3 3-gram 复现比值={ratio_carry} 达标={m3_ok}")


# ---------- S 层 ----------

def cmd_semantic():
    from app import project
    # S1：采集 Phase 2 已在盘的设定清算产物（canon_audit.audit_chapter 逐章产物）
    s1 = []
    tr = os.path.join(PROJ, "追踪")
    for fn in sorted(os.listdir(tr)):
        if fn.startswith("设定清算_第") and fn.endswith(".json"):
            try:
                s1.append({"file": fn, **json.load(open(os.path.join(tr, fn),
                                                        encoding="utf-8"))})
            except (OSError, json.JSONDecodeError):
                pass
    hard = sum(len(r.get("hard", []) or []) for r in s1)
    violations = sum(len(r.get("violations", []) or []) for r in s1)
    log(f"S1 清算产物 {len(s1)} 章：硬伤 {hard}、违反 {violations}")
    cross = None   # S1x（stealth 复审计）挪到函数末尾：stealth 空响应长尾不拖累本地审计

    # S2+S3 合并单发/章：钩子兑现 + 爽点兑现（结构化 JSON）
    cli = _client(False)
    outlines = {n: open(p, encoding="utf-8").read()
                for n, p in project.list_outlines(PROJ)}
    chapters = {n: project.read_file(p) for n, _t, p in project.list_chapters(PROJ)}
    nums = sorted(chapters)
    hook_rows, payoff_rows = [], []
    for i, n in enumerate(nums):
        prev_end = chapters[nums[i - 1]][-400:] if i else "（第一章）"
        hp = ("你是网文编辑。只输出 JSON。对照材料评估本章（第 %d 章）：\n"
              '{"hook_type":"章末钩子类型：悬念缺口/危机迫近/身份揭晓/承诺兑现/反转/行动指令/无钩",'
              '"hook_strength":1-10整数,'
              '"prev_hook_answered":"上一章结尾钩子在本章开头是否被应答：true/false/partial",'
              '"promises":["细纲承诺要点，≤3条"],'
              '"delivered":["与 promises 对齐：true/false/partial"],'
              '"payoff_rate":0到1的小数,'
              '"evidence":"引原文≤60字"}\n'
              f"上一章结尾：\n{prev_end}\n\n本章细纲：\n{outlines.get(n, '（无细纲）')}"
              f"\n\n本章正文：\n{chapters[n]}") % n
        r = _json_block(_ask(cli, hp, "quality_semantic")) or {}
        hook_rows.append({"chapter": n, **{k: r.get(k) for k in
                                           ("hook_type", "hook_strength",
                                            "prev_hook_answered", "evidence")}})
        payoff_rows.append({"chapter": n, **{k: r.get(k) for k in
                                             ("promises", "delivered",
                                              "payoff_rate")}})
        log(f"  S2/S3 第{n}章 hook={r.get('hook_type')}({r.get('hook_strength')}) "
            f"answered={r.get('prev_hook_answered')} payoff={r.get('payoff_rate')}")
    hook_ok = _hook_rate(hook_rows)
    payoff_ok = _payoff_rate(payoff_rows)
    log(f"S2 钩子有效率 {hook_ok}（判据 ≥0.8）| S3 兑现率 {payoff_ok}（判据 ≥0.7）")

    # S1x：stealth 独立通道复审计第 3 章（交叉验证；单发预算，空响应即放弃不拖尾）
    if _key_remote():
        try:
            from app.core import canon_audit
            from app.llm.client import LLMClient
            _c3 = {"id": "x", "name": "stealth-judge", "base_url": URL_REMOTE,
                   "api_key": _key_remote(), "model": MODEL_REMOTE,
                   "stream": False, "max_tokens": 32768, "timeout": 900}
            cfg2 = {"connections": [_c3],
                    "slots": {"writing": "x", "helper": "x", "review": "x"},
                    "dialogue_log": {"enabled": False}}

            class _R:
                def client(self, slot):
                    return LLMClient.from_connection(_c3)

            prose3 = project.read_file(project.get_chapter_path(PROJ, 3))
            res = canon_audit.audit_chapter(PROJ, 3, prose3, cfg2, router=_R())
            cross = {"violations": len(res.get("violations", []) or []),
                     "hard": len(res.get("hard", []) or []),
                     "raw_keys": sorted(res.keys())}
            log(f"S1x stealth 复审计第3章：违反 {cross['violations']} 硬伤 {cross['hard']}")
        except Exception as e:  # noqa: BLE001
            cross = {"error": f"{type(e).__name__}: {str(e)[:150]}"}
            log(f"S1x 失败（记录不阻塞）：{cross['error']}")

    out = {"S1_ledger": s1, "S1_hard_total": hard, "S1_violations_total": violations,
           "S1x_stealth_reaudit_ch3": cross,
           "S2_hooks": hook_rows, "S2_hook_rate": hook_ok,
           "S3_payoffs": payoff_rows, "S3_payoff_rate": payoff_ok,
           "S2_ok": hook_ok >= 0.8, "S3_ok": payoff_ok >= 0.7}
    json.dump(out, open(os.path.join(OUT, "_quality_semantic.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)


def _hook_rate(rows):
    ok = [r for r in rows if r.get("hook_type") not in (None, "无钩")]
    ans = [r for r in rows[1:] if r.get("prev_hook_answered") in (True, "true", "partial")]
    n = len(rows)
    return round((len(ok) + len(ans)) / max(n + max(n - 1, 1), 1), 2)


def _payoff_rate(rows):
    vals = [float(r.get("payoff_rate") or 0) for r in rows]
    return round(sum(vals) / max(len(vals), 1), 2)


# ---------- B 层 ----------

RUBRIC = """你是资深网文责编。对给定章节正文按 10 个维度打分（1-10，整数），每个维度必须给一句原文引句作证。只输出 JSON：
{"scores":{"开篇抓力":n,"节奏推进":n,"人物一致性":n,"对话自然度":n,"爽点兑现":n,"钩子力度":n,"文笔流畅":n,"AI味读感":n,"前后文连贯":n,"平台合规":n},"evidence":{"维度":"引句≤40字"},"总评":"一句话"}
评分定义：开篇抓力=前三段能否按住读者；节奏推进=有无注水/原地踏步；人物一致性=言行与前文设定自洽；对话自然度=像人话还是说明书；爽点兑现=期待-铺垫-兑现闭环；钩子力度=章末是否让人想点下一章；文笔流畅=语病/硬译腔；AI味读感=模板腔/排比堆砌/机械清单越少越高分；前后文连贯=承接上一章结尾；平台合规=无敏感内容。5 分=勉强及格，7 分=可发布，9 分=头部水准。"""


def _length_normalize(text: str, lo: int = 1400, hi: int = 3600) -> str:
    """W5-b（0.24.0）：盲评长度配平——超出 [lo,hi] 的稿按句边界截到 hi（评委有
    长度偏好，LitBench 实证：不配平测的是长度不是质量）；过短稿保留原样（截无可截）。"""
    t = text or ""
    if len(t) <= hi:
        return t
    cut = t[:hi]
    m = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"))
    return cut[:m + 1] if m >= lo else cut


def cmd_blind():
    from app import project
    chapters = {n: project.read_file(p) for n, _t, p in project.list_chapters(PROJ)}
    nums = sorted(chapters)
    labels = {n: f"稿-{chr(65 + i)}{i + 1}" for i, n in enumerate(nums)}  # 稿-A1…
    order = nums[:]
    random.Random(42).shuffle(order)
    local_j = _client(False)
    remote_j = _client(True) if _key_remote() else None
    results = {}
    for n in order:
        text = _length_normalize(chapters[n])
        lab = labels[n]
        scores = []
        for rep in (1, 2):
            raw = _ask(local_j, f"{RUBRIC}\n\n待评正文（{lab}）：\n{text}",
                       "quality_blind_local")
            j = _json_block(raw)
            if j and j.get("scores"):
                scores.append(j)
            log(f"  B 本地 {lab} 第{rep}发：{j.get('scores') if j else '解析失败'}")
        remote_res = None
        if remote_j:
            raw = _ask(remote_j, f"{RUBRIC}\n\n待评正文（{lab}）：\n{text}",
                       "quality_blind_remote")
            rj = _json_block(raw)
            remote_res = rj
            log(f"  B stealth {lab}：{rj.get('scores') if rj else '解析失败'}")
        results[lab] = {"chapter": n, "local_passes": scores, "remote": remote_res}
    summary = _blind_summary(results)
    out = {"labels": labels, "results": results, "summary": summary,
           "protocol": {"length_normalize": "[1400,3600]句边界截断",
                        "position_permutation": "乱序呈现（seed=42）",
                        "passes": "local×2 + remote×1"}}
    json.dump(out, open(os.path.join(OUT, "_quality_blind.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"B 汇总：{json.dumps(summary, ensure_ascii=False)}")


def _blind_summary(results):
    dims = ["开篇抓力", "节奏推进", "人物一致性", "对话自然度", "爽点兑现",
            "钩子力度", "文笔流畅", "AI味读感", "前后文连贯", "平台合规"]

    def _avg(entries):
        per = {d: [] for d in dims}
        for j in entries:
            s = j.get("scores") or {}
            for d in dims:
                if isinstance(s.get(d), (int, float)):
                    per[d].append(s[d])
        return {d: (round(sum(v) / len(v), 1) if v else None) for d, v in per.items()}

    local_all, remote_all = [], []
    for lab, r in results.items():
        local_all += r["local_passes"]
        if r.get("remote"):
            remote_all.append(r["remote"])
    out = {"local_dims": _avg(local_all), "remote_dims": _avg(remote_all)}
    for k in ("local_dims", "remote_dims"):
        vals = [v for v in out[k].values() if v is not None]
        out[k + "_mean"] = round(sum(vals) / len(vals), 2) if vals else None
    return out


# ---------- A 层 ----------

def cmd_ab():
    from app import project
    outline = open(project.get_outline_path(PROJ, 3), encoding="utf-8").read()
    world = project.read_file(os.path.join(PROJ, "设定", "世界书.md"))
    rules = project.read_file(os.path.join(PROJ, "设定", "正则.md"))
    summary = project.read_file(os.path.join(PROJ, "追踪", "全局摘要.md"))
    prompt = ("【任务】依据以下材料写第 3 章完整正文，约 2000 字，直接输出正文（不要解释/标题）。\n\n"
              f"【世界书】\n{world}\n\n【正则（必须遵守）】\n{rules}\n\n"
              f"【前情摘要】\n{summary}\n\n【第3章细纲】\n{outline}")
    log("A/B：双模型同题生成（同提示、同细纲）")
    d_local = _ask(_client(False), prompt, "ab_draft", temperature=0.7)
    log(f"  qwen 稿 {len(d_local)} 字")
    d_remote = _ask(_client(True), prompt, "ab_draft", temperature=0.7)
    log(f"  stealth 稿 {len(d_remote)} 字")
    pair = [("甲", d_local), ("乙", d_remote)]
    random.Random(7).shuffle(pair)
    local_j, remote_j = _client(False), _client(True)
    verdicts = {}
    for who, cli in (("local", local_j), ("remote", remote_j)):
        judge_prompt = (f"{RUBRIC}\n\n有两篇同题稿（甲/乙），各按 10 维打分，"
                        "并给出总排名与理由。只输出 JSON，结构："
                        '{"稿1":"甲","稿2":"乙","scores":{"甲":{"维度":n,...},'
                        '"乙":{"维度":n,...}},"winner":"甲或乙","理由":"一句话"}'
                        f"\n\n稿甲：\n{pair[0][1][:6000]}"
                        f"\n\n稿乙：\n{pair[1][1][:6000]}")
        raw = _ask(cli, judge_prompt, f"ab_judge_{who}")
        j = _json_block(raw) or {}
        verdicts[who] = j
        log(f"  A {who} 评委：winner={j.get('winner')}")
    # 还原匿名映射
    mapping = {"甲": pair[0][0], "乙": pair[1][0]}
    true_model = {"甲": None, "乙": None}
    for tag, text in (("甲", pair[0][1]), ("乙", pair[1][1])):
        true_model[tag] = "qwen" if text == d_local else "stealth"
    out = {"prompt_chars": len(prompt), "qwen_chars": len(d_local),
           "stealth_chars": len(d_remote), "mapping": mapping,
           "true_model": true_model, "verdicts": verdicts,
           "drafts": {"qwen": d_local, "stealth": d_remote}}
    json.dump(out, open(os.path.join(OUT, "_quality_ab.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    todo = {"baseline": cmd_baseline, "machine": cmd_machine,
            "semantic": cmd_semantic, "blind": cmd_blind,
            "ab": cmd_ab}.get(cmd)
    if cmd == "all":
        for f in (cmd_baseline, cmd_machine, cmd_semantic, cmd_blind, cmd_ab):
            f()
    elif todo is None:
        print(__doc__)
        sys.exit(1)
    else:
        todo()
        sys.exit(0)


if __name__ == "__main__":
    main()
