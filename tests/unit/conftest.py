# -*- coding: utf-8 -*-
"""单测引导：把仓库根目录加入 sys.path，保证 `from app import ...` 可导入"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
