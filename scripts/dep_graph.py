# -*- coding: utf-8 -*-
"""AST-based module dependency analysis for qianbi-novel app/ package.

Outputs (stdout, utf-8):
  1. module-level dependency list (adjacency)
  2. circular dependencies (Tarjan SCC, size>1 or self-loop)
  3. top15 most-depended-on modules (fan-in)
  4. layering violations (ui->core reverse, core->ui, llm->core/ui, etc.)

Read-only on source: never modifies the code it scans; machine-readable side
file goes to tests_output/ (gitignored).

Usage: ./.venv/Scripts/python.exe scripts/dep_graph.py
"""
import ast
import json
import os
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(REPO, "app")
OUT_DIR = os.path.join(REPO, "tests_output")

# ---------- collect modules ----------
py_files = []
for root, dirs, files in os.walk(APP):
    dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "node_modules")]
    for f in files:
        if f.endswith(".py"):
            py_files.append(os.path.join(root, f))

mod_of_file = {}
file_of_mod = {}
for fp in py_files:
    rel = os.path.relpath(fp, REPO).replace("\\", "/")
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    mod = ".".join(parts)
    mod_of_file[fp] = mod
    file_of_mod[mod] = fp

all_mods = set(mod_of_file.values())

def resolve(node_mod, target):
    """Resolve an import target to an in-app module (module or package)."""
    if target in all_mods:
        return target
    # try as submodule of a package that exists
    parts = target.split(".")
    while parts:
        cand = ".".join(parts)
        if cand in all_mods:
            return cand
        parts.pop()
    return None

# ---------- parse imports ----------
deps = defaultdict(set)          # mod -> set(mod it imports)
dep_edges_detail = defaultdict(list)  # mod -> [(target_raw, lineno)]
relative_level = []              # relative imports beyond top-level (level>=2)

