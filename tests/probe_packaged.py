# -*- coding: utf-8 -*-
"""打包版验证探针（封装计划 T1.3 + v0.15.0 一致性门禁）

四道门禁，缺一不可：
1. **Qt 运行模块在位**：Main.qml 加载链缺一个模块就是白屏，且报错散在日志里不好查。
2. **资源清单双向审计**：开发树每个资源文件（.qml / 预设 json / assets）都要在
   `dist/…/_internal/` 有同名同 sha256 的孪生，反向也不能多出计划外的资源。
   —— 不依赖程序能不能跑起来，报的是「哪个文件没了」。
3. **启动冒烟**：60s 内出现主窗口 → 存活 5s → 无崩溃（原 T1.3 门禁）。
4. **打包态摘要对拍**：`exe --selftest` 与 `python -m app.selftest` 各产一份摘要后逐字段比对。
   这才是「打包后的程序实现原程序所有效果」的正面证据——模块导不进来、装配字节变了、
   QML 对象没建出来，都会在这里现形。

用法：python tests/probe_packaged.py --exe dist/QianBi-Novel/QianBi-Novel.exe
门禁：build_release.py 在发版流水线中调用；--skip-qml 仅供调试（对拍跳过 qml 段）
"""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

TITLE = "千笔一文 Novel"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 与 app/selftest._MANIFEST_SPECS 同构：(相对目录, 允许的扩展名 / None=全部)
AUDIT_SPECS = [("app/ui/qml", (".qml", "")), ("app/presets", (".json",)), ("assets", None)]

# Qt 运行模块：offscreen（探针用）与 windows（真实运行用）都要在
QT_RUNTIME = [
    "PySide6/qml/QtQuick/Controls/Basic",
    "PySide6/qml/QtQuick/Layouts",
    "PySide6/qml/QtQuick/Templates",
    "PySide6/qml/QtQuick/Window",
    "PySide6/plugins/platforms/qoffscreen.dll",
    "PySide6/plugins/platforms/qwindows.dll",
]


class Gate:
    def __init__(self):
        self.failed = []

    def check(self, name, ok, detail=""):
        print(("[OK ] " if ok else "[FAIL] ") + name
              + (("\n       " + detail.replace("\n", "\n       ")) if detail and not ok else ""),
              flush=True)
        if not ok:
            self.failed.append(name)
        return ok


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _wanted(fn: str, allow) -> bool:
    ext = os.path.splitext(fn)[1].lower()
    if ext in (".pyc", ".pyo"):
        return False
    return allow is None or ext in allow


def list_tree(base: str, allow) -> set:
    """目录下受审计资源的相对路径集合（排除 __pycache__ 与编译产物）"""
    found = set()
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            if _wanted(fn, allow):
                found.add(os.path.relpath(os.path.join(dp, fn), base).replace("\\", "/"))
    return found


def audit_resources(gate: Gate, internal: str) -> int:
    total, missing, changed, extra = 0, [], [], []
    for rel_dir, allow in AUDIT_SPECS:
        sep = rel_dir.replace("/", os.sep)
        base = os.path.join(ROOT, sep)
        dst_base = os.path.join(internal, sep)
        if not os.path.isdir(base):
            gate.check("资源目录存在 " + rel_dir, False, base)
            continue
        dev_files = list_tree(base, allow)
        dist_files = list_tree(dst_base, allow) if os.path.isdir(dst_base) else set()
        total += len(dev_files)
        missing += [f"{rel_dir}/{p}" for p in sorted(dev_files - dist_files)]
        extra += [f"{rel_dir}/{p}" for p in sorted(dist_files - dev_files)]
        for p in sorted(dev_files & dist_files):
            src, dst = os.path.join(base, p.replace("/", os.sep)), \
                os.path.join(dst_base, p.replace("/", os.sep))
            if sha256_file(src) != sha256_file(dst):
                changed.append(f"{rel_dir}/{p}")
    gate.check(f"资源清单双向审计（开发树 {total} 个文件，包内不多不少且逐字节一致）",
               not missing and not changed and not extra,
               "\n".join(filter(None, [
                   "包内缺失: " + ", ".join(missing[:12]) if missing else "",
                   "包内多出: " + ", ".join(extra[:12]) if extra else "",
                   "内容不一致: " + ", ".join(changed[:12]) if changed else ""])))
    return total


def audit_qt_runtime(gate: Gate, internal: str):
    absent = [p for p in QT_RUNTIME
              if not os.path.exists(os.path.join(internal, p.replace("/", os.sep)))]
    gate.check(f"Qt 运行模块在位（{len(QT_RUNTIME)} 项）", not absent,
               "缺失: " + ", ".join(absent))


def find_window() -> int:
    return ctypes.windll.user32.FindWindowW(None, TITLE)


