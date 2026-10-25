r"""长会话复现：**开着用几小时之后**，导航为什么变成几秒、关闭为什么变成十几秒。

## 用户 2026-10-25 的怀疑（这就是要被证伪或证实的东西）

> "我使用这个程序的时候，它已经在我的电脑上运行了几个小时，一直开着没有关过……
>  每一次打开的目录在导航窗格里全部都是展开的状态……是不是随着运行时间变长、
>  使用次数变多，左边导航窗格不停地在展开、不停地在叠加，原来展开的目录没有收回去，
>  才导致了……打开时长达几秒，最后关闭时甚至长达十几秒的性能异常？"

## 这份探针量什么

按顺序导航到几十条**真实存在**的深路径（自动从几个根目录里采），每次量：

* `reveal_in_tree`（树）+ `record_accessed_path`（列表）**分开计时**
* 累计树节点数、其中**处于展开状态**的节点数、**可见行数**
* 关闭耗时

`--seed-rows N` 可以先把数据库塞 N 条记录 —— 用来分离"列表重建"的贡献
（README 记过：6000 行一次重排约 0.63 秒）。

输出全 ASCII。

```powershell
python tools\probes\probe_tree_accumulate.py
python tools\probes\probe_tree_accumulate.py --rounds 80 --seed-rows 6000
```
"""
from __future__ import annotations

import argparse
import ctypes
import os
import random
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

ROOTS = [r"C:\Windows", r"C:\Program Files", r"C:\ProgramData",
         r"C:\Users\Neus117\AppData", r"C:\Windows\WinSxS",
         r"C:\Windows\System32\DriverStore"]


def pump(rounds: int = 10, pause: float = 0.005) -> None:
    for _ in range(rounds):
        wx.YieldIfNeeded()
        time.sleep(pause)


def harvest(count: int, min_depth: int = 3, max_depth: int = 5) -> list[str]:
    """从几个根目录里采一批**真实存在**的目录（深度 3~5，带长路径优先）。"""
    found: list[str] = []
    for root in ROOTS:
        for current, dirs, _files in os.walk(root):
            depth = current[len(root):].count(os.sep)
            if depth < min_depth:
                dirs[:] = dirs[:20]          # 别把整台机器走完
                continue
            if depth > max_depth:
                dirs[:] = []
                continue
            try:
                if len(os.listdir(current)) > 0:
                    found.append(current)
            except OSError:
                pass
            if len(found) >= count * 3:
                break
        if len(found) >= count * 3:
            break
    random.shuffle(found)
    # 深路径优先：越深越能暴露"沿路径展开"的成本
    found.sort(key=lambda p: p.count(os.sep), reverse=True)
    return found[:count]


def count_nodes(tree) -> int:
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=60)
    parser.add_argument("--seed-rows", type=int, default=0,
                        help="先塞这么多条记录，模拟用了一段时间的数据库")
    parser.add_argument("--every", type=int, default=10)
    args = parser.parse_args(argv)

    paths = harvest(args.rounds)
    if len(paths) < args.rounds:
        print("only found %d paths (asked %d)" % (len(paths), args.rounds))

    global _APP
    _APP = wx.App(redirect=False)
    lang.apply(lang.PREFERENCE_CHINESE)

    with probe_temp("accumulate") as scratch:
        db = os.path.join(scratch, "p.db")
        app_mod.default_db_path = lambda: db
        app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
        store = app_mod.PathStore(db)
        if args.seed_rows:
            for index in range(args.seed_rows):
                store.record_access(os.path.join(
                    scratch, "seed", "rec-%05d" % index))
            print("seeded %d rows" % args.seed_rows)
        else:
            store.close()

        frame = app_mod.FileTracker()
        frame.SetSize((1300, 800))
        frame.Show()
        pump(40)
        frame.open_folder = open_in_explorer_stub()
        if args.seed_rows:
            frame.reload_rows() if hasattr(frame, "reload_rows") else None

        tree = frame.dir_ctrl.GetTreeCtrl()
        print("start: nodes=%d rows(visible in tree)=%d"
              % (count_nodes(tree), tree.GetVisibleCount() if hasattr(
                  tree, "GetVisibleCount") else -1))
        print()
        print("%4s %8s %8s %8s %7s %6s  %s"
              % ("#", "reveal", "record", "nodes", "expand", "rows", "path"))
        total_reveal = total_record = 0.0
        for index, path in enumerate(paths, 1):
            plan = app_mod.build_walk_plan(path, frame.last_directory)
            t0 = time.perf_counter()
            frame.reveal_in_tree(plan["folder"], plan)
            t1 = time.perf_counter()
            frame.record_accessed_path(path)
            t2 = time.perf_counter()
            reveal_ms = (t1 - t0) * 1000
            record_ms = (t2 - t1) * 1000
            total_reveal += reveal_ms
            total_record += record_ms
            if index % args.every == 0 or index == len(paths):
                print("%4d %7.1f %8.1f %8d %7s %6d  %s"
                      % (index, reveal_ms, record_ms, count_nodes(tree),
                         "-", tree.GetVisibleCount()
                         if hasattr(tree, "GetVisibleCount") else -1,
                         path[-52:]))

        print()
        print("totals: reveal %.0f ms, record %.0f ms over %d navigations"
              % (total_reveal, total_record, len(paths)))
        nodes = count_nodes(tree)
        print("nodes now: %d   visible rows: %d"
              % (nodes, tree.GetVisibleCount()
                 if hasattr(tree, "GetVisibleCount") else -1))

        # 最后一击：再导航一次，看"已经很大"的树上单次成本
        t0 = time.perf_counter()
        frame.reveal_in_tree(app_mod.build_walk_plan(
            paths[0], frame.last_directory)["folder"])
        print("one more reveal on the big tree: %.1f ms"
              % ((time.perf_counter() - t0) * 1000))

        try:
            frame.store.close()
        except Exception:
            pass
        t0 = time.perf_counter()
        frame.Destroy()
        pump(10)
        print("close with %d nodes: %.1f ms"
              % (nodes, (time.perf_counter() - t0) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
