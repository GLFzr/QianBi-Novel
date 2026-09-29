# -*- coding: utf-8 -*-
"""C29 自动备份（BACKUP）：关项目/关应用时把项目目录 zip 归档。

对标事实（w2_maturity）：novelWriter「关项目自动 zip」是品类标配，本模块补齐
千笔的这块成熟度短板。bridge 在三个时点调用（打开项目 / 关书换书 / 关应用），
判定与打包都收敛在这里：

- 打包：整项目 zip（排除 .git/__pycache__ 等缓存类目录与备份目录自身），
  命名 `<书名>_auto_<时间戳>.zip`（含书名与时间戳，字典序即时间序）；
- 保留策略：只保留最近 keep 份（默认 5，超删旧；keep<=0 = 不裁剪）；
- 铁律「永不阻断关闭流程」：项目读不了（损坏/权限/不存在）→ 记日志返回
  None，绝不抛出；单个文件读不了 → 跳过该文件继续打包；
- 纯 core：不 import app-top（dep_graph 铁律），备份目录由调用方按
  app/config.py 的用户数据目录约定（CONFIG_DIR/backups/<书名>/）传入；
- 当日去重：标记存 cfg["auto_backup"]["done"]（项目规范路径 → 日期），
  每项目每日一份，避免一天开关十次应用就攒十份 zip。
"""
import datetime
import logging
import os
import time
import zipfile

logger = logging.getLogger("qianbi.auto_backup")

DEFAULT_KEEP = 5          # 默认保留份数（与 config.py 出厂键一致）
_DONE_CAP = 10            # 当日去重标记的容量上限（与 recent_projects 对齐）

# 打包排除：版本控制与缓存类目录 + 备份目录自身（按名字排除；备份目录若嵌在
# 项目里再由 realpath 兜底，防止递归打包）
_EXCLUDE_DIRS = {
    "backups", ".git", ".hg", ".svn", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".coverage",
    "node_modules", ".idea", ".vscode",
}


def enabled(cfg: dict) -> bool:
    """开关：cfg["auto_backup"]["enabled"]，缺省即开（出厂默认 on）。"""
    try:
        ab = (cfg or {}).get("auto_backup") or {}
        return bool(ab.get("enabled", True))
    except Exception:  # noqa: BLE001 - 配置脏值按出厂默认走
        return True


def keep_n(cfg: dict) -> int:
    """保留份数：cfg["auto_backup"]["keep"]，缺省 5；<=0 表示不裁剪。"""
    try:
        ab = (cfg or {}).get("auto_backup") or {}
        return int(ab.get("keep", DEFAULT_KEEP))
    except Exception:  # noqa: BLE001
        return DEFAULT_KEEP


def _today() -> str:
    return datetime.date.today().isoformat()


def due(cfg: dict, project_path: str, today: str = "") -> bool:
    """当日尚未备份过该项目 → True（enabled 判定在调用方先行）。"""
    done = ((cfg or {}).get("auto_backup") or {}).get("done") or {}
    key = os.path.normpath(str(project_path or ""))
    return done.get(key) != (today or _today())


def mark_done(cfg: dict, project_path: str, today: str = "") -> None:
    """落当日去重标记并裁剪（cfg 就地改；是否落盘由调用方 save_config 决定）。"""
    if cfg is None:                              # 注意别用 (cfg or {})：空 dict 是
        cfg = {}                                 # falsy，会写进临时对象导致更新丢失
    ab = cfg.setdefault("auto_backup", {})
    done = ab.setdefault("done", {})
    key = os.path.normpath(str(project_path or ""))
    done[key] = today or _today()
    if len(done) > _DONE_CAP:
        # 按日期留最近 _DONE_CAP 本（ISO 日期字典序即时间序）
        for k in sorted(done, key=lambda k: done.get(k, ""))[:-_DONE_CAP]:
            done.pop(k, None)


def _timestamp() -> str:
    """zip 文件名时间戳（模块级函数：单测 monkeypatch 注入递增时刻）。"""
    return time.strftime("%Y%m%d_%H%M%S")


def _safe_name(name: str) -> str:
    """书名进文件名：替换 Windows 非法字符（正常项目目录名本就合法，兜底）。"""
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip(" .") or "project"


def _quiet_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _trim(backup_dir: str, book: str, keep: int) -> None:
    """裁剪：只留最近 keep 份（按 mtime，新→旧）；keep<1 = 不裁剪。永不抛出。"""
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        return
    if keep < 1:
        return
    try:
        prefix = _safe_name(book) + "_auto_"
        zips = [os.path.join(backup_dir, n) for n in os.listdir(backup_dir)
                if n.startswith(prefix) and n.endswith(".zip")]
        zips.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
        for old in zips[keep:]:
            _quiet_remove(old)
    except OSError as e:
        logger.warning("备份裁剪异常（不阻断）：%s", e)


def create_backup(project_path: str, backup_dir: str,
                  keep: int = DEFAULT_KEEP, book_name: str = "") -> str:
    """把项目目录 zip 进 backup_dir，保留最近 keep 份；返回 zip 路径或 ""。

    任何失败（项目不存在/读不了/写不了/校验不过）都只记日志并返回 ""，
    绝不向调用方抛出——调用方都在关书/关应用路径上，备份不许阻断关闭。
    """
    out = ""
    try:
        proj = os.path.normpath(str(project_path or ""))
        if not proj or not os.path.isdir(proj):
            logger.warning("自动备份跳过：项目目录不可读 %r", project_path)
            return ""
        bdir = str(backup_dir or "")
        if not bdir:
            logger.warning("自动备份跳过：未指定备份目录")
            return ""
        book = _safe_name(str(book_name) or os.path.basename(proj))
        os.makedirs(bdir, exist_ok=True)
        out = os.path.join(bdir, "%s_auto_%s.zip" % (book, _timestamp()))
        _bdir_real = os.path.realpath(bdir)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(proj):
                dirs[:] = [
                    d for d in dirs
                    if d not in _EXCLUDE_DIRS
                    and os.path.realpath(os.path.join(root, d)) != _bdir_real]
                for fn in files:
                    p = os.path.join(root, fn)
                    try:
                        zf.write(p, os.path.relpath(p, proj))
                    except (OSError, ValueError) as e:
                        # 单文件读不了（占用/权限）不整包失败：跳过并记录
                        logger.warning("备份跳过不可读文件 %s：%s", p, e)
        with zipfile.ZipFile(out) as zf:   # 产物自检：写完当场验一遍可解
            bad = zf.testzip()
        if bad is not None:
            raise OSError("zip 自检失败（成员损坏）：%s" % bad)
        _trim(bdir, book, keep)
        return out
    except Exception as e:  # noqa: BLE001 - 损坏项目/磁盘异常都不许阻断关闭流程
        logger.warning("自动备份失败 %r：%s", project_path, e)
        _quiet_remove(out)
        return ""
