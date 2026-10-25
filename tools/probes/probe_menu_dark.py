r"""临时：**走真实启动路径**验证"深色主题下右键菜单是深色"。

用户 2026-10-26："在深色主题下，选中路径记录器当中的条目并右键点击，
其菜单没有随深色主题反色，依然是浅色背景。"

## 判据（不做单点读数）

把**整个菜单矩形**抓下来，算：
* **众数色** = 菜单背景色（浅色应 > 160 亮度，深色应 < 80）；
* **暗像素占比**。

## A/B

同一进程里跑两轮：
1. 修好之后（`FileTrackerApp.OnInit` 按**程序主题**设进程级深色）；
2. 手动把进程级深色关掉（= 修复前的行为，第 3 行那个
   `system_uses_light_theme()` 分支的结果）。

## 两条环境事实

* `wx.Timer` / `wx.CallLater` 在**没有 MainLoop** 的循环里不触发
  （`wx.Yield()` 也不行），所以必须 `MainLoop()`，让定时器在菜单的模态循环里跑；
* 对菜单窗口调 `SetWindowTheme(DarkMode_Explorer)` 会把它**变浅**（实测
  众数色从 (44,44,44) 变成 (249,249,249)）—— 所以**别用那个 hack**。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "src"))

import ctypes.wintypes as wt

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

RESULTS = []


def find_popup_menus(pid: int) -> list[int]:
    user32 = ctypes.windll.user32
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _param):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, 255)
        if name.value == "#32768":
            found.append(int(hwnd))
        return True

    user32.EnumWindows(proto(callback), 0)
    return found


def grab(hwnd: int, tag: str) -> dict:
    rect = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
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
    mode, count = counter.most_common(1)[0]
    return {"mode": mode, "share": round(count / max(total, 1), 3),
            "dark_share": round(dark / max(total, 1), 3), "size": (w, h),
            "png": path}


def main() -> int:
    holder = probe_temp("menu-dark")
    scratch = holder.__enter__()
    cfg = os.path.join(scratch, "c.json")
    with open(cfg, "w", encoding="utf-8") as handle:
        json.dump({"theme": "dark"}, handle)      # 程序设为深色，系统仍是浅色
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    app_mod.default_config_path = lambda: cfg
    store = app_mod.PathStore(app_mod.default_db_path())
    store.record_access(scratch)
    store.close()

    print("系统是浅色吗 =", win32.system_uses_light_theme())
    app = app_mod.FileTrackerApp(False)           # ← 走真实 OnInit
    frame = app.frame
    lang.apply(lang.PREFERENCE_CHINESE)
    print("程序主题 is_dark =", frame.theme.is_dark)
    print("进程级深色模式（应为 True）= ", getattr(win32, "process_dark_mode", "n/a"))

    pid = os.getpid()
    plan = [("修复后（按程序主题）", None),
            ("修复前（按系统主题 = 浅色）", False)]
    state = {"round": 0}

    def close_current(hwnd):
        ctypes.windll.user32.PostMessageW(hwnd, 0x0100, 0x1B, 0)
        ctypes.windll.user32.PostMessageW(hwnd, 0x0101, 0x1B, 0)

    def run_round():
        tag, force = plan[state["round"]]
        if force is not None:
            win32.set_process_dark_mode(force)
        wx.CallLater(250, lambda: show_menu(tag))

    def show_menu(tag):
        menu = wx.Menu()
        for label in ("复制路径", "顶置", "打开", "删除"):
            menu.Append(wx.ID_ANY, label)

        def poll():
            menus = find_popup_menus(pid)
            if not menus:
                wx.CallLater(150, poll)
                return
            hwnd = menus[0]
            RESULTS.append((tag, grab(hwnd, "r%d" % state["round"])))
            close_current(hwnd)
            state["round"] += 1
            wx.CallLater(300, finish_round)

        wx.CallLater(400, poll)       # 等淡入动画结束
        frame.PopupMenu(menu)
        menu.Destroy()

    def finish_round():
        if state["round"] < len(plan):
            run_round()
        else:
            frame.Close()

    wx.CallLater(400, run_round)
    wx.CallLater(12000, frame.Close)
    app.MainLoop()

    print()
    for tag, reading in RESULTS:
        print("  %-28s 众数色=%-16r 暗占比=%.3f  尺寸=%s"
              % (tag, reading["mode"], reading["dark_share"], reading["size"]))
        print("  %28s png: %s" % ("", reading["png"]))
    holder.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
