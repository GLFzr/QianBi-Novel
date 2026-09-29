# -*- coding: utf-8 -*-
"""Static scan for qianbi-novel:
  1. longest functions top20 (AST, logical statements + real LOC)
  2. TODO/FIXME/HACK/XXX full list
  3. duplicate code blocks (normalized 6-line windows heuristic, cross-module)
  4. suspected dead code (module-level funcs/classes never referenced by name repo-wide;
     NOTE: PySide signal slots / dynamic dispatch cause false positives -> each hit is
     checked for string-reference of its bare name anywhere in repo to reduce noise)

Read-only on source. Outputs to stdout; JSON side-file to tests_output/ (gitignored).

Usage: ./.venv/Scripts/python.exe scripts/static_scan.py
"""
import ast, json, os, re, sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "tests_output")
SCAN_DIRS = ["app", "scripts", "tools", "tests", "run.py", "build_exe.py"]

py_files = []
for d in SCAN_DIRS:
    p = os.path.join(REPO, d)
    if os.path.isfile(p):
        py_files.append(p); continue
    for root, dirs, files in os.walk(p):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", ".venv", "node_modules", "build", "dist")]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

trees = {}
for fp in py_files:
    try:
        with open(fp, encoding="utf-8", errors="replace") as fh:
            trees[fp] = ast.parse(fh.read(), filename=fp)
    except SyntaxError as e:
        print(f"SYNTAX-ERR {fp}: {e}", file=sys.stderr)

out = []

# ---------- 1. longest functions ----------
def qual_name(node, parents):
    return ".".join(parents + [node.name])

func_stats = []
parents_map = {}
for fp, tree in trees.items():
    stack = []
    def walk(node, parents):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stmts = sum(1 for n in ast.walk(child) if isinstance(n, ast.stmt))
                end = getattr(child, "end_lineno", child.lineno)
                loc = end - child.lineno + 1
                func_stats.append((loc, stmts, fp, child.lineno, end, qual_name(child, parents)))
                walk(child, parents + [child.name])
            elif isinstance(child, ast.ClassDef):
                walk(child, parents + [child.name])
            else:
                walk(child, parents)
    walk(tree, [])
func_stats.sort(key=lambda x: -x[0])
out.append("=" * 25 + " 1. LONGEST FUNCTIONS TOP20 (by LOC) " + "=" * 25)
for loc, stmts, fp, ln, end, name in func_stats[:20]:
    out.append(f"{loc:5d} LOC {stmts:5d} stmts  {os.path.relpath(fp, REPO)}:{ln}-{end}  {name}")

