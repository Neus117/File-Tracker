"""验：**双击导航窗格中的文件**之后，焦点与选中要和「打开」按钮**完全一致**。

## 用户实测报回来的差异（2026-10-17）

> "使用「打开」按钮一切正常符合预期，**只有双击导航窗格中的文件**记录的条目这样，
>   也就是双击导航窗格中的文件后**焦点没有转移到记录窗格**，一直停留在导航窗格。"

根因：`on_dir_item_activated` 里**没有** `_focus_pane = "tree"`，
而 `record_accessed_path` 里"给列表焦点 + 换选中"整块都由 `from_tree` 把关 ⇒
双击文件那条路上这两件事**一起被跳过**。

## 判据（两条路**并排比**，不各测各的）

| # | 判据 |
|---|---|
| ① | 双击文件后：**焦点 = ListCtrl**（不是导航树） |
| ② | 双击文件后：刚记录那条**被上成高亮蓝** |
| ③ | 双击文件后：`_focus_pane == "tree"`（意图声明正确） |
| ④ | **阳性对照**：「打开」按钮那条路的这两项**本来就对**（不能被改坏） |
| ⑤ | 两条路的"焦点 + 选中颜色"**结果一致**（这才是用户要的） |

⚠️ 本探针**不弹资源管理器**（`open_folder` 换桩），只测焦点与上色。
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
    try:
        ctypes.windll.user32.SetCursorPos(6, 902)
    except Exception:
        pass


def pump(rounds: int = 25) -> None:
    park_mouse()
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.004)
    park_mouse()


class FakeActivateEvent:
    """`wx.TreeEvent` 的最小替身：只要 `GetItem()` 与 `Veto()`。

    用它而不是真发一个双击，是为了**把"用户双击"和"事件怎么来的"分开**：
    被测的是 `on_dir_item_activated` 的行为，不是 wx 的事件派发。
    """

    def __init__(self, item) -> None:
        self._item = item
        self.vetoed = False

    def GetItem(self):
        return self._item

    def Veto(self) -> None:
        self.vetoed = True

    def Skip(self) -> None:
        pass


class Painter:
    """记录给哪一行上过什么色。"""

    def __init__(self, ctrl) -> None:
        self.ctrl = ctrl
        self.rows: list[tuple[int, str]] = []
        self.original = ctrl.SetItemBackgroundColour

        def wrapper(row, colour):
            self.rows.append((row, colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()))
            return self.original(row, colour)

        wrapper.__name__ = "wrapped"
        self.wrapper = wrapper
        ctrl.SetItemBackgroundColour = wrapper

    def take(self) -> list[tuple[int, str]]:
        out, self.rows = self.rows, []
        return out

    def stop(self) -> None:
        self.ctrl.SetItemBackgroundColour = self.original


def focus_name() -> str:
    focus = wx.Window.FindFocus()
    return type(focus).__name__ if focus else "None"


with probe_temp("probe-tree-dblclick") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(20):
        seed.record_access(os.path.join(scratch, f"dir-{i:03d}"))
    seed.close()

    # **一个真实的文件**：双击它应当记录它的**父文件夹**
    victim_file = os.path.join(scratch, "target-file.txt")
    with open(victim_file, "w", encoding="utf-8") as handle:
        handle.write("probe\n")
    victim_folder = scratch

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()      # 不弹资源管理器
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    theme = frame.theme
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()
    painter = Painter(ctrl)
    print(f"系统高亮 = {highlight}   row_hover = {theme.row_hover.upper()}")
    print(f"要双击的文件 = {victim_file}")
    print(f"应当记录的父文件夹 = …{victim_folder[-24:]}")

    try:
        tree = frame.dir_ctrl.GetTreeCtrl()

        # ══ 场景 A：双击导航窗格里的**文件** ══════════════════════
        print("\n══ 场景A：双击导航窗格里的**文件**")
        item = tree.expand_to(victim_file, select=True)
        if item is None or not item.IsOk():
            # 树里定位不到这个文件：退一步只展开到父目录，仍然测焦点与选中
            print("   （树里定位不到该文件，退回展开父目录）")
            item = tree.expand_to(victim_folder, select=True)
        print(f"   树节点 = {item!r}   GetPath = {frame.dir_ctrl.GetPath(item)[-30:]}")

        # 先把焦点交给树（模拟"用户刚在导航窗格操作"）
        tree.SetFocus()
        frame._focus_pane = "list"          # **故意设成 list**：复刻修复前的残留值
        pump(15)
        painter.take()

        event = FakeActivateEvent(item)
        frame.on_dir_item_activated(event)
        pump(30)

        focus_a = focus_name()
        pane_a = getattr(frame, "_focus_pane", None)
        sel_a = ctrl.GetFirstSelected()
        painted_a = painter.take()
        colours_a = [c for r, c in painted_a if r == sel_a]
        path_a = frame.row_path(sel_a)
        print(f"   焦点 = {focus_a}   _focus_pane = {pane_a!r}   "
              f"选中 = {sel_a}（…{path_a[-24:]}）  上色 = {colours_a}")
        print(f"   event.Veto() 已调 = {event.vetoed}")

        check("① 双击文件后：**焦点转移到了记录列表**（不再停在导航树）",
              focus_a == "ListCtrl", f"焦点 = {focus_a}")
        check("② 双击文件后：刚记录那条被上成**高亮蓝**",
              highlight in colours_a, f"上色 = {colours_a}")
        # ⚠️ **终态是 `'list'` 才对**（第一版我把判据写反了）。
        #
        # 顺序是：
        #   ① `on_dir_item_activated` 设 `_focus_pane = "tree"`   ← 让 from_tree 为真
        #   ② `record_accessed_path` 里 `SetFocus()` + 上色
        #   ③ `SetFocus()` 触发 `EVT_SET_FOCUS` → `on_list_selection_made`
        #      → `_focus_pane = "list"`                            ← **正确的终态**
        #
        # `_focus_pane` 的语义是"用户最后一次在哪里操作"，
        # 而此刻焦点**确实已经在记录列表上**了 —— 所以终态必须是 `'list'`。
        # 判据①（焦点=ListCtrl）与②（上色）才是真正要验的东西：
        # 它们成立本身就证明 `from_tree` 当时为真。
        check("③ 双击文件后：焦点归列表 ⇒ `_focus_pane` 终态为 'list'（语义正确）",
              pane_a == "list", f"_focus_pane = {pane_a!r}")
        check("③b 记录的是**文件的父文件夹**（v1.1 就有的规则）",
              path_a == victim_folder, f"记录 …{path_a[-26:]} vs 期望 …{victim_folder[-26:]}")

        # ══ 场景 B：阳性对照 —— 「打开」按钮那条路 ═════════════════
        print("\n══ 场景B（阳性对照）：「打开」按钮那条路")
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(0, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                          wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        tree.SetFocus()
        frame._focus_pane = "tree"
        pump(15)
        painter.take()
        fresh_folder = os.path.join(scratch, "brand-new-folder")
        os.makedirs(fresh_folder, exist_ok=True)
        tree.expand_to(fresh_folder, select=True)
        pump(10)
        frame.on_open(None)                  # = 按「打开」
        pump(30)

        focus_b = focus_name()
        sel_b = ctrl.GetFirstSelected()
        painted_b = painter.take()
        colours_b = [c for r, c in painted_b if r == sel_b]
        print(f"   焦点 = {focus_b}   _focus_pane = {frame._focus_pane!r}   "
              f"选中 = {sel_b}  上色 = {colours_b}")

        check("④ 阳性对照：「打开」按钮那条路焦点也 = ListCtrl（没被改坏）",
              focus_b == "ListCtrl", f"焦点 = {focus_b}")
        check("④b 阳性对照：「打开」按钮那条路也上成高亮蓝",
              highlight in colours_b, f"上色 = {colours_b}")
        check("⑤ **两条路结果一致**（焦点 + 上色颜色）",
              (focus_a, highlight in colours_a) == (focus_b, highlight in colours_b),
              f"双击文件=({focus_a}, {highlight in colours_a})  "
              f"打开按钮=({focus_b}, {highlight in colours_b})")
    finally:
        painter.stop()
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
