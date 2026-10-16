"""复现**真实的一次「打开」按钮点击**，看记录器那条的行底色到底是什么。

## 为什么上一版探针不算数

我上一版直接调 `record_accessed_path()` —— **那是按钮点击之后的第二步**。
真实路径是：

```
点「打开」按钮 → on_open(event) → open_targets() → record_accessed_path()
                     ↑ 这一步会读 _focus_pane、可能触发别的重绘
```

用户截图里是灰的，探针里是蓝的 ⇒ **差别必在这条链上**。

## 判据

* 让焦点先落在按钮上（模拟"鼠标刚点完按钮"）
* 调**真正的** `on_open(None)`
* 回读：那条记录的行底色是不是 `#0078D7`，以及 `_focus_pane` 到底是什么
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


def settle(times: int = 30) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def hex_of(colour) -> str:
    return f"#{colour.Red():02X}{colour.Green():02X}{colour.Blue():02X}"


with probe_temp("probe-real-open") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    target = os.path.join(scratch, "picked-in-tree")
    os.makedirs(target, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(50)
    ctrl = frame.list_ctrl
    tree = frame.dir_ctrl

    highlight = hex_of(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT))
    print(f"  系统高亮色 = {highlight}")

    # ① 用户先点树（选中一个目录）
    tree.expand_to(scratch, select=True)
    tree.SetFocus()
    settle(15)
    print(f"  点树之后 _focus_pane = {frame._focus_pane!r}")

    # ② 用户点「打开」按钮 —— 焦点转到按钮
    frame.open_btn.SetFocus()
    settle(15)
    print(f"  点按钮之后 _focus_pane = {frame._focus_pane!r}"
          f"  焦点 = {type(wx.Window.FindFocus()).__name__}")

    # ③ **走真正的处理函数**（点按钮触发的就是它）
    for attr, value in (("selected_path", lambda: target),):
        pass
    # 让树选中目标，这样 open_targets() 会取到它
    tree.expand_to(target, select=True)
    settle(10)

    before_sel = ctrl.GetFirstSelected()
    print(f"  打开之前 列表选中 = {before_sel}")
    print()

    try:
        frame.on_open(None)
    except Exception as error:                       # noqa: BLE001
        print(f"  on_open 抛异常：{type(error).__name__}: {error}")
    settle(40)

    after_sel = ctrl.GetFirstSelected()
    after_path = (frame._rows[after_sel].path
                  if 0 <= after_sel < len(frame._rows) else "?")
    colour = hex_of(ctrl.GetItemBackgroundColour(after_sel)) if after_sel >= 0 else "?"

    print(f"  ── 走真正的 on_open 之后 ──")
    print(f"    列表选中 = {after_sel}（…{after_path[-26:]}）")
    print(f"    行底色   = {colour}")
    print(f"    _focus_pane = {frame._focus_pane!r}")
    print(f"    焦点 = {type(wx.Window.FindFocus()).__name__}")
    print()
    if after_path == target and colour == highlight:
        print("  ✅ 与探针一致（蓝） —— 那用户看到的灰可能来自别的路径")
    elif after_path != target:
        print(f"  ❌ **选中的不是刚打开的那条** ⇒ 蓝色自然也不在它身上")
    else:
        print(f"  ❌ 选中对了但底色是 {colour} ⇒ 高亮没画上")

    frame.store.close()
    frame.Destroy()
