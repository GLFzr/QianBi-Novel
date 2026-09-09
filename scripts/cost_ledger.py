# -*- coding: utf-8 -*-
"""成本台账：扫描全部历史 usage.jsonl，逐行按模型分价重算，输出完整成本表。

价格口径（DeepSeek v4 off-peak，$/M）：flash hit .007 / miss .22 / out .66；
pro hit .022 / miss .66 / out 1.98。¥ = ×7.2。
真实目录的行按日期聚类（一天=一个跑次）；bench 变体按目录=一个跑次。
"""
from __future__ import annotations

import glob
import json
import os
import sys

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# W-5：盲区 token 的口径与 chapter_curve 必须同源，唯一定义在 app.usage
from app.usage import blind_spread, cache_caliber  # noqa: E402
REAL_USAGE = os.path.join(os.path.expanduser("~"), ".qianbi_novel", "usage", "usage.jsonl")
USD_CNY = 7.2
PRICE = {
    "flash": {"hit": 0.007e-6, "miss": 0.22e-6, "out": 0.66e-6},
    "pro": {"hit": 0.022e-6, "miss": 0.66e-6, "out": 1.98e-6},
}

# 跑次语义标注（变体目录 → 说明）
BENCH_LABELS = {
    "_prepare_home": ("种子书 prepare", "设定+卷纲+6 细纲（一次性基建）"),
    "smoke2": ("台子冒烟", "1 章微循环"),
    "base": ("E1 基线", "0.18.5 架构全流程 3 章"),
    "prose_low": ("E2 prose=low", "全流程 3 章（否决：+5%）"),
    "review_low_fast": ("E3 审校low+快速道", "全流程 3 章"),
    "audit_med": ("E4 清算 medium(杀)", "2.5 章，被外部终止"),
    "audit_high_seed": ("E5b 清算 high 基线", "固定草稿直奔清算 3 章（pro 全量）"),
    "audit_low_seed": ("E5a 清算 low", "同输入（-93% 成本）"),
    "audit_medseed": ("E7 清算 medium+16k", "同输入（检出缩水，否决）"),
    "audit_hiflash": ("E6 清算 high on flash", "同输入（确定性空流，不可行）"),
    "audit_noreason": ("E9' 清算关推理", "同输入（59% 引文不实，否决）"),
    "cascade_e9": ("E9 级联首跑", "pro 复核 bug 版（3 章全采信）"),
    "cascade_e9b": ("E9 级联修复版", "最终形态：预扫干净零 pro / 硬伤 pro 复核 flagged"),
    "review_disabled": ("E10 审校 disabled", "全流程 3 章（埋雷召回 4/4 的档位）"),
    "prose_med": ("E8 prose=medium", "全流程 3 章（+64%，强烈否决）"),
    "review_tier_home": ("审校三档埋雷", "12 票：4 颗植入缺陷 × 3 档 × 2 票 + 干净章对照"),
    # ---- 成本优化战役 v2（tests/bench_variants/ 预设名对齐）----
    "baseline_e01": ("E0.1 基线", "0.19 全流程六章基线（R0：所有收益算术的新基数）"),
    "e11_span_deslop": ("E1.1 span-deslop", "deslop 相位 span 级输出对照（O1，逐相位独立测）"),
    "e11_span_trim": ("E1.1 span-trim", "trim 相位 span 级输出对照（预期 16k→4-6k）"),
    "e11_span_reviewfix": ("E1.1 span-reviewfix", "review_fix 相位 span 级输出对照（预期 30k→8-12k）"),
    "e12_outline_budget": ("E1.2 outline-budget", "细纲显式长度预算（O2：长度指令服从度）"),
    "e12_prose_thinkbudget": ("E1.2 prose-thinkbudget", "正文思考软预算（O2，均值 60% 口径）"),
    "e12_prose_structure": ("E1.2 prose-structure", "正文先场景卡后成文（O2 对照：结构化替代思考）"),
    "cachecheck_e21": ("E2.1 缓存复检", "前缀卫生修复后六章命中率对照（目标 ≥88%）"),
    "e32_cisc": ("E3.2 CISC 置信加权", "审校票 confidence 加权重裁对照（O5）"),
    "e33_earlystop": ("E3.3 清算早停", "清算条目级早停分诊（O6：unsure 展开制）"),
    "ext_qwen_e41": ("E4.1 摘要外迁 qwen", "tracking/摘要三相位移交 qwen-flash（O3）"),
    "ext_doubao_e41b": ("E4.1b 摘要外迁 doubao", "同上换 doubao-1.5-lite（O3，~1/8 输出价）"),
    # ---- S 轮结构调整（六章，DS 口径；变体缺标注即不入账，2026-09-07 补录）----
    "s1_volume": ("S1 卷会话", "6 章 hit 93.3% / ¥0.291 每章 / 盲评 7.53 ✅（S 轮最干净增益）"),
    "s2_volume": ("S2 会话清算+条目早停", "6 章 hit 93.5% / ¥0.335 每章 / 盲评 7.35 ✅"),
    "s3_nopro": ("S3 节拍窗口+去 Pro", "6 章 hit 92.5% / ¥0.211 每章 / 盲评 7.22 ✅（D4 -0.9 观察）"),
    "e13_trim_low": ("E1.3 trim=low", "六章对照，D2 爽点闭环待 T4a 雷章复验"),
    "t1_long20": ("T1 二十章长卷", "20 章 hit 95.9% / ¥0.273 每章 / 盲评 7.10 ❌"
                                  "（vs 同场锚点 7.69 Δ-0.59，D4 主跌；S 全栈·tr-dsv4f·无 Pro）"),
    "t2_outline": ("T2 前置·补细纲 21-26", "两臂共读的细纲批次（--outlines-only，不出正文）"),
    "t2_smoke1": ("冒烟·seed 续写接栈", "1 章 @tr-dsv4f：验证换名续写不再退回空栈"
                                       "（prose in 285,683 / hit 248,320），实测 ¥0.822/章"),
    "t1c_bailian": ("T1c 跨渠道校定", "续写 21-24 章 @bailian-flash，第 25 章撞 429 中断；"
                                      "章界浅命中在两渠道同构复现（miss 41-42k/章）"),
    "t2_smoke2": ("哈希诊断·续写 2 章", "@tr-dsv4f；章界那笔只记到 hit 4.5%，"
                                        "其后同链 enrich 记到 95.8%（整跑均值 90.9%）——记账抖动的在册证据"),
    # ---- T2 压缩 A/B 与 T4 雷章复核（2026-09-07 晚，看板 §5 22:30 / 23:10）----
    "t2a_keep": ("T2 对照臂·不压缩", "续写 21-26 章：hit 97.7% / ¥0.332 每章；"
                                     "短章触发字数预检跳过审校，调用数反低于压缩臂"),
    "t2b_compact": ("T2 压缩臂", "同起点续写 21-26：读量降至 29% 但 miss 反升 105%、"
                                 "hit 91.7%、LLM 秒 +78% ⇒ 热缓存下『压缩省钱』前提不成立"),
    "t4a_recall": ("T4a B 类雷召回", "3 章雷稿（B01/B02+干净对照）走 去味/审校/清算："
                                     "审校对两雷均未判阻塞（召回 ❌ 0/2），对照章无 B 类误报"),
    "t4b_base": ("T4b 对照·修复默认档", "C01/D01 雷稿，review_fix 整段输出模式"),
    "t4b_span": ("T4b 实验·修复 span 档", "同稿只改 review_fix.output_mode=span"
                                          "（自有格式，不经网关参数 ⇒ TR 上有效）"),
    "t3_long60": ("T3 压力终验·首段（9/60 章）", "tr-dsv4f 跑到第 10 章连回三次 503 SERVICE_BUSY "
                                                 "致 cost_bench 崩、无 metrics——成本按 usage 重算；"
                                                 "续跑见 t3b_long60（scripts/t3_resume.py）"),
    "t3b_long60": ("T3 续跑段 b（10-38 章）", "tr-dsv4f / deepseek-v4-flash，驱动在 00:36 探到渠道恢复自动接跑；"
                                             "04:25 再度 503 超时停"),
    "t3c_long60": ("T3 续跑段 c（38 章）", "⚠️ 本段起切 ocgo-omen（**omen-alpha，换了生成模型**）；"
                                          "38/39 章因驱动按正文最大章号推算起跑点而被重写一次"),
    "t3d_long60": ("T3 续跑段 d（39-40 章）", "omen-alpha；卷三从 39 章起＝栈断崖重置（911,606→13,470 tok），"
                                             "该章 miss 峰值即渠道切换税＋卷界税叠加"),
    "t3e_long60": ("T3 续跑段 e（41-53 章）", "omen-alpha；单笔延迟 89s ≈ dsv4f 段的 2.7-3.4×；"
                                             "53 章后渠道 5xx 卡住（TR 亦已 DOWN 16h+）"),
    # ---- 09-09 凌晨 V7 审校空转取证族（官方 deepseek-v4-flash-0731；驱动中断⇒无 metrics.json）----
    "v_smoke3": ("V7 取证·3 章 a", "09-09 00:50 起跑 3 章；审校轮在跑但不出协议（P0 复现）"),
    "v_smoke3b": ("V7 取证·3 章 b", "09-09 01:30 同族第二段 28 笔，hit 89.6%"),
    "v_smoke3c": ("V7 取证·3 章 c", "09-09 03:42 同族第三段，hit 87.3%"),
    "v_full20": ("V7 取证·20 章规格", "09-09 01:45 起跑，实落 13 章 prose／review 27 笔；"
                                      "整章回声取证见《T 轮增补》表2②（正常票 948 字 vs 回声票）"),
    "v_full20b": ("V7 取证·20 章续段", "09-09 02:43 同族续跑 3 章 prose"),
    "v7_long13": ("V7 取证·13 章长卷", "09-09 04:03，11 章 prose／review 33 票＝**11/11 整章回声**"
                                       "⇒ P0（review_static_tail 把 92.7% 审校轮搬进 system）的对照基线"),
}


