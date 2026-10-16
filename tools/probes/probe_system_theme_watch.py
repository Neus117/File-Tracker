r"""验：设置对话框期间挂起"系统主题监视"之后，**真正的系统主题变化不会丢**。

## 为什么必须验这个

用户报的"从跟随系统出发、点确定会闪一下"，修法是**设置对话框打开期间挂起**
`on_activate` 里那段"重读系统主题"（见 `app.on_activate`）。

但那引入一个新风险：**挂起期间系统主题真的被改了，会不会就丢了？**
（用户在设置里切换到系统设置改了主题再回来，是真实可达的。）

⇒ 本探针把"读系统主题"替换成**可注入的假值**（`theme_from_system`），
不依赖本机真实主题，然后验三条：

| # | 判据 |
|---|---|
| 1 | 挂起期间系统主题变了：**挂起时不改界面**（否则又会闪） |
| 2 | 关闭设置后**补上**那次变化（跟随系统时） |
| 3 | 用户最终选了**明确主题**时 —— 系统主题变化**不该**影响界面 |
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
from file_tracker import lang
from file_tracker.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM, Theme

app = wx.App(redirect=False)
lang.apply(lang.PREFERENCE_CHINESE)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def pump(rounds=12, pause=0.004):
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


class FakeSystem:
    """把 `app.theme_from_system` 换成可注入的假值。"""

    def __init__(self, frame, dark: bool):
        self.frame = frame
        self.dark = dark
        self.original = app_mod.theme_from_system
        app_mod.theme_from_system = lambda: (
            Theme.dark() if self.dark else Theme.light())

    def set(self, dark: bool):
        self.dark = dark

    def stop(self):
        app_mod.theme_from_system = self.original


with probe_temp("probe-systheme") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    for i in range(20):
        seed.record_access(os.path.join(scratch, "dir-%03d" % i))
    seed.close()

    fake = FakeSystem(None, dark=False)
    frame = app_mod.FileTracker()
    frame.open_folder = open_in_explorer_stub()
    fake.frame = frame
    frame.Show()
    frame.Maximize()
    pump(50)

    rethemes = []
    original_retheme = frame._retheme
    frame._retheme = lambda: (rethemes.append(frame.theme.is_dark),
                              original_retheme())[1]

    try:
        # ══ 场景 1：跟随系统 + 挂起期间系统主题变了 ══════════════
        frame.config.set_theme(THEME_SYSTEM)
        fake.set(False)
        frame.theme = app_mod.theme_from_preference(THEME_SYSTEM)
        original_retheme()
        pump()
        print("【场景1】配置=跟随系统  起点=浅色")

        frame._suspend_system_theme_watch()
        rethemes.clear()
        # 挂起期间：用户去系统里把主题改成深色
        fake.set(True)
        frame.on_activate(wx.PyEvent())
        pump()
        print("   挂起期间系统主题改成深色 → _retheme = %d 次，界面 = %s"
              % (len(rethemes), "深色" if frame.theme.is_dark else "浅色"))
        check("1 挂起期间**不改界面**（否则又会闪）",
              len(rethemes) == 0 and not frame.theme.is_dark,
              "_retheme = %d 次，界面 = %s"
              % (len(rethemes), "深色" if frame.theme.is_dark else "浅色"))

        rethemes.clear()
        frame._resume_system_theme_watch()      # = 设置关闭
        pump()
        print("   关闭设置后 → _retheme = %d 次，界面 = %s"
              % (len(rethemes), "深色" if frame.theme.is_dark else "浅色"))
        check("2 关闭设置后**补上**那次系统主题变化",
              frame.theme.is_dark,
              "界面 = %s（期望深色）" % ("深色" if frame.theme.is_dark else "浅色"))

        # ══ 场景 2：用户最终选了明确主题 ⇒ 系统变化不该影响界面 ══
        frame.config.set_theme(THEME_SYSTEM)
        fake.set(False)
        frame.theme = app_mod.theme_from_preference(THEME_SYSTEM)
        original_retheme()
        pump()
        frame._suspend_system_theme_watch()
        fake.set(True)                          # 系统改成深色
        frame.config.set_theme(THEME_LIGHT)     # 但用户明确选了浅色
        rethemes.clear()
        frame._resume_system_theme_watch()
        pump()
        print("\n【场景2】挂起期间系统→深色，但用户最终选**浅色**")
        print("   关闭设置后 → _retheme = %d 次，界面 = %s"
              % (len(rethemes), "深色" if frame.theme.is_dark else "浅色"))
        check("3 明确选了浅色 ⇒ 系统主题变化**不该**改界面",
              len(rethemes) == 0 and not frame.theme.is_dark,
              "_retheme = %d 次，界面 = %s"
              % (len(rethemes), "深色" if frame.theme.is_dark else "浅色"))
    finally:
        frame._retheme = original_retheme
        fake.stop()
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
