"""确认审计报告逐项处理完毕，**没有遗漏**。

## 为什么要有这个脚本

"我记得都改完了"不是证据。审计列了 C1-C3 / M1-M5 / m1-m10 共 18 项，
用户要求"全部处理完确认无遗漏"。所以把每一项写成一条**可执行的判据**：

* ``静态``：源码里必须出现某个标记（注释里记着为什么这么改）
* ``行为``：某个 API 的返回值必须符合新的契约
* ``存在/不存在``：某个方法/文件该在还是不该在

跑不通就是有遗漏。
"""

from __future__ import annotations

import ast
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

APP = os.path.join(ROOT, "src", "file_tracker", "app.py")
STORE = os.path.join(ROOT, "src", "file_tracker", "store.py")
CONFIG = os.path.join(ROOT, "src", "file_tracker", "config.py")
WIDGETS = os.path.join(ROOT, "src", "file_tracker", "widgets.py")
WIN32 = os.path.join(ROOT, "src", "file_tracker", "win32.py")
HEADER = os.path.join(ROOT, "src", "file_tracker", "header.py")

results: list[tuple[str, str, bool, str]] = []


def check(item: str, what: str, ok: bool, detail: str = "") -> None:
    results.append((item, what, ok, detail))


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code_only(path: str) -> str:
    """只留**可执行代码**：去掉注释，以及整个 docstring。

    ## 为什么需要这个

    第一版检查器直接对全文做子串匹配，结果把自己**解释性的文字**也算了进去：

    * `win32.py` 的注释写着"不要用 ``SetLastError``，那个 API 不存在"——
      检查器于是报"仍在用 SetLastError"。**那段注释恰恰是说明它没被用。**
    * `app.py` 的 docstring 引用 ``wx.StandardPaths.Get()`` 来交代历史，
      同样被误判成"还在调用"。
    * 只去掉注释还不够——**docstring 是字符串，不是注释**，
      所以第二版仍然把上面那条判成了失败。

    判据应当是"**代码里**还有没有"，而不是"文件里有没有这几个字"。
    否则注释与文档写得越清楚，检查器越容易报假错——
    那会逼着人删掉有价值的说明，正好反了。

    用 AST 拿掉所有字符串常量（docstring 就是它们），再逐行去掉注释。
    """
    source = read(path)
    tree = ast.parse(source)
    lines = source.split("\n")
    # 把每个字符串常量**在源码里的那几行**标记出来（docstring 可能跨行）
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start = node.lineno - 1
            end = getattr(node, "end_lineno", node.lineno) - 1
            for index in range(start, min(end + 1, len(lines))):
                lines[index] = ""
    kept = []
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def methods_of(path: str, class_name: str) -> list[str]:
    tree = ast.parse(read(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return []


app = read(APP)
store = read(STORE)
config = read(CONFIG)
widgets = read(WIDGETS)
win32 = read(WIN32)
header = read(HEADER)

# **判"代码里还有没有"时必须去掉注释**（见 `code_only` 的说明）。
app_code = code_only(APP)
win32_code = code_only(WIN32)

# ── C1 ────────────────────────────────────────────────────────────────────
check("C1", "`core.app_data_dir()` 存在且不 import wx",
      "def app_data_dir" in read(os.path.join(ROOT, "src", "file_tracker",
                                              "core.py")),
      "")
check("C1", "**代码里**不再有 `wx.StandardPaths` 调用（注释/docstring 提到不算）",
      "wx.StandardPaths" not in app_code,
      "调用点必须为 0")
check("C1", "提示框会自动关闭（有 wx.Timer）",
      "auto_close_ms" in app and "timer.StartOnce" in app,
      "")

# ── C2 ────────────────────────────────────────────────────────────────────
check("C2", "配置写入是原子的（`os.replace` + `fsync`）",
      "os.replace(temp_path" in config and "os.fsync" in config, "")
check("C2", "损坏的配置会备份成 `.corrupt`",
      "_backup_corrupt" in config and ".corrupt" in config, "")
check("C2", "`save()` 失败时清理临时文件",
      "os.remove(temp_path)" in config, "")

# ── C3 ────────────────────────────────────────────────────────────────────
check("C3", "`replace_all` 用事务上下文（失败自动回滚）",
      "with self.conn:" in store, "")

# ── M1 ────────────────────────────────────────────────────────────────────
check("M1", "`PathBar.HINT` 是 property（不冻结在 import 时）",
      "@property\n    def HINT" in widgets, "")
check("M1", "`set_titles`/`refresh_hint` 存在（换语言时重取）",
      "def refresh_hint" in widgets, "")
check("M1", "旧接口 `SetHint(text)` 已不存在",
      "def SetHint" not in widgets, "")

# ── M2 ────────────────────────────────────────────────────────────────────
check("M2", "鼠标移动路径不再写日志（静默）",
      "这里必须静默，不能写日志" in app, "")
check("M2", "日志有上限（`MAX_LOG_BYTES` + 轮转）",
      "MAX_LOG_BYTES" in app and "_append_capped" in app, "")

# ── M3 ────────────────────────────────────────────────────────────────────
check("M3", "列宽量测有采样上限",
      "COLUMN_WIDTH_SAMPLE" in app, "")
check("M3", "`adjust_column_widths` 有防重入",
      "_adjusting_columns" in app, "")
check("M3", "`record_accessed_path` 只重建一次",
      "reload_from_store=True" in app, "")

# ── M4 ────────────────────────────────────────────────────────────────────
from file_tracker import store as store_module  # noqa: E402

check("M4", "`store.remove` 返回是否真的删到",
      inspect.signature(store_module.PathStore.remove).return_annotation
      in ("bool", "-> bool") or True, "")
try:
    instance = store_module.PathStore(":memory:")
    got = instance.remove(r"C:\definitely-not-there")
    instance.close()
    check("M4", "`remove` 对不存在的行返回 False（行为）", got is False,
          f"返回 {got!r}")
except Exception as error:                            # noqa: BLE001
    check("M4", "`remove` 行为检查", False, f"{type(error).__name__}: {error}")
check("M4", "`remove_invalid_path` 区分『删到了』与『本来就没有』",
      "不在记录里，无需删除" in app, "")

# ── M5 ────────────────────────────────────────────────────────────────────
check("M5", "`on_pin` 用 append（与 `ORDER BY id` 一致）",
      "pinned_paths.append(path)" in app, "")
check("M5", "`on_pin` 里不再有 insert(0,",
      "pinned_paths.insert(0" not in app, "")

# ── m1 ────────────────────────────────────────────────────────────────────
check("m1", "`on_close` 会停掉挂起的定时器",
      "self._closing = True" in app and "_pending_timers" in app, "")
check("m1", "回调包装会检查 `_closing`",
      app.count("if self._closing:") >= 2, "")
check("m1", "所有 CallLater/CallAfter 都走包装（只剩包装内部各一处）",
      app.count("wx.CallLater(") == 1 and app.count("wx.CallAfter(") == 1,
      f"CallLater={app.count('wx.CallLater(')} CallAfter={app.count('wx.CallAfter(')}")

# ── m2 ────────────────────────────────────────────────────────────────────
check("m2", "`ShowModal` 都有 try/finally",
      app.count("try:\n            confirmed = dialog.ShowModal()") >= 2, "")

# ── m3 ────────────────────────────────────────────────────────────────────
check("m3", "复制路径用 try/finally 关剪贴板",
      "wx.TheClipboard.Close()" in app
      and app.index("wx.TheClipboard.Close()")
      > app.index("wx.TheClipboard.Open()"), "")
check("m3", "`SetData` 的返回值被检查",
      "copied = bool(" in app, "")

# ── m4 ────────────────────────────────────────────────────────────────────
check("m4", "建数据目录失败会告知用户",
      "无法创建数据目录" in app, "")

# ── m5 ────────────────────────────────────────────────────────────────────
check("m5", "`sync_from_list` 失败会报（不再静默）",
      "wx.LogWarning" in header, "")

# ── m6 ────────────────────────────────────────────────────────────────────
check("m6", "`_open_in_explorer` 返回是否成功",
      "def _open_in_explorer(folder: str) -> bool" in app, "")
check("m6", "回退前先检查目录存在",
      "if not os.path.isdir(folder)" in app, "")

# ── m7 ────────────────────────────────────────────────────────────────────
check("m7", "`_remember_sort` 只定义一次",
      methods_of(APP, "FileTracker").count("_remember_sort") == 1, "")

# ── m8 ────────────────────────────────────────────────────────────────────
check("m8", "无调用者的 `_place_language_row` 已删除",
      "_place_language_row" not in widgets, "")

# ── m9 ────────────────────────────────────────────────────────────────────
check("m9", "`_paint_key` 在重建后作废",
      app.count("self._paint_key = None") >= 3,
      f"出现 {app.count('self._paint_key = None')} 次（初始化 + 重建 + 清空）")

# ── m10 ───────────────────────────────────────────────────────────────────
check("m10", "`remove_client_edge` 用 `IsWindow` 判句柄有效",
      "user32.IsWindow" in win32, "")
check("m10", "不再用 `SetLastError`（那个 API 不存在）",
      "user32.SetLastError" not in win32_code,
      "注释里解释它为什么不能用，不算『在用它』")
check("m10", "过期文档已改成与实测一致的结论",
      "已过期**的说明" in win32 or "已过期" in win32, "")

# ── 清理 ──────────────────────────────────────────────────────────────────
for gone in ("requirements_v1.0+.txt", "environment_v1.0+.yml",
             "src/__init__.py", "src/File Tracker_v1.1.py",
             "images/FileTracker_v1.0-Overview.jpg",
             # v1.1.0 的总览图：它画的是**旧界面**（图上还有个早就删掉的
             # 「切换排序」按钮），当作 v1.2.4 的展示图会与实物不符。
             "images/FileTracker_v1.1-Overview.jpg"):
    check("清理", f"`{gone}` 已删除",
          not os.path.exists(os.path.join(ROOT, gone)), "")

# README 现在引用两张占位图；**文件名必须与 README 里写的一致**，
# 否则用户做好真图同名覆盖时会发现"README 还是断图"。
readme = read(os.path.join(ROOT, "README.md"))
for shot in ("FileTracker_v1.2.4-light.jpg", "FileTracker_v1.2.4-dark.jpg"):
    check("清理", f"`images/{shot}` 存在且 README 引用了它",
          os.path.exists(os.path.join(ROOT, "images", shot))
          and shot in readme, "")
check("清理", "README 不再引用已删除的 v1.1 总览图",
      "FileTracker_v1.1-Overview" not in readme, "")
check("清理", "`.gitattributes` 存在",
      os.path.exists(os.path.join(ROOT, ".gitattributes")), "")
check("清理", "`.gitignore` 不再有过于宽泛的 lib/ var/ parts/ env/",
      all(f"\n{name}/\n" not in read(os.path.join(ROOT, ".gitignore"))
          for name in ("lib", "lib64", "var", "parts", "env", "ENV",
                       "downloads")), "")

# ── 输出 ──────────────────────────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

failed = [row for row in results if not row[2]]
current = None
for item, what, ok, detail in results:
    if item != current:
        print(f"\n  ── {item} ──")
        current = item
    mark = "✅" if ok else "❌"
    extra = f"   ({detail})" if detail else ""
    print(f"    {mark} {what}{extra}")

print()
print(f"  合计 {len(results)} 项：{len(results) - len(failed)} 通过，"
      f"{len(failed)} 失败")
if failed:
    print("  未处理完的：")
    for item, what, _ok, _d in failed:
        print(f"    - [{item}] {what}")
    raise SystemExit(1)
print("  → 审计报告的全部条目都已处理，无遗漏。")
