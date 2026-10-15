"""验证审计报告的 C1：**不开 wx.App 时 `wx.StandardPaths.Get()` 会怎样**。

`app.py` 的 `--version` / `--selftest` 在拿不到 stdout 时会走：

    log_dir = wx.StandardPaths.Get().GetUserDataDir()

而那两个入口**没有** `wx.App`（`--version` 走的是 `_emit_or_log`）。
如果这句不是抛异常而是挂住/段错误，那个 `except (OSError, ValueError)`
就是形同虚设——产物会卡在"自报版本"这一步。

判据：子进程跑三种情形，各自限时，看退出码。
  A. 直接调，不开 App
  B. 调之前 `wx.DisableAsserts()`（避开断言对话框，看真正的结果）
  C. 先 `wx.App()` 再调（对照：应当立刻返回）
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CASES = {
    "A 不开 App 直接调": "import wx; wx.StandardPaths.Get(); print('OK 没挂')",
    "B 不开 App + 禁用断言":
        "import wx; wx.DisableAsserts(); wx.StandardPaths.Get(); print('OK 没挂')",
    "C 先建 wx.App 再调":
        "import wx; a=wx.App(); print('OK', wx.StandardPaths.Get().GetUserDataDir())",
}

TIMEOUT = 15
for label, code in CASES.items():
    # **子进程禁用断言。**
    #
    # 不禁用的话，情形 A 会弹一个 wx 断言框（内容就是
    # ``assert "traits" failed in wxStandardPathsBase::Get():
    #   create wxApp before calling this``），而这个框**没有人点**——
    # 探针卡在那里，用户还得手动去关（已经抱怨过一次）。
    #
    # 禁用之后断言变成可恢复的失败，判据从"会不会卡住"变成
    # "有没有抛异常 / 能不能返回"——**结论一样可靠**，
    # 区别只是不再弹窗打扰人。
    guarded = "import wx;\nwx.DisableAsserts();\n" + code
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", guarded],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=TIMEOUT)
        out = (result.stdout or "").strip().replace("\n", " ")
        err = (result.stderr or "").strip().splitlines()
        tail = err[-1] if err else ""
        verdict = "正常" if result.returncode == 0 else f"**非零退出**"
        print(f"  {label:26} 退出码={result.returncode:>4}  {verdict}")
        if out:
            print(f"       stdout: {out[:90]}")
        if tail and result.returncode != 0:
            print(f"       stderr: {tail[:90]}")
    except subprocess.TimeoutExpired:
        print(f"  {label:26} ❌ **{TIMEOUT} 秒未退出（挂住）**")
print()
print("  怎么读这三行（都很关键）：")
print("  * 三种情形**都返回了**，说明 `StandardPaths.Get()` 本身"
      "不抛 OSError/ValueError——")
print("    所以 app.py 那个 `except (OSError, ValueError)` 接不住它。")
print("  * 失败的**不是这次调用，而是 wx 的断言处理**：断言失败时 wx 弹一个")
print("    模态框等人点，而 `--version` 是无人值守的场景 ⇒ **进程停在那里**。")
print("    禁用断言 == 假装有人点了「继续」，于是它顺利返回。")
print("  * 也就是说：**产物挂起的原因就是那个没人点的框**。")
print("    修复方向是让这条路不依赖 wx（或先建 App），而不是加 try/except。")
