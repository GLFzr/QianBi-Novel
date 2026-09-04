# -*- coding: utf-8 -*-
"""版本清单获取：多通道 + 代理 + 本地缓存 + 验签（GUI-only，不进 dual_sync 共享层）

为什么不「一个 URL 拉 JSON」就完事：
    国内 raw.githubusercontent 常年 DNS 污染、Release 资产 CDN 会被重置，单通道失败在
    旧实现里被吞成 None，于是「检查失败」在界面上长成「已是最新版本」——假绿。

为什么多通道必须和验签同一轮上线：
    通道加多的同时被放大的正是「谁有权告诉你该装什么」。这个应用持有凭据管理器里的
    API Key、能写用户书稿目录，所以「能递一份 1KB 清单进来」绝不能等于
    「能在你机器上跑任意 exe」。规则钉在这里：未过验签的清单只能被**显示**，
    永远不能触发下载或执行（`CheckResult.can_install`）。
"""
from __future__ import annotations

import base64
import glob
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger("qianbi.update")

# 打包漏收这个依赖时，症状是「更新功能静默失效」而不是崩溃——所以它必须同时出现在
# app/selftest.py 的导入清单里（闸门红），而不是只在这里被 try 掉。
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    CRYPTO_OK = True
    CRYPTO_ERR = ""
except Exception as _e:  # noqa: BLE001
    Ed25519PublicKey = None      # type: ignore[assignment]
    CRYPTO_OK = False
    CRYPTO_ERR = type(_e).__name__

# 发布公钥（可轮换：多把并存，签名命中任意一把即视为作者发布）。
# 私钥永不进仓库，见 scripts/update_keys.py 与 docs/release_checklist.md。
# 换钥的正确姿势是**追加**新公钥并发一版应用：删掉旧条目会让老客户端失去判断依据，
# 而不是让它们「更安全」。
PUBKEYS: list[dict] = [
    {"kid": "b75dcbf8", "pub": "0yXI3cLydSg7X+yeUEE9mbtVJsBxWs7WwkXMpZ63xVY="},
]

OFFLINE_ENV = "QIANBI_OFFLINE"
TIMEOUT = 6.0            # 单通道单次请求
DEADLINE = 25.0          # 整条通道链的总预算：自动检查在子线程，但没人愿意等半分钟
DEFAULT_INTERVAL_HOURS = 24.0

STATE_NEW = "new"
STATE_LATEST = "latest"
STATE_FAILED = "failed"

CHANNEL_LABELS = {
    "custom": "自定义更新源",
    "raw": "GitHub raw",
    "pages": "GitHub Pages",
    "jsdelivr": "jsDelivr CDN",
    "cache": "本机缓存的上次清单",
    "file": "本地清单文件",
}


