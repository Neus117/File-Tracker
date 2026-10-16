"""量：置顶时视角**跟不跟**，取消置顶时视角**动不动**。

## 用户要的两条

1. **置顶** → 焦点跟随，落到被置顶那条（**最顶端**）
   > "我需要置顶时，焦点跟随落在被置顶的那条路径上——也就是最顶端。"
2. **取消置顶** → **保持原样**
   > "取消置顶时的聚焦逻辑是正确的，**不要动**。"

## 判据

* 置顶后：`GetTopItem()` 应当让被置顶那条**可见**（它在第 0 行，所以顶行应当很小）
* 取消置顶后：`GetTopItem()` 应当**基本不变**（保持视角）

**"我觉得应该对了"不算证据** —— 这一阶段已经在这上面返工四轮。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

COUNT = 200


def settle(times: int = 25) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def state(frame, label):
    ctrl = frame.list_ctrl
    top = ctrl.GetTopItem()
    sel = ctrl.GetFirstSelected()
    top_path = frame._rows[top].path if 0 <= top < len(frame._rows) else "?"
    sel_path = frame._rows[sel].path if 0 <= sel < len(frame._rows) else "?"
    print(f"    {label:16} top={top:<4} sel={sel:<4}")
    print(f"    {'':16} 顶行 …{top_path[-26:]}")
    print(f"    {'':16} 选中 …{sel_path[-26:]}")
    return top, sel, sel_path


with probe_temp("probe-pin-focus") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(COUNT):
        seed.record_access(os.path.join(scratch, f"dir-{i:04d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    frame.Maximize()
    settle(60)
    ctrl = frame.list_ctrl

    # 滚到靠下、选中靠下的一条（模拟"翻到下面，右键置顶"）
    target = COUNT - 40
    ctrl.EnsureVisible(target)
    ctrl.ScrollLines(target - ctrl.GetTopItem())
    settle()
    chosen = target + 6
    for i in range(COUNT):
        if i != chosen:
            ctrl.Select(i, False)
    ctrl.SetItemState(chosen,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    settle()

    chosen_path = frame._rows[chosen].path
    print(f"  置顶目标 = …{chosen_path[-30:]}")
    print()
    print("  ── 置顶之前 ──")
    before_top, _, _ = state(frame, "初始")
    print()

    frame.on_pin(None)
    settle(40)
    print("  ── 置顶之后（期望：跟到最顶端，能看见它）──")
    after_top, after_sel, after_sel_path = state(frame, "置顶后")
    print()

    pin_ok = after_sel_path == chosen_path
    visible = after_top <= 2
    print(f"    ① 选中仍是置顶那条      {'✅' if pin_ok else '❌ ' + after_sel_path[-26:]}")
    print(f"    ② 视角跟到了最顶端      "
          f"{'✅ top=' + str(after_top) if visible else '❌ 还在 top=' + str(after_top)}")
    print()

    # ── 取消置顶：**不该动** ──
    frame.on_unpin(None)
    settle(40)
    print("  ── 取消置顶之后（期望：位置基本不动）──")
    unpin_top, _, _ = state(frame, "取消置顶后")
    print()
    drift = abs(unpin_top - after_top)
    print(f"    ③ 视角保持（漂移应很小）  "
          f"{'✅ 漂移 ' + str(drift) + ' 行' if drift <= 3 else '❌ 漂移 ' + str(drift) + ' 行'}")

    frame.store.close()
    frame.Destroy()
