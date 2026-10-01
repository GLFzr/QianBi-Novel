# -*- coding: utf-8 -*-
"""一键发布流水线（封装计划 T1.2）

步骤：版本 → 质量闸门（可跳过）→ version_info 生成（Windows）→ PyInstaller onedir
    → 打包版冒烟探针 → 代码签名（配了证书才做）→ 便携 zip → SHA256SUMS
    → （可选）安装包 + 签名 → latest.json 回填与 Ed25519 签名

平台分支（Windows / macOS）：
  Windows：安装包 = Inno Setup 的 setup.exe，资产进 assets.setup；
  macOS  ：安装包 = hdiutil 出的 .dmg，资产进 assets.dmg（客户端 asset_kind() 在
           darwin 上认的就是 dmg），便携包 = 压缩 .app 的 macos.zip；
           version_info / signtool / Inno 三步在 mac 上不存在，跳过而不是硬跑。

签名：设 QIANBI_SIGN_PFX（+ QIANBI_SIGN_PASS / QIANBI_SIGN_SUBJECT）或
      QIANBI_SIGN_SHA1，并确保能找到一个 signtool.exe；没配就照旧产出未签名包。

用法：
  python scripts/build_release.py                 # 全流程（含质量闸门与冒烟）
  python scripts/build_release.py --skip-tests    # 跳过质量闸门（仅调试，发版禁用）
  python scripts/build_release.py --no-installer  # 跳过 Inno Setup（未装 ISCC 时自动跳过）
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

# PRIVACY.md 在仓库的 docs/ 下（与 out_dir 的拷贝清单同源）；zip 内落根目录
PORTABLE_DOCS = ("LICENSE", "THIRD-PARTY-LICENSES.md", "docs/PRIVACY.md")

IS_MAC = sys.platform == "darwin"


def write_portable_zip(zip_path: str, dist_dir: str, readme_name: str,
                       readme_bytes: bytes, root: str = None,
                       arc_prefix: str = "") -> str:
    """便携 zip 装配（N-21 门禁版）。

    《使用说明》承诺「详见包内」的三份文档必须打进包里：直接从 ROOT（源码库）
    读取打包——旧实现读 out_dir 里的拷贝，而拷贝发生在打包之后 ⇒ 新版本首构建
    /干净机必然不存在 ⇒ os.path.exists 假 ⇒ 静默少打三份，MIT 分发落空。
    现在缺任何一份即抛错中止，不许静默出包。"""
    root = root or ROOT

    def _arc(rel: str) -> str:
        rel = rel.replace(os.sep, "/")
        return f"{arc_prefix}/{rel}" if arc_prefix else rel

    # N-21 门禁前置：三份承诺文档在**开包之前**逐一校验，缺任何一份即抛错中止。
    # 旧实现在 with ZipFile(...,"w") 之后才校验 ⇒ 缺文档时 zip 已被创建、dist 已写入，
    # 盘上留下一个"看似完整实则缺 MIT 三文档"的半成品孤儿——门禁必须 fail-fast、零产物。
    for doc in PORTABLE_DOCS:
        if not os.path.exists(os.path.join(root, doc)):
            raise FileNotFoundError(
                f"N-21 门禁：便携包承诺文档缺失 {doc}（拒绝静默出包）")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, dns, fs in os.walk(dist_dir):
            # 符号链接（macOS 的 .app 里 Python.framework 靠 Versions/Current 这类
            # 链接搭结构）：os.walk 不跟进 ⇒ 链接目录一条文件都没有、整个被漏掉，
            # 链接文件被 z.write 解引用成一份拷贝。两种都是解包后开不了机，
            # 所以按 symlink 条目原样写（Unix 属性位），解包后还是链接。
            for d in list(dns):
                full = os.path.join(dp, d)
                if os.path.islink(full):
                    _write_symlink(z, full, _arc(os.path.relpath(full, dist_dir)))
                    dns.remove(d)
            for f in fs:
                full = os.path.join(dp, f)
                if os.path.islink(full):
                    _write_symlink(z, full, _arc(os.path.relpath(full, dist_dir)))
                else:
                    z.write(full, _arc(os.path.relpath(full, dist_dir)))
        # 说明与三份承诺文档放包根（与 .app 并列），不塞进前缀里
        z.writestr(readme_name, readme_bytes)
        for doc in PORTABLE_DOCS:
            z.write(os.path.join(root, doc), os.path.basename(doc))
    return zip_path


def _write_symlink(z, full: str, arcname: str):
    """把符号链接写成 zip 的 symlink 条目（create_system=3/Unix，S_IFLNK 权限位）。

    不解引用、不丢条目：解包方按属性位还原成链接，.app 的框架结构才还在。
    """
    zi = zipfile.ZipInfo(arcname.replace(os.sep, "/"))
    zi.create_system = 3
    zi.external_attr = (0o120777 << 16)
    zi.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(zi, os.readlink(full))


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


def find_signtool() -> str:
    """signtool.exe：PATH 优先，其次 Windows 10/11 SDK 的 bin\\x64（取版本号最大的）"""
    found = shutil.which("signtool")
    if found:
        return found
    import glob
    kits = [os.path.join(os.environ.get(k, ""), "Windows Kits", "10", "bin")
            for k in ("ProgramFiles(x86)", "ProgramFiles")]
    cands = []
    for root in kits:
        if root and os.path.isdir(root):
            cands += glob.glob(os.path.join(root, "*", "x64", "signtool.exe"))
            cands += glob.glob(os.path.join(root, "x64", "signtool.exe"))
    return max(cands, key=os.path.dirname) if cands else ""


def signing_plan():
    """返回 (cert 或 None, 没配证书时的人话原因)

    证书只从环境变量读，绝不写进仓库或 latest.json。pfx 口令走 signtool 的 argv，
    意味着签名那几秒本机其它进程能在进程列表里看到它——自己机器上构建可以接受，
    共享 CI runner 上要用 QIANBI_SIGN_SHA1（证书已装进存储）绕开这个暴露。
    """
    sha1 = (os.environ.get("QIANBI_SIGN_SHA1") or "").strip()
    if sha1:
        return {"sha1": sha1, "subject": ""}, ""
    pfx = (os.environ.get("QIANBI_SIGN_PFX") or "").strip()
    if not pfx:
        return None, "未配置签名证书（QIANBI_SIGN_PFX / QIANBI_SIGN_SHA1），产物不签名"
    if not os.path.exists(pfx):
        return None, "QIANBI_SIGN_PFX 指向的文件不存在：%s" % pfx
    return ({"pfx": pfx,
             "pass": os.environ.get("QIANBI_SIGN_PASS") or "",
             "subject": (os.environ.get("QIANBI_SIGN_SUBJECT") or "").strip()}), ""


def sign(path: str, cert: dict, signtool: str):
    """签一个文件。时间戳必须带：证书到期后无戳签名会一起失效。"""
    cmd = [signtool, "sign", "/fd", "SHA256",
           "/tr", "http://timestamp.digicert.com", "/td", "SHA256", "/sm"]
    if cert.get("sha1"):
        cmd += ["/sha1", cert["sha1"]]
    elif cert.get("subject"):
        cmd += ["/n", cert["subject"]]
    else:
        cmd += ["/f", cert["pfx"]]
        if cert.get("pass"):
            cmd += ["/p", cert["pass"]]
    cmd.append(path)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0, ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]


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
程序与数据分开，两种版本共用同一套数据位置：

    %USERPROFILE%\\.qianbi_novel\\
        config.json     连接与闸门配置
        presets\\        自定义题材预设
        logs\\           运行日志与崩溃现场
    %USERPROFILE%\\Documents\\千笔一文\\
        <书名>\\          你的小说项目（每本书一个文件夹，
                         新建时可在「保存位置」改到别处）

想备份或迁移，上面两个目录都要拷走——只拷 .qianbi_novel 会丢掉全部书稿。
删掉这两个目录 = 彻底清除；程序目录里没有你的稿子。

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


def portable_readme_mac(version: str) -> bytes:
    """macOS 包内的《使用说明.txt》。

    与 Windows 版的区别都是真事：Mac 上没有 exe/安装器/SmartScreen，
    Key 进的是钥匙串，升级换的是 .app，把 Windows 那份原样塞进去等于骗人。
    """
    text = f"""千笔一文 Novel v{version} —— macOS 使用说明
