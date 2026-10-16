"""验两个兜底：**文件开关**能不能开诊断、**退出兜底**能不能保住报告。

## 为什么必须验这两条（2026-10-17 实测）

用户按说明设了 `$env:FT_DEBUG_PAINT = "1"` 再跑 `run.ps1`，
`[PAINT]` **一行都没出来**；同一个 PowerShell 里查环境变量却打印 `None` ——
**那个 `python` 不是 `run.ps1` 用的解释器，变量没进到被测进程。**

⇒ 教训：**不能让"开诊断"依赖某一条特定启动路径。** 所以补了两条兜底：

| 兜底 | 解决什么 |
|---|---|
| **文件开关** `enable-paint-trace` | 与启动方式无关；用户还能一眼看见"现在开着没有" |
| **`atexit` 钩子** | 用户直接关控制台 / Ctrl+C 时 `on_close` **不会跑**，报告照样落盘 |

## 判据

1. 只有文件开关（无环境变量）时：判定为开、能装上、报告能出
2. **不调用 `on_close`**、让进程正常结束：报告仍然存在
3. 两个开关都关掉时：判定为关、`install()` 返回 `None`、**一行 `[PAINT]` 都不打**

⚠️ 子进程里**必须把 `data_dir` 指到临时目录** —— 否则会在用户真实的
`%APPDATA%\File Tracker\` 里留下开关文件，把诊断给他常开着了。
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src")

sys.path.insert(0, HERE)
sys.path.insert(0, SRC)
from _probe_guard import harden_wx  # noqa: E402
from _probe_temp import probe_temp  # noqa: E402

import wx  # noqa: E402

harden_wx()
from file_tracker import paint_trace  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


REPORT_NAME = "paint-trace.txt"

CHILD = textwrap.dedent('''
    import os, sys, time
    sys.path.insert(0, {here!r})
    sys.path.insert(0, {src!r})
    import wx
    from _probe_guard import harden_wx
    harden_wx()
    import file_tracker.app as app_mod
    from file_tracker import lang, paint_trace

    scratch = {scratch!r}
    # **只开文件开关**：环境变量一律清掉，模拟"变量没传进来"的那台机器
    os.environ.pop(paint_trace.ENV_FLAG, None)
    os.environ.pop(paint_trace.ENV_FOCUS_FLAG, None)
    # 临时目录当数据目录：绝不动用户真实的 %APPDATA%
    paint_trace.data_dir = lambda: scratch
    open(os.path.join(scratch, paint_trace.ENABLE_FILE_NAME), "w").close()

    app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(os.path.join(scratch, "p.db"))
    for i in range(30):
        seed.record_access(os.path.join(scratch, "m%03d" % i))
    fresh = os.path.join(scratch, "m020-new")
    os.makedirs(fresh, exist_ok=True)
    seed.close()

    app = wx.App(redirect=False)
    lang.apply(lang.PREFERENCE_CHINESE)
    frame = app_mod.FileTracker()
    frame.open_folder = lambda path: None
    frame.Show()
    frame.Maximize()
    for _ in range(60):
        wx.YieldIfNeeded(); time.sleep(0.005)

    print("CHILD enabled =", paint_trace.enabled())
    print("CHILD how     =", paint_trace.how_enabled())
    print("CHILD tracer  =", type(getattr(frame, "_paint_tracer", None)).__name__)

    ctrl = frame.list_ctrl
    mid = max(ctrl.GetItemCount() // 3, 1)
    ctrl.EnsureVisible(mid); ctrl.ScrollLines(mid - ctrl.GetTopItem())
    for i in range(ctrl.GetItemCount()):
        ctrl.Select(i, False)
    ctrl.SetItemState(mid, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                      wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
    frame.dir_ctrl.GetTreeCtrl().expand_to(fresh, select=True)
    frame._focus_pane = "tree"
    for _ in range(15):
        wx.YieldIfNeeded(); time.sleep(0.005)
    frame.on_open(None)
    for _ in range(40):
        wx.YieldIfNeeded(); time.sleep(0.005)

    # **故意不走 on_close** —— 模拟用户直接关掉控制台窗口
    try:
        frame.store.close()
    except Exception:
        pass
    print("CHILD 结束时没有调用 on_close（模拟关控制台）")
''')


def run_child(scratch: str) -> str:
    code = ("import sys; "
            f"sys.path.insert(0, {HERE!r}); "
            "from _probe_guard import harden_wx, install_excepthook; "
            "install_excepthook(); harden_wx()\n"
            + CHILD.format(here=HERE, src=SRC, scratch=scratch))
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=240, cwd=HERE)
    return (result.stdout or "") + (result.stderr or "")


with probe_temp("probe-file-switch") as scratch:
    output = run_child(scratch)
    print(output)

    report = os.path.join(scratch, REPORT_NAME)
    check("① 文件开关（无环境变量）能开诊断",
          "CHILD enabled = True" in output,
          next((l for l in output.splitlines() if "enabled" in l), ""))
    check("② 文件开关下记录器装上了",
          "CHILD tracer  = PaintTracer" in output,
          next((l for l in output.splitlines() if "CHILD tracer" in l), ""))
    check("③ **没走 on_close**，报告仍由退出兜底落盘",
          os.path.exists(report), f"{report} 存在 = {os.path.exists(report)}")

    if os.path.exists(report):
        with open(report, encoding="utf-8") as handle:
            text = handle.read()
        print("\n── 报告头部 ──")
        for line in text.splitlines()[:11]:
            print("   " + line)
        print("\n── 一句话结论 ──")
        for line in text.splitlines()[-2:]:
            print("   " + line)
        check("④ 报告写明是**哪个开关**打开的", "文件开关" in text, "")
        check("⑤ 报告自带「一句话结论」", "一句话结论" in text, "")
        check("⑥ 结论指向真实调用者（不是 tracer 自己）",
              "paint_trace.py" not in text.split("一句话结论")[-1],
              text.strip().splitlines()[-1].strip()[:110])

    # ── 两个开关都关：必须完全安静 ───────────────────────────────
    quiet_code = textwrap.dedent(f'''
        import os, sys
        sys.path.insert(0, {SRC!r})
        from file_tracker import paint_trace
        os.environ.pop(paint_trace.ENV_FLAG, None)
        paint_trace.data_dir = lambda: {os.path.join(scratch, "nowhere")!r}
        print("ENABLED=", paint_trace.enabled())
        print("INSTALL=", paint_trace.install(None))
    ''')
    quiet = subprocess.run([sys.executable, "-X", "utf8", "-c", quiet_code],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, cwd=HERE)
    quiet_out = (quiet.stdout or "") + (quiet.stderr or "")
    check("⑦ 两个开关都关时：判定为关、不装、**一行都不打**",
          "ENABLED= False" in quiet_out and "INSTALL= None" in quiet_out
          and "[PAINT]" not in quiet_out,
          quiet_out.strip().replace("\n", " | "))

    # ── 残留检查：不许碰用户真实的 %APPDATA% ─────────────────────
    real_switch = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                               "File Tracker", paint_trace.ENABLE_FILE_NAME)
    check("⑧ 没有在用户真实的应用数据目录里留下开关文件",
          not os.path.exists(real_switch), real_switch)

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    if detail:
        print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
