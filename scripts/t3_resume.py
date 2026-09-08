# -*- coding: utf-8 -*-
"""T3 断点续跑驱动：渠道 503 恢复后自动接跑，单次崩溃不再让整轮夭折。

背景（E1，2026-09-08 00:24）：`t3_long60` 跑到第 10 章时 TokenRhythm 连回三次
`503 SERVICE_BUSY`，`client` 重试耗尽抛 LLMError → cost_bench 崩 → `bench_queue` 把该变体
标 FAIL 后**整个队列就结束了**（队列只有一个变体，"跳过继续"等于没有继续）。
而 503 是瞬时故障，指南 §5.3 本就写着 T3"分 3-4 夜跑"——缺的只是把这层续跑落下来。

做的事：
  1. 找进度：扫 `tests_output/bench/t3*_long60/` 里 prose 章数最多的那个 home，
     从"已完成章数 + 1"续跑（`--seed-home` 已修好标签沿用，旧卷栈能接住）；
  2. 等渠道：每 `--probe-every` 秒打一发 `max_tokens=4` 的小请求，200 才发车；
     累计等不到 `--wait-max` 轮就退出（不通宵空转）；
  3. 守住预算：把所有 t3* home 的用量按 **TIER_PRICE[flash]** 折成上限成本，
     超 `--budget` 就停（DS 口径是上限口径，比实付高约 20%，宁可早停）；
  4. 段段留痕：每段跑完立刻把 usage 复制成 `<变体>.usage.jsonl` 切片、
     把 `正文/` 导出成 `<变体>.chapters/`——**崩溃段没有 metrics 的那次教训**。

用法（脱离终端跑）：
  nohup .venv/Scripts/python.exe scripts/t3_resume.py --chapters 60 --budget 24 \
      > tests_output/bench/t3_resume.log 2>&1 &
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

import httpx

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "tests_output", "bench")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
# 与 cost_bench.TIER_PRICE["flash"] 同口径（$/tok × 汇率折算在 cost_bench 里做；
# 这里只做**上限闸门**，宁可保守）
PRICE = {"hit": 0.007 / 1e6, "miss": 0.22 / 1e6, "out": 0.66 / 1e6}
CNY_PER_USD = 7.2


def log(msg: str) -> None:
    print(time.strftime("%m-%d %H:%M:%S ") + msg, flush=True)


def next_segment_name() -> str:
    """段名按**已存在的段**推，不能按本轮循环序号：驱动会被多次启动，
    序号从 1 重来就会把目标算成已有的种子名，而 cmd_run 对目标 home 先 rmtree ⇒ 整段进度没了。"""
    used = set()
    for h in homes():
        m = re.match(r"t3([a-z]?)_long60$", os.path.basename(h))
        if m and m.group(1):
            used.add(m.group(1))
    for ch in "bcdefghijklmnop":          # 续跑段后缀从 b 起（a 不用，避免与首段混淆）
        if ch not in used:
            return "t3%s_long60" % ch
    raise SystemExit("续跑段名用完了（>16 段），先合并历史段")


def global_last_chapter(home: str) -> int:
    """全局已完成章数——**不能**用本段 prose 数：跨段续跑时本段只写了 10..38 共 29 笔，
    照 29 推算会从第 30 章重跑、把 30-38 章写坏。正文目录里的最大章号才是真值。"""
    body = os.path.join(home, "bench", "种子书", "正文")
    nums = []
    for p in glob.glob(os.path.join(body, "第*.md")):
        m = re.match(r"第(\d+)章", os.path.basename(p))
        if m and os.path.getsize(p) > 600:
            nums.append(int(m.group(1)))
    return max(nums, default=prose_count(home))


def homes():
    """所有 t3*_long60 段 home（首段 t3_long60，续跑段 t3b/t3c…）"""
    return sorted(glob.glob(os.path.join(BENCH, "t3*_long60")))


def prose_count(home: str) -> int:
    p = os.path.join(home, ".qianbi_novel", "usage", "usage.jsonl")
    if not os.path.isfile(p):
        return 0
    n = 0
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                try:
                    if json.loads(ln).get("phase") == "prose":
                        n += 1
                except ValueError:
                    pass
    return n


def spent_cny() -> float:
    tot = 0.0
    for h in homes():
        p = os.path.join(h, ".qianbi_novel", "usage", "usage.jsonl")
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                r = json.loads(ln)
                tot += (r.get("hit", 0) * PRICE["hit"] + r.get("miss", 0) * PRICE["miss"]
                        + r.get("out", 0) * PRICE["out"])
    return tot * CNY_PER_USD


def preserve(name: str) -> None:
    """段落盘：usage 切片 + 正文导出（metrics 由 cost_bench 自己写，缺了就缺了）"""
    home = os.path.join(BENCH, name)
    src = os.path.join(home, ".qianbi_novel", "usage", "usage.jsonl")
    if os.path.isfile(src):
        shutil.copyfile(src, os.path.join(BENCH, name + ".usage.jsonl"))
    body = os.path.join(home, "bench", "种子书", "正文")
    dst = os.path.join(BENCH, name + ".chapters")
    if os.path.isdir(body):
        os.makedirs(dst, exist_ok=True)
        for p in glob.glob(os.path.join(body, "第*.md")):
            m = re.match(r"第(\d+)章[ _]?(.*)\.md", os.path.basename(p))
            if not m:
                continue
            try:
                if len(open(p, encoding="utf-8").read().strip()) < 200:
                    continue
            except OSError:
                continue
            shutil.copyfile(p, os.path.join(dst, "第%03d章_%s.md"
                                            % (int(m.group(1)), m.group(2).strip() or "续写")))
    n = prose_count(home)
    log("  段留痕：%s.usage.jsonl + %s.chapters（prose %d 章｜账面 ¥%.2f｜omen 真实价粗估 ¥%.2f）"
        % (name, name, n, spent_cny(), rough_real_cny()))


def alive(conn, timeout: float = 90.0) -> bool:
    base = conn["base"].rstrip("/")
    headers = {"Authorization": "Bearer %s" % conn["key"], "Content-Type": "application/json"}
    if "opencode" in base:
        # 与 app/llm/client._headers 同口径：缺这个头恒 400 MissingSessionID，
        # 那会被误判成"渠道没活"而白等两小时、放弃整段续跑
        headers["x-session-id"] = "qianbi-bench-t3-probe"
    try:
        r = httpx.post(base + "/chat/completions",
                       headers=headers,
                       json={"model": conn["model"],
                             "messages": [{"role": "user", "content": "只回一个字：好"}],
                             "max_tokens": 4, "stream": False,
                             "thinking": {"type": "disabled"}}, timeout=timeout)
        return r.status_code == 200
    except Exception:                                     # noqa: BLE001 网络栈异常一律算"没活"
        return False


def wait_channel(conn, every: int, attempts: int) -> bool:
    for i in range(1, attempts + 1):
        if alive(conn):
            log("渠道已恢复（第 %d 次探测）" % i)
            return True
        log("渠道仍 5xx/异常，%ds 后重探（%d/%d）" % (every, i, attempts))
        time.sleep(every)
    log("等待超时，退出——不通宵空转")
    return False


def rough_real_cny() -> float:
    """omen 真实价粗估：指南 §4 记 ocgo-omen 缓存读价 $0.04/M ≈ ¥0.29/M，
    长卷里 96% 以上是命中读量 ⇒ 直接按总输入量估。只是**别拿账面价当实付**的提醒数。"""
    tot = 0
    for h in homes():
        p = os.path.join(h, ".qianbi_novel", "usage", "usage.jsonl")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                tot += sum(int(json.loads(ln).get("in") or 0) for ln in f if ln.strip())
    return tot / 1e6 * 0.29


def main() -> None:
    ap = argparse.ArgumentParser(description="T3 断点续跑驱动（渠道 503 恢复后自动接跑）")
    ap.add_argument("--chapters", type=int, default=60)
    ap.add_argument("--preset", default="tests/bench_variants/t1_long20.json")
    ap.add_argument("--conn", default="tr-dsv4f")
    ap.add_argument("--budget", type=float, default=24.0, help="DS 口径上限（≈实付 ¥20）")
    ap.add_argument("--segments", type=int, default=6, help="最多续跑几段")
    ap.add_argument("--probe-every", type=int, default=180)
    ap.add_argument("--wait-max", type=int, default=40, help="每段最多等渠道多少次")
    a = ap.parse_args()

    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from cost_bench import _load_key
    conn, _pro = _load_key(prefer_id=a.conn)
    log("T3 续跑驱动启动：目标 %d 章｜上限成本预算 ¥%.1f｜渠道 %s"
        % (a.chapters, a.budget, conn["model"]))

    stalls = 0
    for seg in range(1, a.segments + 1):
        best = max(homes(), key=global_last_chapter, default="")
        done = global_last_chapter(best) if best else 0
        if done >= a.chapters:
            log("已完成 %d 章，收工" % done)
            return
        if spent_cny() > a.budget:
            log("⛔ 上限成本 ¥%.2f 已越预算 ¥%.1f，停止续跑（已 %d 章）"
                % (spent_cny(), a.budget, done))
            return
        # 段名按已存在的段推（跨多次启动也对）；护栏：目标 home 已存在就停——
        # cmd_run 对目标先 rmtree，撞名等于把已有进度删掉
        name = next_segment_name()
        if os.path.isdir(os.path.join(BENCH, name)) or (best and os.path.basename(best) == name):
            log("⛔ 目标段 %s 已存在（或与种子同名），中止——不能 rmtree 自己的进度" % name)
            return
        if not wait_channel(conn, a.probe_every, a.wait_max):
            return
        cmd = [PY, "scripts/cost_bench.py", "--variant", name,
               "--preset-params", "@" + a.preset, "--chapters", str(a.chapters),
               "--start", str(done + 1), "--user-id", "qianbi-bench-t3",
               "--flash-conn", a.conn, "--no-pro"]
        if best:
            cmd += ["--seed-home", os.path.basename(best)]
        log("段 %d：从第 %d 章续跑 → %s（种子 %s）"
            % (seg, done + 1, name, os.path.basename(best) or "bench_base"))
        t0 = time.time()
        env = dict(os.environ, QIANBI_BENCH_MAX_CHAPTERS=str(max(a.chapters, 40)))
        # 漏设这个 env 会被 cost_bench 静默夹回缺省 40 章、还以 rc=0 收尾
        # （12:13 就这样报过一次"全 60 章跑完"的假胜利）
        with open(os.path.join(BENCH, "%s.resume.log" % name), "a", encoding="utf-8") as lf:
            rc = subprocess.call(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, env=env)
        preserve(name)
        now = global_last_chapter(os.path.join(BENCH, name))
        log("段 %d 结束 rc=%d 用时 %.0fmin｜全局完成 %d 章（段前 %d）"
            % (seg, rc, (time.time() - t0) / 60, now, done))
        if now >= a.chapters:
            log("✅ 全 %d 章跑完" % now)
            return
        if rc == 0:
            log("⚠️ rc=0 但只到 %d/%d 章——**不是跑完**，是提前收尾；查 cost_bench 的停止条件"
                "（章数上限、细纲断供、预算）后再续" % (now, a.chapters))
        # 零推进保护：同一章反复崩（如 omen 的 SSL UNEXPECTED_EOF）时，再重启就是
        # 每轮十几分钟重烧同一章的调用 ⇒ 连续两段没推进就停手，交给人看
        if now <= done:
            stalls += 1
            log("  该段零推进（%d→%d 章），连续 %d 次" % (done, now, stalls))
            if stalls >= 2:
                log("⛔ 连续两段没推进，停止续跑：同一章在反复失败，继续只是重烧钱。"
                    "已完成的 %d 章已留痕在盘上。" % now)
                return
        else:
            stalls = 0


if __name__ == "__main__":
    main()
