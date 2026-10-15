"""临时诊断：LVM_SETCOLUMN 到底能不能用（第 N 次，这次按文档逐项对齐）。

之前全失败。这次只查一件事：**pszText 那一项**。
文档说 mask 里含 LVCF_TEXT 时 pszText 不能为 NULL ——
我从来没设 LVCF_TEXT，但结构体里 pszText 是 c_wchar_p，
ctypes 会给它一个 NULL。也许 Windows 在别处读了它。

同时把"列头点击"也一起测了 —— 那才是用户真正要的功能。
"""
import ctypes
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

LVM_FIRST = 0x1000
LVM_SETCOLUMN = LVM_FIRST + 24
LVM_GETCOLUMN = LVM_FIRST + 25
LVCF_FMT, LVCF_WIDTH, LVCF_TEXT, LVCF_SUBITEM = 0x1, 0x2, 0x4, 0x8
LVCFMT_LEFT, LVCFMT_RIGHT, LVCFMT_CENTER = 0, 1, 2

user32 = ctypes.windll.user32
user32.SendMessageW.restype = ctypes.c_void_p
user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p]


def send(hwnd, msg, wparam, lparam):
    result = user32.SendMessageW(hwnd, msg, wparam, lparam)
    return 0 if result is None else int(result)


app = wx.App()
frame = wx.Frame(None, size=(600, 260))
lc = wx.ListCtrl(frame, style=wx.LC_REPORT | wx.BORDER_NONE)
lc.InsertColumn(0, "路径", width=240)
lc.InsertColumn(1, "频次", width=90)
for i in range(4):
    row = lc.InsertItem(lc.GetInsertionPoint() if hasattr(lc, "GetInsertionPoint") else lc.GetItemCount(), rf"C:\p{i}")
    lc.SetItem(row, 1, str((i + 1) * 111))
frame.Show()
for _ in range(30):
    wx.YieldIfNeeded()

hwnd = lc.GetHandle()
print(f"列表 hwnd={hwnd} 类名={__import__('win32gui').GetClassName(hwnd)}")

# 用结构化缓冲区手工打包，字段偏移按 commctrl.h:
#   mask(0) iSubItem(4) fmt(8) cx(12) pszText(16,指针) cchTextMax(24) iImage(28) iOrder(32)
def pack(mask, subitem=0, fmt=0, cx=0, text=None):
    buf = ctypes.create_string_buffer(48)
    ctypes.memset(buf, 0, 48)
    struct.pack_into("<I", buf, 0, mask)
    struct.pack_into("<i", buf, 4, subitem)
    struct.pack_into("<i", buf, 8, fmt)
    struct.pack_into("<i", buf, 12, cx)
    if text is not None:
        # 把字符串放进同一块缓冲区的尾部，pszText 指向它
        offset = 48
        wide = ctypes.create_unicode_buffer(text)
        struct.pack_into("<q", buf, 16, ctypes.addressof(wide))
        buf._keep = wide  # 防回收
    return buf


def readback(index):
    buf = ctypes.create_string_buffer(48)
    ctypes.memset(buf, 0xAA, 48)
    struct.pack_into("<I", buf, 0, LVCF_FMT)
    ret = send(hwnd, LVM_GETCOLUMN, index, ctypes.addressof(buf))
    return ret, struct.unpack_from("<i", buf.raw, 8)[0]


print()
print("=== 试各种组合，看 LVM_SETCOLUMN 什么时候返回 1 ===")
attempts = [
    ("仅 FMT", pack(LVCF_FMT, fmt=LVCFMT_CENTER)),
    ("FMT|WIDTH（带 cx）", pack(LVCF_FMT | LVCF_WIDTH, fmt=LVCFMT_CENTER, cx=90)),
    ("FMT|SUBITEM", pack(LVCF_FMT | LVCF_SUBITEM, subitem=1, fmt=LVCFMT_CENTER)),
    ("FMT|TEXT（带空串）", pack(LVCF_FMT | LVCF_TEXT, fmt=LVCFMT_CENTER, text="")),
    ("FMT|TEXT（带文字）", pack(LVCF_FMT | LVCF_TEXT, fmt=LVCFMT_CENTER, text="频次")),
    ("全都要", pack(LVCF_FMT | LVCF_WIDTH | LVCF_TEXT | LVCF_SUBITEM,
                    subitem=1, fmt=LVCFMT_CENTER, cx=90, text="频次")),
]
for name, buf in attempts:
    set_ret = send(hwnd, LVM_SETCOLUMN, 1, ctypes.addressof(buf))
    get_ret, got_fmt = readback(1)
    verdict = "★成功" if got_fmt == LVCFMT_CENTER else "失败"
    print(f"  {name:22} set_ret={set_ret} 回读 fmt={got_fmt}  {verdict}")

print()
print("=== 列头点击事件能不能收到（wx.ListCtrl）===")
import wx.lib.mixins.listctrl as listmix  # noqa: F401

hits = []


def on_col(event):
    hits.append(event.GetColumn())
    print(f"    收到列头点击，列号 = {event.GetColumn()}")


lc.Bind(wx.EVT_LIST_COL_CLICK, on_col)

# 真实点击表头
pos = lc.GetScreenPosition()
nonclient = lc.GetSize().height - lc.GetClientSize().height
col0 = lc.GetColumnWidth(0)
x = pos[0] + col0 + lc.GetColumnWidth(1) // 2
y = pos[1] - max(nonclient, 24) // 2
user32.SetCursorPos(int(x), int(y))
for _ in range(10):
    wx.YieldIfNeeded()
user32.mouse_event(0x0002, 0, 0, 0, 0)
for _ in range(6):
    wx.YieldIfNeeded()
user32.mouse_event(0x0004, 0, 0, 0, 0)
for _ in range(30):
    wx.YieldIfNeeded()
print(f"  合计收到 {len(hits)} 个列头点击事件，列号 = {hits}")

print()
print("=== 结论 ===")
print("  wx.ListCtrl 的 EVT_LIST_COL_CLICK 能收到列号 → 列头排序可行")
print("  LVM_SETCOLUMN 若仍全部失败 → 只能放弃原生居中对齐")

frame.Destroy()
