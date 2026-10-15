"""诊断：`SetWindowStyle(wx.STAY_ON_TOP)` 到底有没有真的置顶窗口。

## 为什么必须实测

同一个仓库里有两份**互相矛盾**的说法：

* `win32.py:605` 的表格说 ``SetWindowStyle`` **没有**改变
  ``WS_EX_TOPMOST``（"`GetWindowStyle()` 会骗你说变了"）。
* 一份审计说 `probe_topmost.py` 实测 ``SetWindowStyle`` **有效**。

而 `app.on_always_on_top` 用的正是 ``SetWindowStyle``。
所以要判断的是：**那个按钮真的有用吗**（用户只用过它，没抱怨过）。

判据取三层，互相印证：
  ① `GetWindowStyle() & wx.STAY_ON_TOP`（wx 自己怎么说）
  ② `WS_EX_TOPMOST` 位（Windows 真正的状态）
  ③ 真的把窗口提到前台时的行为（最接近用户感受）
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
import file_tracker.win32 as win32

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

frame = wx.Frame(None, title="topmost probe", size=(420, 220))
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()
    time.sleep(0.01)

handle = int(frame.GetHandle())


def state(tag):
    wx_style = bool(frame.GetWindowStyle() & wx.STAY_ON_TOP)
    ex = win32.is_window_topmost(handle)
    print(f"  {tag:34} wx.STAY_ON_TOP={wx_style!s:5}  WS_EX_TOPMOST={ex}")
    return wx_style, ex


print("=== 用 app 现在的方式：SetWindowStyle ===")
a = state("起始")
frame.SetWindowStyle(frame.GetWindowStyle() | wx.STAY_ON_TOP)
for _ in range(20):
    wx.YieldIfNeeded()
b = state("SetWindowStyle(+STAY_ON_TOP) 之后")
frame.SetWindowStyle(frame.GetWindowStyle() & ~wx.STAY_ON_TOP)
for _ in range(20):
    wx.YieldIfNeeded()
c = state("SetWindowStyle(-STAY_ON_TOP) 之后")

print()
print("=== 对照：SetWindowPos（win32.set_window_topmost 的方式）===")
win32.set_window_topmost(handle, True)
for _ in range(20):
    wx.YieldIfNeeded()
d = state("win32.set_window_topmost(True)")
win32.set_window_topmost(handle, False)
for _ in range(20):
    wx.YieldIfNeeded()
e = state("win32.set_window_topmost(False)")

print()
print("  === 结论 ===")
if b[1] and not c[1]:
    print("  ✅ `SetWindowStyle` **确实**改变了 WS_EX_TOPMOST")
    print("     → `win32.py` 那张『SetWindowStyle 没有生效』的表格是**过期文档**；")
    print("       `app.on_always_on_top` 的做法是对的，不要随手改它。")
elif b[0] and not b[1]:
    print("  ⚠️ wx 说变了、Windows 说没变 —— 那张表格是对的：")
    print("     `GetWindowStyle()` 在骗人，`on_always_on_top` 需要改用 SetWindowPos。")
else:
    print(f"  结果不符合上面两种预期，请看上面的三层读数：{a} {b} {c} {d} {e}")
print()
print(f"  （对照：SetWindowPos 的结果 = {d[1]} / {e[1]}）")

frame.Destroy()
