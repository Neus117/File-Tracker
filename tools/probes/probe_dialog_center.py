"""诊断：提示窗的正文与按钮是不是**真的居中了**。

用户要求："现在让所有提示窗内容居中显示。"

判据用**几何**，不用像素（本环境的像素取样已被证明不可靠）：

  * 正文字符串画出来的矩形，其中心应当 ≈ 客户区中心
  * 按钮组的中心应当 ≈ 客户区中心
  * 左右留白应当相等

行宽用 `dc.GetTextExtent(line).width`（与 `_draw_body` 同一个来源），
所以量的是"按实现的算法会画在哪"，而不是"屏幕上是什么样"。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import theme as theme_mod
from file_tracker.widgets import ThemedDialog

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
theme_mod.from_system = lambda: theme_mod.Theme.light("#2959CB")
app_mod.theme_from_system = theme_mod.from_system

cases = [
    ("短消息（单行）", "确定要清空所有记录吗？", "确认清空", "是(Y)", "否(N)"),
    ("多行消息", "⚠️ 这条路径已失效：\n\nH:\\【!!装机必备!!】\n\n要从记录中删除它吗？",
     "路径已失效", "删除", "保留"),
    ("超长消息（要折行）",
     "⚠️ 初始化数据库时发生错误: " + "很长的一段说明文字，" * 12,
     "数据库错误", "好", None),
]

with probe_temp("probe-center") as scratch:
    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    frame = app_mod.FileTracker()
    frame.SetTitle("probe-center")
    frame.SetSize((1500, 900))
    frame.Show()
    for _ in range(60):
        wx.YieldIfNeeded()
        time.sleep(0.02)

    for tag, message, title, yes, no in cases:
        dialog = ThemedDialog(frame, frame.theme, message, title=title,
                              yes_label=yes, no_label=no)
        dialog.Show()
        for _ in range(40):
            wx.YieldIfNeeded()
            time.sleep(0.02)

        client_w, client_h = dialog.GetClientSize()
        left, top, right, bottom = dialog._body_rect
        dc = wx.ClientDC(dialog)
        dc.SetFont(dialog.GetFont())
        line_h = dc.GetTextExtent("频次").height or 1
        center = (left + right) // 2

        print(f"=== {tag} ===")
        print(f"  客户区 = {client_w}x{client_h}   正文区 = {dialog._body_rect}")
        print(f"  行数 = {len(dialog._lines)}")

        worst = 0
        for i, line in enumerate(dialog._lines):
            width = dc.GetTextExtent(line).width
            x = center - width // 2
            gap_left, gap_right = x, client_w - (x + width)
            worst = max(worst, abs(gap_left - gap_right))
            print(f"    行{i}: 宽={width:4}  画在 x={x:4}  "
                  f"左空={gap_left:4} 右空={gap_right:4}  "
                  f"差={abs(gap_left - gap_right)}  {line[:22]!r}")
        print(f"  ---- 正文左右留白最大差 = {worst} px"
              f"  {'✅ 居中' if worst <= 1 else '❌ 没居中'}")

        # 正文的垂直范围也要落在正文区里
        body_h = line_h * len(dialog._lines)
        fits = top + body_h <= bottom + 1
        print(f"  正文高 = {body_h}，正文区高 = {bottom - top}"
              f"  {'✅ 装得下' if fits else '❌ 溢出（说明测量与实际不一致）'}")

        # 按钮组居中
        rects = dialog._button_rects
        group_left = min(x for x, _ in rects)
        group_right = max(x + w for x, w in rects)
        gl, gr = group_left, client_w - group_right
        print(f"  按钮组：左空={gl} 右空={gr} 差={abs(gl - gr)}"
              f"  {'✅ 居中' if abs(gl - gr) <= 1 else '❌ 没居中'}"
              f"   （各按钮 x = {[x for x, _ in rects]}）")
        print()

        dialog.Destroy()
        for _ in range(20):
            wx.YieldIfNeeded()
    frame.store.close()
    frame.Destroy()
    for _ in range(20):
        wx.YieldIfNeeded()
