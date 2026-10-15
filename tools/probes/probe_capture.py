"""诊断：本进程内哪种抓图方式真的能拿到像素。

之前对外部窗口试过 `WM_PRINTCLIENT` / `PrintWindow` / `GetDC+BitBlt`，全失败。
这里是**本进程**的窗口，试四种：
  ① `wx.WindowDC` → `wx.MemoryDC.Blit`
  ② `wx.ClientDC` → `wx.MemoryDC.Blit`
  ③ `wx.ScreenDC`  + 窗口屏幕坐标 → `Blit`
  ④ `wx.MemoryDC` + `wx.RendererNative` / `DrawWindow`

判据：抓一张**已知颜色**的窗口（整块纯红），看抓到的中心像素是不是红。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)

RED = "#FF0000"


def test(name, grab):
    frame = wx.Frame(None, size=(200, 120))
    frame.SetBackgroundColour(wx.Colour(RED))
    panel = wx.Panel(frame)
    panel.SetBackgroundColour(wx.Colour(RED))
    frame.Show()
    frame.Raise()
    for _ in range(50):
        wx.YieldIfNeeded()
        time.sleep(0.02)
    try:
        bitmap = grab(frame)
        if bitmap is None or not bitmap.IsOk():
            print(f"  {name:28} 抓取失败（bitmap 无效）")
            return
        image = bitmap.ConvertToImage()
        w, h = image.GetWidth(), image.GetHeight()
        r, g, b = image.GetRed(w // 2, h // 2), image.GetGreen(w // 2, h // 2), \
            image.GetBlue(w // 2, h // 2)
        ok = r > 200 and g < 60 and b < 60
        print(f"  {name:28} {w}x{h} 中心=({r},{g},{b})  {'✅ 拿到真像素' if ok else '❌ 不是红色'}")
    except Exception as exc:
        print(f"  {name:28} 抛异常: {exc!r}")
    frame.Destroy()
    for _ in range(10):
        wx.YieldIfNeeded()


def grab_window_dc(frame):
    size = frame.GetSize()
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    source = wx.WindowDC(frame)
    memory.Blit(0, 0, size.width, size.height, source, 0, 0)
    memory.SelectObject(wx.NullBitmap)
    return bitmap


def grab_client_dc(frame):
    frame.Update()
    size = frame.GetSize()
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    source = wx.ClientDC(frame)
    memory.Blit(0, 0, size.width, size.height, source, 0, 0)
    memory.SelectObject(wx.NullBitmap)
    return bitmap


def grab_screen_dc(frame):
    pos, size = frame.GetScreenPosition(), frame.GetSize()
    bitmap = wx.Bitmap(size.width, size.height)
    memory = wx.MemoryDC(bitmap)
    source = wx.ScreenDC()
    memory.Blit(0, 0, size.width, size.height, source, pos.x, pos.y)
    memory.SelectObject(wx.NullBitmap)
    return bitmap


def grab_print_window(frame):
    bitmap = wx.Bitmap(frame.GetSize().width, frame.GetSize().height)
    memory = wx.MemoryDC(bitmap)
    ctypes.windll.user32.PrintWindow(
        ctypes.c_void_p(frame.GetHandle()),
        ctypes.c_void_p(memory.GetHDC()), 0)
    memory.SelectObject(wx.NullBitmap)
    return bitmap


print("=== 抓一个整块纯红的窗口，看哪种方式拿到真像素 ===")
test("① wx.WindowDC + Blit", grab_window_dc)
test("② wx.ClientDC + Blit", grab_client_dc)
test("③ wx.ScreenDC + Blit", grab_screen_dc)
test("④ PrintWindow(hwnd, hdc, 0)", grab_print_window)
