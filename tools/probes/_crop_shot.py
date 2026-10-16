"""在留档画面里**找出蓝色的行**并裁出来（不靠行号猜）。

前面按行号硬算坐标裁错了 —— 因为每跑一次探针，选中的行号都会变。
所以改成"先扫出蓝色像素在哪几行，再裁那几行"，只用数据说话。
"""
from __future__ import annotations

import os
import sys

import wx

app = wx.App(redirect=False)

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")


def find_blue_rows(image: wx.Image, blue: str = "#0078D7") -> list[int]:
    """扫描每一行的蓝色像素占比，返回占比 > 50% 的行号。"""
    target = (int(blue[1:3], 16), int(blue[3:5], 16), int(blue[5:7], 16))
    hits: list[int] = []
    for y in range(image.GetHeight()):
        same = 0
        total = 0
        for x in range(30, max(image.GetWidth() - 30, 31), 4):
            total += 1
            if (abs(image.GetRed(x, y) - target[0]) <= 6
                    and abs(image.GetGreen(x, y) - target[1]) <= 6
                    and abs(image.GetBlue(x, y) - target[2]) <= 6):
                same += 1
        if total and same * 100 // total > 50:
            hits.append(y)
    return hits


def crop(name: str, top: int, height: int, out: str, width: int = 640) -> None:
    image = wx.Image(os.path.join(SHOTS, name), wx.BITMAP_TYPE_PNG)
    piece = image.GetSubImage(wx.Rect(0, top, min(width, image.GetWidth()), height))
    piece.SaveFile(os.path.join(SHOTS, out), wx.BITMAP_TYPE_PNG)
    counts: dict[str, int] = {}
    for y in range(piece.GetHeight()):
        for x in range(0, piece.GetWidth(), 2):
            colour = "#%02X%02X%02X" % (piece.GetRed(x, y), piece.GetGreen(x, y),
                                        piece.GetBlue(x, y))
            counts[colour] = counts.get(colour, 0) + 1
    total = sum(counts.values())
    best = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    print(f"  裁出 {out}: {piece.GetWidth()}x{piece.GetHeight()}  主色 = "
          + "  ".join(f"{c}:{n * 100 // total}%" for c, n in best))


for name in ("user-shape-A.png", "open-after.png"):
    path = os.path.join(SHOTS, name)
    if not os.path.exists(path):
        continue
    image = wx.Image(path, wx.BITMAP_TYPE_PNG)
    rows = find_blue_rows(image)
    print(f"{name}: {image.GetWidth()}x{image.GetHeight()}  "
          f"蓝色行像素所在 y = {rows[:1]}..{rows[-1:] if rows else []}（共 {len(rows)} 行）")
    if rows:
        top = max(rows[0] - 2, 0)
        height = min(rows[-1] - rows[0] + 5, image.GetHeight() - top)
        crop(name, top, height, f"crop-blue-row-{name.replace('.png', '')}.png")
