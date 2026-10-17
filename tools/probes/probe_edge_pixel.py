r"""查：掩码线旁边那条 1 像素的"反色线"到底是什么（**只查，不改**）。

## 用户的观察（2026-10-17）

> "这个列分隔线（掩码线），它的**左边**是不是被渲染了什么东西？
>   我感觉有一条大概 1 像素的反色线（黄色底中显示为白色，
>   黑色底中显示为浅灰色）。你给它上色，比如选中它以后就会特别明显；
>   如果不给它上色，比如这个表头，其实就看不出来。"

## 待验假设

`header.separator_positions()` 与 `app._paint_column_separators()` 都把线画在
``列边界 − 线宽``，也就是**只覆盖列边界左边的那 1 个像素**。
列边界像素本身**没有被线覆盖**，于是露出它自己的底色。

若那个像素的底色与**行背景色**不同（行背景由 `SetItemBackgroundColour`
铺满整行，但可能只铺到 `列边界 − 1`），就会看到一条 1 像素的"异色线"。

## 判据

逐列抓像素，打印 ``x-3 .. x+3`` 每一列在置顶行里的颜色：

* 掩码线应当出现在 ``列边界 − 1``
* **若 ``列边界`` 那一列的颜色与行背景色（置顶黄）不同** ⇒ 假设成立
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx, pixel_at

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

app = wx.App(redirect=False)


def pump(rounds=25, pause=0.004):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def sample_column(frame, x: int, y: int) -> str | None:
    """抓 (x, y) 这个像素的颜色（hex）。抓不到返回 None。

    **用 `pixel_at`（内部走 `client_dc`）**：DC 在 `with` 结束时立即释放。
    手工 `wx.ClientDC(...)` 攒到 `frame.Destroy()` 之后才析构会**访问违例**
    —— 那正是用户看到的 `CrashSender.exe` 报错的真身（见 `_probe_guard`）。
    """
    rgb = pixel_at(frame.list_ctrl, x, y)
    if rgb is None:
        return None
    return "#%02X%02X%02X" % rgb


with probe_temp("probe-edge-pixel") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(10):
        seed.record_access("D:\\dir-%03d" % i, when="2026-10-17 14:43:27")
    for i in range(4):
        seed.set_pinned("D:\\dir-%03d" % i, True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.SetSize((1100, 520))
    frame.Show()
    pump(60)

    try:
        for theme_name, theme in (("浅色", app_mod.Theme.light()),
                                  ("深色", app_mod.Theme.dark())):
            frame.theme = theme
            frame._sync_header()
            frame.list_ctrl.Refresh()
            frame._paint_column_separators()
            pump(25)

            th = max(int(app_mod.METRICS.separator_thickness), 1)
            widths = [frame.list_ctrl.GetColumnWidth(i)
                      for i in range(frame.list_ctrl.GetColumnCount())]
            boundary = widths[0]
            print("\n【%s】第一列宽 %d ⇒ 列边界 x = %d，线宽 %d"
                  % (theme_name, boundary, boundary, th))
            print("   行背景(置顶)=%s  卡片=%s  列表底色=%s  表头=%s"
                  % (theme.pinned_row, theme.card,
                     theme.card, theme.surface_alt))

            # 置顶行里取一个 y（避开文字）
            rect = frame.list_ctrl.GetItemRect(0)
            if not rect or rect.height <= 0:
                print("   拿不到行矩形")
                continue
            y = rect.y + rect.height // 2

            print("   列边界附近每一列的颜色（y=%d，置顶行）：" % y)
            for dx in range(-3, 4):
                x = boundary + dx
                if x < 0:
                    continue
                colour = sample_column(frame, x, y)
                tag = ""
                if dx == -1:
                    tag = "  ← 掩码线应在这一列"
                elif dx == 0:
                    tag = "  ← **列边界像素**"
                print("     x=%d (%+d)  %s%s" % (x, dx, colour, tag))

            # 表头里同一位置
            hth = frame.header.separator_thickness()
            hpos = frame.header.separator_positions()
            if hpos:
                hx = hpos[0]
                hy = frame.header.GetSize().height // 2
                print("   表头里（线 x=%d，y=%d）：" % (hx, hy))
                for dx in range(-3, 4):
                    x = hx + dx
                    if x < 0:
                        continue
                    rgb = pixel_at(frame.header, x, hy)
                    colour = ("#%02X%02X%02X" % rgb) if rgb else None
                    tag = "  ← 掩码线" if dx == 0 else ""
                    print("     x=%d (%+d)  %s%s" % (x, dx, colour, tag))
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(10)
