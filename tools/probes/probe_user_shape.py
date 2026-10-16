"""复现（用**用户自己的配置形状**）：按路径升序 + 视角在中间 + 从导航窗格打开。

## 为什么和前面几个探针不一样

前几个探针自己造了排序（按频次降序），而用户真实的
`%APPDATA%\\File Tracker\\config.json` 写的是：

```json
"sort_column": "path",
"sort_directions": { "path": false, ... },     // 升序
"scroll_position": { "v_relative": 0.333 },    // 视角大概在中间
"theme": "light"
```

**排序口径决定了"新记录会落在哪一行"**，而"落在哪一行"又决定了
它是否在屏幕上、以及是否正好落在一个特殊位置上。
前面七个探针都是"我以为的场景"，这次用**他的**场景。

## 量什么

用 `PrintWindow`（已被校准为**可信**：涂红抓到红）取列表控件的真实画面，
看**选中那一行**是不是 `#0078D7`。
同时把 `_paint_key` / `_highlighted_row` / `_hover_row` 一并打出来 ——
这几个记忆账本一旦和画面不同步，就会出现"永远不变色的行"。
"""
from __future__ import annotations

import ctypes
import json
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


def pump(rounds: int = 30, pause: float = 0.006) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def park_mouse() -> None:
    try:
        ctypes.windll.user32.SetCursorPos(6, 902)
    except Exception:
        pass


def paint(ctrl) -> wx.Image:
    ctrl.Refresh()
    ctrl.Update()
    size = ctrl.GetClientSize()
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(wx.Colour("#FF00FF")))
    memory.Clear()
    ctypes.windll.user32.PrintWindow(ctypes.c_void_p(ctrl.GetHandle()),
                                    ctypes.c_void_p(memory.GetHandle()),
                                    ctypes.c_uint(0))
    memory.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def face(image: wx.Image, ctrl, row: int) -> str:
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


def accounts(ctrl, frame) -> str:
    return (f"选中={ctrl.GetFirstSelected()} 顶行={ctrl.GetTopItem()} "
            f"_paint_key={getattr(frame, '_paint_key', None)} "
            f"_highlighted_row={getattr(frame, '_highlighted_row', None)} "
            f"_hover_row={getattr(frame, '_hover_row', None)} "
            f"_hover_painted={getattr(frame, '_hover_painted', None)}")


with probe_temp("probe-user-shape") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    # **照抄用户的配置形状**
    with open(os.path.join(scratch, "c.json"), "w", encoding="utf-8") as handle:
        json.dump({"last_directory": scratch, "language": "zh",
                   "sort_column": "path",
                   "sort_directions": {"path": False, "clock": True,
                                       "count": True, "date": True},
                   "theme": "light"}, handle)

    seed = app_mod.PathStore(db)
    # 造一条"排序上夹在中间"的记录，以及足够多的其它记录
    names = [f"m{i:03d}" for i in range(40)]
    for name in names:
        seed.record_access(os.path.join(scratch, name))
    # 目标：一条**已经记录过**的路径（从导航窗格打开它会 +1 次访问）
    victim = os.path.join(scratch, "m020")
    os.makedirs(victim, exist_ok=True)
    # 另一条只在导航树里存在、列表里**还没有**的路径
    fresh = os.path.join(scratch, "m020-new")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)
    park_mouse()

    ctrl = frame.list_ctrl
    theme = frame.theme
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    print(f"排序 = {frame.sort_key} / reverse={frame.sort_reverse}"
          f"   主题 = {'dark' if theme.is_dark else 'light'}")
    print(f"系统高亮 = {highlight}   row_hover = {theme.row_hover.upper()}   "
          f"card = {theme.card.upper()}   行数 = {ctrl.GetItemCount()}")

    shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
    os.makedirs(shots, exist_ok=True)

    try:
        check("① 排序口径与用户配置一致（path 升序）",
              frame.sort_key == "path" and frame.sort_reverse is False,
              f"sort_key={frame.sort_key} reverse={frame.sort_reverse}")

        for label, target in (("场景A：打开**已记录过**的路径（视角中间）", victim),
                              ("场景B：打开**列表里还没有**的新路径", fresh)):
            print(f"\n══ {label}\n   目标 …{target[-26:]}")
            # 视角放到**中间**（照用户的 0.333）
            mid = max(ctrl.GetItemCount() // 3, 1)
            ctrl.EnsureVisible(mid)
            ctrl.ScrollLines(mid - ctrl.GetTopItem())
            for i in range(ctrl.GetItemCount()):
                ctrl.Select(i, False)
            ctrl.SetItemState(mid, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                              wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
            pump(15)
            park_mouse()
            print(f"   打开前：{accounts(ctrl, frame)}")

            # 从导航窗格发起
            tree = frame.dir_ctrl.GetTreeCtrl()
            tree.expand_to(target, select=True)
            frame._focus_pane = "tree"
            pump(12)
            print(f"   open_targets = {[p[-24:] for p in frame.open_targets()]}")

            frame.on_open(None)
            pump(40)
            park_mouse()

            image = paint(ctrl)
            image.SaveFile(os.path.join(shots, f"user-shape-{label[2]}.png"),
                           wx.BITMAP_TYPE_PNG)
            selected = ctrl.GetFirstSelected()
            stored = (ctrl.GetItemBackgroundColour(selected)
                      .GetAsString(wx.C2S_HTML_SYNTAX).upper() if selected >= 0 else "?")
            painted = face(image, ctrl, selected) if selected >= 0 else "?"
            print(f"   打开后：{accounts(ctrl, frame)}")
            print(f"   选中路径 = …{frame.row_path(selected)[-26:]}")
            print(f"   **存值** = {stored}    **画出来** = {painted}")
            print("   附近各行（画出来的颜色）：")
            top = ctrl.GetTopItem()
            for row in range(max(top, selected - 2),
                             min(top + 6, ctrl.GetItemCount())):
                marker = "  ←选中" if row == selected else ""
                print(f"     row {row:3} {face(image, ctrl, row)}{marker}")

            check(f"② [{label[:3]}] 存值 = 画出来（账本没骗人）",
                  painted[:7].upper() == stored,
                  f"存={stored}  画={painted}  {accounts(ctrl, frame)}")
            check(f"③ [{label[:3]}] 选中行画出来 = 系统选中蓝",
                  painted[:7].upper() == highlight.upper(),
                  f"画={painted}  期望={highlight}")
        print(f"\n  截图留档：{shots}")
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
