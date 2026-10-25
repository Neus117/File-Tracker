"""量 `DirectoryTree` 在**大目录**下的表现，找性能与健壮性问题。

## 为什么要量

`_entries_of` 现在每个条目要调**三次系统调用**：

```python
os.listdir(path)                  # 1 次
os.path.isdir(full)               # 每个条目 1 次
self._is_hidden(full)             # 每个条目 1 次（GetFileAttributesW）
```

`C:\\Windows\\System32` 有上万个条目 —— 那就是几万次系统调用。

`os.scandir` 能在**一次遍历**里拿到"是不是目录"和"属性"（Windows 上
`DirEntry` 直接带 `dwFileAttributes`），**不发额外请求**。

## 判据

直接量耗时。**"我觉得它慢"不算证据。**
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)

from file_tracker.dir_tree import DirectoryTree
from file_tracker.theme import Theme

# 找几个"条目多"的目录来量
CANDIDATES = [
    r"C:\Windows\System32",
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Users",
]
TARGETS = [p for p in CANDIDATES if os.path.isdir(p)][:2]

frame = wx.Frame(None, size=(400, 600))
tree = DirectoryTree(frame, show_hidden=True)
tree.SetBackgroundColour(wx.Colour(Theme.light().card))
tree.populate()
frame.Show()
for _ in range(20):
    wx.YieldIfNeeded()

for target in TARGETS:
    try:
        total = len(os.listdir(target))
    except OSError:
        continue
    item = tree.expand_to(target, select=False)
    if item is None:
        print(f"  {target}: 树里没走到（不在任何盘符下？）")
        continue
    # ⚠️ **必须先把节点从  里摘掉。**
    #
    # 第一版没摘， 直接早退（已经填过），
    # 量出来是 0 ms —— **量了个空操作**，差点据此认为没有性能问题。
    tree._populated.pop(item, None)
    started = time.perf_counter()
    tree._populate_item(item)
    elapsed = time.perf_counter() - started
    kids = tree.GetChildrenCount(item, recursively=False)
    print(f"  {target}")
    print(f"    目录条目 {total} 个 → 建出子节点 {kids} 个")
    print(f"    `_populate_item` 耗时 **{elapsed * 1000:.0f} ms**"
          + ("  ← 超过 100ms 就是可感知的卡顿" if elapsed > 0.1 else ""))

tree.Destroy()
frame.Destroy()
