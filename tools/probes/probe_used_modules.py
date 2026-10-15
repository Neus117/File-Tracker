"""审计：**运行时真正用到**的模块 vs PyInstaller 打进去的模块。

## 为什么要量而不是猜

`libcrypto-3-x64.dll`（2.11 MB）在产物里，它通常由 `ssl` / `hashlib`
连带进来。但"通常"不是证据——本项目里 sqlite3 也在用，而 `_hashlib`
完全可能是别的库拉进来的。

这里把两件事对上：
  ① 导入 `file_tracker.app` **之后** `sys.modules` 里有哪些顶层模块
  ② 归档里有哪些项

差集就是"打进去但没用到"的候选。**候选，不是结论**——
有些模块是被 C 扩展在运行中途按需导入的，静态导入看不出来，
所以下面只报"没在导入期出现"，并单独列出需要人工确认的。
"""
import os
import sys
import time

sys.path.insert(0, "src")

#: 归档里我们关心的、可能是多余的项
WATCH = [
    "libcrypto", "libssl", "_hashlib", "_ssl", "ssl",
    "_socket", "socket", "select",
    "_bz2", "bz2", "LIBBZ2",
    "_lzma", "lzma", "liblzma",
    "_decimal", "decimal",
    "unicodedata",
    "_ctypes", "ctypes",
    "sqlite3", "_sqlite3", "sqlite3.dll",
    "wx._html", "wx._adv", "wx._core", "wx._msw", "siplib",
    "_multibytecodec", "multibytecodec",
    "email", "http", "urllib", "xml", "unittest", "distutils",
    "pydoc", "lib2to3", "setuptools", "pip",
]


def top_level(name: str) -> str:
    return name.replace("/", "\\").split("\\")[0].split(".")[0].lower()


print("=== 导入 file_tracker.app 之后，sys.modules 里有哪些关心的模块 ===")
before = set(sys.modules)
import file_tracker.app  # noqa: E402
after = set(sys.modules)
new = after - before

watch_lower = {w.lower() for w in WATCH}
interesting = sorted({n for n in sys.modules
                      if n.lower() in watch_lower
                      or n.lower().split(".")[0] in watch_lower})
for name in interesting:
    print(f"  已导入: {name}")

# **把真实窗口建出来再量一次。** 只 import 不建窗口的话，
# `wx._adv` / `wx._html` / `wx._msw` 这些都还没加载——它们由
# `wx/__init__.py` 或控件实例化时才拉进来，所以"导入期没看见"
# 不等于"运行时不用"。
print()
print("=== 建出真实窗口之后，再量一次 ===")
try:
    import wx  # noqa: E402

    _probe_app = wx.App()
    _probe_frame = file_tracker.app.FileTracker()
    _probe_frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)
    wx_children = sorted({n for n in sys.modules if n.startswith("wx.")})
    print(f"  wx.* 子模块（{len(wx_children)} 个）: {wx_children}")
    loaded = sorted({n for n in sys.modules if n.lower() in watch_lower
                     or n.lower().split(".")[0] in watch_lower})
    print(f"  关心的模块（{len(loaded)} 个）: {loaded}")
    _probe_frame.store.close()
    _probe_frame.Destroy()
except Exception as error:                          # noqa: BLE001
    print(f"  建窗口失败（不影响下面的归档清单）："
          f"{type(error).__name__}: {error}")

print("=== 归档里有、但导入期没出现的『关心项』 ===")
import glob  # noqa: E402

from PyInstaller.archive.readers import CArchiveReader  # noqa: E402

exe = os.path.join("dist", "File Tracker.exe")
if os.path.exists(exe):
    reader = CArchiveReader(exe)
    loaded = {top_level(n) for n in sys.modules}
    for name in sorted(reader.toc):
        base = os.path.basename(name).split(".")[0].lower()
        if not any(w.lower().startswith(base) and len(base) > 2 for w in WATCH):
            continue
        flag = "已导入" if base in loaded else "**未见**"
        entry = reader.toc[name]
        size = entry[1] if isinstance(entry, (list, tuple)) and len(entry) >= 2 \
            and isinstance(entry[1], int) else 0
        print(f"  {flag}  {size:10,d} B  {name}")
else:
    print("  找不到产物，跳过")
