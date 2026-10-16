"""验：窗口**未激活**时，设置了底色 `#0078D7` 的选中行，**画出来**是什么色。

## 这是用户真实报告指向的最后一环

`paint-trace.txt` 显示（用户本机、真实操作）：

```
+5083.4ms  状态(row=31, set=6)        ← 选中行 31
+5088.0ms  SetFocus()
+5209.1ms  底色(row=9, #DCE9F7)  focus=None  active=False   ← **窗口失去激活**
+5372.9ms  底色(row=9, #FFFFFF)  focus=None  active=False
+6613.9ms  （重新激活）            focus=DirectoryTree active=True
+8372.9ms  底色(row=31, #0078D7)                          ← 选中行才被画成蓝
```

选中行 31 在 **+5083** 就被选中，却直到 **+8372**（鼠标移出列表）才被上色，
**中间 3.3 秒是白的**；而失去激活的那一段（+5209 起）正好落在里面。

## 假设

**Windows 对"未激活窗口里的 ListView 选中项"会画它自己的非活动选中色，
而那个颜色压过我们 `SetItemBackgroundColour` 设的值。**

## 判据（单变量：只差"窗口激活 / 未激活"，其余全同）

用 `PrintWindow`（本环境唯一可信的取像素方式，见 `README.md`）抓同一个列表，
比较选中行的像素：

* 激活时 = `#0078D7` → 说明我们的设色生效
* 未激活时 ≠ `#0078D7` → **假设成立，且这就是用户看到的"浅灰"**
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

user32 = ctypes.windll.user32

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


def pump(rounds: int = 25, pause: float = 0.005) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def park_mouse() -> None:
    try:
        user32.SetCursorPos(6, 902)
    except Exception:
        pass


def paint(ctrl) -> wx.Image:
    """`PrintWindow` 打在列表控件上 —— 本环境唯一可信的取像素方式。"""
    ctrl.Refresh()
    ctrl.Update()
    size = ctrl.GetClientSize()
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(wx.Colour("#FF00FF")))
    memory.Clear()
    user32.PrintWindow(ctypes.c_void_p(ctrl.GetHandle()),
                       ctypes.c_void_p(memory.GetHandle()), ctypes.c_uint(0))
    memory.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def face(image: wx.Image, ctrl, row: int) -> str:
    """一行的主色（众数）。"""
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return "（不可见）"
    width = ctrl.GetClientSize().width
    counts: dict[str, int] = {}
    total = 0
    for dy in range(2, max(rect.height - 2, 3), 3):
        for dx in range(31, max(width - 30, 32), 2):
            x, y = dx, rect.y + dy
            colour = ("#%02X%02X%02X" % (image.GetRed(x, y), image.GetGreen(x, y),
                                         image.GetBlue(x, y))
                      if 0 <= x < image.GetWidth() and 0 <= y < image.GetHeight()
                      else "越界")
            counts[colour] = counts.get(colour, 0) + 1
            total += 1
    best = max(counts.items(), key=lambda kv: kv[1]) if counts else ("??????", 0)
    return f"{best[0]}（{best[1] * 100 // max(total, 1)}%）"


def deactivate(frame) -> None:
    """把前台交给别的窗口 —— 用一块独立的小窗来抢，不碰用户的程序。"""
    thief = wx.Frame(None, title="probe-thief", size=(220, 120))
    thief.Show()
    thief.Raise()
    try:
        user32.SetForegroundWindow(ctypes.c_void_p(thief.GetHandle()))
        user32.SetFocus(ctypes.c_void_p(thief.GetHandle()))
    except Exception:
        pass
    pump(20)
    return thief


with probe_temp("probe-inactive") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, f"m{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(50)
    park_mouse()

    ctrl = frame.list_ctrl
    theme = frame.theme
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    print(f"系统高亮 = {highlight}   row_hover = {theme.row_hover.upper()}   "
          f"card = {theme.card.upper()}")

    # 用一个已知的"不可能认错"的颜色做校准：先确认仪器可信
    ctrl.SetItemBackgroundColour(2, wx.Colour("#FF0000"))
    image = paint(ctrl)
    calib = face(image, ctrl, 2)
    print(f"\n校准：row2 涂纯红 → 抓到 {calib}")
    check("仪器可信（涂红抓到红）", calib.startswith("#FF0000"), calib)
    ctrl.SetItemBackgroundColour(2, wx.Colour(theme.card))

    try:
        # ── 布景：选中第 6 行，并用官方方式上色 ──
        target = 6
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(target, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                          wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        ctrl.SetItemBackgroundColour(target, wx.Colour(highlight))
        ctrl.SetFocus()
        pump(25)
        park_mouse()

        active_image = paint(ctrl)
        active_colour = face(active_image, ctrl, target)
        print(f"\n【激活】active={frame.IsActive()}  选中行 {target} 画出来 = {active_colour}")

        # ── 单变量：只把激活状态改掉，别的都不动 ──
        thief = deactivate(frame)
        inactive_image = paint(ctrl)
        inactive_colour = face(inactive_image, ctrl, target)
        print(f"【未激活】active={frame.IsActive()}  选中行 {target} 画出来 = {inactive_colour}")
        print(f"  存值仍然是 = "
              f"{ctrl.GetItemBackgroundColour(target).GetAsString(wx.C2S_HTML_SYNTAX).upper()}")

        thief.Destroy()
        pump(10)
        frame.Raise()
        user32.SetForegroundWindow(ctypes.c_void_p(frame.GetHandle()))
        pump(25)
        park_mouse()
        back_image = paint(ctrl)
        back_colour = face(back_image, ctrl, target)
        print(f"【重新激活】active={frame.IsActive()}  选中行 {target} 画出来 = {back_colour}")

        shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
        os.makedirs(shots, exist_ok=True)
        for name, image in (("sel-active.png", active_image),
                            ("sel-inactive.png", inactive_image)):
            image.SaveFile(os.path.join(shots, name), wx.BITMAP_TYPE_PNG)

        check("① 激活时：选中行画出来 = 系统高亮蓝",
              active_colour.startswith(highlight), active_colour)
        check("② **未激活时：选中行被画成别的颜色**（假设的核心）",
              not inactive_colour.startswith(highlight), inactive_colour)
        check("③ 未激活时那个颜色 ≠ row_hover（不是我们的预选灰）",
              not inactive_colour.startswith(theme.row_hover.upper()),
              f"未激活={inactive_colour}  row_hover={theme.row_hover.upper()}")
        check("④ 重新激活后恢复成高亮蓝", back_colour.startswith(highlight),
              back_colour)
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    if detail:
        print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
