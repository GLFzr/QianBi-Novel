# -*- coding: utf-8 -*-
"""MiMo-V2.5 逐屏 UI 评审：25 张审计截图逐一打分+找缺陷"""
import base64
import httpx
import os
import sys
import time

KEY = os.environ.get("MIMO_KEY", "")
BASE = "https://api.xiaomimimo.com/v1"
DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests_output", "ui_audit")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests_output", "ui_audit_评审_round3.md")

PROMPT = """这是小说写作应用的界面截图（应用主界面目标审美=VS Code/ZCode/Linear 现代开发工具风；
若截图是「阅读模式」且为羊皮纸/纯白底色，那是刻意设计的阅读主题，按成熟小说阅读器标准评分，不要因为浅色扣分）。
请严格评审 UI：
1) 打分（1-10，以现代商业软件为标准，吝啬给分）
2) 列出所有显得廉价/过时/不协调的具体元素（对齐问题、边框滥用、字号层级混乱、间距失衡、图标风格不一、颜色突兀、中文排版问题等），每条指出位置
3) 一句最值得改的改进
直接输出，格式：【分数】x/10\\n【问题】- …\\n【最该改】…"""


def ask(img_path):
    b64 = base64.b64encode(open(img_path, "rb").read()).decode()
    payload = {"model": "mimo-v2.5", "max_tokens": 5000, "messages": [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
            {"type": "text", "text": PROMPT}]}]}
    for attempt in range(3):
        try:
            r = httpx.post(BASE + "/chat/completions", json=payload,
                           headers={"Authorization": "Bearer " + KEY}, timeout=180)
            if r.status_code == 200:
                c = r.json()["choices"][0]["message"]["content"] or ""
                if c.strip():
                    return c
            else:
                print("http", r.status_code, r.text[:100], flush=True)
        except Exception as e:
            print("err", str(e)[:80], flush=True)
        time.sleep(5)
    return "(评审失败)"


def main():
    files = sorted(f for f in os.listdir(DIR) if f.endswith(".png"))
    lines = ["# UI 全量审计评审（MiMo-V2.5 逐屏）", ""]
    scores = []
    for f in files:
        print("reviewing", f, flush=True)
        out = ask(os.path.join(DIR, f))
        try:
            s = int(out.split("/10")[0].split("】")[-1].strip().replace("x", "").replace(" ", ""))
            scores.append((f, s))
        except Exception:
            scores.append((f, -1))
        lines += [f"## {f}", "", out, "", "---", ""]
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        time.sleep(2)
    avg = sum(s for _, s in scores if s > 0) / max(1, len([s for _, s in scores if s > 0]))
    lines += ["", f"## 均分：{avg:.1f}/10", ""] + [f"- {n}: {s}/10" for n, s in scores]
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("AVG", round(avg, 1), flush=True)


if __name__ == "__main__":
    main()
