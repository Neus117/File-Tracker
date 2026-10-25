r"""地址栏回车：**每一处建节点的地方**分别是谁、建了多少、花了多久。

## 为什么还要一个新探针

`probe_pathbar_cost.py` 只把 `on_path_submitted` 切成四段，它告诉了我
"`reveal_in_tree` 慢"，但**看不见里面有几个建节点的入口**。

交接文档留了一条没查清的线索：第 4 版"增量填充"能跑、但节点数仍 +5793，
说明 **`reveal_in_tree` 里除了 `expand_to` 还有第二处全量填充**
（怀疑是末尾那句 `tree.Expand(item)` —— 它**投递**事件，真正干活
发生在之后的事件循环里，所以直接计时的探针量不到它）。

本探针直接在 `DirectoryTree._populate_item` 上装一个计数器：
**谁调的、哪个目录、建了几个子项（其中几个文件）、各花多久**，
并且**在 `on_path_submitted` 返回之后继续泵事件**，
把投递式展开算在"第二阶段"里。同时报节点数增量与关闭耗时。

输出**全 ASCII**：Windows 控制台用 GBK，中文会变成乱码，
而本探针的结论就是那些数字。

```powershell
python tools\probes\probe_pathbar_populate.py
python tools\probes\probe_pathbar_populate.py --path "C:\Windows\System32\drivers\etc"
```
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
import file_tracker.dir_tree as dir_tree_mod
from file_tracker import lang

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

DEFAULT_PATH = r"C:\Windows\System32\drivers\etc"
#: 第二条深路径（祖先里也有大目录 —— 用来看"连续导航会不会越用越慢"）
USER_PATH = r"C:\Windows\System32\WindowsPowerShell\v1.0"

#: 收集到的 `_populate_item` 调用
CALLS: list[dict] = []

#: 接住的 `wx.App`（不能让它被回收，见 _probe_guard.harden_wx 的说明）
_APP = None


def pump(rounds: int = 20, pause: float = 0.003) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def count_nodes(frame) -> int:
    tree = frame.dir_ctrl.GetTreeCtrl()
    total = 0

    def walk(item):
        nonlocal total
        child, cookie = tree.GetFirstChild(item)
        while child.IsOk():
            total += 1
            walk(child)
            child, cookie = tree.GetNextChild(item, cookie)

    for top in frame.dir_ctrl.iter_top():
        total += 1
        walk(top)
    return total


def child_count(tree, item) -> int:
    n = 0
    child, cookie = tree.GetFirstChild(item)
    while child.IsOk():
        n += 1
        child, cookie = tree.GetNextChild(item, cookie)
    return n


def classify(path: str) -> tuple[int, int]:
    r"""(子项数, 其中文件数) —— 直接读文件系统，与被测代码无关。

    盘符根（``C:\``）的扫描代价很高，跳过，返回 ``(-1, -1)``。
    """
    if not path or len(path) <= 3:
        return (-1, -1)
    total = files = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                total += 1
                try:
                    if not entry.is_dir():
                        files += 1
                except OSError:
                    pass
    except OSError:
        return (-1, -1)
    return (total, files)


def install_counter() -> None:
    original = dir_tree_mod.DirectoryTree._populate_item

    def wrapper(self, item, **kwargs):
        try:
            cached = item in self._populated
        except Exception:
            cached = False
        try:
            where = self.path_of_node(item)
        except Exception:
            where = repr(item)
        # 调用方：跳过 wrapper 自己那一层
        stack = traceback.extract_stack(limit=4)
        caller = "?"
        for frame in reversed(stack[:-1]):
            if frame.name != "wrapper":
                caller = "%s:%d:%s" % (os.path.basename(frame.filename),
                                       frame.lineno, frame.name)
                break
        t0 = time.perf_counter()
        original(self, item, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        CALLS.append({
            "caller": caller,
            "path": where,
            "cached": cached,
            "files": kwargs.get("files", "?"),
            "children": child_count(self, item) if not cached else 0,
            "ms": elapsed,
        })

    dir_tree_mod.DirectoryTree._populate_item = wrapper


def report(title: str, since: int) -> int:
    rows = CALLS[since:]
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)
    if not rows:
        print("  (no _populate_item calls)")
        return len(CALLS)
    total_nodes = total_ms = 0
    for row in rows:
        kind = "cached-skip" if row["cached"] else "POPULATE"
        scan_total, scan_files = classify(row["path"])
        print("  %-11s %7.1f ms  nodes=%-5d  %-28s  by %s"
              % (kind, row["ms"], row["children"], row["path"], row["caller"]))
        if not row["cached"]:
            print("              files=%-5s scandir: total=%-5d files=%-5d dirs=%d"
                  % (row["files"], scan_total, scan_files,
                     max(scan_total - scan_files, 0)))
            total_nodes += row["children"]
            total_ms += row["ms"]
    print("  --- %d calls, populated nodes=%d, populate time=%.1f ms"
          % (len(rows), total_nodes, total_ms))
    return len(CALLS)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", action="append", default=None,
                        help="可重复；不给就用默认的两条深路径")
    parser.add_argument("--real-open", action="store_true")
    args = parser.parse_args(argv)

    targets = args.path or [DEFAULT_PATH, USER_PATH, DEFAULT_PATH]
    for target in targets:
        if not os.path.isdir(target):
            print("path not found: %s" % target)
            return 2

    # 必须接住：`wx.App()` 的返回值一旦被回收，后面建窗口就是 PyNoAppError
    global _APP
    _APP = wx.App(redirect=False)
    lang.apply(lang.PREFERENCE_CHINESE)

    with probe_temp("pathbar-pop") as scratch:
        db = os.path.join(scratch, "p.db")
        app_mod.default_db_path = lambda: db
        app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
        store = app_mod.PathStore(db)
        store.close()

        frame = app_mod.FileTracker()
        frame.SetSize((1200, 700))
        frame.Show()
        pump(40)

        if not args.real_open:
            frame.open_folder = open_in_explorer_stub()

        install_counter()

        print("nodes at startup: %d" % count_nodes(frame))

        for round_index, target in enumerate(targets, 1):
            print()
            print("#" * 78)
            print("# ROUND %d   %s" % (round_index, target))
            print("#" * 78)
            mark = len(CALLS)
            nodes_before = count_nodes(frame)
            t0 = time.perf_counter()
            frame.on_path_submitted(target)
            t1 = time.perf_counter()
            nodes_mid = count_nodes(frame)
            stage1_ms = (t1 - t0) * 1000

            t2 = time.perf_counter()
            pump(20)
            t3 = time.perf_counter()
            nodes_after = count_nodes(frame)

            mark = report("populate calls", mark)
            print("  submit wall=%.1f ms  yield wall=%.1f ms"
                  % (stage1_ms, (t3 - t2) * 1000))
            print("  nodes %d -> %d (+%d)   total now %d"
                  % (nodes_before, nodes_after, nodes_after - nodes_before,
                     nodes_after))

        # ---- close ----
        print()
        nodes = count_nodes(frame)
        try:
            frame.store.close()
        except Exception:
            pass
        t0 = time.perf_counter()
        frame.Destroy()
        pump(10)
        t1 = time.perf_counter()
        print("close with %d nodes: %.1f ms" % (nodes, (t1 - t0) * 1000))

    print()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
