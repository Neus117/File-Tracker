"""复现**双击导航窗格里的文件**这条唯一的路径（`on_dir_item_activated`）。

## 为什么这是缺的那一次

用户截图里树选中是 **`Black Myth Wukong`（一个文件）** ⇒ 他是**双击文件**打开的。

我此前三个探针测的是：
1. `record_accessed_path()` 直调
2. **点「打开」按钮** → `on_open()`
3. （更早）焦点在哪

**没有一个是"双击树里的文件"** —— 它走的是 `on_dir_item_activated()`，
而且它对文件是：

```python
if os.path.isfile(path):
    folder_to_open = os.path.dirname(path)
    self.open_folder(folder_to_open)
    self.record_accessed_path(folder_to_open)
    self._call_later(100, self.reset_dir_ctrl_scroll)
    event.Veto()
```

**多了 `open_folder()`（会开资源管理器）与 `_call_later(...)` 两步** ——
后者尤其可疑：**它会在 100 ms 后再跑一个回调**，
很可能在那之后又重画了一次高亮。

## 判据

* 双击文件之后，父目录那条的行底色是不是 `#0078D7`
* **并且等 `_call_later` 的回调跑完之后再读一次**（这才是用户看到的终态）
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

results = []


def settle(times: int = 30) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.005)


def hex_of(colour) -> str:
    return f"#{colour.Red():02X}{colour.Green():02X}{colour.Blue():02X}"


def find_row(frame, path: str) -> int:
    return next((i for i, r in enumerate(frame._rows) if r.path == path), -1)


with probe_temp("probe-dbl-file") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    # **造一个"文件夹 + 里面的文件"** —— 模拟用户的 E:\Games + 里面的 exe
    holder = os.path.join(scratch, "Games")
    os.makedirs(holder, exist_ok=True)
    a_file = os.path.join(holder, "Black Myth Wukong.exe")
    with open(a_file, "w", encoding="utf-8") as handle:
        handle.write("x")
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(50)
    ctrl = frame.list_ctrl
    tree = frame.dir_ctrl

    highlight = hex_of(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT))
    print(f"  系统高亮色 = {highlight}")
    print(f"  打开的是文件 = …{a_file[-30:]}")
    print(f"  期望被选中的是它的父目录 = …{holder[-26:]}")
    print()

    # 走到这个目录、展开，拿到文件节点
    node = tree.expand_to(holder, select=False)
    tree._populated.pop(node, None)
    tree._populate_item(node)
    settle()

    file_item = None
    child, cookie = tree.GetFirstChild(node)
    while child.IsOk():
        if tree.GetItemText(child) == os.path.basename(a_file):
            file_item = child
            break
        child, cookie = tree.GetNextChild(node, cookie)
    if file_item is None:
        print("  ❌ 树里找不到那个文件节点，测不了")
    else:
        tree.UnselectAll()
        tree.SelectItem(file_item)
        tree.SetFocus()                       # 模拟"用户刚点过树"
        settle(15)

        # **别真的开资源管理器**
        frame.open_folder = lambda p: None
        frame.confirm_remove_invalid_path = lambda p: None

        class _Evt:
            def GetItem(self):
                return file_item

            def Veto(self):
                pass

            def Skip(self):
                pass

        frame.on_dir_item_activated(_Evt())
        settle(25)

        row = find_row(frame, holder)
        colour_now = hex_of(ctrl.GetItemBackgroundColour(row)) if row >= 0 else "?"

        # **再等 `_call_later` 的回调跑完** —— 用户看到的是这一步之后的终态
        for _ in range(60):
            wx.YieldIfNeeded()
            time.sleep(0.01)
        row2 = find_row(frame, holder)
        sel2 = ctrl.GetFirstSelected()
        colour_later = (hex_of(ctrl.GetItemBackgroundColour(row2))
                        if row2 >= 0 else "?")

        print(f"  父目录在列表第 {row2} 行")
        print(f"    刚打开完（含 _call_later 之前）底色 = {colour_now}")
        print(f"    等 _call_later 跑完（终态）底色   = {colour_later}")
        print(f"    列表选中 = {sel2}"
              f"（…{frame._rows[sel2].path[-24:] if 0 <= sel2 < len(frame._rows) else '?'}）")
        print()

        results.append(("① 双击文件 ⇒ 父目录那条**是蓝色**",
                        colour_later == highlight,
                        f"{colour_later} vs {highlight}"))
        results.append(("② 列表选中的就是那个父目录",
                        sel2 == row2, f"选中 = {sel2}，父目录 = {row2}"))

    frame.store.close()
    frame.Destroy()

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
