# -*- coding: utf-8 -*-
"""一键发布流水线（封装计划 T1.2）

步骤：版本 → 质量闸门（可跳过）→ version_info 生成 → PyInstaller onedir
    → 便携 zip → SHA256SUMS → 打包版冒烟探针 → （可选）Inno Setup 安装包

用法：
  python scripts/build_release.py                 # 全流程（含质量闸门与冒烟）
  python scripts/build_release.py --skip-tests    # 跳过质量闸门（仅调试，发版禁用）
  python scripts/build_release.py --no-installer  # 跳过 Inno Setup（未装 ISCC 时自动跳过）
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

VERSION_INFO_TPL = """# UTF-8
# 版本资源（Windows 资源管理器属性页显示），由 build_release.py 生成
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v1}, {v2}, {v3}, 0),
    prodvers=({v1}, {v2}, {v3}, 0),
    mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', 'QianBiNovel'),
        StringStruct('FileDescription', '千笔一文 Novel — AI 网文自动写作台'),
        StringStruct('FileVersion', '{ver}.0'),
        StringStruct('InternalName', 'QianBi-Novel'),
        StringStruct('LegalCopyright', 'MIT License. Copyright (c) 2026 GLFzr'),
        StringStruct('OriginalFilename', 'QianBi-Novel.exe'),
        StringStruct('ProductName', '千笔一文 Novel'),
        StringStruct('ProductVersion', '{ver}.0')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ])
"""


def step(name, ok, detail=""):
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def portable_readme(version: str) -> bytes:
    """便携包内的《使用说明.txt》。

    带 BOM：这个文件会被 Windows 记事本直接打开，无 BOM 的 UTF-8 在旧版
    记事本上中文会乱码。
    """
    text = f"""千笔一文 Novel v{version} —— 便携版使用说明
========================================

怎么运行
--------
把整个文件夹解压到任意位置（路径含中文和空格都可以），双击 QianBi-Novel.exe。
不需要安装 Python，也不需要联网安装任何东西。

重要：便携版不会创建桌面快捷方式
--------------------------------
便携版刻意「什么都不装」：不建桌面快捷方式、不写注册表、不出现在
「设置 → 应用」里，因此也没有卸载入口——不想用了直接把整个文件夹删掉。

需要桌面快捷方式和「应用和功能」里的卸载入口，请改用安装版：
    QianBi-Novel-v{version}-setup.exe
安装版是 per-user 安装（不需要管理员权限），默认会勾选「创建桌面快捷方式」，
卸载时会保留你的书稿。

你的数据在哪里
--------------
两种版本共用同一个数据目录：

    %USERPROFILE%\\.qianbi_novel\\
        config.json     连接与闸门配置
        books\\          你的小说项目（每本书一个文件夹）
        presets\\        自定义题材预设
        logs\\           运行日志与崩溃现场

想备份或迁移，整个目录拷走即可。删掉该目录 = 彻底清除。

API Key 存在哪
--------------
Key 不写进 config.json，而是存入 **Windows 凭据管理器**
（项目名 QianBiNovel/connections）。config.json 里只留一个不可逆指纹。
导出配置或截图提问时，不用担心 Key 泄露；反之，换电脑时 Key 需要重新填。

校验下载完整性
--------------
发布页附有 SHA256SUMS.txt。PowerShell 里执行：

    Get-FileHash .\\QianBi-Novel-v{version}-portable.zip -Algorithm SHA256

输出的哈希应与清单中对应那一行完全一致。

首次运行的 SmartScreen 提示
---------------------------
如果 Windows 弹出「Windows 已保护你的电脑 / 未知发布者」，这是正常的：
本项目是开源免费软件，没有购买代码签名证书，因此二进制未签名。
点「更多信息」→「仍要运行」即可。你也可以先用上面的 SHA256 比对确认来源。

隐私
----
书稿、配置、日志全部留在本机，不上传任何地方。遥测默认关闭且只写本地文件。
详见包内 PRIVACY.md。

