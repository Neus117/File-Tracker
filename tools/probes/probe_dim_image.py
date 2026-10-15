"""一次性问清：在 wxPython 4.2.2 上，**哪种方式能真的把一张 wx.Image 压暗**。

## 为什么写这个

为了做两张占位图，我连着猜了三个 API，三个都不对：

1. `wx.Image.SetSize` —— 不存在（`AttributeError`）
2. `wx.Bitmap.GetBitmapDataBuffer` —— 不存在（新版才有）
3. `wx.Image.AdjustChannels(0.45, 0.45, 0.45)` —— **不报错，但像素一个都没变**
   （两张图 MD5 完全相同、平均亮度都是 242.8）

第 3 个最危险：**它静默地什么都不做**。如果我没去比对文件，就会交出一张
"深色主题"和浅色一模一样的图。

## 判据

每种方式跑完都重新读回文件、算**平均亮度**，并要求它**明显低于**原图。
不报错不算成功——**要看到像素真的变了**。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx

from _probe_guard import harden_wx

_APP = harden_wx(need_app=True)

SOURCE = os.path.join("images", "FileTracker_v1.1-Overview.jpg")
OUT = os.path.join(os.environ.get("TEMP", "."), "probe-dim")
os.makedirs(OUT, exist_ok=True)

DIM = 0.45
base = wx.Image(SOURCE, wx.BITMAP_TYPE_JPEG).Scale(
    480, round(480 * wx.Image(SOURCE, wx.BITMAP_TYPE_JPEG).GetSize().height
               / wx.Image(SOURCE, wx.BITMAP_TYPE_JPEG).GetSize().width),
    wx.IMAGE_QUALITY_HIGH)


def brightness(path: str) -> tuple[float, tuple]:
    """读回文件算平均亮度 + 尺寸（**读回来**，不是看内存里那个对象）。"""
    image = wx.Image(path, wx.BITMAP_TYPE_JPEG)
    data = bytes(image.GetDataBuffer())
    size = image.GetSize()
    return (sum(data) / len(data) if data else 0.0, (size.width, size.height))


base_bright, base_size = brightness(SOURCE)
print(f"  原图平均亮度 = {base_bright:.1f}  尺寸 {base_size}")
print()

results = []

# ── 方式 A：AdjustChannels ────────────────────────────────────────────────
path = os.path.join(OUT, "a.jpg")
image = base.Copy()
returned = image.AdjustChannels(DIM, DIM, DIM)
image.SaveFile(path, wx.BITMAP_TYPE_JPEG)
got, size = brightness(path)
results.append(("A. AdjustChannels", got, size, returned))
print(f"  A. AdjustChannels        → 亮度 {got:6.1f}  返回值 {returned!r}")

# ── 方式 B：AdjustChannels 但用返回值 ─────────────────────────────────────
path = os.path.join(OUT, "b.jpg")
image = base.Copy()
returned = image.AdjustChannels(DIM, DIM, DIM)
target = returned if isinstance(returned, wx.Image) else image
target.SaveFile(path, wx.BITMAP_TYPE_JPEG)
got, size = brightness(path)
results.append(("B. AdjustChannels + 返回值", got, size, type(returned).__name__))
print(f"  B. AdjustChannels+ret    → 亮度 {got:6.1f}  返回类型 {type(returned).__name__}")

# ── 方式 C：SetRGB 逐像素 ──────────────────────────────────────────────────
path = os.path.join(OUT, "c.jpg")
image = base.Copy()
w, h = image.GetSize()
for y in range(h):
    for x in range(w):
        r, g, b = image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)
        image.SetRGB(x, y, int(r * DIM), int(g * DIM), int(b * DIM))
image.SaveFile(path, wx.BITMAP_TYPE_JPEG)
got, size = brightness(path)
results.append(("C. SetRGB 逐像素", got, size, "n/a"))
print(f"  C. SetRGB 逐像素         → 亮度 {got:6.1f}")

# ── 方式 D：CreateFromData 重建一张 ────────────────────────────────────────
path = os.path.join(OUT, "d.jpg")
src = base.Copy()
data = bytes(src.GetDataBuffer())
dimmed = bytes(int(v * DIM) for v in data)
w, h = src.GetSize()
rebuilt = wx.Image(w, h)
rebuilt.SetData(dimmed)
rebuilt.SaveFile(path, wx.BITMAP_TYPE_JPEG)
got, size = brightness(path)
results.append(("D. 新建 Image + SetData", got, size, "n/a"))
print(f"  D. 新建+SetData          → 亮度 {got:6.1f}  尺寸 {size}")

print()
print("  ── 判定（亮度必须明显低于原图的 60%）──")
threshold = base_bright * 0.60
winner = None
for name, got, size, _extra in results:
    ok = got < threshold and size[0] > 0
    mark = "✅ 可用" if ok else "❌ 无效"
    print(f"    {mark}  {name:28} 亮度 {got:6.1f}")
    if ok and winner is None:
        winner = name
print()
print(f"  可用的方式：{winner or '**一个都没有**'}")
