"""诊断：把"改底色 / 改选中 / 重画高亮"三件事的**先后顺序**完整记录下来。

## 为什么改量"顺序"而不是"像素"

屏幕抓图在本机**不可信**：把某行涂成纯红 `#FF0000`，抓回来的仍是 `#FFFFFF`
（DWM 合成 + 硬件覆盖层，`BitBlt`/`ScreenDC` 读不到真实合成结果）。
仪器不可信时**不能拿它的读数当结论**。

但**调用顺序**是可观测且无歧义的，而"那一行是不是蓝的"完全由顺序决定：

* 本项目的高亮**不是原生画的** —— 是 `_apply_selection_highlight()`
  用 `SetItemBackgroundColour(行, #0078D7)` 自己画的
* 所以「选中那行变蓝」⇔ **下面两件事的先后**：
  `SetItemState(选中行)` 必须发生在 `SetItemBackgroundColour(选中行, #0078D7)` **之前**

顺序反了 ⇒ 蓝色被画到了**上一次**的选中行，真正选中的那一行**没有人再画**，
屏幕上留着的就是它重建时的底色（或上一次高亮留下的 `theme.row_hover` 灰）。

## 本探针记录

| 事件 | 记录什么 |
|---|---|
| `SetItemBackgroundColour` / `SetItemTextColour` | 行号 + 颜色 |
| `SetItemState` / `Select` | 行号 + 状态位 |
| `_apply_selection_highlight` | **进去没有？还是被 `_paint_key` 早退吃掉了？** |
| 选中行变化 | 只在**真的变了**的时候记一行，便于对齐 |

最后给出**判定**：最后 20 次事件里，蓝色（`SYS_COLOUR_HIGHLIGHT`）
有没有出现在**当前选中行**上、且**晚于**选中变化。
"""
from __future__ import annotations

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

SEL_FOCUS = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
BLUE = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
    .GetAsString(wx.C2S_HTML_SYNTAX).upper()
log: list[str] = []


def pump(rounds: int = 25) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.004)


class OrderProbe:
    """按时间顺序记录"谁把哪一行改成了什么"。"""

    def __init__(self, frame) -> None:
        self.frame = frame
        self.ctrl = frame.list_ctrl
        self.t0 = time.time()
        self.last_sel = self.ctrl.GetFirstSelected()
        self.blue_paints: list[tuple[int, int, str]] = []   # (序号, 行, 蓝)
        self.counter = 0
        self._mark(f"── 开始记录：选中 = {self.last_sel}，"
                   f"顶行 = {self.ctrl.GetTopItem()} ──")
        self._install()

    def _mark(self, text: str) -> None:
        self.counter += 1
        log.append(f"{self.counter:4}. [+{(time.time() - self.t0) * 1000:7.1f}ms] {text}")

    def _install(self) -> None:
        probe = self

        def wrap(owner, name, formatter):
            original = getattr(owner, name, None)
            if original is None:
                return

            def wrapper(*args, **kwargs):
                probe._mark(formatter(*args))
                return original(*args, **kwargs)

            wrapper.__name__ = f"traced_{name}"
            setattr(owner, name, wrapper)

        wrap(self.ctrl, "SetItemBackgroundColour",
             lambda row, colour:
             f"底(row={row}, {colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()})"
             + ("   ★蓝色" if colour.GetAsString(wx.C2S_HTML_SYNTAX).upper() == BLUE
                else ""))
        wrap(self.ctrl, "SetItemTextColour",
             lambda row, colour:
             f"字(row={row}, {colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()})")
        wrap(self.ctrl, "SetItemState",
             lambda row, set_, clear_=0: f"状态(row={row}, set={set_})")
        wrap(self.ctrl, "Select", lambda row, state: f"选中(row={row}, {state})")

        original_highlight = self.frame._apply_selection_highlight

        def traced_highlight():
            before = (self.frame._paint_key, self.ctrl.GetFirstSelected(),
                      getattr(self.frame, "_highlighted_row", None))
            result = original_highlight()
            after = (self.frame._paint_key, self.ctrl.GetFirstSelected(),
                     getattr(self.frame, "_highlighted_row", None))
            if before[0] == after[0]:
                probe._mark(f"高亮() **被 _paint_key 早退吃掉** "
                            f"key={after[0]}")
            else:
                probe._mark(f"高亮() 真的画了  key {before[0]} → {after[0]}")
            return result

        self.frame._apply_selection_highlight = traced_highlight

    def note_blue(self, index: int, row: int) -> None:
        self.blue_paints.append((index, row, "blue"))


with probe_temp("probe-order") as scratch:
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
    print(f"系统高亮 = {BLUE}   row_hover = {frame.theme.row_hover.upper()}"
          f"   card = {frame.theme.card.upper()}")

    try:
        # 只记录"打开"这一段，前面建窗口的噪声丢掉
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(5, SEL_FOCUS, SEL_FOCUS)
        ctrl.EnsureVisible(5)
        ctrl.ScrollLines(5 - ctrl.GetTopItem())
        tree = frame.dir_ctrl.GetTreeCtrl()
        tree.expand_to(fresh, select=True)
        frame._focus_pane = "tree"
        pump(15)

        probes = OrderProbe(frame)
        print(f"\n══ 从导航窗格打开（选中行 5，目标 = …{fresh[-22:]}）")
        frame.on_open(None)
        pump(40)

        selected = ctrl.GetFirstSelected()
        print(f"\n── 事件顺序（{len(log)} 条）──")
        for line in log:
            print("  " + line)

        # ── 判定：最后 20 条里，蓝色有没有落在**当前选中行**上 ──
        print(f"\n── 判定 ──")
        print(f"  最终选中行 = {selected}"
              f"（…{frame.row_path(selected)[-22:]}）")
        tail = log[-24:]
        blue_on_selected = [line for line in tail
                            if "★蓝色" in line and f"(row={selected}," in line]
        states = [line for line in tail if "状态(row=" in line]
        print(f"  最后 {len(tail)} 条里，**蓝色画在选中行 {selected}** 上的次数 = "
              f"{len(blue_on_selected)}")
        for line in blue_on_selected:
            print(f"     {line}")
        print(f"  这段时间里的设选中调用：{len(states)} 次")
        for line in states:
            print(f"     {line}")
        if states and blue_on_selected:
            state_index = log.index(states[-1])
            blue_index = log.index(blue_on_selected[-1])
            verdict = ("✅ 蓝色画在选中**之后**（顺序对）"
                       if blue_index > state_index
                       else "❌ 蓝色画在选中**之前**（顺序反了 —— 就是它）")
            print(f"  最后一次设选中在第 {state_index + 1} 条，"
                  f"最后一次给选中行画蓝在第 {blue_index + 1} 条 ⇒ {verdict}")
        elif states and not blue_on_selected:
            print("  ❌ 设了选中，但**没有任何一次**蓝色落在选中行上 —— "
                  "那一行最终留着的就是别人给的灰")
        else:
            print("  ⚠️ 这段里没有设选中/没有蓝色记录，判定不成立，看上面的顺序清单")
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)
