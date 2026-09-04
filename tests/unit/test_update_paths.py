# -*- coding: utf-8 -*-
"""R3：两条更新路径都不许动用户既有数据

覆盖安装（Inno 的 .iss）和版本清单（latest.json）都不是运行时代码：改了它们，
没有一条 Python 断言会变红，坏消息要等到用户升级那天才听见。所以这里用
「读源文本 + 读清单」的方式把契约钉住，判定口径与被钉的那份实现一一对应。
"""
import json
import os
import re

from app import config as cfg_mod
from app import project
from app.update_check import is_newer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ISS_PATH = os.path.join(ROOT, "tools", "installer.iss")
LATEST_PATH = os.path.join(ROOT, "latest.json")


def _iss():
    with open(ISS_PATH, encoding="utf-8") as f:
        return f.read()


def _section(text, name):
    """取 [Section] 到下一个 [Section] 之间的非注释行"""
    lines, hit = [], False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            hit = (s == "[%s]" % name)
            continue
        if hit and s and not s.startswith(";"):
            lines.append(s)
    return lines


def _names(entries, key):
    """从 `Type: x; Name: "{app}\\y"` 这类条目里抽出某个字段的值"""
    out = []
    for e in entries:
        m = re.search(key + r"\s*:\s*\"([^\"]+)\"", e)
        if m:
            out.append(m.group(1))
    return out


# ---- 安装器：只写程序目录 ----

def test_installer_writes_only_into_app_dir():
    """[Files] 的落点必须全在 {app}：装到别处就等于往用户地盘写文件"""
    dest = _names(_section(_iss(), "Files"), "DestDir")
    assert dest, "没解析出 [Files] 的 DestDir，断言会空转"
    assert set(dest) == {"{app}"}, dest


def test_installer_never_deletes_outside_app_dir():
    """卸载/安装期删除项只允许指向 {app}——书稿与配置在用户目录，一根毛都不能碰"""
    text = _iss()
    for sec in ("InstallDelete", "UninstallDelete"):
        for name in _names(_section(text, sec), "Name"):
            assert name.replace("/", "\\").upper().startswith("{APP}\\"), \
                "%s 里出现了 {app} 之外的删除目标：%s" % (sec, name)


def test_upgrade_clears_previous_program_tree():
    """覆盖安装前清掉旧 _internal：残留的旧模块会和新版拼成没人测过的组合"""
    names = _names(_section(_iss(), "InstallDelete"), "Name")
    assert any(n.replace("/", "\\").endswith("_internal") for n in names), names


def test_installer_blocks_install_dir_on_writing_data(tmp_path):
    """装到书稿目录要有机器拦截，而不是靠用户自己别手滑"""
    code = "\n".join(_section(_iss(), "Code"))
    assert "LooksLikeWritingData" in code
    assert "wpSelectDir" in code and "Result := False" in code, "目录页没有硬拦"
    assert "wpReady" in code, "升级安装会跳过目录页，准备页必须提醒"


def test_installer_deals_with_a_running_app():
    """升级时程序常还开着，而它锁着自己的 exe——这一段两条都不许反着改"""
    text = _iss()
    # 没有 CloseApplications：文件复制失败被排到重启后，症状是「升级了行为还是旧的」
    assert "CloseApplications=yes" in text
    # [Run] 已经提供「立即运行」，安装器再自己重启一次会撞单实例锁
    # （第二个进程 raise 一下就退），用户看到的是「更新完程序打不开」
    assert "RestartApplications=no" in text
    # 也别退回 AppMutex + ctypes 具名互斥量：per-user 非管理员会话没有
    # SeCreateGlobalPrivilege，互斥量静默落在 Local 前缀，而 Inno 找 Global 前缀
    assert "AppMutex" not in text, "接不通的死重量：见 CloseApplications 上方的注释"


def test_code_section_rejects_ini_style_comments():
    """[Code] 交给 Pascal 编译器：一行 ; 注释就能让整包编译不过（'BEGIN' expected）"""
    text = _iss()
    body = text.split("[Code]", 1)[1] if "[Code]" in text else ""
    bad = [ln for ln in body.splitlines() if ln.strip().startswith(";")]
    assert not bad, "Inno 的 Pascal 段不认 ; 注释，改用 // 或 { }：%s" % bad[:2]


