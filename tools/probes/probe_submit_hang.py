"""复现"输入路径回车 → 未响应"，并用 `faulthandler` 超时**转储调用栈**。

## 为什么用 faulthandler

"未响应"是**卡死**，不是异常 —— 没有 traceback 可看。
`faulthandler.dump_traceback_later(秒数, exit=True)` 会在超时后
把**当前所有线程的调用栈**打出来，**直接指出卡在哪一行**。

这比读代码猜可靠得多 —— 本会话已经三次读代码没找出来、
一上探针就定案了。
"""
import ctypes
import faulthandler
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

#: 卡住超过这么多秒就把调用栈打出来并退出
faulthandler.dump_traceback_later(25, exit=True)

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

with probe_temp("probe-submit-hang") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    seed.record_access(scratch)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    for _ in range(50):
        wx.YieldIfNeeded()
        time.sleep(0.01)

    # 目标：一个**真实存在、有若干层**的路径
    target = os.path.join(scratch, "deep", "target-folder")
    os.makedirs(target, exist_ok=True)
    print(f"  提交路径 = {target}")
    print("  调用 on_path_submitted …（若卡死，25 秒后会转储调用栈）")
    sys.stdout.flush()

    started = time.time()
    try:
        frame.on_path_submitted(target)
    except Exception as error:                     # noqa: BLE001
        print(f"  抛异常：{type(error).__name__}: {error}")
    elapsed = time.time() - started
    print(f"  返回，用了 {elapsed:.2f} 秒")

    # 再看一遍导航选中的是不是它
    for _ in range(20):
        wx.YieldIfNeeded()
    print(f"  导航选中 = {frame.dir_ctrl.GetPaths()}")

    frame.store.close()
    frame.Destroy()

faulthandler.cancel_dump_traceback_later()
print("  完成（没卡）")
