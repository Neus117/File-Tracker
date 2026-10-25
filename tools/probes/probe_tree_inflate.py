r"""成本曲线：树里**已经有多少节点**时，一次导航和一次关闭各要多久。

## 为什么要单独量这条曲线

用户 2026-10-25："用了几小时之后，地址栏回车要卡六七秒才打开，
关闭要等十几秒。" 他的怀疑是**树一直在展开、从不收回**。

`probe_tree_accumulate.py` 说明"正常导航几十次"只会到 ~1200 节点（祖先共享，
走过一次就缓存了）。所以问题只可能出在**节点数真的很大**的时候。
本探针把树人为撑到指定节点数，然后量：

* 撑大本身要多久（顺便给出每个节点的成本）
* **在这么大的树上**再导航一次要多久
* 关闭要多久

```powershell
python tools\probes\probe_tree_inflate.py --target-nodes 2000
python tools\probes\probe_tree_inflate.py --target-nodes 10000
python tools\probes\probe_tree_inflate.py --target-nodes 30000
```

⚠️ `--target-nodes 30000` 会真的建三万个节点并逐个销毁，**关闭那一步可能十几秒**。
这是被测对象本身慢，不是探针卡住；仍受上层 120 秒硬超时保护。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "src"))

import wx

from _probe_guard import harden_wx

harden_wx()
from _probe_temp import open_in_explorer_stub, probe_temp

import file_tracker.app as app_mod
from file_tracker import lang

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

_APP = None

#: 用来撑大树的真实目录（都是"有很多子目录"的那种）
INFLATE_ROOTS = [
    r"C:\Windows\System32",
    r"C:\Windows\WinSxS",
    r"C:\Windows\Microsoft.NET\assembly",
    r"C:\Program Files",
    r"C:\ProgramData",
    r"C:\Users\Neus117\AppData\Local",
]


def pump(rounds: int = 5, pause: float = 0.002) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def node_count(tree) -> int:
    if hasattr(tree, "GetCount"):
        return tree.GetCount()
    total = 0
    stack = []
    root = tree.GetRootItem()
    child, cookie = tree.GetFirstChild(root)
    while child.IsOk():
        stack.append(child)
        child, cookie = tree.GetNextChild(root, cookie)
    while stack:
        node = stack.pop()
        total += 1
        child, cookie = tree.GetFirstChild(node)
        while child.IsOk():
            stack.append(child)
            child, cookie = tree.GetNextChild(node, cookie)
    return total


def inflate(tree, target: int) -> int:
    """把树撑到至少 `target` 个节点（按目录逐层展开，全量填充）。"""
    queue = list(INFLATE_ROOTS)
    seen = 0
    while queue and node_count(tree) < target:
        path = queue.pop(0)
        item = tree.expand_to(path, select=False)
        if item is not None:
            tree._populate_item(item, files=True)   # 这一棵全量
            seen += 1
        # 把这个目录下的子目录排进队列（继续往下撑）
        try:
            with os.scandir(path) as entries:
                added = 0
                for entry in entries:
                    try:
                        if entry.is_dir() and added < 40:
                            queue.append(os.path.join(path, entry.name))
                            added += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return seen


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-nodes", type=int, default=10000)
    args = parser.parse_args(argv)

    global _APP
    _APP = wx.App(redirect=False)
    lang.apply(lang.PREFERENCE_CHINESE)

    with probe_temp("inflate") as scratch:
        app_mod.default_db_path = lambda: os.path.join(scratch, "p.db")
        app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
        store = app_mod.PathStore(app_mod.default_db_path())
        store.close()

        frame = app_mod.FileTracker()
        frame.SetSize((1300, 800))
        frame.Show()
        pump(30)
        frame.open_folder = open_in_explorer_stub()
        tree = frame.dir_ctrl.GetTreeCtrl()

        print("target nodes: %d   start nodes: %d" % (args.target_nodes,
                                                      node_count(tree)))
        t0 = time.perf_counter()
        touched = inflate(tree, args.target_nodes)
        build_ms = (time.perf_counter() - t0) * 1000
        pump(10)
        nodes = node_count(tree)
        print("inflated to %d nodes via %d directories in %.0f ms  (%.0f us/node)"
              % (nodes, touched, build_ms, build_ms * 1000 / max(nodes, 1)))

        # 在这么大的树上再做一次正常导航（走用户真实的路）
        target = os.path.join(scratch, "navigate-target")
        os.makedirs(target, exist_ok=True)
        t0 = time.perf_counter()
        frame.on_path_submitted(target)
        submit_ms = (time.perf_counter() - t0) * 1000
        print("one normal submit (reveal + open + record) on that tree: %.1f ms"
              % submit_ms)

        # 再来一次"穿过大目录"的导航（模拟用户遇到的最坏情况）
        probe_path = r"C:\Windows\System32\drivers\etc"
        if os.path.isdir(probe_path):
            t0 = time.perf_counter()
            frame.on_path_submitted(probe_path)
            print("submit through a known deep path: %.1f ms"
                  % ((time.perf_counter() - t0) * 1000))

        nodes = node_count(tree)
        try:
            frame.store.close()
        except Exception:
            pass
        t0 = time.perf_counter()
        frame.Destroy()
        pump(5)
        print("close with %d nodes: %.1f ms"
              % (nodes, (time.perf_counter() - t0) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