def offline() -> bool:
    """探针/打包自检的统一杀开关：默认开自动检查之后，闸门里必须能一键断网

    `app/selftest.py` 的纪律第 2 条写着「零网络」，而打包态 selftest 就跑在发布流水线里。
    """
    return (os.environ.get(OFFLINE_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


# ---------- 版本比较 ----------

def parse_ver(v: str) -> tuple:
    nums = re.findall(r"\d+", (v or "").strip())
    return tuple(int(x) for x in nums[:3]) if nums else (0,)


def is_newer(remote: str, local: str) -> bool:
    """按点分数字逐段比较（非严格 semver，容忍 0.14 / 0.14.0 混写）"""
    return parse_ver(remote) > parse_ver(local)


# ---------- 通道 ----------

def gh_slug(url: str) -> tuple:
    """从 GitHub 系 URL 里取出 (user, repo)，用来派生 Pages / jsDelivr 变体

    刻意不再写死第二份仓库地址：默认清单 URL 就是唯一来源，两处常量迟早会漂。
    """
    for pat in (r"github\.com/([^/]+)/([^/]+)",
                r"raw\.githubusercontent\.com/([^/]+)/([^/]+)"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1), re.sub(r"\.git$", "", m.group(2))
    return ("", "")


def _canonical_default_url(url: str) -> str:
    """与出厂默认只差大小写的存量配置，统一按出厂那份的大小写走

    GitHub 的仓库路径大小写不敏感，派生通道却敏感：jsDelivr 的 gh 路径区分大小写、
    Pages 子域名只认小写。老版本出厂写的是小写仓库名（本机 config 就是），照抄过去
    等于给用户一条注定 404 的通道。
    """
    from .config import DEFAULT_CONFIG
    default = (DEFAULT_CONFIG.get("updates") or {}).get("manifest_url") or ""
    if default and url.lower() == default.lower():
        return default
    return url


def channels(cfg: dict) -> list:
    """有序清单通道；`updates.last_channel` 记过的成功通道提到最前"""
    u = cfg.get("updates") or {}
    out = []
    custom = (u.get("custom_url") or "").strip()
    if custom:
        out.append(("custom", custom))
    primary = _canonical_default_url((u.get("manifest_url") or "").strip())
    if primary:
        out.append(("raw", primary))
        user, repo = gh_slug(primary)
        if user and repo:
            # Pages 只认小写；jsDelivr 的 gh 路径区分大小写，必须用原样 slug。
            # jsDelivr 对分支 ref 的缓存实测 s-maxage=43200 / max-age=604800（2026-09-04 响应头）：
            # 只连得上这一条通道的用户，最坏会晚约 12 小时才知道发了新版。这是延迟不是漏洞——
            # 清单带签名，滞后的镜像只会「少报」，报不出一个不存在的新版本。
            out.append(("pages", "https://%s.github.io/%s/latest.json"
                        % (user.lower(), repo.lower())))
            out.append(("jsdelivr", "https://cdn.jsdelivr.net/gh/%s/%s@main/latest.json"
                        % (user, repo)))
    stick = u.get("last_channel")
    if stick:
        for i, (k, _url) in enumerate(out):
            if k == stick and i:
                out.insert(0, out.pop(i))
                break
    return [(k, v) for k, v in out if is_http_url(v)]


# ---------- 代理 ----------

def system_proxy() -> tuple:
    """读 WinINET 的注册表设置（不碰 ctypes/WinINet：省掉一套句柄与 GlobalFree）

    返回 (proxy_url, note)。note 是「为什么没用上系统代理」的人话，拿不准时宁可留空
    并说清楚，也不要猜一个地址出去连。
    """
    if os.name != "nt":
        return ("", "")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            enable = winreg.QueryValueEx(k, "ProxyEnable")[0] if _has_value(k, "ProxyEnable") else 0
            server = winreg.QueryValueEx(k, "ProxyServer")[0] if _has_value(k, "ProxyServer") else ""
            pac = winreg.QueryValueEx(k, "AutoConfigURL")[0] if _has_value(k, "AutoConfigURL") else ""
    except OSError:
        return ("", "")
    if not enable:
        return ("", "系统未启用代理" + ("（配了 PAC 自动脚本，应用不解析，需要时请手填代理）" if pac else ""))
    https_val = http_val = bare = ""
    for part in (server or "").split(";"):
        p = part.strip()
        if not p:
            continue
        if "=" in p:
            scheme, _, rest = p.partition("=")
            scheme, value = scheme.strip().lower(), rest.strip()
            if scheme == "https" and not https_val:
                https_val = value
            elif scheme == "http" and not http_val:
                http_val = value
        elif not bare:
            bare = p
    # WinINET 允许只写 http=…（局域网代理常见），只有 https= 时才优先它
    host = https_val or http_val or bare
    if not host:
        return ("", "系统代理开着但 ProxyServer 里没有可用地址"
                + ("（PAC 脚本 %s，应用不解析，请手填代理）" % pac if pac
                   else "，请在面板里手填代理地址"))
    if not host.startswith("http"):
        host = "http://" + host
    return (host, "")


def _has_value(key, name: str) -> bool:
    import winreg
    try:
        winreg.QueryValueEx(key, name)
        return True
    except OSError:
        return False


@dataclass
class ProxyPlan:
    proxy: str = ""
    trust_env: bool = True
    label: str = "跟随环境变量"
    note: str = ""


def resolve_proxy(cfg: dict) -> ProxyPlan:
    """updates.proxy_mode: system（默认）| env | none | custom"""
    u = cfg.get("updates") or {}
    mode = (u.get("proxy_mode") or "system").strip().lower()
    if mode == "none":
        return ProxyPlan(trust_env=False, label="不使用代理")
    if mode == "env":
        return ProxyPlan(trust_env=True, label="跟随环境变量")
    if mode == "custom":
        url = (u.get("proxy_url") or "").strip()
        if not url:
            return ProxyPlan(trust_env=False, label="未填代理地址", note="自定义代理没填地址，本次不使用代理")
        if not url.startswith("http"):
            url = "http://" + url
        return ProxyPlan(proxy=url, trust_env=False, label="自定义 " + url)
    url, note = system_proxy()
    if url:
        return ProxyPlan(proxy=url, trust_env=False, label="跟随系统 " + url)
    # 系统没配代理：交回 httpx 自己看环境变量，别把「没有系统代理」误读成「没有代理」
    return ProxyPlan(trust_env=True, label="跟随环境变量", note=note)


def is_https_url(url: str) -> bool:
    try:
        return urlparse(url or "").scheme.lower() == "https"
    except ValueError:
        return False


def is_http_url(url: str) -> bool:
    """只放 http/https 出去：`file://` 能让「打开链接」变成启动本地 PE，
    `\\\\host\\share` 会在无人知情时把 NTLM 哈希送出内网。
    """
    try:
        return urlparse(url or "").scheme.lower() in ("http", "https")
    except ValueError:
        return False


# ---------- 结果对象 ----------

@dataclass
class CheckResult:
    state: str = STATE_FAILED
    manifest: dict | None = None
    verified: bool = False
    verify_reason: str = ""
    channel: str = ""
    proxy_label: str = ""
    errors: list = field(default_factory=list)
    checked_at: float = 0.0

    @property
    def is_new(self) -> bool:
        return self.state == STATE_NEW

    @property
    def can_install(self) -> bool:
        """一键安装的唯一门票：签名验过，且确实有更新"""
        return self.is_new and self.verified

    def version(self) -> str:
        return str((self.manifest or {}).get("version") or "")

    def errors_text(self) -> str:
        return "\n".join("%s · %s" % (CHANNEL_LABELS.get(e.get("channel", ""), e.get("channel", "")),
                                      e.get("reason", "")) for e in self.errors)

    def to_map(self) -> dict:
        m = self.manifest or {}
        return {
            "state": self.state,
            "checking": False,
            "hasNew": self.is_new,
            "verified": self.verified,
            "verifyReason": self.verify_reason,
            "canInstall": self.can_install,
            "channel": self.channel,
            "channelLabel": CHANNEL_LABELS.get(self.channel, self.channel),
            "proxyLabel": self.proxy_label,
            "version": str(m.get("version") or ""),
            "notes": str(m.get("notes") or ""),
            "url": str(m.get("url") or ""),
            "sha256": asset_sha(m),
            "errors": self.errors_text(),
            "checkedAt": self.checked_at,
            "fromCache": self.channel == "cache",
        }


# ---------- 验签 ----------

def canonical_bytes(data: dict) -> bytes:
    """签名的作用域：去掉 sig 后的全部字段，键序与空白固定

    必须与 scripts/sign_manifest.py 逐字节同一套序列化，否则「签了但验不过」。
    """
    body = {k: v for k, v in (data or {}).items() if k != "sig"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def verify_manifest(data: dict) -> tuple:
    """(verified, reason) —— 失败原因要能对人解释，不能只回一个 bool"""
    sig = str((data or {}).get("sig") or "")
    if not sig:
        return (False, "清单未签名：只能显示，不会自动下载或安装")
    if not CRYPTO_OK:
        return (False, "验签库 cryptography 未随包安装（%s）" % CRYPTO_ERR)
    if not PUBKEYS:
        return (False, "应用内未内置发布公钥")
    try:
        raw = base64.b64decode(sig, validate=True)
    except Exception:  # noqa: BLE001
        return (False, "清单签名不是合法 base64")
    payload = canonical_bytes(data)
    for entry in PUBKEYS:
        try:
            pub = base64.b64decode(entry.get("pub") or "", validate=True)
            # 参数顺序是 (signature, data)：写反的症状不是崩溃，而是「签名正确却永远验不过」
            Ed25519PublicKey.from_public_bytes(pub).verify(raw, payload)
            return (True, "签名公钥 %s" % (entry.get("kid") or "?"))
        except Exception:  # noqa: BLE001
            continue
    return (False, "签名与内置公钥都不匹配")


# ---------- 缓存与限流 ----------

def updates_dir() -> str:
    from . import config as cfg_mod
    d = os.path.join(cfg_mod.CONFIG_DIR, "updates")
    os.makedirs(d, exist_ok=True)
    return d


def cache_file() -> str:
    return os.path.join(updates_dir(), "manifest.json")


def save_cache(raw: str, channel: str) -> None:
    tmp = cache_file() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"fetched_at": time.time(), "channel": channel, "raw": raw}, f,
                      ensure_ascii=False)
        os.replace(tmp, cache_file())
    except OSError as e:
        logger.info("更新清单缓存没写成（不影响本次结果）: %s", e)


def read_cache() -> tuple:
    """(raw_text, channel, fetched_at)；读不到/读坏都返回 ("", "", 0.0)"""
    try:
        with open(cache_file(), encoding="utf-8") as f:
            d = json.load(f)
        raw = d.get("raw")
        if not isinstance(raw, str) or not raw.strip():
            return ("", "", 0.0)
        return (raw, str(d.get("channel") or "cache"), float(d.get("fetched_at") or 0.0))
    except (OSError, ValueError):
        return ("", "", 0.0)


def should_auto_check(cfg: dict, now: float | None = None) -> bool:
    """自动检查的三重门：开关、离线杀开关、限流"""
    u = cfg.get("updates") or {}
    if not u.get("auto_check", False) or offline():
        return False
    hours = float(u.get("interval_hours") or DEFAULT_INTERVAL_HOURS)
    last = float(u.get("last_check_ts") or 0.0)
    return (now if now is not None else time.time()) - last >= hours * 3600.0


# ---------- 取清单 ----------

def error_reason(err: Exception, via_proxy: str = "") -> str:
    """人话版死因。

    走代理时优先报代理：一台死掉的本地代理抛的是 ConnectError，
    照类型表会说成「DNS 被污染或被重置」——用户于是去折腾 DNS，
    而该做的是把代理地址填对、或者在面板里选「不使用代理」。
    """
    name = type(err).__name__
    if via_proxy and name in ("ConnectError", "ConnectTimeout", "ProxyError"):
        return "代理 %s 连不上（核对代理地址，或选「不使用代理」）" % via_proxy
    return {"ConnectError": "连接失败（DNS 被污染或被重置）",
            "ConnectTimeout": "连接超时",
            "ReadTimeout": "读取超时",
            "SSLCertVerifyError": "TLS 证书校验失败",
            "ProxyError": "代理不可用",
            "TooManyRedirects": "重定向次数过多"}.get(name, name)


def fetch_text(url: str, plan: ProxyPlan, timeout: float = TIMEOUT) -> tuple:
    """(text, reason) —— 不吞成 None：调用方要能说出是哪一条通道怎么死的"""
    if offline():
        return ("", "已置 %s=1，本次不联网" % OFFLINE_ENV)
    try:
        import httpx
        with httpx.Client(proxy=plan.proxy or None, trust_env=plan.trust_env,
                          timeout=timeout, follow_redirects=True) as c:
            r = c.get(url)
            if r.status_code != 200:
                return ("", "HTTP %s（未发布或路径不对）" % r.status_code)
            return (r.text, "")
    except Exception as e:  # noqa: BLE001
        return ("", error_reason(e, plan.proxy))


def decode(text: str) -> tuple:
    """(dict, reason) —— 结构不合法就到此为止，不进验签"""
    try:
        data = json.loads(text)
    except ValueError:
        return (None, "返回的不是合法 JSON（多半被门户/网关劫持了）")
    if not isinstance(data, dict) or not str(data.get("version") or "").strip():
        return (None, "清单里没有 version 字段")
    return (data, "")


def check(cfg: dict, local_version: str, *, timeout: float = TIMEOUT,
          deadline: float = DEADLINE) -> CheckResult:
    """跑一遍通道链找新版。

    代理只解析一次；若解析出的代理让全链都失败，再无任何代理跑一遍——陈旧的系统代理
    配置（本机就有 git 指着死掉的 127.0.0.1:7997 的先例）不该把本来能成的更新挡死。
    """
    started = time.monotonic()
    errs: list = []
    plan = resolve_proxy(cfg)
    passes = [plan]
    if plan.proxy:
        passes.append(ProxyPlan(trust_env=False, label="不使用代理（回退）"))
    for p in passes:
        for key, url in channels(cfg):
            if time.monotonic() - started > deadline:
                errs.append({"channel": key, "reason": "超过总时限 %ds，后面的通道没试" % int(deadline)})
                return CheckResult(errors=errs, proxy_label=p.label, checked_at=time.time())
            text, reason = fetch_text(url, p, timeout)
            if not text:
                errs.append({"channel": key, "reason": reason})
                continue
            data, bad = decode(text)
            if data is None:
                errs.append({"channel": key, "reason": bad})
                continue
            verified, why = verify_manifest(data)
            result = CheckResult(state=STATE_NEW if is_newer(str(data.get("version")), local_version)
                                 else STATE_LATEST,
                                 manifest=data, verified=verified, verify_reason=why,
                                 channel=key, proxy_label=p.label, errors=errs,
                                 checked_at=time.time())
            if result.is_new:
                save_cache(text, key)
            return result
        if p is passes[0] and len(passes) > 1:
            errs.append({"channel": "proxy", "reason": "带代理全链失败，改用直连再试一次"})
    return CheckResult(state=STATE_FAILED, errors=errs, proxy_label=plan.label,
                       checked_at=time.time())


def cached_result(cfg: dict, local_version: str) -> CheckResult | None:
    """开机立刻恢复上次结果：图标不等网络就能亮，断网时也有内容可看

    缓存只存原文，验签在每次读取时重做——否则「一次验过」会变成永久信任。
    """
    raw, channel, fetched_at = read_cache()
    if not raw:
        return None
    data, bad = decode(raw)
    if data is None:
        logger.info("更新清单缓存读不懂（%s），当作没有缓存", bad)
        return None
    verified, why = verify_manifest(data)
    # 缓存写着有新版、但本机已经升到那一版了：不拿旧消息去骚扰用户
    if not is_newer(str(data.get("version")), local_version):
        return None
    return CheckResult(state=STATE_NEW, manifest=data, verified=verified, verify_reason=why,
                       channel="cache", proxy_label="", errors=[], checked_at=fetched_at)


def load_manifest_file(path: str) -> tuple:
    """离线导入：朋友/手机拷过来的 1KB 清单（断网机器的唯一入口）"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:
        return (None, "读不到这个文件：%s" % e)
    data, bad = decode(text)
    if data is None:
        return (None, bad)
    verified, why = verify_manifest(data)
    return (data, "" if verified else why)


# ---------- 这份程序是怎么被跑起来的 ----------

def install_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_mode() -> str:
    """installed（Inno 装过）| portable（解压即跑）| dev（源码）

    只认安装器自己写在程序目录里的 `unins*.dat`：注册表要跟 AppId 对齐才查得到，
    便携版被用户搬过家就查不到，而卸载器数据永远躺在真正被安装过的那个目录里。
    """
    if not getattr(sys, "frozen", False):
        return "dev"
    try:
        return "installed" if glob.glob(os.path.join(install_dir(), "unins*.dat")) else "portable"
    except OSError:
        return "portable"


# ---------- 下载落盘名的卫生 ----------

def safe_asset_url(url: str) -> bool:
    """清单里的地址是否允许被下载：**只认 https**

    清单那一侧允许 http（它带签名，走明文最坏是晚一点拿到）；载荷这一侧不允许——
    51MB 的 exe 走明文，链路上任何人都能试着换包（哈希会拦住，代价是一次「更新失败」），
    还能看清谁在什么时候拉了哪个版本。用户自己填的镜像前缀不归本函数管，
    那是局域网/自建源的明确意图，由调用方按 http/https 放行并照样过 sha256。
    """
    return is_https_url(url)


def asset_sha(manifest: dict, kind: str = "setup") -> str:
    """校验值：优先 assets.<kind>.sha256，回落到顶层 sha256（老清单只有顶层那一个）"""
    entry = ((manifest or {}).get("assets") or {}).get(kind) or {}
    return str(entry.get("sha256") or (manifest or {}).get("sha256") or "").strip()


def asset_url_list(manifest: dict, kind: str = "setup") -> list:
    entry = ((manifest or {}).get("assets") or {}).get(kind) or {}
    out = [str(entry.get("url") or ""), str((manifest or {}).get("url") or "")]
    out += [str(x) for x in (entry.get("mirrors") or [])]
    return [u for u in out if u]


def sanitize_version(v: str) -> str:
    """版本号会拼进下载文件名：`../../x` 这种塞得进 version 字段

    分隔符先没了就没法穿越，但留下的点会拼出 `QianBi-Novel-v....x-setup.exe` 这种
    没人念得动的名字（Windows 还会因结尾点另生枝节），所以连续点压一、首尾点掐净。
    """
    s = re.sub(r"[^0-9A-Za-z.\-]", "", str(v or ""))
    return re.sub(r"\.{2,}", ".", s).strip(".")[:32]


def setup_download_name(manifest: dict) -> str:
    m = manifest or {}
    assets = m.get("assets") or {}
    name = str((assets.get("setup") or {}).get("name") or "")
    if name and os.path.basename(name) == name and name.lower().endswith(".exe"):
        return name
    v = sanitize_version(m.get("version")) or "latest"
    return "QianBi-Novel-v%s-setup.exe" % v


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()
