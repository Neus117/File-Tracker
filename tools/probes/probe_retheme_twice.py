r"""验：**"跟随系统" → 明确主题 → 点确定，会不会闪一下**（真实对话框）。

## 用户报的现象（2026-10-17）

> "界面主题在深浅之间互相切换时……点完确定以后不会反复刷新。
>   但是我观察到，**一旦从'跟随系统主题'开始**，变成与系统主题不同的主题状态，
>   那么你在点**确定**的时候，大概率会观察到**部分组件的二次刷新**。
>   帮我检查一下，希望是我的错觉。"

**不是错觉。** 机制（本探针量的就是这个）：

```
① 预览选深色              → 界面变深（正确，所见即所得）
② 点「确定」→ 对话框关闭 → 主窗口重获激活
   → `on_activate` 跑到"只有跟随系统才重读注册表"那一段，
     而**此刻配置还没落盘、仍是 "system"**
   → 重读系统主题（浅色）⇒ **把界面改回浅色**
③ `on_settings` 的自愈再把它改回深色
   ⇒ 中间那次就是用户看到的"二次刷新"
```

而"深浅互切"（配置里本来就是明确的 light/dark）**走不到**这段，
所以**只有从"跟随系统"出发时才闪** —— 与用户的观察完全吻合。

## 判据

| # | 判据 |
|---|---|
| 1 | 从"跟随系统"→明确主题、点确定：**确定阶段 `_retheme` = 0 次** |
| 2 | 深浅互切、点确定：确定阶段 `_retheme` = 0 次（本来就对，阳性对照） |
| 3 | 确定之后**界面停在用户选的主题**上（不许被系统主题顶掉） |
| 4 | 真对话框：点主题按钮时**预览确实生效**（`_retheme` ≥ 1） |

**用真实 `SettingsDialog` + 定时器自动操作** —— 不弹给人、也不模拟对话框，
所以走的是与用户完全同一条代码路径（含 `ShowModal` 的模态循环）。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
import file_tracker.widgets as widgets_mod
from file_tracker import lang
from file_tracker.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=15, pause=0.004):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


class RethemeCounter:
    """数 `_retheme` 被调了几次，并可随时"清零重数"。"""

    def __init__(self, frame):
        self.frame = frame
        self.count = 0
        self.original = frame._retheme

        def wrapper():
            self.count += 1
            return self.original()

        wrapper.__name__ = "counted_retheme"
        frame._retheme = wrapper

    def reset(self):
        self.count = 0

    def stop(self):
        self.frame._retheme = self.original


def drive_settings(frame, counter, *, start_theme, picked_theme):
    """打开**真实**设置对话框，用定时器点主题再点确定。

    :return: (预览阶段 _retheme 次数, 确定阶段 _retheme 次数, 结束后是否深色)
    """
    frame.config.set_theme(start_theme)
    frame.theme = app_mod.theme_from_preference(start_theme)
    counter.original()
    pump()

    marks = {"preview": None, "confirm_start": None}

    def automation():
        dialog = None
        for window in wx.GetTopLevelWindows():
            if isinstance(window, widgets_mod.SettingsDialog):
                dialog = window
                break
        if dialog is None:
            wx.CallLater(30, automation)
            return
        # ① 点主题按钮
        #
        # ⚠️ `RoundedButton` 的点击走 **`wx.EVT_BUTTON`**（`_on_left_up` 里
        # `ProcessEvent` 一个 CommandEvent），**不是 `on_click` 回调** ——
        # 只有 `IconButton` 才用回调。第一版探针按 `on_click` 找，
        # 一个都找不到，于是"预览 = 0"（假失败）。
        #
        # 这里直接调 `_choose_theme`：它就是按钮 `Bind` 的那个处理函数，
        # 走的是**同一条预览路径**，而且不依赖鼠标坐标。
        counter.reset()
        dialog._choose_theme(picked_theme)
        pump(4)
        marks["preview"] = counter.count
        # ② 点「确定」—— 用真的 `wx.EVT_BUTTON` 发给它
        counter.reset()
        marks["confirm_start"] = True
        yes_button = dialog._buttons[0]        # `_buttons[0]` 就是确定
        click = wx.CommandEvent(wx.EVT_BUTTON.typeId, yes_button.GetId())
        click.SetEventObject(yes_button)
        yes_button.GetEventHandler().ProcessEvent(click)

    wx.CallLater(80, automation)
    frame.on_settings(None)                    # ← 走真实的模态流程
    pump(20)
    return marks.get("preview"), counter.count, frame.theme.is_dark


with probe_temp("probe-retheme-twice") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    frame.Show()
    frame.Maximize()
    pump(50)

    counter = RethemeCounter(frame)
    system_dark = app_mod.theme_from_system().is_dark
    opposite = THEME_LIGHT if system_dark else THEME_DARK
    print("系统主题 = %s" % ("深色" if system_dark else "浅色"))
    print("与系统相反的主题 = %s\n" % opposite)

    try:
        for label, start, pick in (
                ("A 深浅互切（起点=明确主题）", THEME_DARK, THEME_LIGHT),
                ("B **跟随系统 → 相反主题**", THEME_SYSTEM, opposite),
        ):
            preview, confirm, is_dark = drive_settings(
                frame, counter, start_theme=start, picked_theme=pick)
            want_dark = (pick == THEME_DARK)
            print("── %s ──" % label)
            print("   起点=%s  选=%s" % (start, pick))
            print("   预览阶段 _retheme = %s" % preview)
            print("   **确定阶段 _retheme = %s**" % confirm)
            print("   结束后 主题 = %s（期望 %s）"
                  % ("深色" if is_dark else "浅色",
                     "深色" if want_dark else "浅色"))

            tag = label[0]
            check("1 [%s] 点主题按钮时预览生效（_retheme ≥ 1）" % tag,
                  (preview or 0) >= 1, "预览 = %s" % preview)
            check("2 [%s] **确定阶段不该再重上色**（_retheme = 0）" % tag,
                  confirm == 0,
                  "确定阶段 _retheme = %s 次" % confirm)
            check("3 [%s] 确定后停在**用户选的主题**上" % tag,
                  is_dark == want_dark,
                  "结束时 %s，期望 %s"
                  % ("深色" if is_dark else "浅色",
                     "深色" if want_dark else "浅色"))
    finally:
        counter.stop()
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(5)

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print("  %s %s" % ("OK  " if ok else "FAIL", name))
    if detail:
        print("       %s" % detail)
print()
print("  合计 %d 条：%d 通过，%d 失败" % (len(results), passed, len(results) - passed))