License
-------
MIT 开源。详见包内 LICENSE 与 THIRD-PARTY-LICENSES.md。
项目地址：https://github.com/GLFzr/QianBi-Novel
"""
    return text.encode("utf-8-sig")


def main():
    ap = argparse.ArgumentParser(description="千笔一文 Novel 一键发布流水线")
    ap.add_argument("--skip-tests", action="store_true", help="跳过质量闸门（发版禁用）")
    ap.add_argument("--no-installer", action="store_true", help="跳过 Inno Setup 安装包")
    ap.add_argument("--skip-probe", action="store_true", help="跳过打包版冒烟探针")
    ap.add_argument("--skip-qml", action="store_true",
                    help="打包探针跳过 qml 摘要段（调试用；发版禁用）")
    args = ap.parse_args()

    from app import __version__
    print(f"=== 千笔一文 Novel 发布流水线 v{__version__} ===")

    # ---- 1. 工作树检查（发版禁止带未提交改动）----
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                           text=True, cwd=ROOT).stdout.strip()
    step("工作树检查", True, "存在未提交改动（构建继续，发版前须提交）" if dirty else "干净")

    # ---- 2. 质量闸门 ----
    if not args.skip_tests:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/unit", "-q"], cwd=ROOT)
        step("单元测试", r.returncode == 0)
    else:
        print("[WARN] --skip-tests：质量闸门已跳过（发版禁用）")

    # ---- 3. version_info.txt（版本资源，动态生成不入库）----
    parts = __version__.split(".")
    while len(parts) < 3:
        parts.append("0")
    vi = VERSION_INFO_TPL.format(v1=parts[0], v2=parts[1], v3=parts[2], ver=__version__)
    with open("version_info.txt", "w", encoding="utf-8") as f:
        f.write(vi)
    step("version_info.txt", True, f"v{__version__}")

    # ---- 4. PyInstaller onedir ----
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                        "QianBi-Novel.spec"], cwd=ROOT)
    step("PyInstaller onedir", r.returncode == 0)

    dist_dir = os.path.join(ROOT, "dist", "QianBi-Novel")
    exe = os.path.join(dist_dir, "QianBi-Novel.exe")
    step("产物存在", os.path.exists(exe), exe)
    size_mb = sum(os.path.getsize(os.path.join(dp, f)) / 1048576
                  for dp, _, fs in os.walk(dist_dir) for f in fs)
    print(f"       onedir 体积: {size_mb:.0f} MB")

    # ---- 5. 打包版验证（资源清单审计 + 启动冒烟 + 打包态/开发态摘要对拍）----
    if not args.skip_probe:
        cmd = [sys.executable, "tests/probe_packaged.py", "--exe", exe]
        if args.skip_qml:
            cmd.append("--skip-qml")
            print("       [WARN] --skip-qml：摘要对拍跳过 qml 段（发版禁用）")
        r = subprocess.run(cmd, cwd=ROOT)
        step("打包版验证", r.returncode == 0)
    else:
        print("[WARN] --skip-probe：打包冒烟已跳过（发版禁用）")

    # ---- 6. 产物目录 + 便携 zip + SHA256SUMS ----
    out_dir = os.path.join(ROOT, "dist", "release", f"v{__version__}")
    os.makedirs(out_dir, exist_ok=True)
    readme_name = "使用说明.txt"
    readme_bytes = portable_readme(__version__)
    readme_path = os.path.join(out_dir, readme_name)
    with open(readme_path, "wb") as f:
        f.write(readme_bytes)
    portable = os.path.join(out_dir, f"QianBi-Novel-v{__version__}-portable.zip")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, _, fs in os.walk(dist_dir):
            for f in fs:
                full = os.path.join(dp, f)
                z.write(full, os.path.relpath(full, dist_dir))
        # 说明文件放在 zip 根目录，与 exe 并列，解压第一眼就能看到
        z.writestr(readme_name, readme_bytes)
    step("便携 zip", os.path.exists(portable),
         f"{os.path.getsize(portable) / 1048576:.0f} MB")

    # 附带说明文件进产物目录
    for doc in ("LICENSE", "THIRD-PARTY-LICENSES.md", "docs/PRIVACY.md"):
        src = os.path.join(ROOT, doc)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_dir, os.path.basename(doc)))

    # ---- 7. Inno Setup 安装包（检测 ISCC，未装自动跳过）----
    if not args.no_installer:
        iscc_candidates = [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
        ]
        iscc = next((p for p in iscc_candidates if p and os.path.exists(p)), None)
        if iscc:
            r = subprocess.run([iscc, f"/DAppVersion={__version__}",
                                "tools/installer.iss"], cwd=ROOT)
            step("Inno Setup 安装包", r.returncode == 0)
        else:
            print("[SKIP] 未检测到 Inno Setup 6（安装包跳过；安装后重跑 --no-installer --skip-tests --skip-probe 即可补齐）")
    else:
        print("[SKIP] --no-installer")

    # ---- 8. SHA256SUMS（放在安装包之后，确保 setup.exe 也被收录）----
    sums = os.path.join(out_dir, "SHA256SUMS.txt")
    # newline="\n"：默认文本模式在 Windows 上会写成 CRLF，行尾 \r 会让
    # `sha256sum -c` 把文件名当成 "xxx.exe\r" 而报 no such file
    with open(sums, "w", encoding="utf-8", newline="\n") as f:
        for fn in sorted(os.listdir(out_dir)):
            if fn == "SHA256SUMS.txt":
                continue
            fp = os.path.join(out_dir, fn)
            if os.path.isfile(fp):
                f.write(f"{sha256(fp)}  {fn}\n")
    step("SHA256SUMS", True, sums)

    print(f"=== 完成。产物目录: {out_dir} ===")


if __name__ == "__main__":
    main()
