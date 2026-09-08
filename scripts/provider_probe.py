# -*- coding: utf-8 -*-
"""第三方网关探针：验证一个 OpenAI 兼容渠道能否承担我们的测试/长测角色。

四步（每步独立判定，全部通过才够格进渠道池）：
  A. GET /v1/models          —— 模型清单里有没有目标模型（含变体命名）
  B. thinking enabled 调用   —— reasoning_content 是否返回（推理没被禁/剥）
  C. thinking disabled 调用  —— 能否关思考（机械阶段省推理费的前提）
  D. 同前缀复打              —— usage 是否携带缓存命中字段且真命中
                               （没有 hit/miss 字段 = 无法测 99% 命中率 = 出局）

参数格式逐字节复刻 app/llm/client.py 的 payload：
  thinking={"type": "enabled"|"disabled"} + reasoning_effort（enabled 时）
用量：每步 <2k tokens，四个探针总成本 < ¥0.01 量级。

用法：
  python scripts/provider_probe.py --base-url https://tokenrhythm.studio/v1 \
      --api-key sk_xxx --model deepseek-v4-flash [--effort low]
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 复用前缀（步骤 B/D 共用，逐字节一致才能测缓存）：约 1.4k 字符 ≈ 900 tok
PREFIX = (
    "你是一部长篇网络小说的设定 keeper。以下是一部小说的设定摘要，请记住它，"
    "后续问题都以此为基准回答。\n\n" + (
        "第%d条设定：主角团成员「沈孤灯」持有信号灯一盏，灯芯以夜行者的记忆为燃料，"
        "每次点燃会烧去一段记忆，烧到第四段时会遗忘自己最想守护的人。灯焰颜色随剩余"
        "记忆量变化：金、橙、红、灰。沈孤灯的搭档是拾骨人阿蓟，阿蓟能听见骨殖里封存的"
        "遗言，但每听一次会在自己左眼累积一道白翳。二人行走在永夜之城临安，城中坊市以"
        "更漏计时，更夫换班的钟声是唯一的公共时刻。临安的统治者为九司，九司各掌一夜："
        "司灯掌灯火，司籍掌名册，司圹掌葬仪，司泉掌水脉，司市掌集市，司更掌钟漏，司药"
        "掌药材，司械掌机巧，司狱掌囚徒。九司之下有游曳的夜行者，夜行者以记忆易物。"
    ) * 3 +
    "\n\n问题：请用一句话复述：灯焰变灰时意味着什么？"
)


def _flags(d: dict) -> str:
    return " ".join(k for k, v in d.items() if v) or "无"


def main():
    ap = argparse.ArgumentParser(description="第三方网关可用性探针")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--effort", default="low", help="thinking enabled 时附带的 reasoning_effort")
    ap.add_argument("--timeout", type=float, default=90.0)
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    headers = {"Authorization": "Bearer %s" % args.api_key,
               "Content-Type": "application/json"}
    verdict = {}

    with httpx.Client(timeout=args.timeout) as hx:
        # ---- A. 模型清单 ----
        print("=" * 62)
        print("A. GET /models —— 模型在清单里？")
        try:
            r = hx.get(base + "/models", headers=headers)
            names = []
            if r.status_code == 200:
                data = r.json().get("data") or []
                names = sorted(str(m.get("id") or "") for m in data)
            print("   HTTP %s，共 %d 个模型" % (r.status_code, len(names)))
            hits = [n for n in names if "v4" in n.lower() or "flash" in n.lower()
                    or "deepseek" in n.lower()]
            for n in hits[:15]:
                print("   ·", n)
            verdict["A_模型在清单"] = bool(hits)
            if not hits and names:
                print("   （清单里没有 deepseek/v4/flash 字样——以下步骤仍按给定模型名硬试）")
        except Exception as e:  # noqa: BLE001
            print("   失败：%s" % e)
            verdict["A_模型在清单"] = None

        # ---- B/C. thinking on/off ----
        usage_seen = {}
        for tag, think, question in (
                ("B", "enabled", "问题：灯焰变灰意味着什么？一句话回答。"),
                ("C", "disabled", "问题：司更掌管什么？一句话回答。")):
            payload = {
                "model": args.model,
                "messages": [
                    {"role": "system", "content": "你是精确的中文问答助手。"},
                    {"role": "user", "content": PREFIX + "\n\n" + question},
                ],
                "stream": False,
                "max_tokens": 512,
                "temperature": 0.3,
            }
            if think:
                payload["thinking"] = {"type": "enabled"}
                payload["reasoning_effort"] = args.effort
            else:
                payload["thinking"] = {"type": "disabled"}
            print("=" * 62)
            print("%s. thinking %s —— 推理链与 usage 字段" % (tag, think))
            try:
                r = hx.post(base + "/chat/completions", headers=headers,
                            json=payload)
                print("   HTTP %s" % r.status_code)
                if r.status_code != 200:
                    print("   响应体前 300 字：", r.text[:300])
                    verdict["%s_thinking%s" % (tag, think)] = False
                    continue
                d = r.json()
                msg = (d.get("choices") or [{}])[0].get("message") or {}
                rc = msg.get("reasoning_content") or ""
                content = (msg.get("content") or "").strip()
                usage = d.get("usage") or {}
                usage_seen[tag] = usage
                hit = usage.get("prompt_cache_hit_tokens")
                miss = usage.get("prompt_cache_miss_tokens")
                reas = ((usage.get("completion_tokens_details") or {})
                        .get("reasoning_tokens"))
                print("   reasoning_content：%d 字 %s" % (
                    len(rc), ("（首 60：%s…）" % rc[:60]) if rc else "——缺失"))
                print("   content：%d 字（%s…）" % (len(content), content[:40]))
                print("   usage keys：%s" % ", ".join(sorted(usage.keys())))
                print("   缓存 hit/miss 字段：%s / %s；reasoning_tokens：%s"
                      % (hit, miss, reas))
                ok = bool(content) and (len(rc) > 0 if think == "enabled" else True)
                verdict["%s_thinking%s" % (tag, think)] = ok
            except Exception as e:  # noqa: BLE001
                print("   失败：%s" % e)
                verdict["%s_thinking%s" % (tag, think)] = False

        # ---- D. 同前缀复打测缓存（复用 B 的逐字节前缀，再问一个不冲突的问题）----
        payload_d = {
            "model": args.model,
            "messages": [
                {"role": "system", "content": "你是精确的中文问答助手。"},
                {"role": "user", "content": PREFIX + "\n\n"
                 + "问题：阿蓟每听一次遗言会在哪里累积什么？一句话回答。"},
            ],
            "stream": False,
            "max_tokens": 512,
            "temperature": 0.3,
            "thinking": {"type": "disabled"},
        }
        print("=" * 62)
        print("D. 同前缀第二打 —— 缓存命中可测可复现？")
        try:
            r = hx.post(base + "/chat/completions", headers=headers, json=payload_d)
            print("   HTTP %s" % r.status_code)
            if r.status_code == 200:
                usage = r.json().get("usage") or {}
                pt = int(usage.get("prompt_tokens") or 0)
                hit = int(usage.get("prompt_cache_hit_tokens") or 0)
                miss = int(usage.get("prompt_cache_miss_tokens") or 0)
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                print("   prompt_tokens=%s hit=%s miss=%s cached_tokens(details)=%s"
                      % (pt, hit, miss, cached))
                if hit or cached:
                    verdict["D_缓存命中"] = True
                elif hit == 0 and miss == 0 and cached is None:
                    print("   → usage 里没有任何缓存字段：命中不可测量")
                    verdict["D_缓存命中"] = False
                else:
                    print("   → 有字段但 0 命中（缓存未生效或需更长前缀/二次预热）")
                    verdict["D_缓存命中"] = False
            else:
                print("   响应体前 300 字：", r.text[:300])
                verdict["D_缓存命中"] = False
        except Exception as e:  # noqa: BLE001
            print("   失败：%s" % e)
            verdict["D_缓存命中"] = False

    print("=" * 62)
    print("裁决（%s @ %s）：" % (args.model, base))
    for k, v in verdict.items():
        print("  [%s] %s" % ("过" if v else ("？" if v is None else "斩"), k))
    all_ok = all(v for v in verdict.values())
    print("总裁决：%s" % ("四步全过 → 可入渠道池（先小样本跑对照再当长测主力）"
                         if all_ok else "存在未过项 → 按斩项定性（不可测缓存/不可关思考 = 出局）"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
