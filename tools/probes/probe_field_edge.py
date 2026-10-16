"""确认输入框到底有没有 `WS_EX_CLIENTEDGE`，以及去掉之后是否真的没了。

## 为什么这一条能定案

用户给出了**决定性的观察**：

> 框线**右边线、底边线内部**有两条黑色像素；
> 框线**左边线、顶部边线内部**没有。

**这个不对称就是凹陷边框的签名** —— Windows 画 `WS_EX_CLIENTEDGE` 时
用亮色走左上、暗色走右下。

前三次探针都失败了（抓屏读出纯白、样式读取对照不上），
但这条判据**只需要读一个整数**，不依赖抓屏，也不依赖对照：
`WS_EX_CLIENTEDGE` = `0x00000200`，在就是"在"。
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

from file_tracker import win32

GWL_EXSTYLE = -20
WS_EX_CLIENTEDGE = 0x00000200


def read_ex(hwnd: int) -> int:
    return int(ctypes.windll.user32.GetWindowLongW(
        ctypes.c_void_p(hwnd), GWL_EXSTYLE))


with probe_temp("probe-edge") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(3):
        seed.record_access(os.path.join(scratch, f"f{i}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(50):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    tc = frame.path_bar.text_ctrl.GetHandle()
    print(f"  PathBar 铺的父窗口底色 = {frame.theme.background}")
    print(f"  输入框填充            = {frame.theme.surface_alt}")
    print()

    ex = read_ex(tc)
    has = bool(ex & WS_EX_CLIENTEDGE)
    print(f"  ① 输入框 EX 样式 = {ex:#010x}")
    print(f"     WS_EX_CLIENTEDGE（0x200）："
          f"{'✅ **在** —— 这就是那圈黑的来源' if has else '不在'}")

    print()
    print("  ② 再调一次 `remove_client_edge`（`PathBar.__init__` 里已经调过）：")
    ok = win32.remove_client_edge(tc)
    ex2 = read_ex(tc)
    print(f"     EX 样式 = {ex2:#010x}，返回 {ok}")
    print(f"     WS_EX_CLIENTEDGE："
          f"{'❌ 还在（没修掉）' if ex2 & WS_EX_CLIENTEDGE else '✅ 已去掉'}")

    # 对照：目录树（文档记载它带 CLIENTEDGE，但应用会去掉它）
    tree_native = win32.find_child_window(frame.dir_ctrl.GetHandle(),
                                          "SysTreeView32")
    if tree_native:
        tex = read_ex(tree_native)
        print()
        print(f"  ③ 对照——目录树 EX 样式 = {tex:#010x}，"
              f"CLIENTEDGE {'在' if tex & WS_EX_CLIENTEDGE else '已去（应用处理过）'}")

    frame.store.close()
    frame.Destroy()
