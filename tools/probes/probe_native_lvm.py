"""临时诊断：原生 LVM_SETCOLUMN 到底能不能用？

用 CreateWindowExW 直接建一个裸的 SysListView32（完全绕开 wx），
看 LVM_SETCOLUMN 在那里是否成功。这一条决定了：
  · 成功 → 是 wxWidgets 包装层的问题，有绕过办法
  · 失败 → 这台机器/这个 Windows 版本上原生列格式就是不能用，
            必须换成 wx 自己实现的控件（DataViewListCtrl）
"""
import ctypes
import struct
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
LVS_REPORT = 0x0001
LVS_SHOWSELALWAYS = 0x0008

LVM_FIRST = 0x1000
LVM_INSERTCOLUMNW = LVM_FIRST + 27
LVM_SETCOLUMN = LVM_FIRST + 24
LVM_GETCOLUMN = LVM_FIRST + 25
LVCF_FMT = 0x0001
LVCF_WIDTH = 0x0002
LVCF_TEXT = 0x0004
LVCF_SUBITEM = 0x0008
LVCFMT_LEFT, LVCFMT_RIGHT, LVCFMT_CENTER = 0, 1, 2


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwICC", wintypes.DWORD)]


icc = INITCOMMONCONTROLSEX(ctypes.sizeof(INITCOMMONCONTROLSEX), 0x00000001 | 0x00008000)
print("InitCommonControlsEx ->", comctl32.InitCommonControlsEx(ctypes.byref(icc)))

hInstance = kernel32.GetModuleHandleW(None)

user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]

host = user32.CreateWindowExW(0, "STATIC", "probe", WS_OVERLAPPEDWINDOW,
                              80, 80, 600, 300, None, None, hInstance, None)
print(f"宿主窗口 hwnd={host}")

lv = user32.CreateWindowExW(0, "SysListView32", "",
                            WS_CHILD | WS_VISIBLE | LVS_REPORT | LVS_SHOWSELALWAYS,
                            0, 0, 580, 260, host, None, hInstance, None)
print(f"列表控件 hwnd={lv}")


user32.SendMessageW.restype = ctypes.c_void_p
user32.SendMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
]


def send(hwnd, msg, wparam, lparam):
    # restype 是 c_void_p 时，返回值 0 会被转成 None —— 统一成 int
    result = user32.SendMessageW(hwnd, msg, wparam, lparam)
    return 0 if result is None else int(result)


# 插入两列（用裸结构体）
for index, title in enumerate(("路径", "频次")):
    buf = ctypes.create_string_buffer(128)
    struct.pack_into("<I", buf, 0, LVCF_FMT | LVCF_WIDTH | LVCF_TEXT | LVCF_SUBITEM)
    struct.pack_into("<i", buf, 4, index)      # iSubItem（若布局是 mask,iSubItem,fmt,cx）
    struct.pack_into("<i", buf, 8, LVCFMT_LEFT)
    struct.pack_into("<i", buf, 12, 240 if index == 0 else 110)
    struct.pack_into("<q", buf, 16, ctypes.cast(ctypes.c_wchar_p(title), ctypes.c_void_p).value)
    ok = send(lv, LVM_INSERTCOLUMNW, index, ctypes.addressof(buf))
    print(f"  LVM_INSERTCOLUMNW[{index}] ({title}) -> {ok}")

print()
print("=== 在裸控件上试 LVM_SETCOLUMN ===")
for fmt_name, fmt in (("LEFT", LVCFMT_LEFT), ("RIGHT", LVCFMT_RIGHT), ("CENTER", LVCFMT_CENTER)):
    col = ctypes.create_string_buffer(64)
    struct.pack_into("<I", col, 0, LVCF_FMT)
    struct.pack_into("<i", col, 8, fmt)
    set_ret = send(lv, LVM_SETCOLUMN, 1, ctypes.addressof(col))

    back = ctypes.create_string_buffer(64)
    ctypes.memset(back, 0xAA, 64)
    struct.pack_into("<I", back, 0, LVCF_FMT)
    get_ret = send(lv, LVM_GETCOLUMN, 1, ctypes.addressof(back))
    read_fmt = struct.unpack_from("<i", back.raw, 8)[0]
    print(f"  set {fmt_name:7} set_ret={set_ret:<4} get_ret={get_ret} 回读 fmt={read_fmt}")
    print(f"          字节={back.raw[:32].hex()}")

print()
print("=== 对照：wx 的控件上同样的调用 ===")
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
import wx
from file_tracker import win32

app = wx.App()
frame = wx.Frame(None, size=(600, 300))
lc = wx.ListCtrl(frame, style=wx.LC_REPORT)
lc.InsertColumn(0, "路径", width=240)
lc.InsertColumn(1, "频次", width=110)
frame.Show()
wx.YieldIfNeeded()
wx_hwnd = lc.GetHandle()
col = win32.LVCOLUMN()
col.mask = win32.LVCF_FMT
col.fmt = win32.LVCFMT_CENTER
set_ret = send(wx_hwnd, LVM_SETCOLUMN, 1, ctypes.addressof(col))
back = ctypes.create_string_buffer(64)
ctypes.memset(back, 0xAA, 64)
struct.pack_into("<I", back, 0, LVCF_FMT)
get_ret = send(wx_hwnd, LVM_GETCOLUMN, 1, ctypes.addressof(back))
print(f"  wx 控件: set_ret={set_ret} get_ret={get_ret} 回读 fmt={struct.unpack_from('<i', back.raw, 8)[0]}")
print(f"          字节={back.raw[:32].hex()}")
frame.Destroy()

user32.DestroyWindow(host)
