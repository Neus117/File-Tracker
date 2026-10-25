r"""深色 / 浅色主题下，**右键菜单真的是什么颜色**（像素判据）。

## 为什么要有这个探针

用户 2026-10-26 先报"深色主题下右键菜单还是白的"，随后又报"浅色主题菜单
错误保持深色"。

右键菜单、滚动条、系统提示框都是**系统画的**，只看
`uxtheme.SetPreferredAppMode` 那个**进程级**开关：
`2 = ForceDark` / `3 = ForceLight`。**浅色不能传 0** ——
0 的语义是"跟随系统"，系统深色时长出深色菜单。

## 这个探针怎么判

启动**真实的** `FileTrackerApp`（即 `src/main.py` 那条路），用临时配置设定主题，
再打开一次右键菜单，抓**整块菜单矩形**：
* **众数色**（菜单背景色）亮度 < 80 ⇒ 深色；> 160 ⇒ 浅色；
* 暗像素占比（浅色菜单 ≈ 0.0x，深色菜单 ≈ 0.9x）。

⚠️ 两条环境事实（都踩过）：
* `wx.Timer`/`wx.CallLater` 在**没有 `MainLoop`** 的 yield 循环里不触发 ——
  菜单是模态的，必须 `MainLoop()`，让定时器跑在菜单的模态循环里；
* **单点取像素会骗人**（同一位置曾读出 43 和 249，两种解释都成立）。
  所以取整块区域的**众数色**。

用法::

    python tools\probes\probe_menu_dark.py                  # 深色主题（默认）
    python tools\probes\probe_menu_dark.py --theme light    # 浅色主题
    python tools\probes\probe_menu_dark.py --flush          # 设完再 FlushMenuThemes()

`--flush` 用来验证"运行中切主题后菜单能不能立刻跟着变"。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import lang, win32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

RESULTS: list[dict] = []


def find_popup_menus(pid: int) -> list[int]:
    user32 = ctypes.windll.user32
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _param):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd),
                                       ctypes.byref(owner))
        if owner.value != pid:
            return True
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), name, 255)
        if name.value == "#32768":
            found.append(int(hwnd))
        return True

    user32.EnumWindows(proto(callback), 0)
    return found


def grab(hwnd: int, tag: str) -> dict:
    rect = wt.RECT()
    ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd),
                                       ctypes.byref(rect))
    w, h = max(rect.right - rect.left, 1), max(rect.bottom - rect.top, 1)
    bitmap = wx.Bitmap(w, h)
    memory = wx.MemoryDC(bitmap)
    screen = wx.ScreenDC()
    memory.Blit(0, 0, w, h, screen, rect.left, rect.top)
    del screen
    del memory
    image = bitmap.ConvertToImage()
    path = os.path.join(os.environ.get("TEMP", "."), "ft_menu_%s.png" % tag)
    image.SaveFile(path, wx.BITMAP_TYPE_PNG)
    counter = Counter()
    dark = total = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            rgb = (image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y))
            counter[rgb] += 1
            total += 1
            if sum(rgb) / 3 < 80:
                dark += 1
    mode, _count = counter.most_common(1)[0]
    brightness = sum(mode) / 3
    verdict = "DARK" if brightness < 80 else (
        "LIGHT" if brightness > 160 else "AMBIGUOUS")
    return {"mode": mode, "brightness": brightness,
            "dark_share": round(dark / max(total, 1), 3),
            "size": (w, h), "png": path, "verdict": verdict}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--switch", choices=("dark", "light"),
                        help="先以 --theme 启动，**运行中**再切到这一档并量第二次"
                             "（模拟用户在设置里切主题）")
    parser.add_argument("--flush", action="store_true",
                        help="设完进程级模式后调 uxtheme[136]（FlushMenuThemes）")
    args = parser.parse_args(argv)

    holder = probe_temp("menu-dark")
    scratch = holder.__enter__()
    cfg = os.path.join(scratch, "c.json")
    with open(cfg, "w", encoding="utf-8") as handle:
        json.dump({"theme": args.theme}, handle)
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    app_mod.default_config_path = lambda: cfg
    store = app_mod.PathStore(app_mod.default_db_path())
    store.record_access(scratch)
    store.close()

    print("wanted theme =", args.theme)
    print("system is light =", win32.system_uses_light_theme())
    app = app_mod.FileTrackerApp(False)          # ← 真实启动路径
    frame = app.frame
    lang.apply(lang.PREFERENCE_CHINESE)
    print("frame theme is_dark =", frame.theme.is_dark)
    print("process_dark_mode =", win32.process_dark_mode)
    if args.flush:
        try:
            ctypes.WinDLL("uxtheme")[136]()
            print("FlushMenuThemes() called")
        except Exception as error:
            print("FlushMenuThemes failed:", error)

    pid = os.getpid()

    def grab_and_continue(tag, then):
        def finish(hwnd):
            RESULTS.append(grab(hwnd, tag))
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd),
                                              0x0100, 0x1B, 0)
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd),
                                              0x0101, 0x1B, 0)
            wx.CallLater(300, then)

        def poll():
            menus = find_popup_menus(pid)
            if not menus:
                wx.CallLater(150, poll)
                return
            finish(menus[0])

        menu = wx.Menu()
        for label in ("复制路径", "顶置", "打开", "删除"):
            menu.Append(wx.ID_ANY, label)
        wx.CallLater(400, poll)      # 等菜单淡入结束
        frame.PopupMenu(menu)
        menu.Destroy()

    def after_first():
        if not args.switch:
            frame.Close()
            return
        # **模拟用户在设置里切主题**：只走 `_retheme`（代码里就是这么一条路）。
        # 进程级开关的重设与 FlushMenuThemes 都应由 `_retheme` 自己完成 ——
        # 探针**不手写**这两步，否则测的是探针不是产品。
        theme_cls = type(frame.theme)
        wanted = theme_cls.dark(frame.theme.accent) if args.switch == "dark" \
            else theme_cls.light(frame.theme.accent)
        frame.theme = wanted
        frame._retheme()
        print("switched to %s: is_dark = %s  process_dark_mode = %s"
              % (args.switch, frame.theme.is_dark, win32.process_dark_mode))
        wx.CallLater(400, lambda: grab_and_continue(
            "%s-then-%s" % (args.theme, args.switch), frame.Close))

    wx.CallLater(500, lambda: grab_and_continue(args.theme, after_first))
    wx.CallLater(15000, frame.Close)
    app.MainLoop()

    print()
    for reading in RESULTS:
        print("  menu size=%s  mode=%r  brightness=%.0f  dark_share=%.3f  ->  %s"
              % (reading["size"], reading["mode"], reading["brightness"],
                 reading["dark_share"], reading["verdict"]))
        print("  png:", reading["png"])
    holder.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
