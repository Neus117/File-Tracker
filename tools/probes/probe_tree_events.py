"""真双击导航窗格里的文件时，wx **到底发了哪些事件**。

## 为什么必须问这个

`probe_real_dblclick.py` 的结果：

```
真双击后：on_dir_item_activated 被调用 = **没有**
          焦点 = DirectoryTree
          列表行数没变、没有选中
```

⇒ **`wx.EVT_TREE_ITEM_ACTIVATED` 在 Windows 上双击时不发。**
上一轮我改的 `_focus_pane` 那一行**根本执行不到** —— 所以用户回"没修好"，
而我的探针却是绿的，因为探针**自己造了那个不会被发出的事件**。

这又是 `01` 错误一（测试走顺手的那条路）。这次连"事件存在吗"都没验。

## 本探针做什么

在树上把**所有**可能相关的事件都挂上探针，然后发一次**真双击**，
看哪些事件真的到了。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

user32 = ctypes.windll.user32
send_message = user32.SendMessageW
send_message.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                         ctypes.c_void_p, ctypes.c_void_p]
send_message.restype = ctypes.c_void_p

WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0201, 0x0202, 0x0203
MK_LBUTTON = 0x0001


def pump(rounds: int = 25, pause: float = 0.005) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def item_point(tree, item):
    rect = tree.GetBoundingRect(item)
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return None
    return rect.x + max(rect.width // 6, 8), rect.y + rect.height // 2


def send_double_click(tree, item, *, with_dblclk: bool = True) -> bool:
    point = item_point(tree, item)
    if point is None:
        return False
    x, y = point
    hwnd = ctypes.c_void_p(tree.GetHandle())
    lparam = ctypes.c_void_p((y << 16) | (x & 0xFFFF))
    send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(MK_LBUTTON), lparam)
    send_message(hwnd, WM_LBUTTONUP, None, lparam)
    if with_dblclk:
        send_message(hwnd, WM_LBUTTONDBLCLK, ctypes.c_void_p(MK_LBUTTON), lparam)
    send_message(hwnd, WM_LBUTTONUP, None, lparam)
    return True


#: 要挂探针的事件。**一个都不能漏** —— 漏掉的那个可能正是程序该用的。
EVENTS = [
    ("EVT_TREE_ITEM_ACTIVATED", wx.EVT_TREE_ITEM_ACTIVATED),
    ("EVT_TREE_SEL_CHANGED", wx.EVT_TREE_SEL_CHANGED),
    ("EVT_TREE_SEL_CHANGING", wx.EVT_TREE_SEL_CHANGING),
    ("EVT_TREE_ITEM_EXPANDED", wx.EVT_TREE_ITEM_EXPANDED),
    ("EVT_TREE_ITEM_EXPANDING", wx.EVT_TREE_ITEM_EXPANDING),
    ("EVT_LEFT_DOWN", wx.EVT_LEFT_DOWN),
    ("EVT_LEFT_UP", wx.EVT_LEFT_UP),
    ("EVT_LEFT_DCLICK", wx.EVT_LEFT_DCLICK),
    ("EVT_TREE_KEY_DOWN", wx.EVT_TREE_KEY_DOWN),
    ("EVT_SET_FOCUS", wx.EVT_SET_FOCUS),
    ("EVT_KILL_FOCUS", wx.EVT_KILL_FOCUS),
    ("EVT_TREE_ITEM_GETTOOLTIP", wx.EVT_TREE_ITEM_GETTOOLTIP),
    ("EVT_MOTION", wx.EVT_MOTION),
]

observed: list[str] = []

with probe_temp("probe-tree-events") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(10):
        seed.record_access(os.path.join(scratch, f"dir-{i:03d}"))
    seed.close()

    victim_file = os.path.join(scratch, "target-file.txt")
    with open(victim_file, "w", encoding="utf-8") as handle:
        handle.write("probe\n")

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(50)

    tree = frame.dir_ctrl.GetTreeCtrl()

    def spy(label):
        def handler(event):
            try:
                item = event.GetItem()
                detail = frame.dir_ctrl.GetPath(item)[-26:]
            except Exception:
                detail = "-"
            observed.append(f"{label}  item={detail}")
            # **不 Skip 的部分要小心**：Skip 让原生默认行为继续；
            # 这里全部 Skip，避免探针改变行为。
            event.Skip()
        return handler

    # **先把程序原来的绑定摘掉**，否则它的处理器会先跑（这里的目的是"看事件"）
    try:
        tree.Unbind(wx.EVT_TREE_ITEM_ACTIVATED)
    except Exception:
        pass
    for label, event_type in EVENTS:
        tree.Bind(event_type, spy(label))

    try:
        item = tree.expand_to(victim_file, select=True)
        if item is None or not item.IsOk():
            print("（树里定位不到该文件，改用父目录）")
            item = tree.expand_to(scratch, select=True)
        tree.EnsureVisible(item)
        pump(25)
        print(f"目标项 = {frame.dir_ctrl.GetPath(item)[-30:]}")
        print(f"项的屏幕客户区点 = {item_point(tree, item)}")

        tree.SetFocus()
        pump(15)
        observed.clear()

        print("\n── 发一次**真双击**（DOWN/UP/DBLCLK/UP）──")
        send_double_click(tree, item, with_dblclk=True)
        pump(40)
        print(f"收到 {len(observed)} 个事件：")
        for line in observed:
            print(f"   {line}")

        first = list(observed)
        observed.clear()

        print("\n── 再发一次**两次单击**（DOWN/UP/DOWN/UP，没有 DBLCLK）──")
        send_double_click(tree, item, with_dblclk=False)
        pump(40)
        print(f"收到 {len(observed)} 个事件：")
        for line in observed:
            print(f"   {line}")

        print("\n── 结论 ──")
        has_activated = any("ACTIVATED" in line for line in first)
        print(f"  真双击会发 EVT_TREE_ITEM_ACTIVATED 吗？ {'会' if has_activated else '**不会**'}")
        if not has_activated:
            print("  ⇒ 程序里 `tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, "
                  "self.on_dir_item_activated)` **收不到双击**，")
            print("     所以双击文件那条路**根本不走 `on_dir_item_activated`**。")
            dbl = [line for line in first if "LEFT_DCLICK" in line]
            print(f"  真双击发的是：{dbl or '（LEFT_DCLICK 也没收到）'}")
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)
