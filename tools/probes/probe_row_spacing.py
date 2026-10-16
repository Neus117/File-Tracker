"""实测：`LVM_SETITEMSPACING` 到底改不改 **report 视图**的行高。

## 为什么要量

验证器报了一条失败：

```
行高 39px ≥ 文字高 35px + 额外 18px   ← 39 < 53，不成立
```

我配的"额外间距"是 **10 逻辑像素**（@168dpi = 18 物理像素），
而实测净空只有 39-35 = **4px**。两者对不上，三种可能：

1. 我的**模型错了**——行高不等于"文字高 + 间距"
2. `LVM_SETITEMSPACING` 在 report 视图下**部分生效**
3. 它**根本不生效**（MSDN 说该消息只对 icon / small-icon 视图有意义）

**这三种的修法完全不同，所以只能量。**

## 判据

把 extra 设成几个不同的值，**回读行高**。行高随 extra 变 ⇒ 生效；
纹丝不动 ⇒ 是空操作（那么"行距"这件事另有来源）。
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

from file_tracker import win32

with probe_temp("probe-row-spacing") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    seed = app_mod.PathStore(db)
    for i in range(12):
        seed.record_access(os.path.join(scratch, f"folder-{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(40):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    ctrl = frame.list_ctrl
    handle = ctrl.GetHandle()
    print(f"  列表行数 = {ctrl.GetItemCount()}")
    print(f"  GetItemRect(0).height 初始 = {ctrl.GetItemRect(0).height}")
    print(f"  文字高 (GetTextExtent 'Ag') = {ctrl.GetTextExtent('Ag')[1]}")
    print()

    def row_h() -> int:
        for _ in range(10):
            wx.YieldIfNeeded()
        return ctrl.GetItemRect(0).height

    print("  ── 改 extra，回读行高 ──")
    print(f"  {'extra':>6}{'行高':>8}{'净空(行高-文字高)':>20}")
    print("  " + "-" * 36)
    base = None
    results = {}
    for extra in (0, 2, 6, 10, 20, 40):
        win32.set_item_spacing(handle, -1, extra)
        h = row_h()
        results[extra] = h
        if base is None:
            base = h
        print(f"  {extra:>6}{h:>8}{h - ctrl.GetTextExtent('Ag')[1]:>20}")

    print()
    distinct = len(set(results.values()))
    if distinct == 1:
        print("  ⚠️ 行高完全不变 —— `LVM_SETITEMSPACING` 在 report 视图下**是空操作**")
    else:
        print(f"  ✅ 行高随 extra 变化（出现 {distinct} 种取值）—— 确实生效")
        print(f"     但**不是** '文字高 + extra'：")
        for extra, h in results.items():
            print(f"       extra={extra:>3} → 行高 {h}（差 {h - base:+d}）")

    # 对照：换个字号会不会改行高？（那才是 report 视图行高的真正来源）
    print()
    print("  ── 对照：字号改 1pt，行高会不会变 ──")
    f = ctrl.GetFont()
    for pt in (9, 10, 11, 12):
        ctrl.SetFont(wx.Font(pt, f.GetFamily(), f.GetStyle(),
                             wx.FONTWEIGHT_NORMAL, False, f.GetFaceName()))
        h = row_h()
        print(f"    {pt}pt → 行高 {h}px，文字高 {ctrl.GetTextExtent('Ag')[1]}px")

    frame.store.close()
    frame.Destroy()
