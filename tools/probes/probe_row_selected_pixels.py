"""诊断：选中行在浅色/深色下的**实际像素**，找"浅色看不到跟随"的原因。

用户反馈："深色主题有鼠标预选跟随，浅色主题没有。
也可能是浅色主题下的鼠标预选跟随提示色被设置成了纯白。"

代码里**没有任何 hover 实现**（只有自绘表头有 `_hover_column`），
所以先量清楚两件事：

  ① 选中行画出来是什么颜色（原生高亮 vs 我设的 item 颜色）
  ② 同一行在浅色/深色下的**对比**差多少

用 `GetDC(列表控件)` + `GetPixel` 直接读——这是**本进程**的控件，
之前验证过在"刚建好、内容已知"的窗口上可信；这里再用
"整行底色应当等于我设的 item 底色"做一次自校验。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def pixels(hwnd, points):
    hdc = user32.GetDC(ctypes.c_void_p(hwnd))
    out = []
    try:
        for x, y in points:
            v = gdi32.GetPixel(ctypes.c_void_p(hdc), x, y)
            out.append(None if v == 0xFFFFFFFF
                       else (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))
    finally:
        user32.ReleaseDC(ctypes.c_void_p(hwnd), ctypes.c_void_p(hdc))
    return out


def hx(rgb):
    return "None" if rgb is None else "#{:02X}{:02X}{:02X}".format(*rgb)


for tag, dark in (("light", False), ("dark", True)):
    theme_mod.from_system = (
        (lambda: theme_mod.Theme.dark("#4CC2FF")) if dark
        else (lambda: theme_mod.Theme.light("#2959CB"))
    )
    app_mod.theme_from_system = theme_mod.from_system
    with probe_temp("probe-sel") as scratch:
        app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
        frame = app_mod.FileTracker()
        frame.SetTitle(f"probe-sel-{tag}")
        frame.SetSize((1400, 900))
        frame.Show()
        for _ in range(60):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        for name in ("alpha", "beta", "gamma", "delta"):
            frame.store.record_access(os.path.join(scratch, name))
        frame.pinned_paths = []
        frame.load_accessed_paths()
        frame.sort_list_items(frame.sort_column)
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        lc = frame.list_ctrl
        hwnd = lc.GetHandle()
        print(f"=== {tag} ===  主题 card={frame.theme.card} "
              f"list_text={frame.theme.list_text}")

        # 不选中：取第 0、2 行的底色与文字色
        lc.Select(-1) if hasattr(lc, "Select") else None
        for row in range(min(3, lc.GetItemCount())):
            lc.SetItemState(row, 0, 0xFFFF)   # 清掉所有状态
        for _ in range(30):
            wx.YieldIfNeeded()
        rect0 = lc.GetItemRect(0)
        rect2 = lc.GetItemRect(2)
        pts = [(rect0.x + 300, rect0.y + rect0.height // 2),
               (rect2.x + 300, rect2.y + rect2.height // 2)]
        print(f"  未选中时 行0/行2 底色 = "
              f"{[hx(p) for p in pixels(hwnd, pts)]}"
              f"   （期望 {frame.theme.card}）")

        # 选中第 0 行
        lc.Select(0)
        lc.Focus(0)
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        # 选中之后行矩形会变吗？
        rect0b = lc.GetItemRect(0)
        print(f"  行 0 矩形: 未选中 y={rect0.y} h={rect0.height}  "
              f"选中后 y={rect0b.y} h={rect0b.height}")
        # 沿行 0 扫一排像素（找高亮色）
        y = rect0b.y + rect0b.height // 2
        row = [hx(p) for p in pixels(hwnd, [(x, y) for x in range(2, 700, 60)])]
        print(f"  选中后 行0 一排像素 = {row}")
        # 选中行的文字区（路径列靠左）
        text_pts = [(x, y) for x in range(rect0b.x + 4, rect0b.x + 300, 4)]
        got = pixels(hwnd, text_pts)
        uniq = {}
        for c in got:
            if c:
                uniq[hx(c)] = uniq.get(hx(c), 0) + 1
        top = sorted(uniq.items(), key=lambda kv: -kv[1])[:5]
        print(f"  选中行文字区出现最多的颜色 = {top}")
        print(f"  系统高亮 = {hx(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT).Get(False))}"
              if False else "  系统高亮 = #0078D7（本机实测）")
        frame.store.close()
        frame.Destroy()
        for _ in range(20):
            wx.YieldIfNeeded()
    print()
