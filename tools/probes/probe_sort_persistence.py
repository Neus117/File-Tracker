"""诊断：排序偏好是不是真的"下次启动也生效"。

用户要求："可以选择下次启动时的排序方式。"

所以要验的是**跨启动**，不是"点一下当场变"：

  ① 造一个有已知频次/时间的数据集
  ② 打开窗口 → 点表头换成"路径" → 记下第一行
  ③ 关掉窗口，**新建一个**（模拟下次启动）
  ④ 断言新窗口的初始排序就是"路径"，且第一行内容一致
  ⑤ 反向也验一遍（换回频次降序）

判据用**列表里第一行的路径文本**，不依赖像素。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from file_tracker import core, lang
from _probe_temp import probe_temp

import file_tracker.app as app_mod

app = wx.App()
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)


def first_rows(frame, count=3):
    return [frame.list_ctrl.GetItemText(row)
            for row in range(min(count, frame.list_ctrl.GetItemCount()))]


def first_column_text(frame):
    """列表里第一行的**路径列**（只看第一列，不受居中空格影响）。"""
    return frame.list_ctrl.GetItemText(0, 0).strip()


with probe_temp("probe-sort") as scratch:
    db = os.path.join(scratch, "p.db")
    cfg = os.path.join(scratch, "config.json")
    # 两个"位置"都要换成临时目录——否则会往用户真实的
    # `%APPDATA%\File Tracker\config.json` 里写排序偏好。
    # （`app.py` 里 import 的是名字，所以要替换 `app_mod` 上的那一个。）
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: cfg

    # ---- 造数据：频次与字母序**故意相反**，这样两种排序的第一行不同 ----
    #
    # zeta 访问 5 次、alpha 访问 1 次：
    #   按频次降序 → zeta 在前
    #   按路径升序 → alpha 在前
    # 如果两者第一行相同，这个探针就什么都验不出来。
    seed = app_mod.PathStore(db)
    for name, times in (("zeta", 5), ("alpha", 1), ("mid", 3)):
        for _ in range(times):
            seed.record_access(os.path.join(scratch, name))
    seed.close()

    def open_frame():
        frame = app_mod.FileTracker()
        frame.SetTitle("probe-sort")
        frame.Show()
        for _ in range(60):
            wx.YieldIfNeeded()
            time.sleep(0.02)
        return frame

    # ---- 第一次启动：默认应当是"频次、降序" ----
    frame = open_frame()
    print(f"  ① 首次启动  列={frame.sort_key} 降序={frame.sort_reverse} "
          f"首行={first_column_text(frame)!r}  行数={frame.list_ctrl.GetItemCount()}")
    default_first = first_column_text(frame)
    print(f"     期望首行含 'zeta'（频次最高）→ "
          f"{'✅' if 'zeta' in default_first else '❌'}")

    # ---- 切到"路径"（升序应当自动带出该列的默认方向）----
    frame.apply_sort(app_mod.COLUMN_PATH, toggle=True)
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  ② 点'路径'  列={frame.sort_key} 降序={frame.sort_reverse} "
          f"首行={first_column_text(frame)!r}")
    path_first = first_column_text(frame)
    print(f"     期望首行含 'alpha'（字母序在前）→ "
          f"{'✅' if 'alpha' in path_first else '❌'}")

    # 再点一次应当翻成降序
    frame.apply_sort(app_mod.COLUMN_PATH, toggle=True)
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  ③ 再点'路径' 降序={frame.sort_reverse} 首行={first_column_text(frame)!r}"
          f"  期望翻成 zeta → {'✅' if 'zeta' in first_column_text(frame) else '❌'}")

    # 翻回升序，作为"下次启动"的期望值
    frame.apply_sort(app_mod.COLUMN_PATH, reverse=False)
    for _ in range(20):
        wx.YieldIfNeeded()
    expected_first = first_column_text(frame)
    print(f"  ④ 设为路径升序，首行={expected_first!r}")
    frame.store.close()
    frame.Destroy()
    for _ in range(20):
        wx.YieldIfNeeded()

    # ---- 第二次启动（模拟"下次启动"）----
    frame2 = open_frame()
    got = first_column_text(frame2)
    print(f"  ⑤ 再次启动  列={frame2.sort_key} 降序={frame2.sort_reverse} "
          f"首行={got!r}")
    ok = (frame2.sort_key == "path" and frame2.sort_reverse is False
          and got == expected_first)
    print(f"     与上次一致 → {'✅ 是' if ok else '❌ 否'}")
    print(f"     配置读到 = sort_column={frame2.config.get_sort_column()!r} "
          f"direction={frame2.config.get_sort_direction('path')}")
    frame2.store.close()
    frame2.Destroy()
    for _ in range(20):
        wx.YieldIfNeeded()
