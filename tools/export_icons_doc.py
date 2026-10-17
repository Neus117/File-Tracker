r"""把 `widgets.py` 里**八个自绘图形**的代码抽出来，生成 `Icons-Drawing.md`。

## 为什么要自动抽

手抄会漂移：改了 `widgets.py` 却忘了改文档，下一个人照文档抄就抄到旧版。
这里按函数名精确切片，改完重跑一次即可。

用法：

```powershell
python tools/export_icons_doc.py
```
"""
from __future__ import annotations

import io
import os
import re

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src",
                   "file_tracker", "widgets.py")
#: 经验库在 `D:\Coding\DeepSeek 开发经验`，而本脚本在
#: `D:\Coding\MyGitHub\File-Tracker\tools` ⇒ 要往上 **三层**
#: （tools → File-Tracker → MyGitHub → Coding）。少算一层会生成到
#: `D:\Coding\MyGitHub\DeepSeek 开发经验`（实测踩过）。
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "..", "..", "DeepSeek 开发经验", "Icons-Drawing.md")

#: 要抽取的顶层名字，**顺序就是文档里的顺序**（基础设施 → 各图标）。
#: 每个名字会连同它上方的注释一起抽出来。
WANTED = (
    "_draw_icon",
    "_NATIVE_FOLDER",
    "icon_sun",
    "icon_moon",
    "icon_monitor",
    "icon_path",
    "icon_count",
    "icon_time",
    "_arrow",
    "icon_arrow_up",
    "icon_arrow_down",
    "SORT_ICONS",
)

#: 文档里的标题与一句话说明（英文名，简洁）
TITLES = {
    "_draw_icon": ("`_draw_icon` — the primitive renderer",
                   "Takes a **list of primitives** and draws them on a "
                   "`wx.GraphicsContext`. Supported kinds: `rect` (stroke only), "
                   "`line`, `ellipse` (stroke only), `polygon` (filled), "
                   "`ellipse_fill` (filled, geometry-exact)."),
    "_NATIVE_FOLDER": ("`_NATIVE_FOLDER` — folder outline data",
                       "Normalised 2-D points for the folder icon, modelled on "
                       "Windows Explorer. Ratio **1.29 : 1**, sharp corners."),
    "icon_sun": ("`icon_sun` — Theme : light",
                 "Filled disc + **eight dots**. Disc and dots both use "
                 "`ellipse_fill` so the centre is geometry-exact."),
    "icon_moon": ("`icon_moon` — Theme : dark",
                  "Crescent = whole circle minus an offset circle, one filled "
                  "polygon. Shifted right by `0.12 × size` to compensate the "
                  "visual weight."),
    "icon_monitor": ("`icon_monitor` — Theme : follow system",
                     "Hollow frame + base line. Width is **0.86 ×** the default "
                     "so the display reads as 16 : 9."),
    "icon_path": ("`icon_path` — Sort by : path",
                  "Folder, filled, from `_NATIVE_FOLDER`."),
    "icon_count": ("`icon_count` — Sort by : count",
                   "Three filled bars of different heights."),
    "icon_time": ("`icon_time` — Sort by : time",
                  "Filled dial + two hands drawn in the **button background "
                  "colour** (that is what makes them look punched out)."),
    "_arrow": ("`_arrow` — shared arrow builder",
               "One shaft + two barbs. `upward=False` flips it."),
    "icon_arrow_up": ("`icon_arrow_up` — Order : ascending",
                      "Arrow pointing up."),
    "icon_arrow_down": ("`icon_arrow_down` — Order : descending",
                        "Arrow pointing down."),
    "SORT_ICONS": ("`SORT_ICONS` — sort key to painter map",
                   "Used by `SettingsDialog._build_sort_rows`."),
}


def read_source() -> list[str]:
    with io.open(SRC, encoding="utf-8") as handle:
        return handle.read().splitlines(keepends=True)


def slice_block(lines: list[str], name: str) -> str:
    """从 `name` 的定义（含上方紧邻的注释）切到下一个顶层定义之前。"""
    # 定义可能是 `def name(` 或 `name =` / `name: ... =`
    pattern = re.compile(
        r"^(?:def %s\(|%s\s*(?::[^=]+)?=)" % (re.escape(name), re.escape(name)))
    start = None
    for index, line in enumerate(lines):
        if pattern.match(line):
            start = index
            break
    if start is None:
        return "# (not found: %s)\n" % name

    # 往上吃掉紧邻的注释行（# 开头），但不越过空行
    head = start
    while head > 0:
        prev = lines[head - 1].strip()
        if prev.startswith("#") or prev.startswith('"""'):
            head -= 1
        else:
            break
    # 再往上如果还有一行空行，保留它作为分隔（不把空行算进块里）
    start = head

    # 往下切到下一个顶层定义（0 缩进的 def/class/大写常量）
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        if re.match(r"^(?:def |class |@|[A-Z_][A-Z_0-9]*\s*(?::[^=]+)?=)", line):
            end = index
            # 把紧邻在它上方的注释留给下一块
            while end > start and lines[end - 1].strip().startswith("#"):
                end -= 1
            break
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "".join(lines[start:end]).rstrip() + "\n"


def main() -> None:
    lines = read_source()
    chunks = []
    for name in WANTED:
        title, blurb = TITLES.get(name, (name, ""))
        body = slice_block(lines, name)
        chunks.append("## %s\n\n%s\n\n```python\n%s```\n" % (title, blurb, body))

    header = """# Icons — drawing code

The eight custom glyphs used by the settings dialog, plus the tiny primitive
renderer they share. **Generated** from `src/file_tracker/widgets.py` by
`tools/export_icons_doc.py` — do not edit by hand, re-run the script instead.

Referenced from [`DevAesthetics of Neus117.md`](DevAesthetics%20of%20Neus117.md).

## Why primitives instead of glyphs

Every icon is a **list of geometric primitives**, not a character from a font.
That means it never depends on "does this font have that codepoint" — it renders
identically on any Windows, any theme, any font. Several earlier attempts used
`💻` / `☀` / `☾` and broke on machines whose font lacked the glyph (or, worse,
rendered it at a wildly different width and blew up the button size).

## Size contract

`size` is a **scalar** (in practice the height of the letter `M` at the current
font, so the icon matches the height of adjacent text buttons). Every coordinate
below is normalised against it, so one icon scales with DPI for free.

Eight icons:

| Icon | Where | Shape |
|---|---|---|
| `icon_monitor` | Theme → follow system | hollow frame + base line |
| `icon_sun` | Theme → light | filled disc + 8 dots |
| `icon_moon` | Theme → dark | crescent (filled polygon) |
| `icon_path` | Sort by → path | folder |
| `icon_count` | Sort by → count | 3 bars |
| `icon_time` | Sort by → time | dial + 2 hands |
| `icon_arrow_up` | Order → ascending | ↑ |
| `icon_arrow_down` | Order → descending | ↓ |

---

"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + "\n".join(chunks))
    print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
