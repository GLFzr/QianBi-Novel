# -*- coding: utf-8 -*-
"""公有领域（PD）中文经典语料抓取 → tests/corpus_pd/（P6，手动运行）

用途（审核 Agent 样本库）：
  1. 维 E（AI 味）/维 F（钩子）的正例文风锚点
  2. 缺陷注入基底：对干净段落程序化注入复读/数值矛盾/弱钩子，生成对抗样本
  3. 金标扩容

版权口径（仅抓公有领域，2026-09 时点）：
  - 鲁迅（卒 1936）/朱自清（卒 1948）/萧红（卒 1942）：作者逝世超 50 年，中国境内 PD
  - 老舍（卒 1966）：2017-01-01 起 PD
  - 四大名著：古籍，PD
  - 金庸/巴金/茅盾等仍在保护期 —— 不抓

数据源：中文维基文库（zh.wikisource.org）MediaWiki API（TextExtracts 纯文本）。
篇目结构经实测核对：回章体小说用索引页子页枚举（三國演義/第001回 式），
鲁迅/朱自清散篇为独立页面直取（维基文库篇名为繁体，已按实测篇名登记）。
用法：
  python scripts/fetch_pd_corpus.py            # 全量抓取
  python scripts/fetch_pd_corpus.py --list     # 只列书目
  python scripts/fetch_pd_corpus.py --only 野草 --max 5   # 限量试抓
目录已 .gitignore；build_release 打包不含 tests/。
"""
import argparse
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DEST = os.path.join(ROOT, "tests", "corpus_pd")

API = "https://zh.wikisource.org/w/api.php"
UA = ("qianbi-novel-pd-corpus-fetch/1.0 (personal offline research corpus; "
      "public-domain works only)")

# 书目：save_dir → spec（prefix=索引页子页枚举；pages=独立篇目直取）+ 版权依据
WORKS = [
    ("鲁迅-呐喊", {"author": "魯迅", "pages": [
        "狂人日記", "孔乙己", "藥", "明天", "一件小事", "頭髮的故事", "風波",
        "故鄉", "阿Q正傳", "端午節", "白光", "兔和貓", "鴨的喜劇", "社戲"]},
     "鲁迅卒于1936年，逝世逾50年，公有领域"),
    ("鲁迅-彷徨", {"author": "魯迅", "pages": [
        "祝福", "在酒樓上", "幸福的家庭", "肥皂", "長明燈", "示眾", "高老夫子",
        "孤獨者", "傷逝", "弟兄", "離婚"]}, "同上"),
    ("鲁迅-野草", {"author": "魯迅", "pages": [
        "題辭", "秋夜", "影的告別", "求乞者", "我的失戀", "復讎", "希望", "雪",
        "風箏", "好的故事", "過客", "死火", "狗的駁詰", "失掉的好地獄", "墓碣文",
        "頹敗線的顫動", "立論", "死後", "這樣的戰士", "聰明人和儍子和奴才",
        "臘葉", "淡淡的血痕中", "一覺"]}, "同上"),
    ("鲁迅-故事新编", {"author": "魯迅", "pages": [
        "補天", "奔月", "理水", "採薇", "鑄劍", "出關", "非攻", "起死"]}, "同上"),
    ("老舍-骆驼祥子", {"prefix": ["駱駝祥子/"]},
     "老舍卒于1966年，2017年起公有领域"),
    ("萧红-呼兰河传", {"prefix": ["呼蘭河傳/"]},
     "萧红卒于1942年，逝世逾50年，公有领域"),
    ("萧红-生死场", {"prefix": ["生死場/"]}, "同上"),
    ("朱自清-散文", {"author": "朱自清", "pages": [
        "背影", "荷塘月色", "春", "匆匆", "冬天", "揚州的夏日", "給亡婦",
        "綠", "兒女", "槳聲燈影裡的秦淮河"]},
     "朱自清卒于1948年，逝世逾50年，公有领域"),
    ("四大名著-三国演义", {"prefix": ["三國演義/"]}, "明代古籍，公有领域"),
    ("四大名著-水浒传", {"prefix": ["水滸傳/"]}, "元末明初古籍，公有领域"),
    ("四大名著-西游记", {"prefix": ["西遊記/"]}, "明代古籍，公有领域"),
    ("四大名著-红楼梦", {"prefix": ["紅樓夢/"]}, "清代古籍，公有领域"),
]

