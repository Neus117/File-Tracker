r"""验：**路径列左内边距 == 时间列（居中）左右边距**（用户 2026-10-17）。

## 用户的要求

> "我希望路径(path)数据的左边距和时间(time)的左右边距保持一致，
>   这样可以保证微调边距时保持视觉规整和一致性。具体使用什么算法进行统一你来设计。"

## 两列的实现机制本来就不同

| 列 | 对齐 | 边距从哪来 |
|---|---|---|
| 路径 | 左对齐 | **前导空格**（`PATH_LEFT_PAD`）—— 原生缩进 API 返回 1 却不生效 |
| 时间 | **居中** | 由"列宽 − 数据宽"自动对半分 |

机制不同 ⇒ 各算各的必然跑偏。所以设计上把两者绑到**同一个单位**：

```
路径左内边距 = CELL_PADDING_SPACES × 空格宽
时间列 extra  = 2 × CELL_PADDING_SPACES × 空格宽    （居中 ⇒ 左右各一半）
```

## 判据

| # | 判据 |
|---|---|
| 1 | 两种语言下：**路径左边距 == 时间左边距**（差 ≤ 1 像素，取整误差） |
| 2 | 时间列的左边距与右边距相等（它确实居中） |
| 3 | 阳性对照：两者都 > 0（否则"都等于 0"也会让判据 1 通过） |
| 4 | 改 `CELL_PADDING_SPACES` 时**两边同时变**（差仍然 ≤ 1） |
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

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

app = wx.App(redirect=False)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=20, pause=0.004):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def margins(frame) -> dict:
    """量两列的"数据到列边界"的距离（物理像素）。"""
    dc = wx.ClientDC(frame.list_ctrl)
    dc.SetFont(frame.list_ctrl.GetFont())
    space = dc.GetTextExtent(" ").width

    # 路径列：左内边距就是前导空格的宽度
    path_left = dc.GetTextExtent(app_mod.PATH_LEFT_PAD).width

    # 时间列：居中的左右边距
    time_width = frame.list_ctrl.GetColumnWidth(app_mod.COLUMN_TIME)
    sample = ""
    for row in range(min(frame.list_ctrl.GetItemCount(),
                         app_mod.FileTracker.COLUMN_WIDTH_SAMPLE)):
        text = frame.list_ctrl.GetItemText(row, app_mod.COLUMN_TIME)
        if dc.GetTextExtent(text).width > dc.GetTextExtent(sample).width:
            sample = text
    data_w = dc.GetTextExtent(sample).width
    slack = time_width - data_w
    return {
        "space": space,
        "path_left": path_left,
        "time_left": slack // 2,
        "time_right": slack - slack // 2,
        "time_width": time_width,
        "data_w": data_w,
        "sample": sample,
    }


with probe_temp("probe-cell-padding") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(20):
        seed.record_access("D:\\dir-%03d" % i, when="2026-10-17 14:43:27")
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.SetSize((1100, 460))
    frame.Show()
    pump(60)

    try:
        # ── 判据 1~3：两种语言下两边相等 ──────────────────────
        for preference, name in ((lang.PREFERENCE_CHINESE, "中文"),
                                 (lang.PREFERENCE_ENGLISH, "英文")):
            lang.apply(preference)
            frame.retranslate()
            pump(25)
            info = margins(frame)
            print("\n【%s】空格宽=%d  时间列宽=%d  时间数据宽=%d"
                  % (name, info["space"], info["time_width"], info["data_w"]))
            print("  路径数据左边距 = %d" % info["path_left"])
            print("  时间数据左边距 = %d   右边距 = %d"
                  % (info["time_left"], info["time_right"]))

            # 用户的最终选择：**两边相等**（"微调时保持视觉规整和一致性"）。
            # 中间一度把路径列归零过，但那条空白其实来自 `card_panel` 的
            # 四周留白（不是这个内边距）—— 归零只会让路径文字贴边、
            # 反而破坏与时间列的一致性。用户看效果后要求回到这一版。
            check("1 [%s] 路径左边距 == 时间左边距（差 ≤ 1）" % name,
                  abs(info["path_left"] - info["time_left"]) <= 1,
                  "路径 %d vs 时间 %d（差 %d）"
                  % (info["path_left"], info["time_left"],
                     info["path_left"] - info["time_left"]))
            check("2 [%s] 时间列的左右边距相等（它确实居中）" % name,
                  abs(info["time_left"] - info["time_right"]) <= 1,
                  "左 %d，右 %d" % (info["time_left"], info["time_right"]))
            check("3 [%s] 阳性对照：两边都**大于 0**（不是全都 0 混过去）"
                  % name,
                  info["path_left"] > 0 and info["time_left"] > 0,
                  "路径 %d，时间 %d" % (info["path_left"], info["time_left"]))

        # ── 判据 4：改常量时两边同时变 ────────────────────────
        lang.apply(lang.PREFERENCE_CHINESE)
        frame.retranslate()
        pump(20)
        before = margins(frame)
        original = app_mod.CELL_PADDING_SPACES
        try:
            # 临时改成 4 个空格，看两边是否同步放大
            app_mod.CELL_PADDING_SPACES = 4
            app_mod.PATH_LEFT_PAD = " " * 4
            frame.load_accessed_paths()
            frame.adjust_column_widths()
            pump(25)
            after = margins(frame)
            print("\n【改常量 2 → 4】")
            print("  路径左边距 %d → %d" % (before["path_left"], after["path_left"]))
            print("  时间左边距 %d → %d" % (before["time_left"], after["time_left"]))
            check("4 改常量后，**两边同步放大**且仍相等（差 ≤ 1）",
                  after["path_left"] > before["path_left"]
                  and after["time_left"] > before["time_left"]
                  and abs(after["path_left"] - after["time_left"]) <= 1,
                  "路径 %d→%d，时间 %d→%d"
                  % (before["path_left"], after["path_left"],
                     before["time_left"], after["time_left"]))
        finally:
            app_mod.CELL_PADDING_SPACES = original
            app_mod.PATH_LEFT_PAD = " " * original
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(10)

print()
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败"
      % (len(results), sum(1 for ok, _, _ in results if ok),
         sum(1 for ok, _, _ in results if not ok)))
