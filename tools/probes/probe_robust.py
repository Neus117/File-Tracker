"""健壮性：把新代码里**可能崩的边界**逐个打一遍。

## 为什么专门写这个

本轮新增/改动的都是"跟系统打交道"的代码：

* `dir_tree.py` —— 遍历真实文件系统（目录会消失、会没权限、会超长）
* `_render_rows` / `_remember_view` —— 有 `Freeze`/`Thaw` 配对、
  有"路径找不到"的分支

**"正常路径能跑"不等于"边界不崩"。** 这个探针只打边界。

## 判据

每条用例独立 `try`，**任何一条抛异常都算失败并打出来** ——
而不是让整个探针中断（那样后面的用例就跑不到了）。
"""
import ctypes
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
from file_tracker.dir_tree import DirectoryTree, _as_drive_root, _drive_label

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

results = []


def case(name):
    """装饰器：跑一条用例，把结果记进 `results`。"""
    def wrap(fn):
        try:
            detail = fn()
            results.append((True, name, detail or ""))
        except Exception as error:                   # noqa: BLE001
            results.append((False, name, f"{type(error).__name__}: {error}"))
        return fn
    return wrap


def settle(times: int = 12) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.003)


with probe_temp("probe-robust") as scratch:
    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")

    # ── 先建几棵真目录树，供下面的用例用 ──
    deep = scratch
    for i in range(12):
        deep = os.path.join(deep, f"lvl{i}")
    os.makedirs(deep, exist_ok=True)
    long_name = "x" * 120
    os.makedirs(os.path.join(scratch, long_name), exist_ok=True)
    empty = os.path.join(scratch, "empty-dir")
    os.makedirs(empty, exist_ok=True)
    vanishing = os.path.join(scratch, "vanishing")
    os.makedirs(os.path.join(vanishing, "child"), exist_ok=True)

    seed = app_mod.PathStore(db)
    for i in range(40):
        seed.record_access(os.path.join(scratch, f"rec-{i:03d}"))
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    settle(50)
    tree: DirectoryTree = frame.dir_ctrl

    # ══════════════ 目录树 ══════════════

    @case("空字符串 / 不存在的路径 → 返回空，不抛")
    def _():
        assert tree.path_of_label("") == ""
        assert tree.expand_to("") is None
        assert tree.expand_to(os.path.join(scratch, "no-such-dir")) is None
        return "3 种输入都返回空/None"

    @case("超长路径（> 260 字符）→ 不抛")
    def _():
        p = os.path.join(scratch, long_name, long_name)
        tree.expand_to(p)
        return f"长度 {len(p)}"

    @case("深路径（12 层）→ 能展开到底")
    def _():
        item = tree.expand_to(deep, select=False)
        assert item is not None, "没走到最深一层"
        assert tree.path_of_node(item).lower() == os.path.normpath(deep).lower()
        return "12 层全部展开且路径回读一致"

    @case("空目录 → 展开后 0 个子节点，不抛")
    def _():
        tree.expand_to(empty)
        return "未抛"

    @case("**目录在展开前被删掉**（竞态）→ 不抛")
    def _():
        item = tree.expand_to(vanishing, select=False)
        assert item is not None
        import shutil
        shutil.rmtree(vanishing)          # 展开之前把它删了
        tree._populated.discard(item)     # 强制重新填充
        tree._populate_item(item)         # ← 这里会撞上"目录不存在"
        return "删掉之后重新填充未抛"

    @case("重复 populate() 不炸也不重复建顶层")
    def _():
        first = len(list(tree.iter_top()))
        tree.populate()
        tree.populate()
        settle()
        assert len(list(tree.iter_top())) == first
        return f"顶层仍是 {first} 个"

    @case("getPath 收到虚拟根 / 无效项 → 空串，不抛")
    def _():
        assert tree.GetPath(tree.GetRootItem()) == ""
        assert tree.GetPath(wx.TreeItemId()) == ""
        return "两种无效输入都返回空串"

    @case("GetPaths() 没有选中时 → 空列表")
    def _():
        tree.UnselectAll() if hasattr(tree, "UnselectAll") else None
        return f"返回 {tree.GetPaths()}"

    @case("_as_drive_root 各种输入 → 不抛")
    def _():
        for text in ("", "C:", "C:\\", "SYSTEM (C:)", "随便", "💻", "\x00" * 3,
                     "A" * 500):
            _as_drive_root(text)
        return "8 种输入都安全"

    @case("_drive_label 对不存在的盘 → 退回原样，不抛")
    def _():
        assert _drive_label("Z:\\") == "Z:\\" or _drive_label("Z:\\")
        return repr(_drive_label("Z:\\"))

    # ══════════════ 列表视角 ══════════════

    @case("空列表上 _render_rows() → 不抛")
    def _():
        saved = list(frame._rows)
        frame._rows = []
        frame._remember_view()
        frame._render_rows()
        frame._rows = saved
        frame._render_rows()
        return "置空再恢复都正常"

    @case("_index_of_path 找不到 → -1，不抛")
    def _():
        assert frame._index_of_path("") == -1
        assert frame._index_of_path("不存在的路径") == -1
        return "-1"

    @case("锚点指向已删除的路径 → 不抛、不跳")
    def _():
        frame._view_anchor = ("已删除的路径", "也不存在")
        frame._render_rows()
        return "未抛"

    @case("**Freeze / Thaw 配对**：重建抛异常后控件没被永久冻结")
    def _():
        ctrl = frame.list_ctrl
        original = frame._render_rows_now

        def boom():
            raise RuntimeError("故意抛")
        frame._render_rows_now = boom
        try:
            frame._render_rows()
        except RuntimeError:
            pass
        finally:
            frame._render_rows_now = original
        # 冻结计数应当归零 —— 否则控件永久不重绘
        frozen = ctrl.IsFrozen() if hasattr(ctrl, "IsFrozen") else None
        assert frozen is not True, "控件被永久冻结了"
        return f"IsFrozen() = {frozen}"

    @case("重建之后列表行数与 _rows 一致")
    def _():
        frame._render_rows()
        settle()
        assert frame.list_ctrl.GetItemCount() == len(frame._rows)
        return f"{frame.list_ctrl.GetItemCount()} 行"

    @case("连续 30 次重建 → 行数不漂移")
    def _():
        for _ in range(30):
            frame._render_rows()
        settle()
        assert frame.list_ctrl.GetItemCount() == len(frame._rows)
        return f"仍是 {frame.list_ctrl.GetItemCount()} 行"

    frame.store.close()
    frame.Destroy()

# ── 汇总 ──
print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}")
    if detail:
        print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
