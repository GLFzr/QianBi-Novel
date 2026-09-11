# -*- coding: utf-8 -*-
"""演示内容包加载与校验（0.20.0 演示引导）

内容包 = assets/demo/（开发态与 PyInstaller 打包态都经 main.resource_path 解析）：
    pack.json      书目元数据 + 预算
    script.json    引导步骤脚本（全部小字文案）
    book/          逐阶段落盘的真实产物（演示时拷入演示书）
    replay/        回放素材（真实日志行 / 去味对照 / 审校票 / 共写对话）

任何校验不过都返回 None——演示是个增强功能，包坏了绝不能挡住应用启动。
"""
import json
import os
import sys


def resource_path(rel: str) -> str:
    """开发态=仓库根；PyInstaller 打包态=sys._MEIPASS（与 app.main.resource_path 同口径；
    这里本地复制一份，避免 ui → main 的循环导入）"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), rel)


class DemoPack:
    """只读内容包。missing() 返回问题清单，空列表 = 可用。"""

    def __init__(self, base: str):
        self.base = base
        self.pack = self._json("pack.json")
        self.script = self._json("script.json")
        self.deslop = self._json(os.path.join("replay", "deslop.json"))
        self.review = self._json(os.path.join("replay", "review.json"))
        self.cw = self._json(os.path.join("replay", "cw_dialogue.json"))
        self.run_log = self._text(os.path.join("replay", "run_log.txt"))

    # ---- 构造 ----

    @classmethod
    def load(cls):
        base = resource_path(os.path.join("assets", "demo"))
        if not os.path.isdir(base):
            return None
        try:
            pack = cls(base)
        except Exception:  # noqa: BLE001
            return None
        return pack if not pack.missing() else None

    def _json(self, rel: str):
        with open(os.path.join(self.base, rel), encoding="utf-8") as f:
            return json.load(f)

    def _text(self, rel: str) -> str:
        with open(os.path.join(self.base, rel), encoding="utf-8") as f:
            return f.read()

    # ---- 访问 ----

    @property
    def book_meta(self) -> dict:
        return self.pack.get("book") or {}

    @property
    def ch1(self) -> dict:
        """第 1 章元数据 {rel, file, title, words}——章名自适应（0.19.7）：
        演示书可整体替换，不再硬编码 0.19.6 时代《撕纸角》文件名。"""
        import re as _re
        d = os.path.join(self.base, "book", "正文")
        fn = ""
        if os.path.isdir(d):
            for x in sorted(os.listdir(d)):
                if _re.match(r"^第001章_.+\.md$", x):
                    fn = x
                    break
        text = self._text(os.path.join("book", "正文", fn)) if fn else ""
        m = _re.search(r"#\s*第1章\s*(\S+)", text)
        title = m.group(1) if m else "种子书"
        words = sum(1 for c in text if "一" <= c <= "鿿")
        return {"rel": os.path.join("正文", fn), "file": fn,
                "title": title, "words": words}

    @property
    def steps(self) -> list:
        return (self.script or {}).get("steps") or []

    def book_file(self, rel: str) -> str:
        """book/ 内产物全文"""
        return self._text(os.path.join("book", rel))

    def book_has(self, rel: str) -> bool:
        return os.path.isfile(os.path.join(self.base, "book", rel))

    def log_lines(self) -> list:
        return [ln for ln in (self.run_log or "").splitlines() if ln.strip()]

    def cw_turn(self, i: int) -> dict:
        turns = self.cw or []
        return turns[i] if 0 <= i < len(turns) else {}

    # ---- 校验 ----

    def missing(self) -> list:
        """可用性问题清单；空 = 可用"""
        probs = []
        if not isinstance(self.pack, dict) or not self.pack.get("book"):
            probs.append("pack.json 缺 book 元数据")
        steps = self.steps
        if not steps:
            probs.append("script.json 无步骤")
        ids = [s.get("id") for s in steps]
        if len(ids) != len(set(ids)):
            probs.append("script.json 步骤 id 重复")
        for s in steps:
            if s.get("mode") not in ("user_click", "user_click_cw", "button_next",
                                     "auto", "fill_seq", "replay", "finish"):
                probs.append(f"步骤 {s.get('id')} 未知 mode")
        for rel in ["设定/题材定位.md", "大纲/大纲.md", "大纲/细纲_第001章.md"]:
            if not self.book_has(rel):
                probs.append(f"book/ 缺 {rel}")
        if not self.book_has(self.ch1["rel"]):
            probs.append("book/ 缺 第1章正文（正文/第001章_*.md）")
        if not self.deslop or not self.deslop.get("before"):
            probs.append("replay/deslop.json 缺对照内容")
        if not self.cw:
            probs.append("replay/cw_dialogue.json 为空")
        return probs
