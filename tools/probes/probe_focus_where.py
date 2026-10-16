"""量：从导航窗格「打开」之后，**键盘焦点落在哪个控件**。

## 用户

"导航窗格中打开后聚焦选中为什么是**浅灰色**？"

## 假设（**必须量，不能猜**）

Windows 对**没有键盘焦点**的控件用灰色画选中项（inactive selection）。
如果打开之后焦点跑到了别处（比如「打开」按钮、或右侧列表），
树的选中项就会是灰的。

**但也有别的可能**：
* 树本来就没拿到焦点（点按钮不会把焦点给树）
* 是我们某处调用把焦点挪走了
* 或者树的选中项根本不是"选中"，而是别的东西

**判据**：直接问 `FindFocus()` 是谁，并给出它属于哪一边。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

COUNT = 40


def settle(times: int = 20) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def who_has_focus(frame) -> str:
    """焦点在谁身上 —— 用名字回答，不用句柄。"""
    focused = wx.Window.FindFocus()
    if focused is None:
        return "（没有焦点）"
    tree = frame.dir_ctrl
    if focused is tree:
        return "导航树"
    if focused is frame.list_ctrl:
        return "记录列表"
    for name, widget in (("「打开」按钮", getattr(frame, "open_button", None)),
                         ("「清空」按钮", getattr(frame, "clear_button", None)),
                         ("地址栏", getattr(frame, "path_bar", None))):
        if widget is not None and focused is widget:
            return name
    return f"{type(focused).__name__} <{focused.GetName()}>"


with probe_temp("probe-focus-where") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(COUNT):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    newone = os.path.join(scratch, "opened-from-tree")
    os.makedirs(newone, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(50)

    tree = frame.dir_ctrl
    item = tree.expand_to(scratch, select=True)
    # **把焦点明确给树**（模拟"用户在树里点了一下"）
    tree.SetFocus()
    settle(20)
    print(f"  用户刚点过树之后，焦点在：**{who_has_focus(frame)}**")
    print(f"  树的选中项 = {tree.GetItemText(tree.GetSelection())!r}")
    print()

    frame._focus_pane = "tree"
    frame.record_accessed_path(newone)
    settle(40)

    print(f"  从导航窗格记录之后，焦点在：**{who_has_focus(frame)}**")
    print(f"  树的选中项 = {tree.GetItemText(tree.GetSelection())!r}")
    sel = frame.list_ctrl.GetFirstSelected()
    print(f"  列表选中 = {sel}"
          f"（…{frame._rows[sel].path[-24:] if 0 <= sel < len(frame._rows) else '?'}）")
    print()
    if wx.Window.FindFocus() is tree:
        print("  ⇒ 树**仍有焦点** —— 那灰色就不是 inactive selection，要另找原因")
    else:
        print("  ⇒ 树**失去了焦点** —— 灰色是 Windows 的 inactive selection，"
              "标准行为")

    frame.store.close()
    frame.Destroy()
