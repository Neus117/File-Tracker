"""给探针脚本用的临时目录助手：**保证用完删掉，且删不掉也不留垃圾**。

## 为什么需要这个

用户反馈："你怎么每次打开的测试窗口都不关，我桌面上一堆 target-folder"。

查下来是两个原因叠加：

① 验证脚本在走"地址栏回车"那条路时，**真的调用了 `open_folder`**，
   于是每次验证都会打开一个真实的资源管理器窗口。用户桌面上那一堆
   就是它们。**资源管理器窗口还会占住目录**，导致
   `tempfile.TemporaryDirectory` 的自动清理失败，临时目录留在盘上。

② 各个探针用 `tempfile.mkdtemp()`（**不带清理**），跑一次留一个。
   实测 `%TEMP%` 下积了 19 个 `probe-*` / `shot-*` 目录。

## 用法

```python
from _probe_temp import probe_temp

with probe_temp("probe-focus") as scratch:
    ...  # scratch 是一个目录路径
# 退出 with 时自动删除；删不掉会打印一行说明，而不是静默留下垃圾
```

**探针一律用这个，不要再用 `tempfile.mkdtemp()`。**
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile


@contextlib.contextmanager
def probe_temp(prefix: str = "probe"):
    """建一个临时目录，退出时**尽力删除并报告结果**。

    删除失败（例如有资源管理器窗口占着）时会打印一行警告，
    而不是像 `tempfile.TemporaryDirectory` 那样抛异常或被静默忽略。
    """
    path = tempfile.mkdtemp(prefix=f"{prefix}-")
    try:
        yield path
    finally:
        try:
            shutil.rmtree(path)
        except OSError as error:
            # 不抛异常：探针的结论比清理失败更重要。
            # 但**必须说出来**，否则又变成"靠我记得去清"。
            print(f"  [清理失败] {path}  ({error})")
            print("             多半是资源管理器窗口正占着这个目录；"
                  "关掉窗口后手动删。")


def open_in_explorer_stub(record: list | None = None):
    """`open_folder` 的替身：**只记录，不真的开窗口**。

    验证脚本里凡是要走"地址栏回车"那条路的地方，都必须把
    `frame.open_folder` 换成它，否则每跑一次验证就在用户桌面上
    开一个资源管理器窗口。
    """

    def stub(path: str) -> None:
        if record is not None:
            record.append(path)

    return stub
