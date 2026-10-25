"""量 `DirectoryTree` 对每个盘符**到底解析出什么路径、列出什么子目录**。

## 用户报的两个症状

1. "每个磁盘展开后**下面只有一级**，不能接着展开了"
2. "这一级的**层级还不对**，比如把 D 展开得到的是
   `D:\\Coding\\MyGitHub\\File-Tracker`"

## 第 1 个已经确定

`_populate_item` 里 `AppendItem(...)` 之后**没有再加占位子节点**，
而 `wx.TreeCtrl` 正是靠占位子节点才画展开箭头的 —— 所以走不下去。

## 第 2 个不能猜

当时用 `path_of_label` 查（按文字全局搜索 + 沿父链回拼，全树 O(N)，后来被删掉换成了
`path_of_node`）—— 到底是哪条给出了错的路径，**必须量出来**。

判据：对每个顶层盘符，把 `GetItemText` / `path_of_node` / `os.listdir` 前几项
全部打出来，与真实盘根对照。
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

from file_tracker.dir_tree import DirectoryTree, _as_drive_root
from file_tracker.theme import Theme

frame = wx.Frame(None, size=(500, 700))
tree = DirectoryTree(frame, show_hidden=True)
tree.SetBackgroundColour(wx.Colour(Theme.light().card))
tree.populate()
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()
    time.sleep(0.01)

print('  ── 每个盘符：标签 → 解析出的路径 ──')
for item in tree.iter_top():
    label = tree.GetItemText(item)
    # ⚠️ 原来这里是 `tree.path_of_label(label)` —— 那个方法在换成
    # `path_of_node(item)` 之后就被删了（按文字搜全树是 O(N)，见 dir_tree 的说明）。
    resolved = tree.path_of_node(item)
    via_helper = _as_drive_root(label)
    print(f'    标签 {label!r}')
    print(f'      _as_drive_root  → {via_helper!r}')
    print(f'      path_of_node    → {resolved!r}')
    print(f'      os.path.isdir   → {os.path.isdir(resolved) if resolved else "（空）"}')
    if resolved and os.path.isdir(resolved):
        try:
            names = sorted(os.listdir(resolved))[:6]
            print(f'      实际子目录前 6  → {names}')
        except OSError as error:
            print(f'      listdir 失败    → {error}')
    print(f'      _entries_of    → {tree._entries_of(item)[:6]}')
    print()

# 展开一个盘，看子节点有没有占位（决定能不能再展开）
first = next(iter(tree.iter_top()))
tree._populate_item(first)
print(f'  ── 展开 {tree.GetItemText(first)!r} 后 ──')
child, cookie = tree.GetFirstChild(first)
count = 0
while child.IsOk():
    has_kids = tree.ItemHasChildren(child)
    if count < 5:
        grand = []
        g, gc = tree.GetFirstChild(child)
        while g.IsOk():
            grand.append(tree.GetItemText(g))
            g, gc = tree.GetNextChild(child, gc)
        print(f'    {tree.GetItemText(child)!r:28} '
              f'占位={has_kids}  其子={grand[:2]}')
    count += 1
    child, cookie = tree.GetNextChild(first, cookie)
print(f'    共 {count} 个子节点')

tree.Destroy()
frame.Destroy()
