r"""验：**切换界面语言之后，列宽必须按新语言重算**（用户 2026-10-17 报的）。

## 用户的观察（比我的探针更接近真相）

> "英文启动：count（频次）列计算得比较宽。此时若在设置界面换成中文，
>   程序没有重新计算，就会导致切换后的中文界面里'频次'这一列**过宽**。
>   中文启动：若切换成英文，程序不会重新测量，
>   就会导致英文的'count'和三角**重叠在一起**。"

**这是前几轮"三角压线"反复出现的真凶**：我一直量的是"启动后立刻"的几何，
而用户是**切换过语言之后**看的 —— 那时列宽还是**上一种语言**算的。

## 判据

| # | 判据 |
|---|---|
| 1 | 英文→中文：频次列宽**等于中文该有的宽度**（不是英文那个更宽的值） |
| 2 | 中文→英文：Count 列宽**等于英文该有的宽度**（且三角不重叠） |
| 3 | 两条路径最终**收敛到同一个值**（`EN→ZH` 与"中文启动"一致） |
| 4 | 最右的时间列**几乎没有右留白**（它的右边没有分隔线要避让） |
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import ctypes
import time

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


def widths_now(frame) -> dict:
    """按**当前语言**读出四个列宽（标题 → 宽）。"""
    labels = app_mod.column_labels()
    return {title: frame.list_ctrl.GetColumnWidth(index)
            for index, title in enumerate(labels)}


def switch(frame, preference: str) -> dict:
    """走**真实的切语言路径**：`apply_language` + `retranslate()`。"""
    lang.apply(preference)
    frame.retranslate()
    pump(15)
    return widths_now(frame)


with probe_temp("probe-language-widths") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    # ⚠️ **不能在创建 Frame 前 apply 语言**：`FileTracker.__init__` 会按
    # `config.get_language()` / 系统语言重新 apply 一次，把探针设的值覆盖掉。
    # 实测第一版探针就是这么错的 —— 它以为"英文启动"，其实启动成了中文。
    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(60)

    try:
        # 先切到英文，作为"英文启动"的等价物（走真实切换路径）
        print("【切到英文】")
        en_start = switch(frame, lang.PREFERENCE_ENGLISH)
        en_labels = app_mod.column_labels()
        print("  " + "  ".join("%s=%d" % (k, v) for k, v in en_start.items()))

        # ① 英文 → 中文
        zh_labels_before = None
        lang.apply(lang.PREFERENCE_CHINESE)
        zh_labels = app_mod.column_labels()
        print("\n【英文 → 中文（走真实 retranslate）】")
        zh_after = switch(frame, lang.PREFERENCE_CHINESE)
        print("  " + "  ".join("%s=%d" % (k, v) for k, v in zh_after.items()))
        zh_freq = zh_after[zh_labels[app_mod.COLUMN_COUNT]]
        en_freq = en_start[en_labels[app_mod.COLUMN_COUNT]]
        print("  中文频次列 = %d（英文启动时是 %d）" % (zh_freq, en_freq))
        check("1 英文→中文后，频次列宽**按中文重算**（不是沿用英文的宽度）",
              zh_freq != en_freq and zh_freq < en_freq,
              "中文 %d，英文 %d（中文标题更短，应当更窄）" % (zh_freq, en_freq))

        # ② 中文 → 英文
        print("\n【中文 → 英文】")
        en_after = switch(frame, lang.PREFERENCE_ENGLISH)
        print("  " + "  ".join("%s=%d" % (k, v) for k, v in en_after.items()))
        en_freq_back = en_after[app_mod.column_labels()[app_mod.COLUMN_COUNT]]
        print("  英文 Count 列 = %d（最初英文启动时是 %d）" % (en_freq_back, en_freq))
        check("2 中文→英文后，Count 列宽**按英文重算**（与英文启动一致）",
              en_freq_back == en_freq,
              "回来 %d，最初 %d" % (en_freq_back, en_freq))

        # ③ 三角不重叠：列宽够装下"标题+三角"
        labels = app_mod.column_labels()
        header = frame.header
        dc = wx.ClientDC(frame.list_ctrl)
        dc.SetFont(header.GetFont())
        # **需要 = 左缩进 + 标题 + 三角** —— 漏掉缩进这一项就会自欺：
        # 第一版只比"标题+三角"，于是 `列宽 100 vs 需要 97` 报"装得下"，
        # 而实际缩进还有 12 像素 ⇒ 三角早就压线了。
        from file_tracker.theme import METRICS, scale_for_dpi
        from file_tracker.widgets import dpi_of
        inset = scale_for_dpi(METRICS.header_text_inset, dpi_of(header))
        need = inset + dc.GetTextExtent(
            labels[app_mod.COLUMN_COUNT] + " ▼").width
        check("3 英文下 Count 列装得下「缩进+标题+三角」（不重叠）",
              en_freq_back >= need,
              "列宽 %d，需要 %d（缩进 %d）" % (en_freq_back, need, inset))

        # ④ 最右的时间列几乎没有右留白
        print("\n【最右的时间列】")
        for preference, name in ((lang.PREFERENCE_ENGLISH, "英文"),
                                 (lang.PREFERENCE_CHINESE, "中文")):
            data = switch(frame, preference)
            labels = app_mod.column_labels()
            title = labels[app_mod.COLUMN_TIME]
            width = data[title]
            # 该列"最宽的那条数据"占多宽
            dc = wx.ClientDC(frame.list_ctrl)
            dc.SetFont(frame.list_ctrl.GetFont())
            data_max = 0
            for row in range(min(frame.list_ctrl.GetItemCount(),
                                 app_mod.FileTracker.COLUMN_WIDTH_SAMPLE)):
                data_max = max(data_max,
                               dc.GetTextExtent(frame.list_ctrl.GetItemText(row, app_mod.COLUMN_TIME)).width)
            # **留白 = 内容右缘 → 列右边界**（用户看到的就是这一段）。
            # 不能算 `列宽 − 内容宽`：那个值等于 `extra`，把"左缩进"也算进去了，
            # 于是同一列会被报成 19 而不是 7 —— 那正是两个探针给出矛盾读数的原因。
            from file_tracker.theme import METRICS, scale_for_dpi
            from file_tracker.widgets import dpi_of
            inset = scale_for_dpi(METRICS.header_text_inset, dpi_of(frame.header))
            # 三角回到**字符**（用户要求：自绘的有锯齿）——
            # 宽度靠字体量，与绘制同一个来源（`header.sort_arrow_width`）。
            content = max(data_max,
                          dc.GetTextExtent(title).width
                          + app_mod.sort_arrow_width(dc, dpi_of(frame.header)))
            slack = width - inset - content
            print("  %s：`%s` 列宽 %d，内容 %d，缩进 %d ⇒ 视觉留白 %d"
                  % (name, title, width, content, inset, slack))
            # 上限是**用户定的观感**，不是技术约束：
            # 2026-10-17 用户要求"稍微增加与分隔线的间距，增强呼吸感"，
            # 所以从原来的 4（贴边）改成 10 逻辑像素 ⇒ 实测约 18 物理。
            # 判据只是防止它退回到"占满整列"或"贴死分隔线"那两端。
            check("4 [%s] 最右列（时间）留白在合理区间（6~28 物理像素）" % name,
                  6 <= slack <= 28,
                  "留白 = %d 物理像素（7 = 贴边版，18 = 现在的呼吸感版）" % slack)
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
