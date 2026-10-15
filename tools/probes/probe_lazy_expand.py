"""临时诊断：GenericDirCtrl 的树是懒加载的，展开顺序如何影响子项可见性。"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()
frame = wx.Frame(None, title="probe2")
ctrl = wx.GenericDirCtrl(frame, -1, style=wx.DIRCTRL_3D_INTERNAL)
tree = ctrl.GetTreeCtrl()


def children(item):
    out = []
    child, cookie = tree.GetFirstChild(item)
    while child.IsOk():
        out.append((tree.GetItemText(child), child))
        child, cookie = tree.GetNextChild(item, cookie)
    return out


root = tree.GetRootItem()
drives = children(root)
print("根的子项：", [name for name, _ in drives])

c_item = next(item for name, item in drives if "(C:)" in name)

print("\n--- 展开 C: 之前，它的子项 ---")
before = children(c_item)
print("  ", [name for name, _ in before] or "（无）")

print("\n--- 调用 Expand(C:) ---")
tree.Expand(c_item)
for tick in range(3):
    time.sleep(0.05)
    wx.YieldIfNeeded()
    after = children(c_item)
    print(f"  +{(tick + 1) * 50}ms: {len(after)} 项 -> {[n for n, _ in after][:8]}")

print("\n--- 展开 C:\\Users 之后它的子项 ---")
users = next((item for name, item in children(c_item) if name.casefold() == "users"), None)
if users is None:
    print("  找不到 Users 节点")
else:
    tree.Expand(users)
    time.sleep(0.1)
    wx.YieldIfNeeded()
    names = [name for name, _ in children(users)]
    print(f"  {len(names)} 项 -> {names[:8]}")

    print("\n--- 逐个 Expand 的耗时（Users 下每一级）---")
    start = time.perf_counter()
    node = users
    for _ in range(25):
        kids = children(node)
        if not kids:
            break
        node = kids[0][1]
        tree.Expand(node)
        wx.YieldIfNeeded()
    print(f"  展开 25 级耗时 {time.perf_counter() - start:.3f}s")

frame.Destroy()
