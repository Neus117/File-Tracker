"""兼容垫片：旧入口 ``src/File Tracker_v1.1.py`` 的替代。

**这里没有任何业务逻辑。** 真正的实现全在 :mod:`file_tracker` 包里——
重复一份代码就是重复一份缺陷。

保留它的唯一理由是**升级路径**：如果你有指向旧文件名的快捷方式、任务计划或
命令行历史，它们不会因为这次重构而失效。下一轮可以删掉它。

新入口是 ``src/main.py``::

    python src/main.py

这个文件名带空格，**不可能被 import**（``from "File Tracker_v1.1" import ...``
这种写法不存在），这正是本次把它换掉的原因之一。
"""

from __future__ import annotations

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

warnings.warn(
    "src/File Tracker_v1.1.py 已废弃，请改用 src/main.py。"
    "这个文件只是兼容垫片，不含任何实现。",
    DeprecationWarning,
    stacklevel=1,
)

from file_tracker.app import main  # noqa: E402 - 必须在 sys.path 调整之后导入

if __name__ == "__main__":
    raise SystemExit(main())
