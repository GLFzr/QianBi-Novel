# -*- coding: utf-8 -*-
"""C6 处置：补跑清算（v16 5.1 附带质量事故——v15_tail ch25-30 清算空内容贴顶全
失败 → 六章「未对账+台账断档」，P5 带伤种子必须先补跑或明示接受）。

对显式工程目录逐章重跑 canon_audit.audit_chapter（当前代码=P1 修复后：降级重发
thinking 显式 disabled；配置取 v16 stack 的 canon_audit 档——in_session 无会话自然
回退独立单发，thinking disabled 由 stage_params 传入路由层，此处直接以 overrides
钉在客户端上，与生产 router 路径同参）。升序执行：每章 adoptions 先入台账，
后章审计才能看到。假 home 承载 usage（真机台账零写入），Key 从真机配置注入。

用法：
  python scripts/reaudit_chapters.py --proj tests_output/bench/v16_seed/种子书 \
      --chapters 26,27,28,29,30 --flash-conn ds-official-flash

退出码：0=全部成功；1=有章 failed；2=用法/IO。
"""
from __future__ import annotations

import argparse
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

REAL_HOME = os.path.expanduser("~")   # 模块加载时钉住（env 未重定向时）


def main():
    ap = argparse.ArgumentParser(description="C6 处置：补跑清算（假 home 承载 usage）")
    ap.add_argument("--proj", required=True, help="工程目录（绝对或相对仓库根）")
    ap.add_argument("--chapters", default="26,27,28,29,30")
    ap.add_argument("--flash-conn", default="ds-official-flash")
    ap.add_argument("--home", default=os.path.join(ROOT, "tests_output", "bench", "_reaudit_home"))
    args = ap.parse_args()

    proj = args.proj if os.path.isabs(args.proj) else os.path.join(ROOT, args.proj)
    if not os.path.isdir(os.path.join(proj, "正文")):
        print("[错误] 工程目录不合法：%s" % proj)
        return 2
    nums = [int(x) for x in args.chapters.split(",") if x.strip()]

    home = args.home
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    os.environ["USERPROFILE"] = home
    os.environ["HOME"] = home

    from scripts.cost_bench import _load_key, _mk_cfg
    from app.core import canon_audit
    flash, _pro = _load_key(prefer_id=args.flash_conn, real_home=REAL_HOME)
    cfg = _mk_cfg(flash)
    # 生产档对齐：v16 stack canon_audit thinking disabled（P4a 雷章门裁定落地档）
    cfg.setdefault("writing", {})["corpus_head"] = False
    client = canon_audit._client_for(cfg)

    class _Router:
        def client(self, _slot):
            return client

    client._overrides = lambda _ph: {"thinking": "disabled"}

    print("[reaudit] proj=%s chapters=%s conn=%s" % (proj, nums, flash.get("model")))
    failed = []
    for n in nums:
        chap_files = [f for f in os.listdir(os.path.join(proj, "正文"))
                      if f.startswith("第%03d章" % n) and f.endswith(".md")]
        if not chap_files:
            print("[错误] 缺正文文件：第%d章" % n)
            failed.append(n)
            continue
        with open(os.path.join(proj, "正文", chap_files[0]), encoding="utf-8") as f:
            prose = f.read()
        t0 = time.monotonic()
        rep = canon_audit.audit_chapter(proj, n, prose, cfg, router=_Router())
        lat = round(time.monotonic() - t0, 1)
        v = rep.get("violations") or []
        hard = [x for x in v if x.get("severity") == "硬伤"]
        adopt = rep.get("adoptions") or []
        status = "OK" if not rep.get("failed") else "FAILED"
        print("[ch%02d] %s violations=%d(硬伤%d) adoptions=%d ledger=%d lat=%ss"
              % (n, status, len(v), len(hard), len(adopt),
                 len(rep.get("ledger_updates") or {}), lat), flush=True)
        if rep.get("failed"):
            failed.append(n)
    print("[done] failed=%s" % (failed or "无"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
