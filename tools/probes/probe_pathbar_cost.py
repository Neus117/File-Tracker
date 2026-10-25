r"""地址栏回车为什么慢：把 `on_path_submitted` 拆成四段分别计时。

## 四段（顺序就是 `on_path_submitted` 里的顺序）

| 段 | 做什么 | 可疑点 |
|---|---|---|
| ① `build_walk_plan` | 纯逻辑，规范化 + 判断存在 | 应该 <1 ms |
| ② `reveal_in_tree` | **沿路径逐级展开树** | 每级 `_populate_item` 会**列出该目录全部子项**（含文件） |
| ③ `open_folder` | `os.startfile` | **同步**：走 ShellExecute，可能阻塞在 Explorer 上 |
| ④ `record_accessed_path` | 记一次访问 + 重建列表 | 已知 6000 行约 300 ms |

## 还要量"关闭为什么变慢"

树节点数会随展开暴涨（`_populate_item` 把子项**全建出来**，
包括文件）。`Destroy()` 要逐个释放 —— 所以顺带量一下**节点数**与**销毁耗时**。

用法：

```powershell
python tools/probes/probe_pathbar_cost.py
python tools/probes/probe_pathbar_cost.py --path "C:\Windows\System32"
```
"""
from __future__ import annotations

import argparse
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

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

#: 用户截图里出现过的一条真实深路径（7 层）
DEFAULT_PATH = r"C:\Users\Neus117\AppData\Local\Low\kurogate\战双帕弥什\PhotoAlbum"


def pump(rounds: int = 20, pause: float = 0.003) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def count_nodes(frame) -> int:
    """整棵树的节点数（递归数）。"""
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--real-open", action="store_true",
                        help="真的调 os.startfile（会弹出资源管理器窗口）")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.path):
        print("路径不存在，换一个：%s" % args.path)
        return 2

    app = wx.App(redirect=False)
    lang.apply(lang.PREFERENCE_CHINESE)

    with probe_temp("pathbar") as scratch:
        db = os.path.join(scratch, "p.db")
        app_mod.default_db_path = lambda: db
        app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
        store = app_mod.PathStore(db)
        store.close()

        frame = app_mod.FileTracker()
        frame.SetSize((1200, 700))
        frame.Show()
        pump(40)

        print("目标路径: %s" % args.path)
        print("初始节点数: %d" % count_nodes(frame))
        print()

        # ── ① build_walk_plan ──
        t0 = time.perf_counter()
        plan = app_mod.build_walk_plan(args.path, frame.last_directory)
        t1 = time.perf_counter()
        print("① build_walk_plan            %8.1f ms   status=%s"
              % ((t1 - t0) * 1000, plan["status"]))

        # ── ② reveal_in_tree ──
        nodes_before = count_nodes(frame)
        t0 = time.perf_counter()
        found = frame.reveal_in_tree(plan["folder"], plan)
        t1 = time.perf_counter()
        nodes_after = count_nodes(frame)
        print("② reveal_in_tree            %8.1f ms   找到=%s  节点 %d → %d (+%d)"
              % ((t1 - t0) * 1000, found, nodes_before, nodes_after,
                 nodes_after - nodes_before))

        # ── ③ open_folder（默认用桩，避免真的弹窗）──
        if args.real_open:
            t0 = time.perf_counter()
            ok = frame.open_folder(plan["folder"])
            t1 = time.perf_counter()
            print("③ open_folder（真）        %8.1f ms   成功=%s"
                  % ((t1 - t0) * 1000, ok))
            pump(10)
        else:
            print("③ open_folder              （已跳过：加 --real-open 才真的打开）")

        # ── ④ record_accessed_path ──
        t0 = time.perf_counter()
        frame.record_accessed_path(plan["folder"])
        t1 = time.perf_counter()
        print("④ record_accessed_path      %8.1f ms   列表 %d 行"
              % ((t1 - t0) * 1000, frame.list_ctrl.GetItemCount()))

        # ── 再跑一遍（此时树已展开、记录已存在）──
        print()
        t0 = time.perf_counter()
        frame.reveal_in_tree(plan["folder"], plan)
        t1 = time.perf_counter()
        print("②' reveal_in_tree（第二次）  %8.1f ms" % ((t1 - t0) * 1000))

        # ── 关闭耗时 ──
        print()
        nodes = count_nodes(frame)
        t0 = time.perf_counter()
        try:
            frame.store.close()
        except Exception:
            pass
        frame.Destroy()
        pump(10)
        t1 = time.perf_counter()
        print("关闭（节点数 %d）           %8.1f ms" % (nodes, (t1 - t0) * 1000))

    print()
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
