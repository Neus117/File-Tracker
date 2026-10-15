"""临时诊断：目录树的空白区域为什么点不中。

用户反馈："导航窗格空白部分无法选中。"

树控件在"条目下方的空白处"点击时，原生 `SysTreeView32` 的行为是
**把选中项取消**（如果需要它响应，得看 `TVS_*` 样式与是否有处理）。
这里查：
  * 树有没有 `wx.TR_MULTIPLE`（多选）
  * 点空白能否拿到事件（模拟一次点击）
  * 空白处到底属于树的客户区，还是属于容器（`GenericDirCtrl` 的另一部分）
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx

from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
theme_mod.from_system = lambda: theme_mod.Theme.light("#2959CC")
app_mod.theme_from_system = theme_mod.from_system

with probe_temp("probe-blank") as probe_dir:
    app_mod.default_db_path = lambda: os.path.join(probe_dir, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-blank")
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    tree = frame.dir_ctrl.GetTreeCtrl()
    print("=== 树的样式 ===")
    style = tree.GetWindowStyleFlag()
    print(f"  wx 样式 = {style:#x}")
    for name in ("TR_MULTIPLE", "TR_HAS_BUTTONS", "TR_HIDE_ROOT",
                 "TR_LINES_AT_ROOT", "TR_FULL_ROW_HIGHLIGHT",
                 "TR_ROW_LINES", "TR_SINGLE"):
        val = getattr(wx, name, None)
        if val is not None:
            print(f"    {name:24} = {bool(style & val)}")
    print(f"  GetWindowStyleFlag() 里有 TR_MULTIPLE = "
          f"{bool(style & wx.TR_MULTIPLE)}  "
          f"（DIRCTRL_MULTIPLE 会加它，那才是多选）")

    print()
    print("=== 树的可见范围 vs 客户区 ===")
    print(f"  树客户区 = {tree.GetClientSize()}")
    print(f"  根节点可见吗 = {tree.GetRootItem().IsOk()}")
    # 数一下可见条目占多高
    count = 0
    item = tree.GetFirstVisibleItem()
    last_rect = None
    while item.IsOk():
        rect = tree.GetBoundingRect(item)
        if rect and rect.height:
            last_rect = rect
        count += 1
        item = tree.GetNextVisible(item)
        if count > 5000:
            break
    print(f"  可见条目数 = {count}")
    if last_rect:
        print(f"  最后一条的矩形底边 y = {last_rect.y + last_rect.height}")
        print(f"  树客户区高 = {tree.GetClientSize().height}")
        print(f"  → 下面还有 {tree.GetClientSize().height - (last_rect.y + last_rect.height)}"
              " 像素是空白")

    print()
    print("=== 空白处点一下会怎样（模拟鼠标）===")
    tree.UnselectAll()
    for _ in range(10):
        wx.YieldIfNeeded()
    print(f"  先清空选中，GetSelections() = {len(tree.GetSelections())}")
    blank_y = tree.GetClientSize().height - 8
    point = wx.Point(tree.GetClientSize().width // 2, blank_y)
    print(f"  模拟点击位置 = {point}（空白区）")
    for evt_type in (wx.wxEVT_LEFT_DOWN, wx.wxEVT_LEFT_UP):
        evt = wx.MouseEvent(evt_type)
        evt.SetPosition(point)
        evt.SetEventObject(tree)
        evt.SetEventType(evt_type)
        tree.GetEventHandler().ProcessEvent(evt)
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  点击后 GetSelections() = {len(tree.GetSelections())}")

    print()
    print("=== 结论 ===")
    print("  `SysTreeView32` 的空白区**本来就不会选中任何节点**——")
    print("  那是原生控件行为，不是缺陷。用户想要的多半是")
    print("  '点空白能展开/收起'或'至少有个反馈'。")
    print("  需要确认用户到底期望什么行为，不要猜着改。")

    frame.store.close()
    frame.Destroy()
