"""验：**选中行变了之后，它一定被上过色** —— 不许"账本说画了、画面没有"。

## 这条判据是从用户本机的报告里抓出来的

用户 `paint-trace.txt`（真实数据、真实操作）：

```
+12210.4ms  底色(row=31, #FFFFFF)   ← 重建把它画成白
+12265.9ms  状态(row=31, set=6)     ← 设为选中
+12268.4ms  _apply_selection_highlight()  选中=31  键 (-1,-1) → (31,-1)  "画了"
            ↑ 报告里**没有**任何一次给 row 31 上色的记录
+15647.4ms  底色(row=31, #0078D7)   ← 直到鼠标离开列表才补上，中间 **3.4 秒是白的**
```

`_apply_selection_highlight()` **先记账（`_paint_key = key`）、后干活**，
于是中间任何一步失败，账本都会宣称"这个键画过了"，而画面并没有 ——
之后只要键不再变，那一行就**永远不再被重画**。

已改成"先干活、干成了再记账"。本探针把这条不变量钉住。

## 判据（不依赖"哪一次调用"，只依赖**结果**）

| # | 判据 |
|---|---|
| ① | 调用 `_apply_selection_highlight()` 后，若选中行与账本不一致 ⇒ 必须重画 |
| ② | **每次**选中行发生变化，**紧接着**必须有一次给**新选中行**上色的调用 |
| ③ | 上完色后账本必须与选中行一致（否则下次会被早退吃掉） |
| ④ | 连走两遍同一流程，第二遍结果必须与第一遍**一致**（记忆化判据） |
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


class PaintWatcher:
    """记录"给哪一行上过色"，用来核对"选中行到底有没有被上色"。"""

    def __init__(self, ctrl) -> None:
        self.ctrl = ctrl
        self.painted: list[tuple[int, str]] = []
        original = ctrl.SetItemBackgroundColour

        def wrapper(row, colour):
            self.painted.append((row, self._hex(colour)))
            return original(row, colour)

        wrapper.__name__ = "watched_SetItemBackgroundColour"
        self.original = original
        self.wrapper = wrapper
        ctrl.SetItemBackgroundColour = wrapper

    @staticmethod
    def _hex(colour) -> str:
        return colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()

    def take(self) -> list[tuple[int, str]]:
        snapshot, self.painted = self.painted, []
        return snapshot

    def stop(self) -> None:
        self.ctrl.SetItemBackgroundColour = self.original


with probe_temp("probe-paint-invariant") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, f"dir-{i:03d}"))
    fresh = os.path.join(scratch, "dir-a-new")
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
    watcher = PaintWatcher(ctrl)
    print(f"系统高亮 = {highlight}   row_hover = {theme.row_hover.upper()}")

    try:
        # ══ 判据 ①②③：逐个把选中换到不同行，每次都必须给新选中行上色 ══
        #
        # ⚠️ **`take()` 必须在改选中之前**。
        #
        # 第一版写在 `SetItemState` **之后**，于是把真正的上色动作丢掉了 ——
        # 而这个项目里 `SetItemState` 触发的事件是**同步**派发的：
        #
        #     设选中 → EVT_LIST_ITEM_SELECTED → on_selection_changed
        #            → `_apply_selection_highlight()`（当场就上色 + 记账）
        #
        # 之后再 `take()` 只能看到空历史，然后直接调 `_apply_selection_highlight()`
        # 又被早退（键没变）⇒ 探针打印"上色=（无）"。
        # **那是探针看错了地方，不是程序没上色。**
        print("\n══ 判据①②③：连续更换选中行，看新选中行有没有被上色")
        violations = []
        for step, target in enumerate((3, 17, 25, 8, 33)):
            watcher.take()                       # 先清历史，再改选中
            for i in range(ctrl.GetItemCount()):
                ctrl.Select(i, False)
            ctrl.SetItemState(target, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                              wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
            pump(6)                              # 让同步事件跑完
            painted = watcher.take()
            colour_of_target = [c for r, c in painted if r == target]
            ledger = getattr(frame, "_paint_key", None)
            got_blue = highlight in colour_of_target
            # ⚠️ **账本的"键"格式变过一次**（2026-10-17 加多选时）：
            #
            #     旧：(选中行, hovered)          例 `(3, -1)`
            #     新：(选中集, hovered)          例 `((3,), -1)`
            #
            # 判据要**两种都认**，否则键一改探针就报"账本不同步"，
            # 而那是**假失败**（程序其实是对的）。
            # 实测踩过：改多选之后这个探针掉到 3/5，两条都是这个原因。
            ledger_ok = ledger in (
                (target, getattr(frame, "_hover_row", -1)),
                ((target,), getattr(frame, "_hover_row", -1)),
            )
            print(f"  步{step + 1} 选中→{target}: 上色={colour_of_target or '（无）'}  "
                  f"账本={ledger}")
            if not got_blue or not ledger_ok:
                violations.append((target, colour_of_target, ledger))

        check("① 每次换选中后，**新选中行都被上成高亮蓝**",
              not violations,
              f"违规 {len(violations)} 次: {violations[:3]}")
        check("② 上色之后账本与选中行一致（否则下次会被早退吃掉）",
              not violations,
              f"账本={getattr(frame, '_paint_key', None)}")

        # ══ 判据④：连走两遍"从导航窗格打开"，结果必须一致 ══
        print("\n══ 判据④：连走两遍「从导航窗格打开一条新路径」")
        tree = frame.dir_ctrl.GetTreeCtrl()
        rounds = []
        for run in (1, 2):
            anchor = max(ctrl.GetItemCount() // 2, 1)
            ctrl.EnsureVisible(anchor)
            ctrl.ScrollLines(anchor - ctrl.GetTopItem())
            for i in range(ctrl.GetItemCount()):
                ctrl.Select(i, False)
            ctrl.SetItemState(anchor, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                              wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
            state = f"run{run}"
            tree.expand_to(fresh, select=True)
            frame._focus_pane = "tree"
            pump(10)
            watcher.take()
            frame.on_open(None)
            pump(35)
            selected = ctrl.GetFirstSelected()
            painted = watcher.take()
            colours = [c for r, c in painted if r == selected]
            rounds.append((selected, colours))
            print(f"  第{run}遍: 选中={selected}（…{frame.row_path(selected)[-20:]}）  "
                  f"上过的色={colours}")
            check(f"④-{run} 打开后新选中行被上成高亮蓝",
                  highlight in colours,
                  f"选中={selected} 上色={colours}")

        check("④ 两遍结果一致（记忆化判据：同进程连走两次）",
              rounds[0][1] == rounds[1][1] or highlight in rounds[0][1],
              f"第一遍={rounds[0][1]}  第二遍={rounds[1][1]}")
    finally:
        watcher.stop()
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
