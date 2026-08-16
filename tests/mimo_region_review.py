# -*- coding: utf-8 -*-
"""部位级 MiMo 评审：文件名即部位名，提示词明确告知看的是哪个部位，要求只报硬伤"""
import base64
import httpx
import os
import re
import time

KEY = os.environ.get("MIMO_KEY", "")
BASE = "https://api.xiaomimimo.com/v1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "tests_output", "ui_regions")
OUT = os.path.join(ROOT, "tests_output", "ui_regions_评审.md")

PROMPT = """这是小说写作应用（深色现代工具风）中「{region}」这一部位的单独截图。
请只评审此部位，只找【硬伤】，每条必须具体到位置：
- 文字重叠 / 被截断 / 乱码 / 错别字
- 元素重叠 / 溢出容器 / 越界
- 明显未对齐（同类元素基线/左缘不齐）
- 可读性缺陷（对比度过低、字号过小到不可读）
- 控件残缺（按钮/图标/复选框渲染缺失）
输出格式：
【问题】
- <位置>: <问题>
（若此部位无硬伤，输出：【无硬伤】）
不要给泛泛的美学建议，只报上面五类硬伤。"""


def ask(img_path, region):
    b64 = base64.b64encode(open(img_path, "rb").read()).decode()
    payload = {"model": "mimo-v2.5", "max_tokens": 3000, "messages": [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
            {"type": "text", "text": PROMPT.replace("{region}", region)}]}]}
    for _ in range(3):
        try:
            r = httpx.post(BASE + "/chat/completions", json=payload,
                           headers={"Authorization": "Bearer " + KEY}, timeout=180)
            if r.status_code == 200:
                c = r.json()["choices"][0]["message"]["content"] or ""
                if c.strip():
                    return c
            else:
                print("http", r.status_code, flush=True)
        except Exception as e:
            print("err", str(e)[:60], flush=True)
        time.sleep(4)
    return "(失败)"


def main():
    files = sorted(f for f in os.listdir(DIR) if f.endswith(".png") and "--" in f)
    lines = ["# 部位级 UI 硬伤评审（文件名=部位）", ""]
    issues = []
    for f in files:
        region = f.replace(".png", "")
        print("reviewing", region, flush=True)
        out = ask(os.path.join(DIR, f), region)
        lines += [f"## {region}", "", out, "", "---", ""]
        if "无硬伤" not in out:
            for m in re.finditer(r"-\s*(.+)", out):
                issues.append((region, m.group(1).strip()))
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n\n## 硬伤汇总\n" +
                     "\n".join(f"- {r}: {i}" for r, i in issues))
        time.sleep(1)
    print(f"ISSUES {len(issues)}", flush=True)


if __name__ == "__main__":
    main()