def test_book_root_rule_matches_project_layout():
    """.iss 里「是不是一本书」的判定必须跟 app/project.py 同一口径，否则拦截形同虚设"""
    m = re.search(r"function IsBookRoot.*?end;", _iss(), re.S)
    assert m, "找不到 IsBookRoot"
    quoted = set(re.findall(r"'([^']+)'", m.group(0)))
    assert quoted == set(project.PROJECT_DIRS), (quoted, project.PROJECT_DIRS)


# ---- 版本清单：应用内检查更新读到的是哪一份 ----

def _latest():
    with open(LATEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_latest_manifest_is_self_consistent():
    from app import __version__
    m = _latest()
    assert set(m) >= {"version", "url", "notes", "sha256"}, sorted(m)
    assert re.fullmatch(r"[0-9a-f]{64}", m["sha256"]), "sha256 不是十六进制摘要"
    assert m["version"] in m["url"], "清单指向的 tag 与 version 不是同一个版本"
    assert not is_newer(m["version"], __version__), \
        "清单宣称有比当前代码更新的版本，等于推一个还没发布的包"


def test_manifest_url_points_at_the_file_we_test():
    """配置里读的 URL 必须就是仓库根这份 latest.json，否则上面的断言钉的是空气"""
    url = cfg_mod.DEFAULT_CONFIG["updates"]["manifest_url"]
    repo = re.search(r"github\.com/([^/]+/[^/.]+)", _latest()["url"]).group(1)
    assert url == ("https://raw.githubusercontent.com/%s/main/latest.json" % repo), url


def test_auto_check_is_off_by_default():
    """开机自连 GitHub 是对外请求，默认必须关；手动「检查更新」不受该开关影响"""
    assert cfg_mod.DEFAULT_CONFIG["updates"]["auto_check"] is False


# ---- 配置的升级安全 ----

def _use_tmp_config(tmp_path, monkeypatch, raw):
    from app import secrets as secrets_mod
    d = tmp_path / "cfgdir"
    d.mkdir()
    f = d / "config.json"
    f.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", str(d))
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(f))
    # 凭据隔离：load/save 会经 hydrate/dehydrate，测试绝不碰真实凭据存储
    monkeypatch.setattr(secrets_mod, "SERVICE", "QianBiNovel/test-run")
    return d, f


def test_corrupt_config_is_kept_not_overwritten(tmp_path, monkeypatch):
    """读不懂 ≠ 没有配置：坏文件必须留下来，否则下一次保存就把用户设置抹了"""
    garbage = '{"connections": [ 这行断了'
    d, f = _use_tmp_config(tmp_path, monkeypatch, garbage)
    cfg = cfg_mod.load_config()
    assert cfg["connections"], "坏配置应回落到默认连接而不是空"
    kept = [n for n in os.listdir(d) if n.startswith("config.json.broken-")]
    assert kept, "坏配置被就地丢弃，没有另存"
    with open(os.path.join(str(d), kept[0]), encoding="utf-8") as fh:
        assert fh.read() == garbage


def test_dead_check_on_start_key_does_not_become_auto_check(tmp_path, monkeypatch):
    """v0.15 的 check_on_start 从没被任何调用点读到，那份 True 不是用户的选择，
    搬到新键上等于升级后偷偷开机联网"""
    raw = json.dumps({"connections": [{"id": "c1", "name": "N", "base_url": "u",
                                       "api_key": "", "model": "m", "temperature": 0.7,
                                       "max_tokens": 100, "timeout": 60}],
                      "slots": {"writing": "c1", "helper": "c1", "review": "c1"},
                      "updates": {"manifest_url": "https://example.invalid/m.json",
                                  "check_on_start": True}}, ensure_ascii=False)
    _d, f = _use_tmp_config(tmp_path, monkeypatch, raw)
    cfg = cfg_mod.load_config()
    assert "check_on_start" not in cfg["updates"]
    assert cfg["updates"]["auto_check"] is False
    assert cfg["updates"]["manifest_url"] == "https://example.invalid/m.json"
    with open(f, encoding="utf-8") as fh:
        assert fh.read() == raw, "load_config 不该把迁移结果顺手写回磁盘"


