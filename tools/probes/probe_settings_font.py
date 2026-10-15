"""诊断：设置窗口的标签会不会被按钮压住（**含真实字体条件**）。

## 为什么必须专门测这个

用户截图：设置窗口里「界面语言」「排序方式」「排序方向」三个标签的
**最后两三个字被右边的按钮压住**。

探针一度测不出来，因为它用的是 wx 默认字体（9pt）；而真实程序里
`app._apply_body_font()` 有一句**类级**的
``wx.StaticText.SetFont(self, body)``，把之后创建的所有 StaticText
都换成 10pt 的 body 字体。字体一换，文字的**实际宽度**就与
`GetBestSize()` 缓存的宽度对不上了。

所以这个探针跑三种条件，且**必须包含 10pt**。

## 判据

对每一行：`标签左 + 标签所需宽度 <= 第一个按钮的左边界`。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker import lang, theme as theme_mod
from file_tracker.widgets import SettingsDialog, _label_width

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

DPI = ctypes.windll.user32.GetDpiForSystem() if hasattr(
    ctypes.windll.user32, "GetDpiForSystem") else 96
print(f"  系统 DPI = {DPI}")


def check(tag, label_texts):
    """造一个设置窗口，逐行断言"标签不被按钮压住"。"""
    frame = wx.Frame(None, size=(1200, 700))
    frame.Show()
    for _ in range(20):
        wx.YieldIfNeeded()
    dialog = SettingsDialog(frame, theme_mod.Theme.light("#2959CB"), "zh",
                            sort_key="count", sort_reverse=True)
    dialog.Show()
    for _ in range(30):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    print(f"  === {tag} ===  客户区={tuple(dialog.GetClientSize())}")
    ok = True
    for label, chunks in dialog._rows:
        need = _label_width(label)
        cached = label.GetBestSize().width
        buttons = [b for chunk in chunks for b in chunk]
        first_x = min((b.GetRect().x for b in buttons), default=None)
        first_y = min((b.GetRect().y for b in buttons), default=None)
        label_rect = label.GetRect()
        right_edge = label_rect.x + need
        label_bottom = label_rect.y + label_rect.height

        # **两种合格情况**：
        #   ① 按钮与标签同一行 → 按钮必须在标签右边留出间距
        #   ② 按钮在标签**下面一行** → 水平方向不必避让（垂直避开即可）
        same_line = first_y is not None and first_y < label_bottom
        if same_line:
            spacing = first_x - right_edge
            good = spacing >= 0
            how = f"同行，间隙 = {spacing:4}"
        else:
            good = True
            how = "另起一行（标签独占一行）"
        ok = ok and good
        print(f"    {label.GetLabel()!r:14} 需要 {need:4}（缓存 {cached:4}）"
              f" 标签右 = {right_edge:4}  按钮左 = {first_x:4}  "
              f"{how}  {'✅' if good else '❌ 压住'}")
    print(f"    → {'✅ 无压字' if ok else '❌ 有标签被压住'}")
    dialog.Destroy()
    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()
    return ok


results = []

# ① wx 默认字体（探针原来的条件）
results.append(check("wx 默认字体", None))

# ②③ 真实程序的条件：**类级**字体设置。
#
# `app._apply_body_font()` 里就是 `wx.StaticText.SetFont(self, body)` ——
# 传的是**窗口实例**（`self`），而它只用来取字体所属的"窗口类"，
# 效果是**类级**的：之后创建的所有 StaticText 都用这个字体。
#
# 踩过：这里最早写成 `wx.StaticText.SetFont(wx.StaticText(), body)`，
# 现造一个临时控件当参数——wx 断言 `((HWND)GetHWND())` 直接失败，
# 因为它要一个**已创建**的窗口。所以先建一个窗口再用它。
host = wx.Frame(None)
for label, size in (("10pt body 字体（真实程序）", 10),
                    ("12pt（压力测试）", 12)):
    font = wx.Font(size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                   wx.FONTWEIGHT_NORMAL, False, "Microsoft YaHei UI")
    wx.StaticText.SetFont(host, font)
    wx.Button.SetFont(host, font)
    wx.TextCtrl.SetFont(host, font)
    results.append(check(label, None))
host.Destroy()

print()
print(f"  三种条件都不压字 = {all(results)}")
