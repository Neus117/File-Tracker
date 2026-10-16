"""验：不同扩展名是否真的拿到**不同图标**，以及没碰坏别的。

## 为什么单独写一条

`_shell_icon` 返回"有效位图"**不等于**"不同扩展名拿到不同图标" ——
必须看**图列表下标是否真的分化**。

（之前那个"全部下标 2"的读数就是被这个区别骗过一次。）
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), 'src'))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)

from file_tracker.dir_tree import DirectoryTree

with probe_temp("probe-icon-index") as scratch:
    frame = wx.Frame(None, size=(400, 600))
    tree = DirectoryTree(frame)
    tree.populate()
    frame.Show()
    for _ in range(20):
        wx.YieldIfNeeded()

    names = ["a.exe", "b.exe", "c.dll", "d.txt", "e.zip", "f.md",
             "g.py", "h.png", "noext"]
    print("  各名字拿到的图标下标：")
    groups: dict = {}
    for name in names:
        index = tree._icon_for(name, False)
        groups.setdefault(index, []).append(name)
        print(f"    {name:<10} -> 下标 {index}")

    print()
    print(f"  **不同图标数 = {len(groups)}**"
          f"（>1 才算真的按扩展名分化了）")
    for index, got in groups.items():
        print(f"    下标 {index}: {got}")

    same_ext = tree._icon_for("x.exe", False) == tree._icon_for("y.exe", False)
    print(f"  同扩展名复用同一张（缓存生效）= {same_ext}")

    print(f"  目录仍走 ICON_FOLDER：{tree._icon_for('some-dir', True)}")
    print(f"  图列表张数 = {tree.GetImageList().GetImageCount()}")

    frame.Destroy()
