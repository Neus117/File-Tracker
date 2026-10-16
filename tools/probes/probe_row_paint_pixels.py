"""诊断：从导航窗格打开之后，记录列表那条**真正被画成什么色**（可信的像素）。

## 仪器（这一步终于修对了）

| 口径 | 结果 |
|---|---|
| `GetItemBackgroundColour(行)` | 只说明"存了什么"，永远是我们设的值 |
| `wx.ScreenDC` + Blit | ❌ 不可信：把某行涂纯红，抓回来仍是白（合成层） |
| **`PrintWindow(列表控件, hdc, flag)`** | ✅ **可信**：涂纯红就抓到 `#FF0000` |

`PrintWindow` 让控件**自己重画一遍**到给定 DC，所以拿到的是
"画出来的东西"，不是"存下来的东西" —— 正是这一轮一直缺的那只眼睛。

⚠️ 但**只能抓列表控件本身**：抓外层 Frame 时子控件不会被递归画（全白），
所以坐标一律用**列表客户区**坐标，且**必须先 `Refresh()`+`Update()`**。

## 判据

从导航窗格打开之后，**选中那一行的内部像素**必须等于
`SYS_COLOUR_HIGHLIGHT`（本项目 = `#0078D7`）。

* 若等于 `theme.row_hover`（`#DCE9F7`）⇒ 用户看到的"浅灰"就是**预选那一档**
* 若等于 `theme.card`（`#FFFFFF`）⇒ 那行根本没被上色
* 若等于存值以外的第三种 ⇒ 还有别人在画

两侧各留 30px 边距再采样，避开圆角与边框。
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

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


def park_mouse() -> None:
    ctypes.windll.user32.SetCursorPos(6, 902)


def pump(rounds: int = 25) -> None:
    park_mouse()
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.004)
    park_mouse()


def paint(ctrl, *, force: bool = True) -> wx.Image:
    """把列表控件的画面取回来。

    :param force: 是否**先让它重画一遍**。
        * ``True``  —— `Refresh()`+`Update()` 后抓，拿到的是"**应该**画成什么"
        * ``False`` —— 直接抓，拿到的是"**现在屏幕上就是**什么"

        两者不一致的地方，正是用户看到的东西和程序以为的东西的差别。
    """
    if force:
        ctrl.Refresh()
        ctrl.Update()
    size = ctrl.GetClientSize()
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(wx.Colour("#FF00FF")))   # 没画到的地方一眼可见
    memory.Clear()
    ctypes.windll.user32.PrintWindow(ctypes.c_void_p(ctrl.GetHandle()),
                                    ctypes.c_void_p(memory.GetHandle()),
                                    ctypes.c_uint(0))
    memory.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def hex_of(image: wx.Image, x: int, y: int) -> str:
    if not (0 <= x < image.GetWidth() and 0 <= y < image.GetHeight()):
        return "越界"
    return "#%02X%02X%02X" % (image.GetRed(x, y), image.GetGreen(x, y),
                              image.GetBlue(x, y))


def row_report(image: wx.Image, ctrl, row: int) -> tuple[str, str]:
    """一行的**最常出现的颜色**和**横向色带**（行号 → (众数, 色带)）。"""
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return "（不可见）", ""
    width = ctrl.GetClientSize().width
    counts: dict[str, int] = {}
    total = 0
    for dy in range(2, max(rect.height - 2, 3), 3):
        for dx in range(31, max(width - 30, 32), 2):
            colour = hex_of(image, dx, rect.y + dy)
            counts[colour] = counts.get(colour, 0) + 1
            total += 1
    best = max(counts.items(), key=lambda kv: kv[1]) if counts else ("??????", 0)
    band = " ".join(f"{dx}:{hex_of(image, dx, rect.y + rect.height // 2)}"
                    for dx in (33, 200, 450, 700, 950, width - 33))
    return f"{best[0]}（{best[1] * 100 // max(total, 1)}%）", band


with probe_temp("probe-row-paint") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    # **照用户那边的形状铺数据**：默认按频次降序，所以
    #   ① 前 32 条各访问 5 次 → 排在前面
    #   ② 后面 8 条只访问 1 次 → 排在后面
    # 新记录只有 1 次 → 落在这 8 条**里面**（约第 32~40 行），
    # 也就是**屏幕中间**，正是交接里 `GetFirstSelected() = 31` 那一幕。
    for i in range(32):
        for _ in range(5):
            seed.record_access(os.path.join(scratch, f"hot-{i:03d}"))
    for i in range(8):
        seed.record_access(os.path.join(scratch, f"cold-{i:03d}"))
    fresh = os.path.join(scratch, "cold-zzz-brand-new")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    theme = frame.theme
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    print(f"系统高亮 = {highlight}   row_hover = {theme.row_hover.upper()}   "
          f"card = {theme.card.upper()}   pinned = {theme.pinned_row.upper()}")

    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
    os.makedirs(shots, exist_ok=True)

    try:
        # ── 校准：把两行涂成不可能认错的颜色，确认仪器可信 ──
        ctrl.SetItemBackgroundColour(2, wx.Colour("#FF0000"))
        ctrl.SetItemBackgroundColour(3, wx.Colour("#00FF00"))
        image = paint(ctrl)
        red, _ = row_report(image, ctrl, 2)
        green, _ = row_report(image, ctrl, 3)
        print(f"\n校准：row2 → {red}（期望 #FF0000）   row3 → {green}（期望 #00FF00）")
        check("仪器校准：涂红抓到红、涂绿抓到绿",
              red.startswith("#FF0000") and green.startswith("#00FF00"),
              f"红={red}  绿={green}")

        # ── 场景：视角停在**新记录将要落到的那一段**，从导航窗格打开它 ──
        anchor = 32                      # 新记录排序后会落在这里
        ctrl.EnsureVisible(anchor)
        ctrl.ScrollLines(anchor - 2 - ctrl.GetTopItem())
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(anchor - 4, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                          wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        tree = frame.dir_ctrl.GetTreeCtrl()
        tree.expand_to(fresh, select=True)
        frame._focus_pane = "tree"
        pump(15)

        image = paint(ctrl)
        image.SaveFile(os.path.join(shots, "open-before.png"), wx.BITMAP_TYPE_PNG)
        print(f"\n【打开前】顶行 = {ctrl.GetTopItem()}  "
              f"选中 = {ctrl.GetFirstSelected()}  行数 = {ctrl.GetItemCount()}")
        for row in range(ctrl.GetTopItem(), ctrl.GetTopItem() + 5):
            face, band = row_report(image, ctrl, row)
            print(f"  row {row:3} {face}   色带 {band}")

        print(f"\n【从导航窗格打开 …{fresh[-22:]}】")
        frame.on_open(None)
        pump(45)

        # ⚠️ 两种口径都量：
        #   * 不强制重画 —— **用户此刻看到的**
        #   * 强制重画   —— **程序以为应该看到的**
        live_image = paint(ctrl, force=False)
        live_image.SaveFile(os.path.join(shots, "open-after-live.png"),
                            wx.BITMAP_TYPE_PNG)
        image = paint(ctrl)
        image.SaveFile(os.path.join(shots, "open-after.png"), wx.BITMAP_TYPE_PNG)
        selected = ctrl.GetFirstSelected()
        stored = (ctrl.GetItemBackgroundColour(selected)
                  .GetAsString(wx.C2S_HTML_SYNTAX).upper() if selected >= 0 else "?")
        face, band = row_report(image, ctrl, selected)
        live_face, live_band = row_report(live_image, ctrl, selected)
        rect = ctrl.GetItemRect(selected) if selected >= 0 else None
        print(f"  顶行 = {ctrl.GetTopItem()}   选中 = {selected}"
              f"（…{frame.row_path(selected)[-22:]}）  rect = {rect}")
        print(f"  **存值**         = {stored}")
        print(f"  **不重画 · 屏幕** = {live_face}")
        print(f"  **重画后 · 画面** = {face}")
        print(f"  屏幕色带 = {live_band}")
        print(f"  重画色带 = {band}")
        print("  附近各行（屏幕口径）：")
        for row in range(max(ctrl.GetTopItem(), selected - 2),
                         min(ctrl.GetTopItem() + 6, ctrl.GetItemCount())):
            marker = "  ←选中" if row == selected else ""
            face_row, _ = row_report(live_image, ctrl, row)
            print(f"    row {row:3} {face_row}{marker}")

        painted = face[:7]
        on_screen = bool(rect) and rect.y < ctrl.GetClientSize().height
        check("① 选中落到刚打开的那条", frame.row_path(selected) == fresh,
              f"选中 …{frame.row_path(selected)[-24:]} vs …{fresh[-24:]}")
        check("①b 场景有效：选中行**在屏幕上**（否则像素量不到）", on_screen,
              f"rect={rect}  列表客户区高 = {ctrl.GetClientSize().height}")
        check("①c **不强制重画**时，屏幕上那行也是蓝的（= 用户看到的）",
              live_face[:7].upper() == highlight.upper(),
              f"屏幕={live_face}  重画后={face}  存值={stored}")
        check("② 存值和**画出来**的颜色一致", painted.upper() == stored,
              f"存={stored}  画={painted}")
        check("③ 那一行画出来 = 系统选中蓝", painted.upper() == highlight.upper(),
              f"画={face}  期望={highlight}")
        check("④ 不是预选浅灰（theme.row_hover）",
              painted.upper() != theme.row_hover.upper(),
              f"画={face}  row_hover={theme.row_hover.upper()}")

        print(f"\n  截图留档：{shots}\\open-before.png / open-after.png")
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