def test_unknown_future_keys_survive_roundtrip(tmp_path, monkeypatch):
    """降级/旧版读新配置时不该丢掉自己看不懂的键：合并策略是补齐而非重建"""
    raw = json.dumps({"connections": [{"id": "c1", "name": "N", "base_url": "u",
                                       "api_key": "", "model": "m", "temperature": 0.7,
                                       "max_tokens": 100, "timeout": 60}],
                      "slots": {"writing": "c1", "helper": "c1", "review": "c1"},
                      "brand_new_section": {"keep": 1}}, ensure_ascii=False)
    _d, f = _use_tmp_config(tmp_path, monkeypatch, raw)
    cfg_mod.save_config(cfg_mod.load_config())
    with open(f, encoding="utf-8") as fh:
        disk = json.load(fh)
    assert disk["brand_new_section"] == {"keep": 1}
    assert disk["connections"][0]["id"] == "c1"      # 用户自建连接不被默认模板顶掉


# ---- QML ↔ Bridge 接线（跨语言，基线探针看不见）----

def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_update_state_is_one_map_not_a_four_string_signal():
    """以前 updateFound(str,str,str,str) 加一个参数就得同步改 QML 处理函数，
    漏改的症状是「新版本静默显示不出来」。改成一份 QVariantMap 属性后，
    字段错位在这条断言上就会红，而不是在用户眼睛里静默。"""
    bridge = _src("app/ui/bridge.py")
    assert "updateStateChanged = Signal()" in bridge
    assert re.search(r'@Property\("QVariantMap", notify=updateStateChanged\)\s*\n\s*def updateState',
                     bridge), "更新状态不再是 QVariantMap 属性，QML 读不到"
    assert "updateFound" not in bridge, "旧的四字符串信号还在，等于两套真相"
    assert "bridge.updateState" in _src("app/ui/qml/components/UpdateDialog.qml")
    assert "bridge.updateAvailable" in _src("app/ui/qml/Main.qml"), "左栏图标没接更新状态"


def test_startup_check_is_wired_and_gated():
    bridge = _src("app/ui/bridge.py")
    assert "checkForUpdates(false)" in _src("app/ui/qml/Main.qml"), "开机检查没接线"
    body = re.search(r"    def checkForUpdates\(self, manual: bool\):(.*?)\n    @Slot",
                     bridge, re.S).group(1)
    # 开关 + QIANBI_OFFLINE 杀开关 + 24h 限流全在 should_auto_check 里，
    # 绕过它就等于绕过「探针与打包自检零网络」那条纪律
    assert "should_auto_check" in body, "开机检查没读开关与限流"


def test_update_settings_patch_is_key_whitelisted():
    """setUpdateSettings 收 QML 传来的 JSON：不做白名单就能从这里写 connections/slots"""
    bridge = _src("app/ui/bridge.py")
    keys = re.search(r"_UPDATE_KEYS = \((.*?)\)", bridge, re.S).group(1)
    listed = {k.strip().strip('"') for k in keys.split(",") if k.strip().strip('"')}
    assert {"auto_check", "custom_url", "proxy_mode", "proxy_url", "interval_hours"} <= listed
    assert not listed & {"connections", "slots", "last_project", "gates"}, listed
    assert "if k in self._UPDATE_KEYS" in bridge, "补丁没过滤键，白名单形同虚设"


def test_install_path_keeps_all_three_gates():
    """installUpdateNow 是应用唯一会执行下载文件的地方，三道门少一道就等于自动执行任意 exe"""
    body = re.search(r"    def installUpdateNow\(self\):(.*?)\n    @Slot",
                     _src("app/ui/bridge.py"), re.S).group(1)
    assert "can_install" in body, "验签门没了"
    assert 'install_mode() != "installed"' in body, "便携版会去覆盖正在运行的自己"
    assert "sha256_file" in body, "装前不再重算哈希：校验过被换掉就没人发现"


def test_update_check_does_not_emit_from_bare_thread():
    """裸 threading.Thread 里直接 emit = 从别的线程调进正在求值的 QML 绑定"""
    body = re.search(r"    def checkForUpdates\(self, manual: bool\):(.*?)\n    @Slot",
                     _src("app/ui/bridge.py"), re.S).group(1)
    assert "threading.Thread" not in body
    assert "_UpdateWorker" in body