# ---------- 2. TODO/FIXME/HACK ----------
out.append("")
out.append("=" * 25 + " 2. TODO/FIXME/HACK/XXX " + "=" * 25)
pat = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.I)
n_marks = 0
for fp in py_files:
    try:
        with open(fp, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        continue
    for i, line in enumerate(lines, 1):
        m = pat.search(line)
        if m:
            n_marks += 1
            out.append(f"{os.path.relpath(fp, REPO)}:{i}: [{m.group(1).upper()}] {line.strip()[:160]}")
out.append(f"TOTAL markers: {n_marks}")

# ---------- 3. duplicate blocks ----------
out.append("")
out.append("=" * 25 + " 3. DUPLICATE CODE BLOCKS (6-line normalized windows) " + "=" * 25)
def normalize_lines(fp):
    with open(fp, encoding="utf-8", errors="replace") as fh:
        raw = fh.readlines()
    norm = []
    for i, l in enumerate(raw, 1):
        s = re.sub(r"#.*", "", l).strip()
        if not s or s.startswith(('"""', "'''")):
            norm.append(None); continue
        s = re.sub(r"'[^']*'", "S", s)
        s = re.sub(r'"[^"]*"', "S", s)
        s = re.sub(r"\b\d+\b", "N", s)
        norm.append((s, i))
    return norm

W = 6
import hashlib
def hashlib_md5(s):
    return hashlib.md5(s.encode("utf-8", "replace")).hexdigest()

hashes = defaultdict(list)
for fp in py_files:
    norm = normalize_lines(fp)
    for j in range(len(norm) - W + 1):
        win = norm[j:j + W]
        if any(x is None for x in win):
            continue
        key = "\n".join(x[0] for x in win)
        joined = key.replace("\n", " ")
        if joined.count("import ") + joined.count("from ") >= 5:
            continue
        hashes[hashlib_md5(key)].append((fp, win[0][1], win[-1][1]))

# group into clusters: same file different location or cross-file
clusters = {h: locs for h, locs in hashes.items() if len(locs) > 1}
# merge overlapping windows per pair (simple: count per file-pair)
pair_counts = defaultdict(int)
pair_example = {}
for h, locs in clusters.items():
    for i in range(len(locs)):
        for j in range(i + 1, len(locs)):
            a, b = locs[i], locs[j]
            ka = (os.path.relpath(a[0], REPO), os.path.relpath(b[0], REPO))
            pair_counts[ka] += 1
            if ka not in pair_example:
                pair_example[ka] = (a, b)

ranked = sorted(pair_counts.items(), key=lambda kv: -kv[1])
out.append(f"duplicate 6-line window pairs: {len(ranked)}; top30 by repetition count:")
for (fa, fb), cnt in ranked[:30]:
    (a, b) = pair_example[(fa, fb)]
    same = "SAME-FILE" if fa == fb else "CROSS-FILE"
    out.append(f"x{cnt:3d} {same}  {fa}:{a[1]}-{a[2]}  <->  {fb}:{b[1]}-{b[2]}")

# ---------- 4. suspected dead code ----------
out.append("")
out.append("=" * 25 + " 4. SUSPECTED DEAD CODE (module-level defs, name-ref filtered) " + "=" * 25)
all_text = {}
for fp in py_files:
    with open(fp, encoding="utf-8", errors="replace") as fh:
        all_text[fp] = fh.read()
# also scan qml + spec + json for name references (signal slots!)
extra_text = []
for extra_root in ["app/ui/qml", "QianBi-Novel.spec"]:
    p = os.path.join(REPO, extra_root)
    if os.path.isfile(p):
        extra_text.append(open(p, encoding="utf-8", errors="replace").read())
    else:
        for root, dirs, files in os.walk(p):
            for f in files:
                fp2 = os.path.join(root, f)
                if f.endswith((".qml", ".js")):
                    extra_text.append(open(fp2, encoding="utf-8", errors="replace").read())
BULK = "\n".join(all_text.values()) + "\n".join(extra_text)

defs = []  # (name, loc, kind, refs)
for fp, tree in trees.items():
    if os.sep + "tests" + os.sep in fp:
        continue
    for node in tree.body:  # module level only
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if name.startswith("__") and name.endswith("__"):
                continue
            refs = len(re.findall(r"\b" + re.escape(name) + r"\b", BULK))
            if name == "main":
                refs -= 1
            kind = "class" if isinstance(node, ast.ClassDef) else "func"
            defs.append((name, f"{os.path.relpath(fp, REPO)}:{node.lineno}", kind, refs))

name_counts = defaultdict(int)
for name, _, _, _ in defs:
    name_counts[name] += 1

dead = [(n, l, k, r) for (n, l, k, r) in defs if r <= 1]
out.append(f"suspected dead (<=1 total textual refs incl. def line): {len(dead)}")
for name, loc, kind, refs in dead:
    amb = " [name-collision: shared by multiple defs - LOW confidence]" if name_counts[name] > 1 else ""
    out.append(f"  {kind:5s} {loc:44s} {name}  textrefs={refs}{amb}")

os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, "static_scan.json"), "w", encoding="utf-8") as fh:
    json.dump({"funcs": func_stats[:60], "dead": defs}, fh, ensure_ascii=False)

print("\n".join(out))
