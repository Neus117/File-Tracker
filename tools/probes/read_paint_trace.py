"""把 `paint-trace.txt` 扫成一句话结论：**选中行最后归谁管**。

## 为什么要这个脚本

报告里最多有几百条改动，人眼找"选中行最后一次被谁写成什么"很容易看漏，
**看漏的代价是把"程序是对的"误判成"程序有 bug"**（或反过来）。

本脚本只回答三个问题：

1. 选中行上出现过的**所有**颜色，各是谁写的、几次
2. 其中**最后一次**是哪个颜色、谁写的
3. 有没有任何一次把选中行写成 `row_hover`（那就是"浅灰"的元凶）

用法：

```bash
python tools/probes/read_paint_trace.py            # 读默认报告
python tools/probes/read_paint_trace.py <路径>
```
"""
from __future__ import annotations

import os
import re
import sys

DEFAULT = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                       "File Tracker", "paint-trace.txt")

ROW = re.compile(r"底色\(row=(\d+),\s*(#[0-9A-Fa-f]{6})\)")
HEAD = re.compile(r"^\[PAINT\]\s+\+?\s*([\d.]+)ms")
SELECTED = re.compile(r"选中行=(\d+)")
HOVER = re.compile(r"row_hover\s*=\s*(#[0-9A-Fa-f]{6})")
CARD = re.compile(r"card\s*=\s*(#[0-9A-Fa-f]{6})")
HIGHLIGHT = re.compile(r"真画了（键变了）\s*=\s*(\d+) 次\s*\n\s*被 _paint_key 早退吃掉 = (\d+) 次")
ACTIVE = re.compile(r"激活吗\*\* = (\S+)")


def is_entry(line: str) -> bool:
    """判断是不是一条报告条目的**首行**。

    ⚠️ **踩过两次的坑**：条目在报告里有**两格前导缩进**
    （`report()` 里写的 `f"  {self.last[key]}"`），
    所以 `line.startswith("[PAINT]")` 一条都匹配不到 ——
    结果报告里明明有记录，扫描器却说"共 0 次"，
    **差一点被读成"程序根本没上色"**。

    判据只能看 **`strip()` 之后**的结果。
    """
    return line.strip().startswith("[PAINT]")


def main(path: str) -> int:
    if not os.path.exists(path):
        print(f"找不到报告：{path}")
        return 2
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    selected = -1
    hover_colour = card_colour = None
    switch = ""
    for line in lines:
        found = SELECTED.search(line)
        if found and selected < 0:
            selected = int(found.group(1))
        if HOVER.search(line):
            hover_colour = HOVER.search(line).group(1).upper()
        if CARD.search(line):
            card_colour = CARD.search(line).group(1).upper()
        if line.startswith("诊断开关"):
            switch = line.split("=", 1)[1].strip()

    if selected < 0:
        print("报告里没有「选中行=」，无法判定（报告可能不完整）")
        return 2

    # ⚠️ **每条记录是"多行"的**：第一行是 `[PAINT] …`（带两格缩进），
    #    后面几行是调用栈。所以：
    #    ① 用 `is_entry`（strip 后判断）找条目首行
    #    ② 把紧随其后的调用栈行归给它
    records: list[tuple[int, float, str]] = []
    for index, line in enumerate(lines):
        if not is_entry(line):
            continue
        stamp = HEAD.search(line.strip())
        records.append((index, float(stamp.group(1)) if stamp else -1.0, line))

    def caller_of(index: int) -> str:
        for follower in lines[index + 1:index + 9]:
            if is_entry(follower):
                break
            text = follower.strip().lstrip("← ").strip()
            if text and "paint_trace.py" not in text:
                return text
        return "?"

    entries: list[tuple[int, float, str, str]] = []   # (序号, 时间, 颜色, 调用者)
    for index, when, line in records:
        found = ROW.search(line)
        if found and int(found.group(1)) == selected:
            entries.append((index, when, found.group(2).upper(), caller_of(index)))

    print(f"报告      = {path}")
    print(f"诊断开关  = {switch or '（没写）'}")
    print(f"选中行    = {selected}")
    print(f"row_hover = {hover_colour}    card = {card_colour}")
    print(f"条目总数  = {len(records)}（含所有行，不只选中行）")

    whole = "\n".join(lines)
    found_active = ACTIVE.search(whole)
    if found_active:
        print(f"窗口此刻激活吗 = {found_active.group(1)}"
              "   ← False 时 Windows 会用非活动选中色盖掉我们的蓝（实测 #F0F0F0）")
    found_hl = HIGHLIGHT.search(whole)
    if found_hl:
        painted, early = found_hl.group(1), found_hl.group(2)
        note = ""
        if early != "0":
            note = "   ← 有早退：要查是不是「选中行已变却没画」"
        print(f"画高亮那一步   = 真画了 {painted} 次，被 _paint_key 早退吃掉 {early} 次{note}")

    print(f"\n选中行上的底色改动：共 {len(entries)} 次\n")

    if not entries:
        print("  ⚠️ **选中行上没有任何底色改动记录** ⇒ 它现在画的是重建时的底色。")
        return 0

    by_colour: dict[str, list[tuple[int, float, str]]] = {}
    for index, when, colour, caller in entries:
        by_colour.setdefault(colour, []).append((index, when, caller))
    for colour in sorted(by_colour,
                         key=lambda c: -max(i for i, _, _ in by_colour[c])):
        hits = by_colour[colour]
        last_index, last_when, last_caller = max(hits, key=lambda item: item[0])
        tag = "  ← **预选灰（屏幕上就是浅灰）**" if colour == hover_colour else ""
        print(f"  {colour}  ×{len(hits):<4} 最后一次 +{last_when:8.1f}ms  "
              f"{last_caller}{tag}")

    last_index, last_when, last_colour, last_caller = max(entries,
                                                          key=lambda item: item[0])
    print(f"\n最后一次：{last_colour}  （+{last_when:.1f}ms，由 {last_caller} 写入）")
    print("\n── 判定 ──")
    if hover_colour and last_colour == hover_colour:
        print(f"  ❌ 选中行最后一次被写成 **预选灰 {hover_colour}**。")
        print(f"     元凶 = {last_caller}")
    elif last_colour == "#0078D7":
        print(f"  ✅ 选中行最后一次被写成**系统高亮蓝 {last_colour}**（{last_caller}）。")
        print("     若屏幕上仍是灰 ⇒ **问题不在本程序的配色**：")
        print("     窗口未激活 / 被别的窗口遮住 / 另一处覆盖在上面。")
    else:
        print(f"  ⚠️ 选中行最后一次是 {last_colour}（{last_caller}）——"
              f" 既不是蓝也不是预选灰，需要看完整清单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
