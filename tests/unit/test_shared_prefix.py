# -*- coding: utf-8 -*-
"""共享前缀架构（体验轮 A1'）：逐字节稳定性是缓存命中的地基"""
import os
import time

from app import project
from app.core.shared_prefix import project_header, constraints_block


def _mk_proj(tmp_path, core="核心设定", regex="# 正则\n- 规则：测试｜level：must", wb="## 世界书\n- **斗气**：能量。\n  [常驻]"):
    proj = tmp_path / "前缀书"
    for d in ("设定", "大纲", "正文", "追踪"):
        (proj / d).mkdir(parents=True)
    project.write_file(str(proj / "设定" / "题材定位.md"), core)
    project.write_file(str(proj / "设定" / "正则.md"), regex)
    project.write_file(str(proj / "设定" / "世界书.md"), wb)
    return str(proj)


def test_header_deterministic_within_process(tmp_path):
    proj = _mk_proj(tmp_path)
    a = project_header(proj)
    b = project_header(proj)
    assert a == b and a, "进程内两次构造必须逐字节一致"


def test_header_contains_core_components(tmp_path):
    proj = _mk_proj(tmp_path, core="## 核心设定\n## 金手指约束条款\n- 单层\n## 授权自创清单\n- 能力轮")
    h = project_header(proj)
    assert "正则契约" in h and "测试" in h, "must 全文进头部"
    assert "常驻条目" in h and "斗气" in h, "世界书常驻进头部"
    assert "金手指约束条款" in h and "授权自创清单" in h, "约束注入进头部"
    assert "全局写作纪律" in h, "句式纪律进头部"


def test_header_invalidates_when_source_changes(tmp_path):
    proj = _mk_proj(tmp_path, core="核心设定 V1")
    h1 = project_header(proj)
    assert "V1" in h1
    target = os.path.join(proj, "设定", "题材定位.md")
    project.write_file(target, "核心设定 V2")
    os.utime(target, (time.time() + 5, time.time() + 5))   # 显式推进 mtime，避开同刻度抖动
    h2 = project_header(proj)
    assert "V2" in h2 and h2 != h1, "源文件变更即失效重建"


def test_constraints_block_sections(tmp_path):
    proj = _mk_proj(tmp_path, core="### 金手指约束条款\n- 单层\n### 全局红线\n- 禁拟人\n### 授权自创清单\n- 能力轮")
    c = constraints_block(proj)
    assert "金手指约束条款" in c and "全局红线" in c and "授权自创清单" in c
    assert "单层" in c and "能力轮" in c