========================================

怎么运行
--------
双击 QianBi-Novel.app。要长期使用就把它拖进「应用程序」文件夹。
不需要安装 Python，也不需要联网安装任何东西。

第一次打开被系统拦下怎么办
--------------------------
没有 Apple 开发者签名证书，Gatekeeper 会提示「无法打开，因为无法验证开发者」。
在 Finder 里右键点 QianBi-Novel.app →「打开」→ 再点一次「打开」即可（一次性），
之后双击正常启动。也可以用命令行放行：

    xattr -dr com.apple.quarantine /Applications/QianBi-Novel.app

你的数据在哪里
--------------
程序与数据分开，两种版本共用同一套数据位置：

    ~/.qianbi_novel/
        config.json     连接与闸门配置
        presets/        自定义题材预设
        logs/           运行日志与崩溃现场
    ~/Documents/千笔一文/
        <书名>/          你的小说项目（每本书一个文件夹，
                         新建时可在「保存位置」改到别处）

想备份或迁移，上面两个目录都要拷走——只拷 .qianbi_novel 会丢掉全部书稿。
删掉这两个目录 = 彻底清除；程序目录里没有你的稿子。

API Key 存在哪
--------------
Key 不写进 config.json，而是存入 **macOS 钥匙串**
（条目在「登录」钥匙串，账户为 QianBiNovel）。config.json 里只留一个不可逆指纹。
导出配置或截图提问时，不用担心 Key 泄露；反之，换电脑时 Key 需要重新填。

