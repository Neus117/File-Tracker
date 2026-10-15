"""启动 File Tracker。

用法::

    python src/main.py
"""

from __future__ import annotations

import os
import sys

# 允许直接 `python src/main.py` —— 此时 sys.path[0] 是 src/，包能正常导入；
# 但若从别处以 `python -m` 方式运行到别的目录，这里补上 src/ 保证导入成立。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from file_tracker.app import main  # noqa: E402 - 必须在 sys.path 调整之后导入

if __name__ == "__main__":
    raise SystemExit(main())
