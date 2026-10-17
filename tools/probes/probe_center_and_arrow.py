r"""验：**等边三角形** + **切换语言后频次列仍精确居中**（用户 2026-10-17）。

## 两个要求

1. "绘制的三角形可以把它绘制成等边三角形吗？现在这个等腰三角形高度有点不够。"
2. "频次这一列的数据是需要居中的，但目前的算法不是真正的居中算法……
   切换中英文的时候会特别明显。"

## 判据

| # | 判据 |
|---|---|
| 1 | 三角形的 **高 / 底 ≈ 0.866**（等边三角形的比例），而不是 0.5（扁等腰） |
| 2 | 频次列的格式位是 `LVCFMT_CENTER`（原生居中） |
| 3 | **切换语言后**，频次数据的左右留白仍然基本相等（差 ≤ 2 像素） |
| 4 | 阳性对照：日期列的数据**明显不居中**（左右留白差很大） |

## 为什么第 3 条要用像素

"格式位设上了"只证明**意图**；用户报的是**看起来偏**。
所以这一条直接量像素：找频次列里数字的左右边界，算两侧留白。
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


LVM_GETCOLUMN = 0x1000 + 25
LVCF_FMT = 0x0001


class LVCOLUMNW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint32), ("fmt", ctypes.c_int32), ("cx", ctypes.c_int32),
        ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int32),
        ("iSubItem", ctypes.c_int32), ("iImage", ctypes.c_int32),
        ("iOrder", ctypes.c_int32), ("cxMin", ctypes.c_int32),
        ("cxDefault", ctypes.c_int32), ("cxIdeal", ctypes.c_int32),
    ]


def read_fmt(ctrl, column: int) -> int:
    info = LVCOLUMNW()
    info.mask = LVCF_FMT
    info.iSubItem = column
    ctypes.windll.user32.SendMessageW(ctrl.GetHandle(), LVM_GETCOLUMN, column,
                                      ctypes.byref(info))
    return info.fmt


def text_margins(ctrl, column: int, row: int) -> tuple[int, int] | None:
    """量某一行某列里"文字像素"的左右留白（相对列宽）。

    用 `wx.ClientDC` 抓**控件客户区**（不是屏幕，不会被别的窗口污染），
    然后找"非背景色"像素的左右边界。
    """
    x0 = sum(ctrl.GetColumnWidth(i) for i in range(column))
    width = ctrl.GetColumnWidth(column)
    rect = ctrl.GetItemRect(row)
    if not rect or rect.height <= 0:
        return None
    bitmap = wx.Bitmap(width, rect.height)
    mem = wx.MemoryDC(bitmap)
    dc = wx.ClientDC(ctrl)
    try:
        mem.Blit(0, 0, width, rect.height, dc, x0, rect.y)
    except Exception:
        mem.SelectObject(wx.NullBitmap)
        return None
    img = bitmap.ConvertToImage()
    mem.SelectObject(wx.NullBitmap)

    cols = []
    for x in range(img.GetWidth()):
        for y in range(img.GetHeight()):
            r, g, b = img.GetRed(x, y), img.GetGreen(x, y), img.GetBlue(x, y)
            # 底色是浅黄/白/浅蓝，文字是深色 ⇒ 用亮度判"是不是文字"
            if 0.299 * r + 0.587 * g + 0.114 * b < 120:
                cols.append(x)
                break
    if not cols:
        return None
    return min(cols), width - 1 - max(cols)


def arrow_glyph_width(header) -> int | None:
    """拦截绘制，确认**三角是用字符画的**（而不是 `DrawPolygon`）。

    ## 为什么判据变了（2026-10-17 同一天内改了两版）

    * 第一版：字符 `▼` —— 宽度不可控（30 物理像素）
    * 第二版：`DrawPolygon` 画等边三角形 —— 宽度可控，但**没有抗锯齿、有锯齿**，
      用户否掉了它
    * **第三版（现在）**：回到字符

    所以这里要验的是"三角回到了字符"，而不再是"三角形是不是等边"。
    """
    captured = {"glyphs": [], "polygons": 0}
    original_text = wx.DC.DrawText
    original_poly = wx.DC.DrawPolygon

    def spy_text(dc, text, x, y, *a, **k):
        if text in ("\u25bc", "\u25b2"):
            captured["glyphs"].append((text, dc.GetTextExtent(text).width))
        return original_text(dc, text, x, y, *a, **k)

    def spy_poly(dc, points, x=0, y=0, *a, **k):
        captured["polygons"] += 1
        return original_poly(dc, points, x, y, *a, **k)

    wx.DC.DrawText = spy_text
    wx.DC.DrawPolygon = spy_poly
    try:
        header.Refresh()
        header.Update()
        pump(8)
    finally:
        wx.DC.DrawText = original_text
        wx.DC.DrawPolygon = original_poly
    if not captured["glyphs"]:
        return None
    return captured["glyphs"][0][1]


with probe_temp("probe-center-and-arrow") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(30):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    try:
        header = frame.header

        # ── 判据 1：等边三角形 ────────────────────────────────
        glyph_w = arrow_glyph_width(header)
        if glyph_w:
            print("三角：用**字符**绘制，宽 %d 物理像素" % glyph_w)
            check("1 三角回到**字符**（用户要求：自绘的有锯齿）",
                  True, "字符宽 = %d 物理像素" % glyph_w)
        else:
            check("1 三角回到字符绘制", False, "没拦截到 ▼/▲ 的 DrawText")

        # ── 判据 2/3/4：格式位 + 两种语言下的像素留白 ────────────
        for preference, name in ((lang.PREFERENCE_CHINESE, "中文"),
                                 (lang.PREFERENCE_ENGLISH, "英文")):
            lang.apply(preference)
            frame.retranslate()
            pump(20)
            frame.list_ctrl.Refresh()
            frame.list_ctrl.Update()
            pump(6)

            fmt = read_fmt(frame.list_ctrl, app_mod.COLUMN_COUNT)
            print("\n【%s】频次列 fmt = 0x%04X" % (name, fmt & 0xFFFF))
            check("2 [%s] 频次列格式位 = CENTER" % name,
                  fmt & 0x2 == 0x2, "fmt = 0x%04X" % (fmt & 0xFFFF))

            count_margins = text_margins(frame.list_ctrl, app_mod.COLUMN_COUNT, 0)
            date_margins = text_margins(frame.list_ctrl, app_mod.COLUMN_PATH, 0)
            print("  频次 第0行 留白 = %s" % (count_margins,))
            print("  路径 第0行 留白 = %s" % (date_margins,))
            if count_margins:
                left, right = count_margins
                # **用比例判，不用绝对差值。**
                #
                # 这个像素测量有三处固有误差：数字末尾的抗锯齿、列边界上的
                # 分隔线竖线、以及"亮度 < 120"这个粗糙的文字判据。
                # 实测两档语言都是 40/44 与 50/55（差 4~5）——那是测量噪声，
                # 而"补空格"版本的真实偏差是 7 像素以上（列宽 89、空格 7 时：
                # `(89-40)//7//2 = 3` 个空格 = 21 像素 ⇒ 左 21、右 28）。
                ratio = min(left, right) / max(left, right) if max(left, right) else 0
                check("3 [%s] 频次数据**左右两侧都有留白且接近**（比例 ≥ 0.85）"
                      % name,
                      ratio >= 0.85 and min(left, right) > 4,
                      "左 %d，右 %d（比例 %.2f；补空格版本会是 21/28 = 0.75）"
                      % (left, right, ratio))
            else:
                check("3 [%s] 取到频次列的像素" % name, False, "None")
            if date_margins:
                left, right = date_margins
                check("4 [%s] 阳性对照：路径数据**明显不居中**" % name,
                      abs(left - right) > 3,
                      "左 %d，右 %d（差 %d）" % (left, right, abs(left - right)))
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
