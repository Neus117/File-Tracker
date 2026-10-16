"""验：记录列表里那条"选中"到底画成什么色，以及**原生 FOCUSED 位**是不是那个灰。

## 从交接里继承的两个判据

* **判据一（存储 ≠ 画面）**：只认从屏幕抓回来的像素。
  `GetItemBackgroundColour()` 永远返回我们设的值，证明不了画成什么。
* **判据二（记忆化要连续两次）**：探针必须让**同一个进程连续走两遍**
  同一流程 —— 每个探针都是全新进程的话，`_paint_key` 那类
  "key 一样就早退"的结构**根本测不到**。

## 本探针量三件事

| 场景 | 做了什么 | 看什么 |
|---|---|---|
| **A：不动 FOCUSED 位** | 对第 N 行只 `Select(N)`，不设 `FOCUSED` | 那行画成什么色 |
| **B：设上 FOCUSED 位** | `SetItemState(N, SELECTED\|FOCUSED, …)` | 同上 |
| **C：连走两遍整流程** | 从导航窗格"打开"两次 | 第二遍和第一遍是否**一样** |

场景 A/B 是**单变量对照**：只差那个位，其余全同。如果 A 是灰、B 是蓝，
"灰"的成因就是**原生焦点矩形**，而不是我们的配色。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

TRACE = bool(os.environ.get("FT_TRACE_PAINT"))
app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

results: list[tuple[bool, str, str]] = []
SEL_FOCUS = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


def pump(rounds: int = 30) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.004)


# ----------------------------------------------------------------------
# 屏幕像素
# ----------------------------------------------------------------------

def screen_image() -> wx.Image:
    screen = wx.ScreenDC()
    width, height = screen.GetSize()
    bitmap = wx.Bitmap(width, height)
    memory = wx.MemoryDC(bitmap)
    memory.Blit(0, 0, width, height, screen, 0, 0)
    memory.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def flush(frame) -> None:
    """**强制真的重画一遍再抓图。**

    ⚠️ 踩过的坑：`frame.Refresh()` 只让**我们自己**的窗口无效，
    `wx.ListCtrl` 是原生控件，它只在"自己那一块被无效"时才重画 ——
    于是屏幕上是**上一次的旧像素**，量出来的颜色和当前状态无关
    （实测：刚 `SetItemState` 设成蓝色，量到的还是三帧之前的浅灰）。

    所以这里对**列表控件本身**再 `Refresh()` + `Update()`，
    `Update()` 是同步重画，回来时像素已经落在屏幕上了。
    """
    frame.list_ctrl.Refresh()
    frame.list_ctrl.Update()
    frame.Refresh()
    frame.Update()
    for _ in range(14):
        wx.YieldIfNeeded()
        time.sleep(0.010)


def pixel(image: wx.Image, x: int, y: int) -> str:
    if not (0 <= x < image.GetWidth() and 0 <= y < image.GetHeight()):
        return "??????"
    return "#%02X%02X%02X" % (image.GetRed(x, y), image.GetGreen(x, y),
                              image.GetBlue(x, y))


def face(image: wx.Image, ctrl, row: int) -> str:
    """一行里面**出现最多的那个颜色**（以整行宽度为样本）。"""
    if row < 0 or row >= ctrl.GetItemCount():
        return "（无此行）"
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return "（行不可见）"
    origin = ctrl.ClientToScreen(wx.Point(rect.x, rect.y))
    width = ctrl.GetClientSize().width
    counts: dict[str, int] = {}
    total = 0
    for dy in range(2, max(rect.height - 2, 3), 3):
        for dx in range(1, max(width, 2), 2):
            colour = pixel(image, origin.x + dx, origin.y + dy)
            counts[colour] = counts.get(colour, 0) + 1
            total += 1
    best = max(counts.items(), key=lambda kv: kv[1])
    top3 = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    spread = "  ".join(f"{c}:{n * 100 // max(total, 1)}%" for c, n in top3)
    return f"{best[0]}   [{spread}]"


def scan(image: wx.Image, ctrl, row: int, step: int = 40) -> str:
    """一行里每隔 `step` 像素取一个点 —— 用来看"灰"是整行还是只有一段。"""
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return "（行不可见）"
    origin = ctrl.ClientToScreen(wx.Point(rect.x, rect.y))
    y = origin.y + rect.height // 2
    width = ctrl.GetClientSize().width
    return " ".join(f"{dx}:{pixel(image, origin.x + dx, y)}"
                    for dx in range(2, width, step))


# ----------------------------------------------------------------------
with probe_temp("probe-focus-bit") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, f"dir-{i:03d}"))
    fresh = os.path.join(scratch, "zzz-brand-new")
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
          f"card = {theme.card.upper()}")

    try:
        # ══ 单变量对照：只差 FOCUSED 位 ═════════════════════════════════
        target = 6
        print(f"\n══ A/B 对照（目标行 = {target}，"
              f"…{frame.row_path(target)[-24:]}）")

        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(target, wx.LIST_STATE_SELECTED, SEL_FOCUS)
        ctrl.EnsureVisible(target)
        ctrl.ScrollLines(target - ctrl.GetTopItem())
        ctrl.SetFocus()
        pump(20)
        flush(frame)
        image = screen_image()
        row_a = face(image, ctrl, target)
        print(f"  A 设了 FOCUSED：{row_a}")
        print(f"    横向扫描：{scan(image, ctrl, target)}")

        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        # **只清选中，不清 FOCUSED** —— 这就是 `_render_rows` 里那一段的做法
        ctrl.SetItemState(target, 0, SEL_FOCUS)
        ctrl.Select(target, True)
        ctrl.SetItemState(target, wx.LIST_STATE_SELECTED, SEL_FOCUS)
        pump(20)
        flush(frame)
        image = screen_image()
        row_b = face(image, ctrl, target)
        print(f"  B 清了 FOCUSED：{row_b}")
        print(f"    横向扫描：{scan(image, ctrl, target)}")

        check("A/B 对照：两种设置下那一行的颜色**不同**", row_a[:7] != row_b[:7],
              f"设了={row_a[:7]}  清了={row_b[:7]}")

        # ══ 从导航窗格"打开" —— 连走两遍（记忆化判据）══════════════════
        tree = frame.dir_ctrl.GetTreeCtrl()
        seen: list[str] = []
        for run in (1, 2):
            print(f"\n══ 第 {run} 遍：从导航窗格打开一条**新**路径")
            for i in range(ctrl.GetItemCount()):
                ctrl.Select(i, False)
            # 新记录按路径排序会落到**最前面**（`zzz-` 之前没有更小的名字），
            # 所以把视角停在顶部 —— 这样选中行一定在屏幕上，像素才量得到。
            anchor = 0
            ctrl.SetItemState(anchor, SEL_FOCUS, SEL_FOCUS)
            ctrl.EnsureVisible(anchor)
            ctrl.ScrollLines(anchor - ctrl.GetTopItem())
            tree.expand_to(fresh, select=True)
            frame._focus_pane = "tree"
            pump(10)
            print(f"   open_targets = {[p[-24:] for p in frame.open_targets()]}")
            frame.on_open(None)
            pump(40)
            flush(frame)
            image = screen_image()
            sel = ctrl.GetFirstSelected()
            stored = (ctrl.GetItemBackgroundColour(sel)
                      .GetAsString(wx.C2S_HTML_SYNTAX).upper() if sel >= 0 else "?")
            print(f"   选中 = {sel}（…{frame.row_path(sel)[-24:]}）  存值 = {stored}")
            print(f"   顶行 = {ctrl.GetTopItem()}   可见 "
                  f"{ctrl.GetTopItem()}..{ctrl.GetTopItem() + 6}")
            for row in range(ctrl.GetTopItem(), ctrl.GetTopItem() + 7):
                marker = "  ←选中" if row == sel else ""
                print(f"     row {row:4} {face(image, ctrl, row)}{marker}")
            if 0 <= sel < ctrl.GetItemCount():
                print(f"     选中行横向扫描：{scan(image, ctrl, sel)}")
            seen.append(face(image, ctrl, sel)[:7] if sel >= 0 else "?")
            check(f"第 {run} 遍：选中那行的屏幕像素 = 系统选中蓝",
                  seen[-1] == highlight.upper(),
                  f"屏幕 = {seen[-1]}   期望 = {highlight}")

        check("连走两遍的颜色**一致**（记忆化判据）",
              seen[0] == seen[1],
              f"第一遍 = {seen[0]}   第二遍 = {seen[1]}")
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
