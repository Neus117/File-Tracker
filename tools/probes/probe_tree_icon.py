"""量导航窗格树的**图标尺寸**与**行高**，判断能不能放大。

## 用户

"对比 Explorer，我们的导航窗格中这些磁盘、文件夹的**标识太小了**，
看着真的很费劲。能放大吗？"

## 要量清楚

1. 树现在挂的 `wx.ImageList` **图标是多大**（宽×高）
2. 行高是多少（我们之前把它调到了 `文字高 × 1.8`）
3. 图标相对行高有多小 —— 这就是"看着费劲"的量化说法
4. 系统提供的大图标列表（`SHIL_LARGE` = 32×32）能不能用

**先量再改**：不知道现在多大就不知道要放多大。
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

with probe_temp("probe-tree-icon") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(3):
        seed.record_access(os.path.join(scratch, f"f{i}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    tree = frame.dir_ctrl.GetTreeCtrl()
    tree_native = win32.find_child_window(frame.dir_ctrl.GetHandle(),
                                          "SysTreeView32")

    print(f"  树行高（TVM_GETITEMHEIGHT） = "
          f"{win32.get_tree_item_height(tree_native)}")

    # wx 侧的图列表（ **不收参数**，实测）
    il = tree.GetImageList()
    if il is not None and il.GetImageCount() > 0:
        w, h = il.GetSize(0)
        print(f"  wx 图列表：{il.GetImageCount()} 张，单张 **{w} x {h}**")
    else:
        print("  wx 图列表：无")

    # 内层原生控件的图列表尺寸（真正决定渲染大小的那个）
    LVM_FIRST, TVM_FIRST = 0x1000, 0x1100
    TVM_GETIMAGELIST = TVM_FIRST + 8
    user32 = ctypes.windll.user32
    h = user32.SendMessageW(ctypes.c_void_p(tree_native),
                            TVM_GETIMAGELIST, 1, 0)   # TVSIL_NORMAL
    print(f"  原生 TVSIL_NORMAL 图列表句柄 = {h}")
    if h:
        # 从 HIMAGELIST 读图标尺寸
        comctl = ctypes.windll.comctl32
        w, hh = ctypes.c_int(), ctypes.c_int()
        if comctl.ImageList_GetIconSize(ctypes.c_void_p(h),
                                        ctypes.byref(w), ctypes.byref(hh)):
            print(f"  **图标实际尺寸 = {w.value} x {hh.value}**")
            row = win32.get_tree_item_height(tree_native)
            if row:
                print(f"  图标高 {hh.value} ÷ 行高 {row} = "
                      f"**{hh.value / row:.2f}** —— 越小越「费劲」")

    # 系统大图标列表（32x32）能不能拿到
    shell32 = ctypes.windll.shell32
    himl = ctypes.c_void_p()
    SHIL_LARGE = 0
    try:
        shell32.SHGetImageList.argtypes = [
            ctypes.c_int, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p)]
        hr = shell32.SHGetImageList(SHIL_LARGE, None, ctypes.byref(himl))
        print(f"  SHGetImageList(SHIL_LARGE) 返回 {hr:#x}")
        if himl.value:
            w2, h2 = ctypes.c_int(), ctypes.c_int()
            comctl.ImageList_GetIconSize(himl, ctypes.byref(w2),
                                         ctypes.byref(h2))
            print(f"  系统大图标列表尺寸 = {w2.value} x {h2.value}"
                  "  ← **可用来放大**")
    except Exception as error:
        print(f"  SHGetImageList 不可用：{error}")

    frame.store.close()
    frame.Destroy()
