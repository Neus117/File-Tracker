"""量导航窗格里的每一处文字，以及各窗格的字号差。

## 用户的要求

> 记录窗格文字是不是比导航窗格大了 2pt 了？这让整体有些不协调。
> 请将**导航窗格内的文字（包括顶栏标题）整体缩小 1pt**，
> **间隔保持住同一种呼吸感**。

所以要量清两件事：

1. 导航窗格内**都有哪些文字**、各是多少 pt
2. **行距比例**（`行高 / 文字高`）—— 缩字号会改变文字高，
   比例必须重算，否则"呼吸感"就变了
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
from file_tracker.widgets import dpi_of


def text_height_of(win) -> int:
    dc = wx.ClientDC(win)
    dc.SetFont(win.GetFont())
    return dc.GetTextExtent("Ag路径")[1]


def show(win, label: str) -> None:
    f = win.GetFont()
    print(f"    {label:28}{f.GetPointSize():>4}pt  "
          f"文字高 {text_height_of(win):>3}px  face={f.GetFaceName()}")


with probe_temp("probe-nav-fonts") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    seed = app_mod.PathStore(db)
    for i in range(10):
        seed.record_access(os.path.join(scratch, f"folder-{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    dpi = dpi_of(frame)
    sys_pt = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetPointSize()

    print(f"  DPI = {dpi}，系统 UI 字号 = {sys_pt}pt")
    print()
    print("  ══ ① 基准：底部按钮 ══")
    show(frame.open_btn, "「打开」")
    show(frame.clear_btn, "「清空」")

    print()
    print("  ══ ② 记录窗格（右上）══")
    show(frame.list_ctrl, "列表条目")
    show(frame.header, "自绘列头")

    print()
    print("  ══ ③ 导航窗格（左侧）══")
    show(frame.path_bar, "PathBar 容器")
    show(frame.path_bar.text_ctrl, "**顶栏标题**（输入框）")
    show(frame.dir_ctrl, "GenericDirCtrl")
    tree_widget = frame.dir_ctrl.GetTreeCtrl()
    show(tree_widget, "树控件（GetTreeCtrl）")
    tree_native = win32.find_child_window(frame.dir_ctrl.GetHandle(),
                                          "SysTreeView32")
    tree_row = win32.get_tree_item_height(tree_native)

    print()
    print("  ══ ④ 行距比例 ══")
    lh_row = frame.list_ctrl.GetItemRect(0).height
    lh_text = text_height_of(frame.list_ctrl)
    th_text = text_height_of(tree_widget)
    print(f"    {'':14}{'行高':>7}{'文字高':>8}{'比例':>9}")
    print("    " + "-" * 34)
    print(f"    {'记录窗格':14}{lh_row:>7}{lh_text:>8}{lh_row/lh_text:>9.3f}")
    print(f"    {'导航窗格':14}{tree_row:>7}{th_text:>8}{tree_row/th_text:>9.3f}")

    print()
    print("  ══ ⑤ 两窗格字号差 ══")
    print(f"    记录窗格 {frame.list_ctrl.GetFont().GetPointSize()}pt "
          f"－ 导航窗格 {tree_widget.GetFont().GetPointSize()}pt "
          f"= **{frame.list_ctrl.GetFont().GetPointSize() - tree_widget.GetFont().GetPointSize()}pt**")

    frame.store.close()
    frame.Destroy()
