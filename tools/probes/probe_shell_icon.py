"""量 `_shell_icon` 为什么对**文件**路径返回 None。

## 症状

`_icon_for('a.exe')` / `'a.dll'` / `'a.txt'` **全都返回下标 2**
—— 那是**兜底**的 `ICON_FILE`，说明 `_shell_icon` 没给出位图。

而 `_build_images()` 里同样调 `_shell_icon(...)` 却是好的（图列表建出了 3 张）。
**同一个函数、两条路，结果不同** —— 必须量，不能猜。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), 'src'))

import wx

from _probe_guard import harden_wx

harden_wx()

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import file_tracker.dir_tree as dt

BACKSLASH = chr(92)
CASES = [
    ("C:" + BACKSLASH + "x.exe", False),
    ("C:" + BACKSLASH + "x.txt", False),
    ("C:" + BACKSLASH + "x.dll", False),
    ("C:" + BACKSLASH + "folder", True),
    ("C:" + BACKSLASH, True),
]

print("  常量：ICON=%#x  LARGE=%#x  USEFILEATTR=%#x"
      % (dt.SHGFI_ICON, dt.SHGFI_LARGEICON, dt.SHGFI_USEFILEATTRIBUTES))
print()
print(f"  {'查询路径':<14}{'isdir':<7}{'返回':<6}{'hIcon':<10}{'iIcon':<7}类型名")
for path, is_dir in CASES:
    info = dt._SHFILEINFO()
    flags = dt.SHGFI_ICON | dt.SHGFI_LARGEICON | dt.SHGFI_USEFILEATTRIBUTES
    attrs = (dt.FILE_ATTRIBUTE_DIRECTORY if is_dir
             else dt.FILE_ATTRIBUTE_NORMAL)
    try:
        got = ctypes.windll.shell32.SHGetFileInfoW(
            ctypes.c_wchar_p(path), attrs, ctypes.byref(info),
            ctypes.sizeof(info), flags)
        err = ""
    except Exception as error:                       # noqa: BLE001
        got, err = -1, f"{type(error).__name__}: {error}"
    print(f"  {path:<14}{str(is_dir):<7}{got:<6}{info.hIcon!s:<10}"
          f"{info.iIcon:<7}{info.szTypeName!r} {err}")

print()
print("  ── 直接调**产品真正用的那个函数** `dt._shell_icon` ──")
print("  （不在探针里复刻它的内部序列 —— 那会变成'量我记忆里的旧代码'）")
for path, is_dir in CASES:
    bitmap = dt._shell_icon(path, directory=is_dir, size=32)
    if bitmap is None:
        print(f"  {path:<14} -> None（退回 ArtProvider）")
    else:
        print(f"  {path:<14} -> {bitmap.GetWidth()}x{bitmap.GetHeight()}"
              f"  IsOk={bitmap.IsOk()}")
