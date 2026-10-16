r"""验用户要的「多选打开 / 多选删除」—— 逐条对着他的原话。

## 用户的原话（2026-10-17）

> 1. 多选操作：按住 CTRL 键时，在这个记录窗格里面能够多选路径条目。
>    并且不止可以点击多选，**还可以拖动多选**。
> 2. 右键菜单：多选后点击右键，只保留两个选项，那就是"打开"和"删除"。

## 判据（一条对一句原话）

| # | 对应用户的话 | 判据 |
|---|---|---|
| [1] | "按住 CTRL 多选路径条目" | 真 Ctrl 点击两行 ⇒ 两条都选中（**原生行为**） |
| [2] | "还可以拖动多选" | 真拖拽 ⇒ 选中一个**区间**（**自己实现的**） |
| [3] | —（必须配套） | 我方高亮把**每一条**选中行都画成蓝色 |
| [4] | "右键只保留两个选项" | 多选时菜单项 = 两项，且是打开/删除 |
| [5] | "多选打开" | `open_targets()` 返回**全部**选中 |
| [6] | "多选删除" | 一次删掉选中的**全部**，未选中的留着 |

拖拽用的是本项目**自己实现**的那条路（原生框选实测不可用，
见 `probe_multiselect_drag.py`），所以这里发的是
`WM_LBUTTONDOWN` / `WM_MOUSEMOVE` / `WM_LBUTTONUP` —— 与真实拖动同一条消息链。
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
send_message = user32.SendMessageW
send_message.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                         ctypes.c_void_p, ctypes.c_void_p]
send_message.restype = ctypes.c_void_p

WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
MK_LBUTTON, MK_CONTROL = 0x0001, 0x0008
VK_CONTROL = 0x11
KEYEVENTF_KEYUP = 0x0002

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=20, pause=0.006):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def selected_rows(ctrl):
    rows = []
    index = ctrl.GetFirstSelected()
    while index != -1:
        rows.append(index)
        index = ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
    return sorted(rows)


def clear_selection(ctrl):
    for i in range(ctrl.GetItemCount()):
        ctrl.Select(i, False)
    pump(8)


def click_row(ctrl, row, *, ctrl_down=False):
    rect = ctrl.GetItemRect(row)
    if rect.height <= 0:
        return False
    x = min(150, max(rect.width // 5, 10))
    y = rect.y + rect.height // 2
    hwnd = ctypes.c_void_p(ctrl.GetHandle())
    lp = ctypes.c_void_p((y << 16) | (x & 0xFFFF))
    if ctrl_down:
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
    try:
        flags = MK_LBUTTON | (MK_CONTROL if ctrl_down else 0)
        send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(flags), lp)
        send_message(hwnd, WM_LBUTTONUP,
                     ctypes.c_void_p(flags & ~MK_LBUTTON), lp)
    finally:
        if ctrl_down:
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    return True


def drag_rows(ctrl, row_from, row_to):
    """发真的拖拽消息链（按下 → 多次移动 → 抬起）。"""
    a, b = ctrl.GetItemRect(row_from), ctrl.GetItemRect(row_to)
    if a.height <= 0 or b.height <= 0:
        return False
    hwnd = ctypes.c_void_p(ctrl.GetHandle())
    x = min(150, max(a.width // 5, 10))
    y0 = a.y + a.height // 2
    y1 = b.y + b.height // 2
    send_message(hwnd, WM_LBUTTONDOWN, ctypes.c_void_p(MK_LBUTTON),
                 ctypes.c_void_p((y0 << 16) | (x & 0xFFFF)))
    steps = 10
    for step in range(1, steps + 1):
        y = y0 + (y1 - y0) * step // steps
        send_message(hwnd, WM_MOUSEMOVE, ctypes.c_void_p(MK_LBUTTON),
                     ctypes.c_void_p((y << 16) | (x & 0xFFFF)))
        pump(3)
    send_message(hwnd, WM_LBUTTONUP, None,
                 ctypes.c_void_p((y1 << 16) | (x & 0xFFFF)))
    pump(15)
    return True


class Painter:
    """记录给哪一行上过什么色。"""

    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.rows = []
        self.original = ctrl.SetItemBackgroundColour

        def wrapper(row, colour):
            self.rows.append((row, colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()))
            return self.original(row, colour)

        wrapper.__name__ = "wrapped"
        ctrl.SetItemBackgroundColour = wrapper

    def take(self):
        out, self.rows = self.rows, []
        return out

    def stop(self):
        self.ctrl.SetItemBackgroundColour = self.original


class MenuSpy:
    """拦下 `PopupMenu`，把菜单项文字记下来（不真的弹出来）。"""

    def __init__(self, frame):
        self.frame = frame
        self.labels = []
        self.original = frame.PopupMenu

        def fake(menu, *args, **kwargs):
            for item in menu.GetMenuItems():
                self.labels.append(item.GetItemLabelText())
            return None

        frame.PopupMenu = fake

    def stop(self):
        self.frame.PopupMenu = self.original


with probe_temp("probe-multiselect-feature") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    for i in range(30):
        os.makedirs(os.path.join(scratch, "dir-%03d" % i), exist_ok=True)

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    painter = Painter(ctrl)
    menu_spy = MenuSpy(frame)
    print("系统高亮 = %s   列表 LC_SINGLE_SEL = %s"
          % (highlight, bool(ctrl.GetWindowStyleFlag() & wx.LC_SINGLE_SEL)))

    try:
        ctrl.SetFocus()
        pump(10)

        # ── [1] 真 Ctrl 点击多选 ────────────────────────────────
        clear_selection(ctrl)
        click_row(ctrl, 2)
        pump(15)
        first = selected_rows(ctrl)
        click_row(ctrl, 6, ctrl_down=True)
        pump(20)
        ctrl_rows = selected_rows(ctrl)
        print("\n[1] 真 Ctrl 点击：点第 2 行 -> %s；Ctrl 点第 6 行 -> %s"
              % (first, ctrl_rows))
        check("[1] 按住 CTRL 能多选（点击）", ctrl_rows == [2, 6],
              "选中 = %s" % ctrl_rows)

        # ── [2] 真拖拽多选 ──────────────────────────────────────
        clear_selection(ctrl)
        pump(8)
        painter.take()
        drag_rows(ctrl, 4, 9)
        drag_result = selected_rows(ctrl)
        print("\n[2] 真拖拽（第 4 行 -> 第 9 行）：选中 = %s" % drag_result)
        check("[2] 拖动能多选出一整段", drag_result == list(range(4, 10)),
              "选中 = %s（期望 4..9）" % drag_result)

        # ── [3] 高亮把每一条选中行都画上 ────────────────────────
        drawn = painter.take()
        blue_rows = sorted({r for r, c in drawn if c == highlight})
        print("\n[3] 被画成蓝色的行 = %s" % blue_rows)
        check("[3] 选中行**每一条**都上成高亮蓝（不是只画第一条）",
              set(drag_result) <= set(blue_rows),
              "选中 = %s；画蓝的 = %s" % (drag_result, blue_rows))

        # ── [4] 右键菜单：多选只有两项 ──────────────────────────
        menu_spy.labels = []
        frame.on_right_click(None)
        pump(10)
        multi_labels = list(menu_spy.labels)
        print("\n[4] 多选时右键菜单项 = %s" % multi_labels)
        check("[4] 多选时右键**只有打开和删除两项**",
              len(multi_labels) == 2
              and multi_labels[0].startswith("打开")
              and multi_labels[1].startswith("删除"),
              "菜单 = %s" % multi_labels)

        # 阳性对照：单选时仍是四项
        clear_selection(ctrl)
        ctrl.Select(0, True)
        pump(10)
        menu_spy.labels = []
        frame.on_right_click(None)
        pump(10)
        single_labels = list(menu_spy.labels)
        print("    阳性对照（单选）= %s" % single_labels)
        check("[4b] 阳性对照：单选时仍是原来的四项（没被砍掉）",
              len(single_labels) == 4, "菜单 = %s" % single_labels)

        # ── [5] 多选打开 = 全部选中 ─────────────────────────────
        clear_selection(ctrl)
        for row in (1, 3, 5):
            ctrl.Select(row, True)
        pump(10)
        frame._focus_pane = "list"
        targets = frame.open_targets()
        expect = [frame.row_path(r) for r in (1, 3, 5)]
        print("\n[5] 多选打开：open_targets() = %s" % [p[-12:] for p in targets])
        check("[5] 多选打开 => 目标 = **全部**选中项（按行号顺序）",
              targets == expect,
              "目标 = %s 期望 = %s"
              % ([p[-12:] for p in targets], [p[-12:] for p in expect]))

        # ── [6] 多选删除 ────────────────────────────────────────
        victim_rows = (2, 4, 6)
        victim_paths = [frame.row_path(r) for r in victim_rows]
        survivor_path = frame.row_path(0)
        clear_selection(ctrl)
        for row in victim_rows:
            ctrl.Select(row, True)
        pump(10)
        before_total = ctrl.GetItemCount()
        selected_now = frame.selected_paths()
        print("\n[6] 多选删除：选中 %d 条（行 %s）" % (len(selected_now), victim_rows))
        frame._remove_paths(selected_now)
        pump(25)
        after_total = ctrl.GetItemCount()
        still_there = [p for p in victim_paths if frame.find_path(p) >= 0]
        print("    列表行数 %d -> %d；应删的还在列表里的 = %s"
              % (before_total, after_total, still_there))
        check("[6] 多选删除 => 选中的**全部**被删掉",
              after_total == before_total - len(selected_now) and not still_there,
              "行数 %d -> %d，残留 = %s" % (before_total, after_total, still_there))
        check("[6b] 多选删除没有误删未选中的",
              survivor_path not in victim_paths,
              "未选中的那条仍然 = …%s" % survivor_path[-24:])

        # ── [6c] 删除之后**选中必须自然消失** ────────────────────
        #
        # ⚠️ 用户 2026-10-17 报的 bug 就在这里：
        #
        # > "多选并删除后，多选状态会**偏移到另外多条记录**上，不会自然消失。"
        #
        # 根因：`_render_rows` 里"全清陈旧选中"那一段原来和"恢复选中"
        # 共用了一个 `if target_rows:` —— 删除之后那些路径已经不在库里，
        # `target_rows` 是空的，**连带全清也被跳过** ⇒ 原生控件里
        # 陈旧的**行号**留了下来，而行号已经平移 ⇒ 选中框跑到隔壁几条上。
        #
        # 判据要**直接量"选中集空不空"**，不能只看行数 ——
        # 只看行数时这个 bug 完全看不出来（行数确实少了）。
        after_rows = selected_rows(ctrl)
        after_paths = frame.selected_paths()
        print("    删除后选中 = %s（paths = %s）" % (after_rows, after_paths))
        check("[6c] **删除后选中自然消失**（不许偏移到别的记录上）",
              after_rows == [] and after_paths == [],
              "删除后仍有选中 = %s" % after_rows)
        # 阳性对照：删除**之前**确实是有选中的，
        # 否则 [6c] 会因为"本来就没选中"而假通过。
        check("[6d] 阳性对照：删除前确实有多选（否则 [6c] 是假通过）",
              len(selected_now) == 3,
              "删除前选中 %d 条" % len(selected_now))
    finally:
        painter.stop()
        menu_spy.stop()
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败" % (len(results), passed, len(results) - passed))
