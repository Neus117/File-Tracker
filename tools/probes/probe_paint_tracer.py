"""验：`FT_DEBUG_PAINT` 诊断**装得上、出得来、且关掉时零开销**。

三条判据：

1. **关掉时**：`_paint_tracer is None`，且列表控件的方法**没被包装**
   （`SetItemBackgroundColour` 的 `__name__` 还是原来的）
2. **打开时**：`_paint_tracer` 装上了，报告里能读到"谁把选中行改成了什么色"
3. **报告能定位**：报告里必须有 `_apply_selection_highlight` 的调用栈，
   以及"选中行存着的底色"
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
from file_tracker import lang, paint_trace

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


def pump(rounds: int = 25) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(0.004)


def build(scratch: str):
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, f"m{i:03d}"))
    fresh = os.path.join(scratch, "m020-new")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(50)
    return frame, fresh


with probe_temp("probe-tracer") as scratch:
    # ── ① 关掉时 ──────────────────────────────────────────────────
    os.environ.pop(paint_trace.ENV_FLAG, None)
    frame, fresh = build(scratch)
    try:
        tracer_off = getattr(frame, "_paint_tracer", None)
        method = frame.list_ctrl.SetItemBackgroundColour
        check("① 不设环境变量时不装诊断", tracer_off is None,
              f"_paint_tracer = {tracer_off!r}")
        check("①b 关掉时控件方法**没有被包装**",
              not method.__name__.startswith("ft_traced_"),
              f"__name__ = {method.__name__}")
    finally:
        frame.store.close()
        frame.Destroy()
        pump(5)

    # ── ② 打开时 ──────────────────────────────────────────────────
    os.environ[paint_trace.ENV_FLAG] = "1"
    report_file = os.path.join(scratch, "paint-trace.txt")
    original_path = paint_trace.report_path
    paint_trace.report_path = lambda: report_file
    frame, fresh = build(scratch)
    try:
        tracer = getattr(frame, "_paint_tracer", None)
        check("② 设了环境变量时装上了诊断", tracer is not None,
              f"_paint_tracer = {type(tracer).__name__ if tracer else None!r}")

        # 复现：从导航窗格打开
        ctrl = frame.list_ctrl
        mid = max(ctrl.GetItemCount() // 3, 1)
        ctrl.EnsureVisible(mid)
        ctrl.ScrollLines(mid - ctrl.GetTopItem())
        for i in range(ctrl.GetItemCount()):
            ctrl.Select(i, False)
        ctrl.SetItemState(mid, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                          wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
        tree = frame.dir_ctrl.GetTreeCtrl()
        tree.expand_to(fresh, select=True)
        frame._focus_pane = "tree"
        pump(12)
        frame.on_open(None)
        pump(35)

        selected = ctrl.GetFirstSelected()
        frame.on_close(wx.PyCommandEvent(wx.EVT_CLOSE.typeId, frame.GetId()))
        pump(10)

        check("②b 报告文件写出来了", os.path.exists(report_file),
              report_file)
        if os.path.exists(report_file):
            with open(report_file, encoding="utf-8") as handle:
                text = handle.read()
            has_stack = "_apply_selection_highlight" in text
            has_stored = "选中行**存着**的底色" in text
            has_ledger = "_paint_key" in text
            print("\n── 报告节选 ──")
            lines = text.splitlines()
            for line in lines[:14]:
                print("   " + line)
            print("   …")
            for line in lines[-18:]:
                print("   " + line)
            check("②c 报告里有调用栈（能指出是谁改的）", has_stack,
                  "_apply_selection_highlight " + ("在" if has_stack else "**不在**"))
            check("②d 报告里有\"选中行存着的底色\"", has_stored, "")
            check("②e 报告里有那三个记忆账本", has_ledger, "")
    finally:
        try:
            frame.store.close()
        except Exception:
            pass
        try:
            frame.Destroy()
        except Exception:
            pass
        pump(5)
        paint_trace.report_path = original_path
        os.environ.pop(paint_trace.ENV_FLAG, None)

    # ── ③ 关掉开关后再建一个：确认没有残留 ──
    frame, _ = build(scratch)
    try:
        check("③ 关掉开关后新窗口不装诊断",
              getattr(frame, "_paint_tracer", None) is None, "")
    finally:
        frame.store.close()
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
