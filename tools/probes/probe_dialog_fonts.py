"""量两件事：

## ① 各弹窗的字体、字号，与「打开」「清空」按钮比

用户要求：设置窗口、所有提示弹窗（**含标题栏**）的字号，
与「打开」「清空」按钮不一致的，统一成按钮那一套。

**所以先得知道"现在各是多少"。** 读代码看不出继承链的最终结果——
对话框用的是 `self.GetFont()`，而它受窗口级传播与类级 `SetFont` 双重影响。

## ② 导航窗格的行距能不能加

导航窗格是 `wx.GenericDirCtrl`，内层是原生 `SysTreeView32`。
树控件有 **`TVM_SETITEMHEIGHT`** —— 那与列表的 `LVM_SETITEMSPACING`
不是一回事（后者在 report 视图下实测无效）。

**判据：回读树项的实际高度，看它随设定值变不变。**
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
from file_tracker.widgets import SettingsDialog, ThemedDialog

TVM_SETITEMHEIGHT = 0x111B          # TV_FIRST + 27
TVM_GETITEMHEIGHT = 0x111C          # TV_FIRST + 28


def describe(widget, label: str) -> None:
    f = widget.GetFont()
    sysf = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    print(f"    {label:26} {f.GetPointSize():>3}pt  "
          f"face={f.GetFaceName():<18} "
          f"{'粗' if f.GetWeight() == wx.FONTWEIGHT_BOLD else '常规'}  "
          f"（系统 {sysf.GetPointSize()}pt）")


with probe_temp("probe-dialog-fonts") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    seed = app_mod.PathStore(db)
    for i in range(6):
        seed.record_access(os.path.join(scratch, f"folder-{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    print("  ══ ① 基准：底部按钮 ══")
    describe(frame.open_btn, "「打开」")
    describe(frame.clear_btn, "「清空」")
    describe(frame.pin_btn, "顶置（图标按钮）")
    describe(frame.header, "自绘列头")
    print(f"    {'frame.body_font':26} {frame.body_font.GetPointSize():>3}pt")

    print()
    print("  ══ ② 设置窗口 ══")
    from file_tracker.lang import PREFERENCE_CHINESE
    dlg = SettingsDialog(frame, frame.theme, PREFERENCE_CHINESE)
    describe(dlg, "对话框本身（自绘文字用它）")
    for name in dir(dlg):
        w = getattr(dlg, name, None)
        if isinstance(w, wx.Window) and name.startswith("_"):
            pass
    # 把里面的子控件都列出来
    def walk(win, depth=0):
        for child in win.GetChildren():
            cls = type(child).__name__
            try:
                txt = child.GetLabel() if hasattr(child, "GetLabel") else ""
            except Exception:
                txt = ""
            describe(child, f"{'  ' * depth}{cls} {txt[:14]}")
            walk(child, depth + 1)
    walk(dlg)

    print()
    print("  ══ ③ 提示弹窗（ThemedDialog，用户报障时看到的）══")
    note = ThemedDialog(frame, frame.theme, "路径已失效，确定要删除吗？",
                        title="确认删除")
    describe(note, "弹窗本身（自绘标题/正文）")
    walk(note)
    print()
    print("    原生标题栏由 Windows 画，**不受 wx 字体控制**——")
    print("    能改的只有自绘的那部分（本项目标题栏是自绘的，见下）。")

    print()
    print("  ══ ④ 导航窗格行距：TVM_SETITEMHEIGHT 能不能用 ══")
    tree = win32.find_child_window(frame.dir_ctrl.GetHandle(), "SysTreeView32")
    print(f"    内层句柄 = {tree}")
    if tree:
        get_h = ctypes.windll.user32.SendMessageW(
            ctypes.c_void_p(tree), TVM_GETITEMHEIGHT, 0, 0)
        print(f"    当前项高（TVM_GETITEMHEIGHT）= {get_h}")
        print()
        print(f"    {'设定值':>6}{'回读值':>8}{'变了?':>8}")
        print("    " + "-" * 22)
        for want in (0, 20, 24, 28, 32, 40):
            ctypes.windll.user32.SendMessageW(
                ctypes.c_void_p(tree), TVM_SETITEMHEIGHT, want, 0)
            for _ in range(6):
                wx.YieldIfNeeded()
            got = ctypes.windll.user32.SendMessageW(
                ctypes.c_void_p(tree), TVM_GETITEMHEIGHT, 0, 0)
            print(f"    {want:>6}{got:>8}"
                  f"{'   ✅' if got != get_h else '   —':>8}")
    else:
        print("    ❌ 找不到内层树控件")

    note.Destroy()
    dlg.Destroy()
    frame.store.close()
    frame.Destroy()