_SLEEP, _TIMEOUT, _RETRY = 1.0, 20, 3


def _api(params: dict) -> dict:
    params = dict(params, format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for i in range(_RETRY + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:     # 限流：长退避
                time.sleep(8.0 * (i + 1))
            else:
                time.sleep(2.0 * (i + 1))
        except Exception as e:    # 网络抖动/限流断连：退避重试
            last = e
            time.sleep(4.0 * (i + 1))
    raise RuntimeError(f"API 请求失败（重试 {_RETRY} 次）：{last}")


def _subpages(prefixes: list, limit: int) -> list:
    """枚举索引页子页（三國演義/第001回、呼蘭河傳/第一章 之类）"""
    titles = []
    for prefix in prefixes:
        cont = None
        while True:
            params = {"action": "query", "list": "allpages", "apnamespace": 0,
                      "apprefix": prefix, "aplimit": 200}
            if cont:
                params["apcontinue"] = cont
            data = _api(params)
            batch = [p["title"] for p in data.get("query", {}).get("allpages", [])]
            titles.extend(batch)
            time.sleep(_SLEEP)
            cont = data.get("continue", {}).get("apcontinue")
            if not cont or (limit and len(titles) >= limit):
                break

    def sort_key(t):    # 第003回/第3章 之类按数字自然排序
        m = re.search(r"(\d+)", t.split("/")[-1])
        return (0, int(m.group(1)), t) if m else (1, 0, t)
    return sorted(dict.fromkeys(titles), key=sort_key)


_DISAMBIG_LINE = re.compile(r"^.{1,30}[（(]\S{1,15}[）)]\s*$")


def _looks_like_disambig(text: str) -> bool:
    """pageprops 漏标的手工消歧义页（如「秋夜」）：正文=「篇名（作者）」清单"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 3 or len(text) > 400:
        return False
    hit = sum(1 for l in lines if _DISAMBIG_LINE.match(l))
    return hit / len(lines) >= 0.5


def _fetch_texts(titles: list) -> tuple:
    """批量取纯文本（TextExtracts，每批 ≤20）

    Returns: (texts: {title: text}, disambig: 消歧义页篇名集合)
    消歧义页（如「秋夜」= 多篇同名作品索引页）经 pageprops 识别并剔除，
    否则抓到的是链接清单不是正文。
    """
    out, disambig = {}, set()
    for i in range(0, len(titles), 20):
        batch = titles[i:i + 20]
        data = _api({"action": "query", "prop": "extracts|pageprops",
                     "explaintext": 1, "ppprop": "disambiguation",
                     "redirects": 1, "titles": "|".join(batch)})
        for p in data.get("query", {}).get("pages", {}).values():
            if p.get("pageprops", {}).get("disambiguation"):
                disambig.add(p.get("title", ""))
                continue
            if "missing" in p or not p.get("extract", "").strip():
                continue
            extract = p["extract"].strip()
            if _looks_like_disambig(extract):
                disambig.add(p.get("title", ""))
                continue
            out[p["title"]] = extract
        time.sleep(_SLEEP)
    return out, disambig


_BOILER = re.compile(r"(本作品收錄於|姊妹计划|初版於|維基數據|作者：)")
_SENT_PUNCT = re.compile(r"[。，、！？…；—]")


def _clean_parsed_html(html: str) -> str:
    """action=parse 渲染 HTML → 干净正文（去导航/版权脚注等样板行）

    样板行（页眉导航/标题作者行/页脚版权）都不含句读标点，
    而正文行（含短诗行）必有 —— 按标点逐行过滤，误伤最小。
    """
    html = re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.S | re.I)
    txt = re.sub(r"</(p|div|h\d|li|blockquote|tr|table)>|<br\s*/?>",
                 "\n", html, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = html_mod.unescape(txt)
    lines = []
    for raw in txt.splitlines():
        line = raw.replace("\u200b", "").strip()
        if not line or line in ("←", "→") or _BOILER.search(line):
            continue
        if _SENT_PUNCT.search(line) or len(line) >= 25:
            lines.append(line)
    return "\n".join(lines).strip()


def _fetch_by_parse(titles: list) -> dict:
    """action=parse 单页兜底（ProofreadPage 转录页 TextExtracts 为空）"""
    out = {}
    for t in titles:
        try:
            data = _api({"action": "parse", "page": t, "prop": "text",
                         "redirects": 1})
            html = data.get("parse", {}).get("text", {}).get("*", "")
            body = _clean_parsed_html(html) if html else ""
            if len(body) >= 100:     # 太短 = 空壳/纯索引页，无采集价值
                out[t] = body
        except Exception as e:
            print(f"    [警告] 解析 {t} 失败：{e}")
        time.sleep(1.2)
    return out


def _safe_name(title: str) -> str:
    tail = title.split("/")[-1]
    tail = re.sub(r'[\\/:*?"<>|]', "", tail).strip()
    return tail[:40] or "untitled"


def fetch_work(save_dir: str, spec: dict, dest_root: str, max_pages: int = 0) -> int:
    entries = []    # [(文件名基准, [候选维基篇名])]
    if spec.get("prefix"):
        for t in _subpages(spec["prefix"], 0):
            entries.append((t, [t]))
    author = spec.get("author", "")
    for t in spec.get("pages", []):
        # 独立篇目页名易撞消歧义页 → 依次试裸名与「篇名（作者）」两种括号
        cands = [t] + ([f"{t}（{author}）", f"{t} ({author})"] if author else [])
        entries.append((t, cands))
    if max_pages:
        entries = entries[:max_pages]
    if not entries:
        print(f"  [跳过] {save_dir}：未找到子页或篇目")
        return 0
    all_titles = list(dict.fromkeys(c for _, cs in entries for c in cs))
    texts, disambig = _fetch_texts(all_titles)
    # ProofreadPage 转录页 extracts 为空 → 单页 parse 兜底（消歧义页不值得解析）
    missing = [t for t in all_titles if t not in texts and t not in disambig]
    if missing:
        texts.update(_fetch_by_parse(missing))
    if not texts:
        print(f"  [跳过] {save_dir}：{len(all_titles)} 个候选页均无正文"
              f"（维基文库篇名可能变动，重跑 --only 排查）")
        return 0
    out_dir = os.path.join(dest_root, save_dir)
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for i, (base, cands) in enumerate(entries, 1):
        pick = next((c for c in cands if c in texts), None)
        if not pick:
            continue
        path = os.path.join(out_dir, f"{i:03d}_{_safe_name(base)}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(texts[pick] + "\n")
        n += 1
    print(f"  [完成] {save_dir}：{n}/{len(entries)} 篇 → {out_dir}")
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="抓取公有领域中文经典 → tests/corpus_pd/")
    ap.add_argument("--list", action="store_true", help="只列书目与版权依据")
    ap.add_argument("--only", default="", help="只抓子串匹配的目录（如 野草）")
    ap.add_argument("--max", type=int, default=0, help="每部作品最多抓 N 篇（0=不限）")
    ap.add_argument("--dest", default=DEFAULT_DEST, help="落盘根目录")
    args = ap.parse_args(argv)

    if args.list:
        for save_dir, spec, basis in WORKS:
            src = ("索引页子页：" + ",".join(spec.get("prefix", []))
                   if spec.get("prefix") else f"独立篇目 {len(spec.get('pages', []))} 篇")
            print(f"{save_dir:<16} ← zh.wikisource {src}（{basis}）")
        return 0

    works = [(d, s, b) for d, s, b in WORKS if args.only in d]
    if not works:
        print(f"没有匹配 --only '{args.only}' 的书目（--list 查看全部）")
        return 1
    os.makedirs(args.dest, exist_ok=True)
    total = 0
    for save_dir, spec, basis in works:
        print(f"[抓取] {save_dir}（{basis}）…")
        try:
            total += fetch_work(save_dir, spec, args.dest, args.max)
        except Exception as e:
            print(f"  [失败] {save_dir}：{e}")
    manifest = {"source": API, "license": "public domain",
                "note": "由 scripts/fetch_pd_corpus.py 生成，勿手工编辑",
                "works": [d for d, _, _ in works]}
    with open(os.path.join(args.dest, "corpus_manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n合计 {total} 篇，落盘 {args.dest}")
    if total == 0:
        print("（0 篇：检查网络或维基文库可达性；脚本本身可用 --list 验证）")
    return 0 if total else 2


if __name__ == "__main__":
    raise SystemExit(main())
