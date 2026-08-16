# -*- coding: utf-8 -*-
"""小说导出：文件格式对齐主流阅读/发布生态

- txt：番茄 / 起点 / 晋江等作者后台上传标准（UTF-8，每章 "第X章 章名" 分节）
- epub：通用电子书格式（EPUB 3，zip 容器，所有阅读器可导入）

内部存储保持 markdown（流水线/追踪依赖），导出时转换。
"""
import html
import os
import re
import time
import zipfile

from . import project


# ============ TXT 导出（平台上传标准）============

def export_txt(proj: str, out_path: str = "") -> str:
    """按章节顺序合并导出 txt。返回输出路径。"""
    chapters = project.list_chapters(proj)
    if not chapters:
        raise ValueError("没有可导出的章节")
    out_path = out_path or os.path.join(proj, f"{os.path.basename(proj)}_全本.txt")
    lines = [f"《{os.path.basename(proj)}》", ""]
    for num, name, path in chapters:
        title = _chapter_title(name, num)
        text = project.read_file(path)
        # 去掉 markdown 标题行（用统一分节行代替）
        text = re.sub(r"^#\s*第\s*\d+\s*章[^\n]*\n+", "", text, flags=re.M)
        lines.append(f"第{num}章 {title}")
        lines.append("")
        lines.append(text.strip())
        lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def _chapter_title(name: str, num: int) -> str:
    """从文件名提取章名：第001章_遗物袋里那支完好的钢笔 → 遗物袋里那支完好的钢笔"""
    m = re.match(r"第\d+章_?(.+)\.md$", name)
    return m.group(1).strip() if m and m.group(1) else f"第{num}章"


# ============ EPUB 3 导出（阅读器标准）============

_EPUB_NS = "http://www.idpf.org/2007/opf"
_XHTML_TPL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
<head><title>{title}</title>
<meta charset="utf-8"/>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<h2>{title}</h2>
{body}
</body>
</html>"""

_STYLE_CSS = """body { font-family: serif; line-height: 1.8; margin: 5% 6%; }
h2 { text-align: center; font-size: 1.3em; margin-bottom: 1.2em; }
p { text-indent: 2em; margin: 0.4em 0; }
"""


def _md_to_xhtml(text: str) -> str:
    """把章节 markdown 转成 epub 正文（xhtml 片段）"""
    # 去掉标题行
    text = re.sub(r"^#\s*第\s*\d+\s*章[^\n]*\n+", "", text, flags=re.M)
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    body = []
    for p in paras:
        if p.startswith("> "):
            body.append(f'<blockquote><p>{html.escape(p[2:])}</p></blockquote>')
        elif p.startswith(("- ", "* ")):
            items = "".join(f"<li>{html.escape(x.lstrip('-* '))}</li>" for x in p.splitlines())
            body.append(f"<ul>{items}</ul>")
        else:
            # 单行内换行合并为空格，保持段落
            one = html.escape(re.sub(r"\s*\n\s*", "", p))
            body.append(f"<p>{one}</p>")
    return "\n".join(body)


def export_epub(proj: str, out_path: str = "") -> str:
    """导出 EPUB 3（无第三方依赖，zipfile 手写容器）。返回输出路径。"""
    chapters = project.list_chapters(proj)
    if not chapters:
        raise ValueError("没有可导出的章节")
    out_path = out_path or os.path.join(proj, f"{os.path.basename(proj)}.epub")
    book_name = os.path.basename(proj)
    uid = f"qianbi-{int(time.time())}"
    chapter_files = []

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 1. mimetype（必须第一个、不压缩）
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        z.getinfo("mimetype").compress_type = zipfile.ZIP_STORED

        # 2. 样式
        z.writestr("OEBPS/style.css", _STYLE_CSS)

        # 3. 每章 XHTML
        for num, name, path in chapters:
            title = _chapter_title(name, num)
            body = _md_to_xhtml(project.read_file(path))
            fname = f"chap_{num:04d}.xhtml"
            z.writestr(f"OEBPS/{fname}",
                       _XHTML_TPL.format(title=html.escape(title), body=body))
            chapter_files.append((fname, title))

        # 4. content.opf
        manifest = "\n".join(
            f'    <item id="c{i}" href="{fn}" media-type="application/xhtml+xml"/>'
            for i, (fn, _) in enumerate(chapter_files)) + "\n"
        manifest += '    <item id="css" href="style.css" media-type="text/css"/>'
        spine = "\n".join(f'    <itemref idref="c{i}"/>' for i in range(len(chapter_files)))
        first_title = html.escape(chapter_files[0][1] if chapter_files else book_name)
        opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="{_EPUB_NS}" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
    <dc:title>{html.escape(book_name)}</dc:title>
    <dc:language>zh-CN</dc:language>
    <dc:creator>千笔一文 Novel</dc:creator>
    <meta property="dcterms:modified">{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}</meta>
  </metadata>
  <manifest>
{manifest}
  </manifest>
  <spine>
{spine}
  </spine>
</package>"""
        z.writestr("OEBPS/content.opf", opf)

        # 5. nav 与 container
        nav_items = "\n".join(
            f'    <li><a href="{fn}">{html.escape(t)}</a></li>'
            for fn, t in chapter_files)
        nav = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目录</title></head>
<body>
<nav epub:type="toc"><h1>目录</h1><ol>
{nav_items}
</ol></nav>
</body>
</html>"""
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")
    return out_path


def export_project(proj: str, fmt: str = "txt", out_path: str = "") -> str:
    """统一入口。fmt: txt / epub"""
    fmt = (fmt or "txt").lower()
    if fmt == "epub":
        return export_epub(proj, out_path)
    return export_txt(proj, out_path)