def smoke_boot(gate: Gate, exe: str) -> bool:
    """原 T1.3 冒烟：窗口出现 + 存活 5s"""
    proc = subprocess.Popen([exe], cwd=os.path.dirname(exe))
    try:
        deadline, hwnd = time.time() + 60, 0
        while time.time() < deadline:
            hwnd = find_window()
            if hwnd:
                break
            if proc.poll() is not None:
                return gate.check("主窗口出现", False,
                                  f"进程提前退出（code={proc.returncode}）")
            time.sleep(0.5)
        if not gate.check("主窗口出现", bool(hwnd), "60s 内未出现主窗口"):
            return False
        time.sleep(5)
        return gate.check("启动 5s 内存活无崩溃", proc.poll() is None,
                          f"进程退出（code={proc.poll()}）")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def run_selftest(cmd, out_path: str, env: dict, timeout: int, label: str) -> dict:
    """跑一侧 selftest：结果只靠文件回传（exe 是 console=False，stdout 到不了终端）"""
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError(f"{label} 超时（{timeout}s）未退出")
    body = proc.stdout.read() or ""
    if not os.path.isfile(out_path):
        raise RuntimeError(f"{label} 退出码 {proc.returncode}，未产出摘要文件：{body[:1200]}")
    with open(out_path, encoding="utf-8") as f:
        report = json.load(f)
    if proc.returncode != 0:
        raise RuntimeError(f"{label} 自检返回非零（rc={proc.returncode}）："
                           f"{json.dumps(report, ensure_ascii=False)[:1200]}")
    return report


def diff_keys(a, b, path="", out=None, limit=25) -> list:
    """递归找差异，报路径而不是整块 blob——发版时要一眼看出差在哪一项"""
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path or '<root>'}: 类型 {type(a).__name__} ≠ {type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append(f"{path}.{k}: 仅打包态有".lstrip("."))
            elif k not in b:
                out.append(f"{path}.{k}: 仅开发态有".lstrip("."))
            else:
                diff_keys(a[k], b[k], f"{path}.{k}" if path else k, out, limit)
    elif isinstance(a, list):
        if all(isinstance(x, dict) for x in a) and all(isinstance(x, dict) for x in b):
            key_of = lambda x: x.get("id") or x.get("path")   # noqa: E731
            amap, bmap = {key_of(x): x for x in a}, {key_of(x): x for x in b}
            if len(amap) != len(a) or len(bmap) != len(b):
                out.append(f"{path}: 存在重复 id/path，无法逐项对拍")
            for k in sorted(set(amap) | set(bmap), key=str):
                if k not in amap:
                    out.append(f"{path}[{k}]: 仅打包态有")
                elif k not in bmap:
                    out.append(f"{path}[{k}]: 仅开发态有")
                else:
                    diff_keys(amap[k], bmap[k], f"{path}[{k}]", out, limit)
        else:
            if len(a) != len(b):
                out.append(f"{path}: 条数 {len(a)} ≠ {len(b)}")
            for i, (x, y) in enumerate(zip(a, b)):
                diff_keys(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: {str(a)[:70]} ≠ {str(b)[:70]}")
    return out


def parity(gate: Gate, exe: str, sandbox: str, sections) -> bool:
    env = dict(os.environ, HOME=sandbox, USERPROFILE=sandbox)
    only = ["--only", ",".join(sections)]
    dist_out = os.path.join(sandbox, "dist.json")
    dev_out = os.path.join(sandbox, "dev.json")
    try:
        dist = run_selftest([exe, "--selftest", dist_out] + only, dist_out,
                            env, 240, "打包态")
        dev = run_selftest([sys.executable, "-m", "app.selftest", dev_out] + only,
                           dev_out, env, 180, "开发态")
    except Exception as e:  # noqa: BLE001
        return gate.check("打包态/开发态摘要可比（两侧 selftest 均跑通）", False, str(e))
    lines = diff_keys(dev, dist)
    covered = "/".join(sorted(sections))
    return gate.check(f"打包态 == 开发态（{covered}，{len(dev.get('assembly', []))} 项装配摘要"
                      f"+{len(dev.get('manifest', {}).get('files', []))} 个资源）",
                      not lines, "\n".join(lines[:25]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, help="打包产物 exe 路径")
    ap.add_argument("--skip-qml", action="store_true",
                    help="摘要对拍跳过 qml 段（offscreen 环境异常时调试用）")
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    dist_dir = os.path.dirname(exe)
    internal = os.path.join(dist_dir, "_internal")
    gate = Gate()

    if not os.path.exists(exe):
        print(f"[FAIL] 产物不存在: {exe}")
        return 1
    if not os.path.isdir(internal):
        print(f"[FAIL] 包目录不存在: {internal}（onedir 产物不完整）")
        return 1

    print(f"[.. ] 打包版验证: {exe}")
    audit_qt_runtime(gate, internal)
    audit_resources(gate, internal)

    sections = ["imports", "manifest", "assembly"] + ([] if args.skip_qml else ["qml"])
    sandbox = tempfile.mkdtemp(prefix="qbn_packaged_")
    try:
        if smoke_boot(gate, exe):
            parity(gate, exe, sandbox, sections)
        else:
            print("[SKIP] 冒烟未过，摘要对拍跳过（先修启动）")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    if gate.failed:
        print(f"\nPROBE_DONE FAIL（{len(gate.failed)} 道门禁未过）: " + "; ".join(gate.failed))
        return 1
    print("\nPROBE_DONE PASS 资源清单/启动冒烟/打包态摘要全部与开发态一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
