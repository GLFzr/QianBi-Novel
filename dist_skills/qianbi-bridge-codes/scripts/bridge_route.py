# -*- coding: utf-8 -*-
"""桥段码路由/查询 CLI（qianbi-bridge-codes 导出包）——由上游导出管线生成

码表为 qianbi-novel app/prompts/bridge_codes.py 的逐字副本（scripts/_vendor/，
MIT License）。查询路由判据/典型位置/路由词；反例码（advisory_only）只作审校
证据，不进正文/细纲路由。

用法：
    python bridge_route.py --list               # 全码清单（人读）
    python bridge_route.py --list --json        # 机器可读（金标同口径）
    python bridge_route.py --group 爽点          # 按组过滤
    python bridge_route.py --code DL            # 单码详情
    python bridge_route.py --route 打脸 当众     # 按路由词查码（细纲解析兜底）

退出码：0 = 正常；2 = 用法错误。
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "_vendor"))

from qbn_exported.qianbi_vendor import bridge_codes as bc  # noqa: E402


def _group_index(code_rec):
    try:
        return bc.GROUP_ORDER.index(code_rec["group"])
    except ValueError:
        return len(bc.GROUP_ORDER)


def _all_codes():
    out = []
    for code in sorted(bc.BRIDGE_CODES):
        rec = bc.BRIDGE_CODES[code]
        out.append({
            "code": code, "name": rec["name"], "group": rec["group"],
            "rule": rec["rule"], "position": rec.get("position", ""),
            "spans": list(rec.get("spans", ())),
            "route_kw": list(rec.get("route_kw", ())),
            "card": rec.get("card", ""),
            "advisory_only": bool(rec.get("advisory_only")),
        })
    out.sort(key=lambda r: (_group_index(bc.BRIDGE_CODES[r["code"]]),
                            r["code"]))
    return out


def _print_detail(code, rec):
    print("%s %s（%s组%s）" % (
        code, rec["name"], rec["group"],
        "，反例证据码" if rec.get("advisory_only") else ""))
    print("  判据：%s" % rec["rule"])
    print("  典型位置：%s" % rec.get("position", "-"))
    spans = rec.get("spans", ("-"))
    print("  典型跨度：%d-%d 章" % (spans[0], spans[1]))
    print("  路由卡：%s" % (rec.get("card") or "（不路由）"))
    kws = rec.get("route_kw") or ()
    if kws:
        print("  路由词：%s" % "、".join(kws))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bridge_route.py")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--group")
    ap.add_argument("--code")
    ap.add_argument("--route", nargs="*", default=[])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    if args.code:
        rec = bc.BRIDGE_CODES.get(args.code)
        if rec is None:
            print("未知码：%s" % args.code, file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({"code": args.code, **{
                k: (list(v) if isinstance(v, tuple) else v)
                for k, v in rec.items()}}, ensure_ascii=False, sort_keys=True,
                indent=1))
        else:
            _print_detail(args.code, rec)
        return 0

    if args.route:
        wanted = [w for w in args.route if w]
        if not wanted:
            ap.error("--route 需要至少一个路由词")
            return 2
        hits = [c for c in _all_codes()
                if any(w in (bc.BRIDGE_CODES[c["code"]].get("route_kw") or ())
                       for w in wanted)]
        if args.json:
            print(json.dumps({"route_kw": wanted, "codes": hits},
                             ensure_ascii=False, sort_keys=True, indent=1))
        else:
            for c in hits:
                _print_detail(c["code"], bc.BRIDGE_CODES[c["code"]])
        return 0

    codes = _all_codes()
    if args.group:
        codes = [c for c in codes if c["group"] == args.group]
        if args.json:
            print(json.dumps({"group": args.group, "codes": codes},
                             ensure_ascii=False, sort_keys=True, indent=1))
            return 0
    if args.json:
        print(json.dumps({"codes": codes}, ensure_ascii=False,
                         sort_keys=True, indent=1))
        return 0

    print("桥段码表 %d 码（%s）" % (
        len(codes), "、".join("%s %d" % (g, bc.GROUP_EXPECTED.get(g, -1))
                              for g in bc.GROUP_ORDER)))
    cur = None
    for c in codes:
        if c["group"] != cur:
            cur = c["group"]
            print("\n[%s]" % cur)
        print("  %-4s %s：%s" % (c["code"], c["name"], c["rule"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