for fp in py_files:
    src_mod = mod_of_file[fp]
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read(), filename=fp)
    except SyntaxError as e:
        print(f"SYNTAX-ERR {fp}: {e}", file=sys.stderr)
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                t = resolve(src_mod, a.name)
                if t and t != src_mod:
                    deps[src_mod].add(t)
                    dep_edges_detail[src_mod].append((a.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level >= 2:
                relative_level.append((src_mod, node.module, node.level, node.lineno))
            base = node.module or ""
            if node.level:  # relative import: anchor at src package
                anchor = src_mod.split(".")
                # level=1 -> current package
                pkg = anchor[: len(anchor) - (node.level - 1) - (0 if src_mod.endswith(("__init__",)) else 0)]
                # simpler: strip (level-1) components from the module's package
                pkg_parts = src_mod.split(".")[:-1]  # package of the file
                for _ in range(node.level - 1):
                    pkg_parts = pkg_parts[:-1]
                base = ".".join(pkg_parts + ([node.module] if node.module else []))
            if not base:
                continue
            t = resolve(src_mod, base)
            if t and t != src_mod:
                deps[src_mod].add(t)
                dep_edges_detail[src_mod].append((f"from {base}", node.lineno))
            # `from pkg import name` where name is itself a submodule -> edge to pkg.name
            for alias in node.names:
                if alias.name == "*":
                    continue
                sub = resolve(src_mod, f"{base}.{alias.name}")
                if sub and sub != src_mod:
                    deps[src_mod].add(sub)
                    dep_edges_detail[src_mod].append((f"from {base} import {alias.name}", node.lineno))

# ---------- layer assignment ----------
def layer_of(mod):
    if mod.startswith("app.ui"):
        return "ui"
    if mod.startswith("app.core"):
        return "core"
    if mod.startswith("app.llm"):
        return "llm"
    if mod.startswith("app.prompts"):
        return "prompts"
    if mod.startswith("app.presets"):
        return "presets"
    if mod.startswith("app.vendor"):
        return "vendor"
    if mod == "app" or mod.startswith("app."):
        return "app-top"   # config, project, update_*, main, export ...
    return "other"

LAYER_ORDER = {"llm": 0, "vendor": 0, "prompts": 0, "presets": 0, "core": 1, "app-top": 2, "ui": 3}

ALLOWED = {
    # from-layer -> set of to-layers allowed (lower or same index, plus a few exceptions)
}
def is_violation(frm, to):
    lf, lt = layer_of(frm), layer_of(to)
    if lf not in LAYER_ORDER or lt not in LAYER_ORDER:
        return None
    # rules:
    if lf == "llm" and lt in ("core", "ui", "app-top"):
        return f"llm-> {lt}"
    if lf == "core" and lt == "ui":
        return "core-> ui (reverse)"
    if lf == "core" and lt == "app-top":
        return "core-> app-top (upward)"
    if lf == "app-top" and lt == "ui":
        return "app-top-> ui (non-main bypasses UI)"
    if lf == "ui" and lt == "llm":
        return "ui-> llm (bypasses core)"
    return None

violations = []
for frm, tos in deps.items():
    for to in sorted(tos):
        v = is_violation(frm, to)
        if v:
            lineno = min((ln for t, ln in dep_edges_detail[frm] if resolve(frm, t) == to), default=0)
            violations.append((frm, to, v, f"{file_of_mod.get(frm,'?')}:{lineno}"))

# ---------- Tarjan SCC ----------
index_counter = [0]
stack, lowlink, index, on_stack = [], {}, {}, {}
sccs = []

def strongconnect(v):
    index[v] = lowlink[v] = index_counter[0]; index_counter[0] += 1
    stack.append(v); on_stack[v] = True
    for w in deps.get(v, ()):
        if w not in index:
            strongconnect(w)
            lowlink[v] = min(lowlink[v], lowlink[w])
        elif on_stack.get(w):
            lowlink[v] = min(lowlink[v], index[w])
    if lowlink[v] == index[v]:
        comp = []
        while True:
            w = stack.pop(); on_stack[w] = False; comp.append(w)
            if w == v:
                break
        sccs.append(comp)

sys.setrecursionlimit(10000)
for v in sorted(all_mods):
    if v not in index:
        strongconnect(v)

cyclic = [sorted(c) for c in sccs if len(c) > 1]
# self loops (a imports b imports a handled by SCC; direct self-import excluded earlier)

# ---------- fan-in ----------
fan_in = defaultdict(set)
fan_out = {m: len(deps.get(m, ())) for m in all_mods}
for frm, tos in deps.items():
    for to in tos:
        fan_in[to].add(frm)
top_fanin = sorted(all_mods, key=lambda m: -len(fan_in.get(m, ())))[:15]
top_fanout = sorted(all_mods, key=lambda m: -fan_out.get(m, ()))[:15]

# ---------- summary (baseline tracking) ----------
core_up = [v for v in violations if v[2] == "core-> app-top (upward)"]

# ---------- output ----------
out = []
out.append("=" * 30 + " 1. DEPENDENCY LIST " + "=" * 30)
for m in sorted(deps):
    if deps[m]:
        out.append(f"{m}  ({len(deps[m])}) -> " + ", ".join(sorted(deps[m])))

out.append("")
out.append("=" * 30 + " 2. CIRCULAR (SCC>1) " + "=" * 30)
if cyclic:
    for c in sorted(cyclic, key=len, reverse=True):
        out.append(f"SCC({len(c)}): " + " <-> ".join(c))
        # show intra edges
        for a in c:
            intra = sorted(deps[a] & set(c))
            if intra:
                out.append(f"    {a} -> {', '.join(intra)}")
else:
    out.append("(none)")

out.append("")
out.append("=" * 30 + " 3. TOP15 FAN-IN " + "=" * 30)
for m in top_fanin:
    out.append(f"{len(fan_in.get(m,())):3d}  {m}  [{layer_of(m)}]")

out.append("")
out.append("---- TOP15 FAN-OUT (for debt analysis) ----")
for m in top_fanout:
    out.append(f"{fan_out[m]:3d}  {m}  [{layer_of(m)}]")

out.append("")
out.append("=" * 30 + " 4. LAYERING VIOLATIONS " + "=" * 30)
if violations:
    for frm, to, v, loc in sorted(violations):
        out.append(f"[{v}]  {frm} -> {to}   @ {loc}")
else:
    out.append("(none)")

out.append("")
out.append("=" * 30 + " 5. MISC " + "=" * 30)
out.append(f"modules total: {len(all_mods)}, files: {len(py_files)}")
out.append(f"relative imports level>=2: {len(relative_level)}")
for m, mod_, lv, ln in relative_level[:20]:
    out.append(f"  {m}:{ln} from {'.'*lv}{mod_ or ''}")
# orphan modules (imported by nobody, not main)
orphans = sorted(m for m in all_mods if not fan_in.get(m) and m not in ("app.main",) and m != "app")
out.append(f"orphans (fan-in=0, excluding app/app.main): {len(orphans)}")
for m in orphans:
    out.append(f"  {m} [{layer_of(m)}]")

out.append("")
out.append("=" * 30 + " 6. BASELINE SUMMARY " + "=" * 30)
out.append(f"SCC count (size>1): {len(cyclic)}")
out.append(f"core->app-top edges: {len(core_up)}")
out.append(f"violations total: {len(violations)}")

print("\n".join(out))

# machine-readable side file for later scripts (gitignored tests_output/)
os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, "dep_graph.json"), "w", encoding="utf-8") as fh:
    json.dump({
        "deps": {k: sorted(v) for k, v in deps.items()},
        "sccs": cyclic,
        "fan_in": {k: sorted(v) for k, v in fan_in.items()},
        "layers": {m: layer_of(m) for m in all_mods},
        "baseline": {
            "scc_count": len(cyclic),
            "core_to_apptop_edges": len(core_up),
            "violations_total": len(violations),
        },
    }, fh, ensure_ascii=False, indent=1)