def _tier(model: str) -> str:
    return "pro" if "pro" in str(model) else "flash"


def _cost(rows) -> dict:
    """逐行按**模型档位**分价重算（W-5 口径：盲区既不白给也不白拿）。

    每个档位（flash/pro＝渠道）单独累计 hit/miss/盲区，于是：
    - `cny`（账面）＝盲区全按 miss 计——未证明命中的 token 不能算命中；
    - `cny_real`（真实）＝盲区按**该档自己已知行的实测命中率**摊派；
    - `hit_pct` 只在已知行上算（盲区不参与分子分母），另单独报 `blind_tok`。
    旧实现对没回缓存明细的行**只计输出钱**（输入当免费），与 chapter_curve 的
    「按 miss 计」正好相反——同一份数据两个数，判据就废了。"""
    out = reas = 0.0
    out_tier = {}
    for r in rows:
        t = _tier(r.get("model", ""))
        h, m, b = cache_caliber(r)
        d = out_tier.setdefault(t, {"hit": 0, "miss": 0, "blind": 0, "out": 0.0,
                                    "reas": 0.0, "calls": 0})
        d["hit"] += h
        d["miss"] += m
        d["blind"] += b
        o = r.get("out") or 0
        d["out"] += o
        d["reas"] += r.get("reasoning") or 0
        d["calls"] += 1
        out += o
        reas += r.get("reasoning") or 0
    usd_book = usd_real = 0.0
    hit = miss = blind = in_total = 0
    retry_calls = 0
    retry_usd = 0.0
    for t, d in out_tier.items():
        p = PRICE[t]
        usd_book += d["hit"] * p["hit"] + (d["miss"] + d["blind"]) * p["miss"] \
            + d["out"] * p["out"]
        add_h, add_m = blind_spread(d["hit"], d["miss"], d["blind"])
        usd_real += (d["hit"] + add_h) * p["hit"] + (d["miss"] + add_m) * p["miss"] \
            + d["out"] * p["out"]
        hit += d["hit"]
        miss += d["miss"]
        blind += d["blind"]
        in_total += d["hit"] + d["miss"] + d["blind"]
    for r in rows:
        # W-4：白付行——没产出可用正文却花了钱的一发（重试/空流/中止），单独列账
        if str(r.get("st") or "").strip():
            p = PRICE[_tier(r.get("model", ""))]
            h, m, b = cache_caliber(r)
            retry_calls += 1
            retry_usd += h * p["hit"] + (m + b) * p["miss"] + (r.get("out") or 0) * p["out"]
    known = hit + miss
    return {
        "calls": len(rows),
        "in_tok": int(in_total),
        "hit_pct": (round(hit / known * 100, 1) if known else 0.0) if out_tier else 0.0,
        "blind_tok": int(blind),
        "blind_share": round(100.0 * blind / max(1, in_total), 1),
        "out_tok": int(out),
        "reasoning": int(reas),
        "usd": round(usd_book, 4),
        "cny": round(usd_book * USD_CNY, 3),
        "usd_real": round(usd_real, 4),
        "cny_real": round(usd_real * USD_CNY, 3),
        "retry_calls": retry_calls,
        "retry_cny": round(retry_usd * USD_CNY, 3),
        "models": {t: d["calls"] for t, d in sorted(out_tier.items())},
    }


