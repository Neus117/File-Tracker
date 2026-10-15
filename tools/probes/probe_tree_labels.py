"""临时诊断：真实的 wx.GenericDirCtrl 树，根节点的子项显示名与 GetPath 结果。

目的：确认我"逐级匹配名称"的假设是否成立，而不是靠猜。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()

frame = wx.Frame(None, title="probe")
ctrl = wx.GenericDirCtrl(frame, -1, style=wx.DIRCTRL_3D_INTERNAL)
tree = ctrl.GetTreeCtrl()


def dump(item, depth, limit=2):
    child, cookie = tree.GetFirstChild(item)
    first = True
    while child.IsOk():
        if depth <= limit:
            label = tree.GetItemText(child)
            try:
                path = ctrl.GetPath(child)
            except Exception as exc:  # noqa: BLE001
                path = f"<GetPath raised {exc!r}>"
            print(f"{'  ' * depth}label={label!r:28} GetPath={path!r}")
        dump(child, depth + 1, limit)
        child, cookie = tree.GetNextChild(item, cookie)


print("=== 根节点的前两层 ===")
dump(tree.GetRootItem(), 1, limit=2)

print("=== 逐级匹配演练 ===")
from file_tracker.tree_nav import TreeWalker, child_names_for_path

walker = TreeWalker(tree)
for probe in [r"C:\Users\Neus117", "C:\\Users", "D:\\"]:
    names = child_names_for_path(probe)
    found = walker.find_by_names(names)
    if found is None:
        print(f"  {probe!r:26} names={names} -> None")
    else:
        print(f"  {probe!r:26} names={names} -> {ctrl.GetPath(found)!r}")

frame.Destroy()