校验下载完整性
--------------
发布页附有 SHA256SUMS.txt。终端里执行：

    shasum -a 256 QianBi-Novel-v{version}-macos.zip

输出的哈希应与清单中对应那一行完全一致。

隐私
----
书稿、配置、日志全部留在本机，不上传任何地方。遥测默认关闭且只写本地文件。
详见包内 PRIVACY.md。

License
-------
MIT 开源。详见包内 LICENSE 与 THIRD-PARTY-LICENSES.md。
项目地址：https://github.com/GLFzr/QianBi-Novel
"""
    return text.encode("utf-8")


def build_dmg(app_bundle: str, out_dmg: str, version: str):
    """hdiutil 出 .dmg（唯一不依赖第三方工具的 macOS 安装包做法）。

    staging 用 copytree(symlinks=True) 拷整个 .app：.app 里的 Python.framework
    靠相对符号链接搭起来，跟着拷才能保持结构；改用软链到 dist 的临时目录再装盘，
    装出来的镜像会指向构建机的 /private/tmp 路径——本机能开、别人拿到是坏的。
    """
    staging = out_dmg + ".staging"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    try:
        shutil.copytree(app_bundle, os.path.join(staging, os.path.basename(app_bundle)),
                        symlinks=True)
        for doc in PORTABLE_DOCS:
            src = os.path.join(ROOT, doc)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(staging, os.path.basename(doc)))
        with open(os.path.join(staging, "使用说明.txt"), "wb") as f:
            f.write(portable_readme_mac(version))
        if os.path.exists(out_dmg):
            os.remove(out_dmg)
        r = subprocess.run(
            ["hdiutil", "create", "-volname", f"千笔一文 Novel v{version}",
             "-srcfolder", staging, "-ov", "-format", "UDZO", out_dmg],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok = r.returncode == 0 and os.path.exists(out_dmg)
        detail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]
        return ok, (detail if not ok else "")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def sign_mac(path: str, identity: str):
    """codesign：Developer ID 身份 + 公证时间戳（--timestamp 需要联网）。

    没有证书就别调用——无身份的 codesign 用的是本机自签，装到别人机器上
    Gatekeeper 照样拦，签了等于没签还多骗自己一次。
    """
    cmd = ["codesign", "--force", "--deep", "--options", "runtime",
           "--timestamp", "-s", identity, path]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        return False, ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]
    v = subprocess.run(["codesign", "--verify", "--deep", "--strict", path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return v.returncode == 0, ((v.stderr or v.stdout or "").strip().splitlines() or [""])[-1]


def build_manifest_entry(data: dict, *, version: str, base: str, kind: str,
                         installer_path: str, portable: str) -> dict:
    """把本次产物写进版本清单（返回更新后的 dict，不落盘、不签名）。

    一条规则两面，都要机器钉住（tests/unit/test_platform_assets.py）：
    - 只改本次产出的两项，**其余平台的 assets 原样保留**——一份 latest.json 服务所有
      平台，Windows/macOS 是两次流水线，整个 dict 重建会把后跑那次之前那侧的包抹掉；
    - 顶层 sha256 只代表「老客户端会拿它去校验的那个文件」：Windows 构建 = setup.exe，
      macOS 构建没有 setup 时不写这个键，绝不拿 dmg 的哈希冒充 setup 的。
    """
    prev_assets = data.get("assets")
    assets = dict(prev_assets) if isinstance(prev_assets, dict) else {}
    assets[kind] = {
        "name": os.path.basename(installer_path),
        "url": base + "download/v%s/%s" % (version, os.path.basename(installer_path)),
        "sha256": sha256(installer_path), "size": os.path.getsize(installer_path),
    }
    assets["portable"] = {
        "name": os.path.basename(portable),
        "url": base + "download/v%s/%s" % (version, os.path.basename(portable)),
        "sha256": sha256(portable), "size": os.path.getsize(portable),
    }
    legacy_sha = ((prev_assets or {}).get("setup") or {}).get("sha256") \
        if isinstance(prev_assets, dict) else None
    if kind == "setup":
        legacy_sha = sha256(installer_path)
    entry = {
        "version": version,
        "url": base + "tag/v%s" % version,      # 老客户端点「前往下载」用它
        "published": datetime.date.today().isoformat(),
        "assets": assets,
    }
    if legacy_sha:
        entry["sha256"] = legacy_sha
    out = dict(data)
    out.update(entry)
    return out


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

    # ---- 2.5 不可跳过的六道闸门 ----
    # 这几条原先只写在 docs/release_checklist.md 里靠人记得跑，等于没有闸门：
    # 一次静默的 prompt 断链、一个写错的 QML 属性或共享层漂移，照样能一路打完安装包。
    # 私钥泄漏扫描、更新链路与连接删除探针也放进来，是因为它们的坏法一样静默——
    # 前者把「给所有用户推任意 exe」的能力推上公开仓库，第二条坏在用户升级那天，
    # 第三条坏的时候少掉的是用户的 Key 与他亲手建的连接。
    # 刻意不受 --skip-tests / --skip-probe 管辖。
    r = subprocess.run([sys.executable, "tests/probe_prompt_baseline.py"], cwd=ROOT)
    step("提示词装配基线", r.returncode == 0,
         "漂移或接线断裂（确认是预期变更后 --update-baseline 重刷）" if r.returncode else "零漂移")

    r = subprocess.run([sys.executable, "tests/probe_qml_compile.py"], cwd=ROOT)
    step("QML 静态编译", r.returncode == 0,
         "有组件编译失败（整棵树会加载不出来，界面白屏/双击无反应）"
         if r.returncode else "全部组件可编译")

    r = subprocess.run([sys.executable, "tools/audit_tokens.py"], cwd=ROOT)
    step("视觉 token 审计", r.returncode == 0,
         "有裸字号/锚点 footer/裸 hex/无描边卡片回潮（见上方 [T*] 清单）"
         if r.returncode else "零违例")

    # 私钥跟着公开仓库推出去 = 把「给所有用户推任意 exe」的能力公开。
    # 这种事不能靠人记得查，必须挡在打包之前。
    r = subprocess.run([sys.executable, "scripts/update_keys.py", "--check-repo"], cwd=ROOT)
    step("私钥泄漏扫描", r.returncode == 0,
         "被跟踪的文件里出现了私钥材料：立刻从历史清除并轮换密钥" if r.returncode else "仓库内无私钥")

    # 更新面板是「升级那天才用得上」的代码，平时没人点，最容易烂在包里
    r = subprocess.run([sys.executable, "tests/probe_update_ui.py"], cwd=ROOT)
    step("更新链路探针", r.returncode == 0,
         "通道/验签/一键安装的接线断了（用户会卡在升级那天）"
         if r.returncode else "46 项全过（零真网络）")

    # 删连接现在会连带销毁凭据管理器里的 Key（不可恢复），退役出厂行的删除护栏同理：
    # 这类逻辑坏掉的症状是「我的 Key / 我的连接不见了」，必须挡在打包之前。
    r = subprocess.run([sys.executable, "tests/probe_conn_delete.py"], cwd=ROOT)
    step("连接删除探针", r.returncode == 0,
         "两步确认 / Key 随连接销毁 / 退役预设护栏有断裂" if r.returncode
         else "20 项全过（凭据走进程内沙箱）")

    # L1-17（§9-Q2 裁决）：TUI 已彻底删除，「共享层同源」闸门随之退役
    # （该闸门对 rc=2 只 WARN 跳过，事实上已不存在）——发布闸门七道改六道。

    # ---- 3. version_info.txt（版本资源，动态生成不入库）----
    # 只有 Windows 的 PE 资源表认它；macOS 的版本信息在 .app/Info.plist 里，
    # 由 spec 的 BUNDLE 段写——在 mac 上硬生成这份文件没有消费方。
    if IS_MAC:
        print("[SKIP] version_info.txt — Windows PE 资源，macOS 用 Info.plist")
    else:
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

    # 产物：Windows 是 dist/QianBi-Novel/QianBi-Novel.exe；macOS 用户拿到的是
    # .app（BUNDLE 在 COLLECT 之外再包一层），冒烟与压缩都以 .app 为准。
    if IS_MAC:
        app_bundle = os.path.join(ROOT, "dist", "QianBi-Novel.app")
        dist_dir = app_bundle
        exe = os.path.join(app_bundle, "Contents", "MacOS", "QianBi-Novel")
        size_root = app_bundle
    else:
        app_bundle = ""
        dist_dir = os.path.join(ROOT, "dist", "QianBi-Novel")
        exe = os.path.join(dist_dir, "QianBi-Novel.exe")
        size_root = dist_dir
    step("产物存在", os.path.exists(exe), exe)
    size_mb = sum(os.path.getsize(os.path.join(dp, f)) / 1048576
                  for dp, _, fs in os.walk(size_root) for f in fs)
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

    # ---- 5.5 代码签名（检测到证书才做；没证书照旧产出，别把发版卡死）----
    # Windows 走 signtool+pfx，macOS 走 codesign+身份：两套证书体系，混用哪个
    # 都会失败，所以按平台分家——没有对应工具就跳过并说明原因，不硬跑。
    if IS_MAC:
        mac_identity = (os.environ.get("QIANBI_SIGN_IDENTITY") or "").strip()
        if not mac_identity:
            print("[SKIP] 未配置签名证书（QIANBI_SIGN_IDENTITY），.dmg/.zip 不签名")
        elif not shutil.which("codesign"):
            print("[WARN] 配了 QIANBI_SIGN_IDENTITY 但找不到 codesign，本次不签名")
        else:
            ok, detail = sign_mac(app_bundle, mac_identity)
            step("代码签名 · 主程序", ok, detail if not ok else os.path.basename(app_bundle))
    else:
        cert, no_cert_reason = signing_plan()
        signtool = find_signtool() if cert else ""
        if cert and not signtool:
            no_cert_reason = "配了证书但找不到 signtool.exe（装 Windows SDK 或把它加进 PATH）"
            print("[WARN] " + no_cert_reason + "，本次不签名")
            cert = None
        if not cert:
            print("[SKIP] " + no_cert_reason)
        else:
            ok, detail = sign(exe, cert, signtool)
            step("代码签名 · 主程序", ok, detail if not ok else os.path.basename(exe))

# ---- 6. 产物目录 + 便携 zip + SHA256SUMS ----
    out_dir = os.path.join(ROOT, "dist", "release", f"v{__version__}")
    os.makedirs(out_dir, exist_ok=True)
    # 说明文件两个名字：包内用中文（解压后与 exe 并列，一眼看到，UTF-8 名解压正常）；
    # 产物目录里的独立副本必须用 ASCII —— GitHub 会把非 ASCII 的 release 资产名
    # 悄悄退化成 "default.txt"。
    readme_in_zip = "使用说明.txt"
    readme_standalone = "PORTABLE_README.txt"
    # 便携包：Windows 装 onedir 文件夹，macOS 装 .app（.app 本身就是可搬的目录）
    readme_bytes = portable_readme_mac(__version__) if IS_MAC else portable_readme(__version__)
    if IS_MAC:
        readme_standalone = "MACOS_README.txt"
    with open(os.path.join(out_dir, readme_standalone), "wb") as f:
        f.write(readme_bytes)
    if IS_MAC:
        portable = os.path.join(out_dir, f"QianBi-Novel-v{__version__}-macos.zip")
    else:
        portable = os.path.join(out_dir, f"QianBi-Novel-v{__version__}-portable.zip")
    # mac 必须把 .app 当成一个整体放进包根：压 Contents/ 本身，解出来是个没有
    # .app 外壳的文件夹——Bootloader 按 *.app 认包结构，认不出就找不到 Frameworks
    # （实测报 Failed to load Python shared library .../Contents/MacOS/_internal/Python）
    write_portable_zip(portable, dist_dir, readme_in_zip, readme_bytes,
                       arc_prefix=os.path.basename(app_bundle) if IS_MAC else "")
    step("便携 zip", os.path.exists(portable),
         f"{os.path.getsize(portable) / 1048576:.0f} MB")

    # 附带说明文件进产物目录
    for doc in ("LICENSE", "THIRD-PARTY-LICENSES.md", "docs/PRIVACY.md"):
        src = os.path.join(ROOT, doc)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_dir, os.path.basename(doc)))

    # ---- 7. 安装包（平台分支：macOS=hdiutil .dmg ｜ Windows=Inno Setup .exe）----
    installer_built = False
    installer_path = os.path.join(out_dir, f"QianBi-Novel-v{__version__}-setup.exe")
    if IS_MAC and not args.no_installer:
        dmg = os.path.join(out_dir, f"QianBi-Novel-v{__version__}-mac.dmg")
        ok, detail = build_dmg(app_bundle, dmg, __version__)
        installer_built = ok
        step("hdiutil 安装包", ok, detail if not ok else os.path.basename(dmg))
        if ok:
            installer_path = dmg
            mac_identity = (os.environ.get("QIANBI_SIGN_IDENTITY") or "").strip()
            if mac_identity and shutil.which("codesign"):
                ok2, detail2 = sign_mac(dmg, mac_identity)
                step("代码签名 · 安装包", ok2,
                     detail2 if not ok2 else os.path.basename(dmg))
            else:
                print("[SKIP] 安装包未签名 — 未配置 QIANBI_SIGN_IDENTITY")
    elif IS_MAC:
        print("[SKIP] --no-installer")
    elif not args.no_installer:
        iscc_candidates = [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
        ]
        iscc = next((p for p in iscc_candidates if p and os.path.exists(p)), None)
        if iscc:
            r = subprocess.run([iscc, f"/DAppVersion={__version__}",
                                "tools/installer.iss"], cwd=ROOT)
            installer_built = r.returncode == 0 and os.path.exists(
                os.path.join(out_dir, f"QianBi-Novel-v{__version__}-setup.exe"))
            step("Inno Setup 安装包", installer_built)
            if installer_built:
                setup = os.path.join(out_dir, f"QianBi-Novel-v{__version__}-setup.exe")
                if not cert:
                    print("[SKIP] 安装包未签名 — " + no_cert_reason)
                else:
                    # 用户下载并双击的就是这个文件，SmartScreen 认的也是它
                    ok, detail = sign(setup, cert, signtool)
                    step("代码签名 · 安装包", ok, detail if not ok else os.path.basename(setup))
        else:
            print("[SKIP] 未检测到 Inno Setup 6（安装包跳过；安装后重跑 --no-installer --skip-tests --skip-probe 即可补齐）")
    else:
        print("[SKIP] --no-installer")

    # ---- 7.5 版本清单回填 + 签名（客户端「检查更新」读的就是这份）----
    manifest = os.path.join(ROOT, "latest.json")
    slug = None
    try:
        from app import config as _cfg
        from app import update_check as _uc
        remote = (_cfg.DEFAULT_CONFIG.get("updates") or {}).get("manifest_url") or ""
        pair = _uc.gh_slug(remote)
        slug = "/".join(pair) if all(pair) else None
    except Exception as e:  # noqa: BLE001
        print("[WARN] 取仓库 slug 失败，latest.json 不会回填：%s" % e)
    if not installer_built:
        print("[SKIP] 本次没有安装包产物，latest.json 未回填（补齐安装包后重跑即可）")
    elif not slug:
        step("版本清单回填", False, "取不到仓库 slug，无法拼出下载地址")
    else:
        data = {}
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
        base = "https://github.com/%s/releases/" % slug
        data = build_manifest_entry(
            data, version=__version__, base=base,
            kind="dmg" if IS_MAC else "setup",
            installer_path=installer_path, portable=portable)
        with open(manifest, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        if __version__ not in str(data.get("notes") or ""):
            print("[WARN] latest.json 的 notes 里没出现 v%s —— 用户看更新说明时会对不上号"
                  % __version__)
        r = subprocess.run([sys.executable, "scripts/sign_manifest.py", manifest], cwd=ROOT)
        v = subprocess.run([sys.executable, "scripts/sign_manifest.py", "--verify", manifest],
                           cwd=ROOT)
        step("版本清单已签名", r.returncode == 0 and v.returncode == 0,
             "没有私钥 → 客户端只会显示新版，不会给一键安装（发版请视为未完成）"
             if (r.returncode or v.returncode) else manifest)

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
