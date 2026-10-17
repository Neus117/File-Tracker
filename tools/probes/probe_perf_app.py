r"""全程序性能体检：量**用户会感知到的六条路径**，全程 < 20 秒。

## 为什么是这六条

用户要的是"性价比高的优化点"，所以只测**每次操作都要走**的路径，
且每条都是他点一下就触发一次的：

| # | 路径 | 触发方式 |
|---|---|---|
| 1 | `FileTracker()` 构造 | 双击 exe |
| 2 | `load_accessed_paths()`（6000 行） | 切目录 / 启动 |
| 3 | `retranslate()` | 切语言 |
| 4 | `apply_theme()` | 切主题 |
| 5 | `sort_list_items()` | 点列头 / 改排序 |
| 6 | `SettingsDialog()` 构造 | 点设置 |

**不测**的：滚动（已有 4.7 ms/帧基线）、拖拽（已有）、数据库单条读写
（微秒级，不在感知范围）。

## 判据

每个操作跑 3 次取**中位**（抗首次冷启动），并标出占总耗时的比例。
只有"占比大 + 改动小"的才值得动。
"""
from __future__ import annotations

import ctypes
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import lang
from file_tracker.widgets import SettingsDialog

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

app = wx.App(redirect=False)
ROWS = 6000


def pump(rounds: int = 20, pause: float = 0.003) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def measure(label: str, fn, repeat: int = 3) -> float:
    """跑 `repeat` 次，返回中位耗时（毫秒）。"""
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        pump(6)
        samples.append((time.perf_counter() - start) * 1000.0)
    median = statistics.median(samples)
    print("  %-34s 中位 %8.1f ms   （%s）"
          % (label, median, ", ".join("%.1f" % s for s in samples)))
    return median


with probe_temp("perf-app") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    # 先灌数据（用 store 直接写，不走界面）
    seed = app_mod.PathStore(db)
    for index in range(ROWS):
        seed.record_access("D:\\perf\\dir-%05d\\file-%05d.txt" % (index, index),
                           when="2026-10-17 %02d:%02d:%02d"
                                % (index % 24, index % 60, index % 60))
    seed.close()
    print("已灌 %d 行" % ROWS)
    print()

    # 用可变的容器装 frame：模块级的 `with` 块里没法用 `nonlocal`
    # （它只能指向**函数**作用域里的名字，而这里是模块作用域）。
    holder = {"frame": None}

    def build_frame():
        frame = holder["frame"]
        if frame is not None:
            try:
                frame.store.close()
            except Exception:
                pass
            frame.Destroy()
            pump(6)
        frame = app_mod.FileTracker()
        frame.open_folder = lambda p: True
        frame.SetSize((1200, 700))
        frame.Show()
        pump(30)
        holder["frame"] = frame

    print("=== 六条用户路径 ===")
    build_frame()

    # ② 载入 6000 行（构造里已经载过一次，这里单独再量）
    frame = holder["frame"]
    measure("② load_accessed_paths(%d 行)" % ROWS,
            lambda: frame.load_accessed_paths())

    # ③ 切语言
    def flip_language():
        lang.apply(lang.PREFERENCE_ENGLISH
                   if lang.is_chinese() else lang.PREFERENCE_CHINESE)
        frame.retranslate()
    measure("③ retranslate（切语言）", flip_language, repeat=3)
    lang.apply(lang.PREFERENCE_CHINESE)
    frame.retranslate()
    pump(10)

    # ④ 切主题
    def flip_theme():
        frame.theme = (app_mod.Theme.dark() if not frame.theme.is_dark
                       else app_mod.Theme.light())
        frame.apply_window_theme()
    measure("④ apply_theme（切主题）", flip_theme, repeat=3)
    frame.theme = app_mod.Theme.light()
    frame.apply_window_theme()
    pump(10)

    # ⑤ 换排序
    measure("⑤ sort_list_items（换排序）",
            lambda: frame.sort_list_items(frame.sort_column), repeat=3)

    # ⑥ 设置窗口
    def open_settings():
        dlg = SettingsDialog(frame, frame.theme, "zh", sort_key="path",
                             sort_reverse=True, theme_preference="light")
        pump(4)
        dlg.Destroy()
    measure("⑥ SettingsDialog 构造", open_settings, repeat=3)

    # ① 构造（放最后：它会重建窗口）
    measure("① FileTracker() 构造 + Show", build_frame, repeat=3)

    last = holder["frame"]
    if last is not None:
        try:
            last.store.close()
        except Exception:
            pass
        last.Destroy()
    pump(10)

print()
print("完成")
