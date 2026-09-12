# -*- coding: utf-8 -*-
"""埋雷/去雷工具（W0.5 雷集 v2 框架的落地端）：对 第*.md 草稿按雷集注入已知缺陷

设计（对接 docs/成本测试方案_v2.md 的「埋雷法 v2 规范」）：
- 雷集数据：tests/planted_defects/defects.json（六维明文硬规则，v1 四雷已迁移）；
- --apply：对目录下 第*.md 逐雷按 inject.mode 注入（幂等：已注入则跳过），
  落盘同时写 <目录>/.planted_manifest.json（雷 id → 注入文件/精确增串/被替换原文），
  --strip 据此逆向精确还原；
- --strip：按 manifest 逆向移除（精确字符串匹配），无 pre-state 时尽力移除并警告；
- --seed N：random.Random(seed).shuffle 控制多雷注入顺序，同 seed 产物逐字节可重放；
- --list：列出雷集与六维分布（不开 API、不碰草稿）。

用法：
  python scripts/plant_defects.py --list
  python scripts/plant_defects.py --drafts <目录> --defects A01,C01 --apply
  python scripts/plant_defects.py --drafts <目录> --defects A01,C01 --strip
  python scripts/plant_defects.py --drafts <目录> --apply --seed 7

退出码：0=成功（含跳过）；1=有雷未埋上/未去净等操作失败；2=用法/IO 错误。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import re
import sys

if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.planted_defects import DIMS, DefectSchemaError, coverage_report, load_defects  # noqa: E402

MANIFEST_NAME = ".planted_manifest.json"
MANIFEST_VERSION = 1


# ---------- 定位与清单 ----------

def _draft_files(drafts_dir):
    """目录下所有 第*.md 草稿（排序保证确定性）。"""
    files = sorted(glob.glob(os.path.join(drafts_dir, "第*.md")))
    return [f for f in files if os.path.isfile(f)]


def _manifest_path(drafts_dir):
    return os.path.join(drafts_dir, MANIFEST_NAME)


def _load_manifest(drafts_dir):
    p = _manifest_path(drafts_dir)
    if not os.path.isfile(p):
        return {"version": MANIFEST_VERSION, "seed": None, "files": {}, "planted": []}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(drafts_dir, manifest):
    """manifest 为空（无 planted 无 files）时删除文件，否则原子写回。"""
    p = _manifest_path(drafts_dir)
    if not manifest["planted"] and not manifest["files"]:
        if os.path.isfile(p):
            os.remove(p)
        return
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def _read(path):
    # newline=""：不换行翻译，保证逐字节 round-trip
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---------- 注入（四种 mode，增串/被替换原文都精确记录，strip 逐字节可逆） ----------

def _nl(content):
    """探测文件换行风格（v1 bench 草稿是 CRLF，测试草稿是 LF）。"""
    return "\r\n" if "\r\n" in content else "\n"


def _inject_after_title(content, text):
    """标题行后插入 text 段；返回 (新内容, 增串)。无标题行抛 ValueError。"""
    m = re.match(r"[^\r\n]*(\r?\n)+", content)
    if not m:
        raise ValueError("文件无标题行（首行应为止）")
    head = m.group(0)  # 标题行 + 紧随的换行（含 CRLF 两个字符）
    nl = _nl(content)
    added = text + nl * 2
    return head + added + content[m.end():], added


def _inject_before_end(content, text):
    """末段之前插入 text 段；返回 (新内容, 增串)。单段文回退为文末追加。"""
    nl = _nl(content)
    sep = nl * 2
    stripped = content.rstrip("\r\n")
    trailing = content[len(stripped):]
    idx = stripped.rfind(sep)
    if idx == -1:
        return _inject_at_end(content, text)
    added = sep + text
    new = stripped[:idx] + added + sep + stripped[idx + len(sep):] + trailing
    return new, added


def _inject_at_end(content, text):
    """文末追加 text 段；返回 (新内容, 增串)。"""
    nl = _nl(content)
    base = content.rstrip("\r\n")
    trailing = content[len(base):]
    added = nl * 2 + text
    return base + added + trailing, added


def _inject_replace_regex(content, pattern, text):
    """按 anchor 正则替换一次；返回 (新内容, 注入串, 被替换原文)。

    未命中抛 ValueError（由调用方计为该雷失败）。
    """
    if not re.findall(pattern, content):
        raise ValueError("anchor 未命中")
    replaced = re.search(pattern, content).group(0)
    return content.replace(replaced, text, 1), text, replaced


_INJECTORS = {
    "after_title": _inject_after_title,
    "before_end": _inject_before_end,
    "at_end": _inject_at_end,
}


def apply_defect(content: str, defect: dict):
    """对单章内容字符串注入单颗雷（内存版：不落盘、不动 manifest）。

    返回 (新内容, 注入串, 被替换原文或 None)。replace_regex 锚点未命中抛
    ValueError——召回量具把植入失败计为该雷失败（量具的量具失灵必须可见，
    不许静默跳过）。
    """
    inj = defect["inject"]
    mode, text = inj["mode"], inj["text"]
    if mode == "replace_regex":
        new, added, replaced = _inject_replace_regex(content, inj["anchor"], text)
        return new, added, replaced
    new, added = _INJECTORS[mode](content, text)
    return new, added, None


# ---------- --apply ----------

def cmd_apply(drafts_dir, defects, seed, all_ids):
    if not os.path.isdir(drafts_dir):
        print("[错误] 草稿目录不存在：%s" % drafts_dir)
        return 2
    files = _draft_files(drafts_dir)
    if not files:
        print("[错误] 目录下没有 第*.md 草稿：%s" % drafts_dir)
        return 2
    order = list(defects)
    random.Random(seed).shuffle(order)  # 同 seed 同顺序：多雷注入顺序可重放
    manifest = _load_manifest(drafts_dir)
    planted_names = {(e["id"], e["file"]) for e in manifest["planted"]}
    errors = 0
    for d_id in order:
        defect = all_ids[d_id]
        inj = defect["inject"]
        mode, text, anchor = inj["mode"], inj["text"], inj["anchor"]
        hits = 0
        for path in files:
            name = os.path.basename(path)
            if (d_id, name) in planted_names:
                print("[skip] %s 已记录于 manifest（%s × %s）" % (d_id, name, mode))
                hits += 1
                continue
            content = _read(path)
            if text in content:
                print("[skip] %s 已注入于 %s（幂等跳过）" % (d_id, name))
                hits += 1
                continue
            entry = {"id": d_id, "file": name, "mode": mode, "text": text, "added": None,
                     "replaced": None}
            try:
                if mode == "replace_regex":
                    new, added, replaced = _inject_replace_regex(content, anchor, text)
                    entry["replaced"] = replaced
                else:
                    new, added = _INJECTORS[mode](content, text)
            except ValueError as e:
                # 单文件未命中只是警告（如 A01 锚点只存在于第 2 章）；整雷 0 落点才算失败
                print("[warn] %s 在 %s 上未埋上：%s" % (d_id, name, e))
                continue
            # pre-state：该文件在本轮/历史 manifest 中首次被动前，记录原文与哈希
            if name not in manifest["files"]:
                manifest["files"][name] = {
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "content_before": content,
                }
            _write(path, new)
            entry["added"] = added
            manifest["planted"].append(entry)
            print("[apply] %s -> %s（%s，%d 字）" % (d_id, name, mode, len(text)))
            hits += 1
        if hits == 0:
            print("[错误] 雷 %s 没有落到任何草稿上" % d_id)
            errors += 1
    manifest["seed"] = seed
    _save_manifest(drafts_dir, manifest)
    print("[done] apply：雷 %d 颗 × 文件 %d 个，manifest=%s"
          % (len(order), len(files), _manifest_path(drafts_dir)))
    return 1 if errors else 0


# ---------- --strip ----------

def cmd_strip(drafts_dir, wanted_ids):
    if not os.path.isdir(drafts_dir):
        print("[错误] 草稿目录不存在：%s" % drafts_dir)
        return 2
    manifest = _load_manifest(drafts_dir)
    has_manifest = bool(manifest["planted"] or manifest["files"])
    if not has_manifest and not wanted_ids:
        print("[警告] 无 %s，且未指定 --defects：无雷可去" % MANIFEST_NAME)
        return 1
    errors = 0
    remaining = []
    touched = {}  # file -> [entries kept/removed]，按文件聚合
    for entry in manifest["planted"]:
        if wanted_ids and entry["id"] not in wanted_ids:
            remaining.append(entry)
            continue
        touched.setdefault(entry["file"], []).append(entry)
    # 逆向移除：从当前内容里精确删除当初的增串/回填被替换原文
    stripped_files = {}
    for name, entries in touched.items():
        path = os.path.join(drafts_dir, name)
        if not os.path.isfile(path):
            print("[警告] 文件已不在，跳过：%s" % path)
            errors += 1
            continue
        content = _read(path)
        for entry in entries:
            text, added, replaced = entry["text"], entry["added"], entry["replaced"]
            probe = added if added is not None else text
            if entry["mode"] == "replace_regex" and replaced is not None:
                if text in content:
                    content = content.replace(text, replaced, 1)
                    print("[strip] %s <- %s（replace_regex 回填原文 %d 字）"
                          % (name, entry["id"], len(replaced)))
                    continue
                print("[miss] %s 的注入串不在 %s（可能已去雷/被改动）" % (entry["id"], name))
                errors += 1
                continue
            if probe and probe in content:
                content = content.replace(probe, "", 1)
                print("[strip] %s <- %s（%s，删除增串 %d 字）"
                      % (name, entry["id"], entry["mode"], len(probe)))
                stripped_files.setdefault(name, []).append(entry["id"])
            else:
                print("[miss] %s 的增串不在 %s（可能已去雷/被改动）" % (entry["id"], name))
                errors += 1
        _write(path, content)
    # 还原校验：文件上所有雷都去净时，与 pre-state 逐字节比对
    kept_by_file = {}
    for e in remaining:
        kept_by_file.setdefault(e["file"], []).append(e["id"])
    for name in stripped_files:
        pre = manifest["files"].get(name)
        if not pre:
            print("[警告] %s 无 pre-state 记录，已尽力移除、无法做逐字节校验" % name)
            continue
        if kept_by_file.get(name):
            print("[info] %s 尚有雷未去（%s），保留 pre-state"
                  % (name, ", ".join(sorted(kept_by_file[name]))))
            continue
        now = _read(os.path.join(drafts_dir, name))
        sha = hashlib.sha256(now.encode("utf-8")).hexdigest()
        if sha == pre["sha256"]:
            print("[ok] %s 还原后与注入前逐字节一致" % name)
            manifest["files"].pop(name, None)
        else:
            print("[警告] %s 还原后与注入前不一致（文件在埋雷后被外部改动过）；"
                  "pre-state 已保留在 manifest，可人工比对 content_before" % name)
            errors += 1
    manifest["planted"] = remaining
    _save_manifest(drafts_dir, manifest)
    print("[done] strip：去雷 %d 条，manifest=%s"
          % (sum(len(v) for v in touched.values()),
             _manifest_path(drafts_dir) if (manifest["planted"] or manifest["files"]) else "（已清空删除）"))
    return 1 if errors else 0


# ---------- --list ----------

def cmd_list():
    data = load_defects()
    report = coverage_report(data)
    rot = data.get("rotation", {})
    print("雷集 v2（version=%s）：%d 颗 ｜ 轮换政策：%s（history %d 条）"
          % (data.get("version"), report["total"], rot.get("policy", "-"), len(rot.get("history", []))))
    print("双人核验进度：%d/%d ｜ legacy_v1 迁移：%d 颗"
          % (report["verified"], report["total"], report["legacy_v1"]))
    print("六维分布：" + "  ".join("%s=%d" % (k, v) for k, v in report["per_dim"].items()))
    if report["missing"]:
        print("[警告] 覆盖缺口：" + ", ".join("%s=%d" % (k, v) for k, v in report["missing"].items()))
    print("-" * 72)
    for d in data["defects"]:
        legacy = "[legacy_v1] " if d.get("legacy_v1") else ""
        verified = " 已核验×%d" % len(d["verified_by"]) if d["verified_by"] else ""
        print("%s %s%s ｜ %s ｜ %s%s" % (d["id"], legacy, d["dim"], d["inject"]["mode"], d["desc"], verified))
        print("      规则：%s" % d["rule_ref"])
    return 0


# ---------- CLI ----------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="雷集 v2 埋雷/去雷工具（第*.md 草稿注入已知缺陷，manifest 逆向还原）")
    ap.add_argument("--drafts", help="草稿目录（含 第*.md）")
    ap.add_argument("--defects", default="",
                    help="逗号分隔的雷 id（如 A01,C01）；缺省=全部")
    ap.add_argument("--apply", action="store_true", help="注入（幂等）")
    ap.add_argument("--strip", action="store_true", help="按 manifest 逆向去雷")
    ap.add_argument("--list", action="store_true", help="列出雷集与六维分布")
    ap.add_argument("--seed", type=int, default=0, help="多雷注入顺序随机种子（可重放）")
    args = ap.parse_args(argv)

    if args.list and not (args.apply or args.strip):
        return cmd_list()
    if not args.drafts or (args.apply == args.strip):
        ap.error("需要 --drafts <目录>，且 --apply / --strip 二选一（--list 可单用）")
        return 2
    try:
        data = load_defects()
    except DefectSchemaError as e:
        print("[错误] 雷集 schema 校验失败：%s" % e)
        return 2
    all_ids = {d["id"]: d for d in data["defects"]}
    wanted = [s.strip() for s in args.defects.split(",") if s.strip()] if args.defects else list(all_ids)
    bad = [i for i in wanted if i not in all_ids]
    if bad:
        print("[错误] 未知雷 id：%s（可用：%s）" % (", ".join(bad), ", ".join(sorted(all_ids))))
        return 2
    if args.apply:
        return cmd_apply(args.drafts, wanted, args.seed, all_ids)
    return cmd_strip(args.drafts, set(wanted))


if __name__ == "__main__":
    sys.exit(main())
