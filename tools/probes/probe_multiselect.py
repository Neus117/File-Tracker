"""临时诊断：GenericDirCtrl 的树为什么会同时选中"驱动器节点"和"深层节点"。

现象：SelectItem(深层节点) 之后 GetSelections() 返回两项：
  目标文件夹 + 'C:\\'
需要判断这是真实的多选累积，还是多选树的固有行为。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker.tree_nav import TreeWalker, child_names_for_path

app = wx.App()
frame = wx.Frame(None)

print("=== 场景 A：带 DIRCTRL_MULTIPLE（当前实现用的就是它）===")
ctrl = wx.GenericDirCtrl(frame, -1, style=wx.DIRCTRL_3D_INTERNAL | wx.DIRCTRL_MULTIPLE)
tree = ctrl.GetTreeCtrl()
for _ in range(20):
    wx.YieldIfNeeded()

target = r"C:\Users\Neus117"
item = TreeWalker(tree).find_by_names(child_names_for_path(target))
print(f"  找到目标节点: {ctrl.GetPath(item) if item else None}")

tree.SelectItem(item)
for _ in range(20):
    wx.YieldIfNeeded()
print(f"  SelectItem 之后 GetSelections() = "
      f"{[ctrl.GetPath(i) for i in tree.GetSelections()]}")

print()
print("  先 UnselectAll 再 SelectItem：")
tree.UnselectAll()
for _ in range(10):
    wx.YieldIfNeeded()
tree.SelectItem(item)
for _ in range(20):
    wx.YieldIfNeeded()
print(f"  GetSelections() = {[ctrl.GetPath(i) for i in tree.GetSelections()]}")

print()
print("=== 场景 B：不带 DIRCTRL_MULTIPLE ===")
ctrl2 = wx.GenericDirCtrl(frame, -1, style=wx.DIRCTRL_3D_INTERNAL)
tree2 = ctrl2.GetTreeCtrl()
for _ in range(20):
    wx.YieldIfNeeded()

item2 = TreeWalker(tree2).find_by_names(child_names_for_path(target))
print(f"  找到目标节点: {ctrl2.GetPath(item2) if item2 else None}")
tree2.SelectItem(item2)
for _ in range(20):
    wx.YieldIfNeeded()
print(f"  GetSelections() = {[ctrl2.GetPath(i) for i in tree2.GetSelections()]}")
try:
    print(f"  GetSelection()  = {ctrl2.GetPath(tree2.GetSelection())}")
except Exception as exc:  # noqa: BLE001
    print(f"  GetSelection() 抛异常: {exc!r}")

print()
print("=== 场景 C：多次 SelectItem 会不会累积 ===")
for probe in (r"C:\Users", r"C:\Windows"):
    node = TreeWalker(tree).find_by_names(child_names_for_path(probe))
    if node:
        tree.SelectItem(node)
        for _ in range(10):
            wx.YieldIfNeeded()
        print(f"  SelectItem({probe}) -> {[ctrl.GetPath(i) for i in tree.GetSelections()]}")

frame.Destroy()
