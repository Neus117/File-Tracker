"""pytest 配置：把 ``src/`` 放进导入路径。

``src/File Tracker_v1.1.py`` 那个文件名**带空格，不可能被 import**——
原来的 ``tests/test_file_tracker.py`` 写的是 ``from src.file_tracker import MainWindow``，
两个名字都不存在。现在源码在 ``src/file_tracker/`` 这个正规包里，
这里只负责把它找出来。
"""

from __future__ import annotations

import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