def _rows(path):
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def _chapters_of(variant: str):
    p = os.path.join(ROOT, "tests_output", "bench", "%s.metrics.json" % variant)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return len(json.load(f).get("chapters") or [])
    except Exception:
        return None


def main():
    ledger = []   # (类别, 名称, 说明, metrics)

    # 1) bench 变体
    unlabeled = []   # U1 台账自检（T 轮增补 §7：T3 续跑段 138M tok 曾因缺标注整段漏账）
    for d in sorted(glob.glob(os.path.join(ROOT, "tests_output", "bench", "*"))):
        name = os.path.basename(d)
        if name in ("_prepare_home",) or not os.path.isdir(d):
            pass
        rows = _rows(os.path.join(d, ".qianbi_novel", "usage", "usage.jsonl"))
        if rows and name in BENCH_LABELS:
            label, note = BENCH_LABELS[name]
            ledger.append(("实验台", label + "（%s）" % name, note, _cost(rows)))
        elif rows:
            unlabeled.append((name, _cost(rows)))

    # 1.5) Temp 残留 fake home（历史 run 被清理脚本误删前的幸存数据）
    temp_root = os.environ.get("TEMP", os.path.expanduser("~/AppData/Local/Temp"))
    for d in sorted(glob.glob(os.path.join(temp_root, "qbn_*"))):
        rows = _rows(os.path.join(d, ".qianbi_novel", "usage", "usage.jsonl"))
        if rows:
            tag = os.path.basename(d)
            span = "%s ~ %s" % (rows[0].get("ts", "?")[11:16], rows[-1].get("ts", "?")[11:16])
            ledger.append(("真机全流程", "e2e 残留（%s）" % tag[:28],
                           "被杀前幸存的 %s 数据（Temp 残留）" % span, _cost(rows)))

    # 2) 5ch e2e 留存
    rows = _rows(os.path.join(ROOT, "tests_output", "5ch_e2e", "usage_run.jsonl"))
    if rows:
        ledger.append(("真机全流程", "5 章端到端（run4 留存）",
                       "0.18.5+ 架构 5 章共写全流程，verdict 全过", _cost(rows)))

    # 3) 真实目录：按日期聚类
    real = _rows(REAL_USAGE)
    by_day = {}
    for r in real:
        by_day.setdefault(str(r.get("ymd") or r.get("ts", "")[:10]), []).append(r)
    day_labels = {
        "2026-08-31": ("能力轮验收跑", "0.18.3 架构 · 执灯人夜行档案（含审校六维/清算/追踪全链）"),
        "2026-09-05": ("0.18.4 发版验收", "双层前缀架构 · 6 章（57 笔全量埋点的那次）"),
        "2026-09-06": ("Agent 化与档位实验", "agent_eval L2 兜底 + review_tier 探测 + 级联首日"),
    }
    for day in sorted(by_day):
        label, note = day_labels.get(day, (day, "真机调用"))
        ledger.append(("真实目录", "%s（%s）" % (label, day), note, _cost(by_day[day])))

    # 输出
    total_calls = sum(m["calls"] for _c, _n, _s, m in ledger)
    total_cny = sum(m["cny"] for _c, _n, _s, m in ledger)
    total_real = sum(m.get("cny_real", m["cny"]) for _c, _n, _s, m in ledger)
    total_blind = sum(m.get("blind_tok", 0) for _c, _n, _s, m in ledger)
    lines = ["# 成本台账（全部真机调用，逐行按模型分价重算）", "",
             "> 价格口径：DeepSeek v4 off-peak——flash 输入 hit $0.007 / miss $0.22 / 输出 $0.66；",
             "> pro 输入 hit $0.022 / miss $0.66 / 输出 $1.98（每百万 token，¥=$×7.2）。",
             "> 每行 usage 记录按其模型分价——修正了早期 metrics 按统一 flash 价低估 pro 行的问题。",
             "> **口径（W-5）**：「命中」只在网关回了缓存明细的行上算；「盲区 tok」＝什么都没回的行，",
             "> 既不进命中的分子也不进分母。¥账面＝盲区按 miss 计（保守上限）；",
             "> ¥真实＝盲区按该档自身实测命中率摊派。两者差额全部来自盲区，不是模型行为。",
             ""]
    cur = None
    for cat, name, note, m in ledger:
        if cat != cur:
            lines.append("## %s" % cat)
            lines.append("")
            lines.append("| 跑次 | 章 | 调用 | 输入 tok | 命中 | 盲区 tok | 输出 tok | "
                         "推理 tok | ¥账面 | ¥真实 | 模型分布 |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
            cur = cat
        models = " / ".join("%s×%d" % (k, v) for k, v in sorted(m["models"].items()))
        ch = _chapters_of(name) if cat == "实验台" else None
        hit_s = m["hit_pct"] if isinstance(m["hit_pct"], str) else "%s%%" % m["hit_pct"]
        lines.append("| %s | %s | %d | %s | %s | %s | %s | %s | %.3f | %.3f | %s |"
                     % (name, str(ch) if ch else "—", m["calls"], f"{m['in_tok']:,}",
                        hit_s, f"{m.get('blind_tok', 0):,}", f"{m['out_tok']:,}",
                        f"{m['reasoning']:,}", m["cny"],
                        m.get("cny_real", m["cny"]), models))
        if note:
            lines.append("  ^ ^ %s" % note)
    total_retry_calls = sum(m.get("retry_calls", 0) for _c, _n, _s, m in ledger)
    total_retry_cny = sum(m.get("retry_cny", 0.0) for _c, _n, _s, m in ledger)
    lines.append("")
    lines.append("**合计**：%d 笔真机调用，约 **¥%.2f**（账面）／**¥%.2f**（真实）"
                 "（全部实验 + 验收 + 探针）。" % (total_calls, total_cny, total_real))
    if total_retry_calls:
        lines.append("")
        lines.append("　其中**白付**（重试/空流/中止，`st` 标记）**%d 笔／¥%.2f**——"
                     "W-4 之前这些发在账上恒等于 0。" % (total_retry_calls, total_retry_cny))
    if total_blind:
        lines.append("")
        lines.append("　两口径差额 ¥%.2f 全部来自 **%s tok 盲区**（网关没回 "
                     "`prompt_tokens_details`）——盲区率高的渠道（如 omen-alpha ~34%% 调用）"
                     "其**账面**数不可与其它渠道互比，只能用同一渠道内部对比。"
                     % (total_cny - total_real, format(total_blind, ",")))
    lines.append("")
    lines.append("## 实验有效性注记（读表前必看）")
    lines.append("")
    lines.append("- **E1-E4 跑在「全 pro」事故配置下**（模型分布 pro×24/28 如实记录）：当时实验台")
    lines.append("  _mk_cfg 的 pro 连接拼接存在 Python 运算符优先级 bug（`A if pro else [] + [...]`），")
    lines.append("  三条连接只剩 pro——E1「基线」实际是全 pro 底色，¥1.943/3 章不代表 0.18.5 默认配置。")
    lines.append("  E5b 起修复（flash×9/pro×3），其审校/追踪相位才是 flash。E2/E3 的对比结论方向不变")
    lines.append("  （同底色下变量对照），但绝对成本数值不可与修复后的变体直接互比。")
    lines.append("- **E5b vs E9b 是同输入同模式的清算对照**：跑级成本 ¥0.879 → ¥0.281（-68%，含追踪/摘要");
    lines.append("  等其他相位噪声）；**相位级**（只看 canon_audit 相位）pro 全量 47.3k tok → flash 预扫")
    lines.append("  14.1k + pro 复核 3.7k，**-82%**——两个口径都对，正文引用注明层级。")
    lines.append("- **单章成本演进（诚实口径，注意字数目标不可直接比）**：0.18.3 能力轮 ~¥0.26/章")
    lines.append("  （2000 字目标 + off-peak）；0.18.4 验收 ¥0.78/章（3000 字目标 + 细纲 41k 输出时代）；")
    lines.append("  0.19 五章端到端 ¥0.33/章（2500 字目标 + 级联前架构）；0.19 级联后清算环节 -68%，")
    lines.append("  全流程预计 ~¥0.25/章（待正式对照跑）。")
    lines.append("- 全部调用走 off-peak 时段（除 09-05 验收部分白天），若含 peak 价成本更高。")
    lines.append("")
    lines.append("## 数据完整性说明（已知缺口，诚实列账）")
    lines.append("")
    lines.append("1. **0.18.4 期间约 544 行丢失**（2026-09-01 ~ 09-05 白天）：一次实验台冒烟测试")
    lines.append("   误截断了真实目录的 usage.jsonl，当时已披露并从日志恢复出 08-31 的 151 行；")
    lines.append("   丢失段含能力轮后续迭代与部分手动测试，**无法恢复**——故 0.18.4 的单章成本")
    lines.append("   口径只有 09-05 晚间验收跑（57 笔）这一个样本。")
    lines.append("2. **5 章 e2e 的一次完整跑丢失**（0.18.5 架构，61 笔请求、5/5 章 verdict 全过）：")
    lines.append("   当时 e2e 收尾脚本直接 rmtree 了 fake home，用量与章节产物一起被清；")
    lines.append("   之后 e2e 已改为「先留存 artifact+usage 再清理」，现台账收录的是留存版")
    lines.append("   （46 笔）与被杀前幸存的残留（31 笔）。")
    lines.append("3. **非真机调用不在账内**：单测/mock/离线探针零 API 消耗；mock 客户端跑的")
    lines.append("   端到端（test_5ch_mock 等）不计成本。")
    lines.append("4. 价格若按 peak 档（北京时间工作日 09:00-12:00 / 14:00-18:00 全价）则翻倍，")
    lines.append("   本账全部按实际发生时段的 off-peak 口径。")
    # U1 台账自检：有用量但缺 BENCH_LABELS 标注的变体——高声报数而非静默跳过
    # （T 轮增补 §7 事故：T3 续跑段 138M tok 因此整段漏账，补正后总账 +¥20.68）
    if unlabeled:
        lines.append("")
        lines.append("## ⚠ 未标注变体（有真实用量但不在 BENCH_LABELS——未计入上表，请补标注后重跑台账）")
        lines.append("")
        lines.append("| 变体 | 调用 | 输入 tok | 成本 ¥ |")
        lines.append("|---|---|---|---|")
        for _n, _m in unlabeled:
            lines.append("| %s | %d | %s | %.3f |" % (_n, _m["calls"],
                                                      f"{_m['in_tok']:,}", _m["cny"]))
        _u_cny = sum(_m["cny"] for _c, _m in unlabeled)
        _u_calls = sum(_m["calls"] for _c, _m in unlabeled)
        lines.append("")
        lines.append("**漏账合计**：%d 笔 / ¥%.3f——补进 BENCH_LABELS 重跑台账即入正表。"
                     % (_u_calls, _u_cny))
    out = os.path.join(ROOT, "docs", "成本台账.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if unlabeled:
        print("⚠ 台账自检：%d 个变体有用量但缺标注（漏账 ¥%.3f）——详见 %s 的未标注节"
              % (len(unlabeled), sum(_m["cny"] for _c, _m in unlabeled), out))
    print("\n".join(lines[-14:]))
    print("→", out)


if __name__ == "__main__":
    main()
