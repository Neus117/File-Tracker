r"""验：删掉一条**失效路径**之后，选中与高亮不许错位。

## 为什么单独验这个

`_remove_paths`（右键删除）走的是"整表重建"，已经被
`probe_multiselect_feature.py` 的 `[6c]` 钉住了。

但 `remove_invalid_path`（双击/打开一条**失效**路径 → 确认删除）
走的是**另一条路**：`DeleteItem(一行)` + 手工重建 `_rows`，
**不整表重建** ⇒ `_render_rows` 里那套"清账本 + 重画"根本不会跑。

`DeleteItem` 会让后面所有行的**行号往前挪一格**，而选中与高亮
账本都是按行号记的 ⇒ 不修就会出现"选中/蓝色偏移到隔壁记录"。

## 判据

| # | 判据 |
|---|---|
| 1 | 删完之后列表里**没有选中**（不许偏移到隔壁） |
| 2 | 删完之后**没有错误的蓝色残留** |
| 3 | 阳性对照：删之前确实有选中、确实有蓝色 |
"""
from __future__ import annotations

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
lang.apply(lang.PREFERENCE_CHINESE)

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


def blue_rows(ctrl):
    """当前**画成高亮蓝**的行（回读底色）。"""
    want = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
    hits = []
    for row in range(ctrl.GetItemCount()):
        got = ctrl.GetItemBackgroundColour(row)
        if (got.Red(), got.Green(), got.Blue()) == (want.Red(), want.Green(), want.Blue()):
            hits.append(row)
    return hits


with probe_temp("probe-remove-invalid") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(20):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    # 一条**失效**路径（目录不存在），夹在中间
    ghost = os.path.join(scratch, "dir-005-ghost")
    seed.record_access(ghost)
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = lambda path: None
    # 弹窗会卡住无人值守的探针 —— 直接放行
    frame._notify = lambda *a, **k: None
    frame.confirm_remove_invalid_path = lambda path: (frame.remove_invalid_path(path), True)[1]
    frame.Show()
    frame.Maximize()
    pump(60)

    ctrl = frame.list_ctrl
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) \
        .GetAsString(wx.C2S_HTML_SYNTAX).upper()

    try:
        row = frame.find_path(ghost)
        print("失效那条在列表第 %s 行；列表共 %d 行" % (row, ctrl.GetItemCount()))
        if row < 0:
            print("（列表里找不到那条失效路径，探针场景无效）")
        else:
            # 选中它，并把它画成蓝色（模拟"用户选中了这条失效记录"）
            for i in range(ctrl.GetItemCount()):
                ctrl.Select(i, False)
            ctrl.Select(row, True)
            frame._paint_key = None
            frame._apply_selection_highlight()
            pump(25)
            before_sel = selected_rows(ctrl)
            before_blue = blue_rows(ctrl)
            print("删除前：选中 = %s   画成蓝的 = %s" % (before_sel, before_blue))
            check("3 阳性对照：删之前确实有选中", bool(before_sel),
                  "选中 = %s" % before_sel)
            check("3b 阳性对照：删之前确实画出了蓝色", bool(before_blue),
                  "蓝行 = %s" % before_blue)

            frame.remove_invalid_path(ghost)
            pump(30)

            after_sel = selected_rows(ctrl)
            after_blue = blue_rows(ctrl)
            print("删除后：列表 %d 行   选中 = %s   画成蓝的 = %s"
                  % (ctrl.GetItemCount(), after_sel, after_blue))
            check("1 删失效路径后**没有选中残留**（不许偏移到隔壁）",
                  after_sel == [], "选中 = %s" % after_sel)
            check("2 删失效路径后**没有错误的蓝色残留**",
                  after_blue == [], "蓝行 = %s" % after_blue)
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
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败" % (len(results), passed, len(results) - passed))
