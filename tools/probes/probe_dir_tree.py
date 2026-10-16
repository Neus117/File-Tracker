"""验证 `DirectoryTree` 真的能用：图标尺寸、盘符、懒加载、路径反查。

**"能导入"不等于"能用"** —— 本会话反复的教训就是"代码看着对、实际没跑"。
所以要在一个真窗口里把它建出来、量它的图列表、展开一个节点看看。
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
from file_tracker.theme import METRICS, Theme, scale_for_dpi
from file_tracker.widgets import dpi_of

frame = wx.Frame(None, size=(600, 700))
frame.SetBackgroundColour(wx.Colour(Theme.light().card))
tree = DirectoryTree(frame, show_hidden=True)
tree.SetBackgroundColour(wx.Colour(Theme.light().card))
tree.populate()
frame.Show()
for _ in range(40):
    wx.YieldIfNeeded()
    time.sleep(0.01)

dpi = dpi_of(tree)
text_h = tree.GetTextExtent("Ag").height or 1
want = max(int(round(text_h * METRICS.tree_icon_ratio)), 8)

images = tree.GetImageList()
print(f"  DPI = {dpi}，树文字高 = {text_h}，"
      f"tree_icon_ratio = {METRICS.tree_icon_ratio} → 期望 {want} 物理")
print(f"  图列表：{images.GetImageCount()} 张")
w, h = images.GetSize(0)
print(f"  **实际图标尺寸 = {w} x {h}**"
      f"{'  ✅' if w == want and h == want else '  ❌ 与期望不符'}")

row = None
try:
    from file_tracker import win32
    native = tree.GetHandle()
    row = win32.get_tree_item_height(native)
except Exception as error:
    print(f"  行高读取失败：{error}")
if row:
    print(f"  行高 = {row}，**图标 ÷ 行高 = {h / row:.2f}**"
          f"（改前 16/50 = 0.32，Explorer 约 0.73）")

# 盘符
top = [tree.GetItemText(i) for i in tree.iter_top()]
print(f"  顶层节点 {len(top)} 个：{top[:4]}{' …' if len(top) > 4 else ''}")

if top:
    first = next(iter(tree.iter_top()))
    print(f"  展开 {tree.GetItemText(first)!r} …")
    tree.Expand(first)
    for _ in range(30):
        wx.YieldIfNeeded()
    children = []
    child, cookie = tree.GetFirstChild(first)
    while child.IsOk():
        children.append(tree.GetItemText(child))
        child, cookie = tree.GetNextChild(first, cookie)
    print(f"  子节点 {len(children)} 个：{children[:5]}"
          f"{' …' if len(children) > 5 else ''}")

    # 路径反查：这是 `GetPath()` 的核心
    if children:
        target = children[0]
        node, cookie = tree.GetFirstChild(first)
        while node.IsOk():
            if tree.GetItemText(node) == target:
                break
            node, cookie = tree.GetNextChild(first, cookie)
        tree.SelectItem(node)
        print(f"  选中 {target!r} → GetPath() = {tree.GetPath()!r}")
        print(f"  GetPaths() = {tree.GetPaths()}")

tree.Destroy()
frame.Destroy()
