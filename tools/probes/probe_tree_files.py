"""端到端验：树里有没有文件、文件能不能点开、选中文件记的是不是父目录。

## 用户要的三件事

1. **导航树要显示文件**（"现在它只展示文件夹，不展示文件。这样用户看不到
   文件夹下有什么东西，会很困惑。"）
2. **(a) 点到文件也能打开，并定位到它的父级目录**
3. **(b) 选中文件时，记录的是它的父级文件夹**

## 判据

* 树的一个节点展开后，**子节点里既有目录也有文件**
* **文件没有展开箭头**（加占位会让它显示一个点不开的箭头）
* **目录排在文件前面**（与资源管理器一致）
* `open_targets()` 在树选中文件时返回**父目录**
* 真的调一次 `on_dir_item_activated`，看它**打开了哪个目录、记了哪条**
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

app = wx.App(redirect=False)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
lang.apply(lang.PREFERENCE_CHINESE)

results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def settle(times: int = 15) -> None:
    for _ in range(times):
        wx.YieldIfNeeded()
        time.sleep(0.004)


with probe_temp("probe-tree-files") as scratch:
    # ── 造一棵**既有目录又有文件**的树 ──
    root = os.path.join(scratch, "Tree")
    os.makedirs(os.path.join(root, "alpha-dir"), exist_ok=True)
    os.makedirs(os.path.join(root, "beta-dir"), exist_ok=True)
    for name in ("zulu.txt", "aaa.txt", "mid.md"):
        with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
            handle.write("x")

    db = os.path.join(scratch, "p.db")
    app_mod.default_db_path = lambda: db
    app_mod.default_config_path = lambda: os.path.join(scratch, "c.json")
    seed = app_mod.PathStore(db)
    seed.record_access(root)
    seed.close()

    frame = app_mod.FileTracker()
    frame.Show()
    settle(50)
    tree = frame.dir_ctrl

    item = tree.expand_to(root, select=False)
    check("能在树里走到测试目录", item is not None,
          f"root = …{root[-30:]}")

    if item is not None:
        tree._populated.pop(item, None)
        tree._populate_item(item)
        settle()

        kids = []
        child, cookie = tree.GetFirstChild(item)
        while child.IsOk():
            full = os.path.join(root, tree.GetItemText(child))
            kids.append((tree.GetItemText(child), os.path.isdir(full),
                         tree.ItemHasChildren(child)))
            child, cookie = tree.GetNextChild(item, cookie)

        names = [k[0] for k in kids]
        dirs = [k for k in kids if k[1]]
        files = [k for k in kids if not k[1]]

        check("① 树里**同时有目录和文件**",
              bool(dirs) and bool(files),
              f"目录 {[k[0] for k in dirs]}｜文件 {[k[0] for k in files]}")

        check("② 目录排在文件**前面**",
              names == [k[0] for k in dirs] + [k[0] for k in files],
              f"实际顺序 = {names}")

        check("③ **文件没有展开箭头**（没加占位子节点）",
              all(not k[2] for k in files),
              f"文件的 ItemHasChildren = {[k[2] for k in files]}")

        check("④ 目录**有**展开箭头（加了占位子节点）",
              all(k[2] for k in dirs),
              f"目录的 ItemHasChildren = {[k[2] for k in dirs]}")

        # ── (b) 选中一个文件 ⇒ open_targets() 应给出父目录 ──
        target_file = None
        child, cookie = tree.GetFirstChild(item)
        while child.IsOk():
            full = os.path.join(root, tree.GetItemText(child))
            if os.path.isfile(full):
                target_file = (child, full)
                break
            child, cookie = tree.GetNextChild(item, cookie)

        if target_file:
            node, full = target_file
            tree.UnselectAll()
            tree.SelectItem(node)
            frame._focus_pane = "tree"
            settle()

            got = frame.open_targets()
            check("⑤ (b) 树选中**文件** ⇒ open_targets() 给出**父目录**",
                  got == [root], f"选中 …{full[-24:]} ⇒ 返回 {[g[-24:] for g in got]}")

            check("⑥ `folder_for` 对目录**原样返回**",
                  frame.dir_ctrl.folder_for(root) == root, "")

            # ── (a) 真的走一次双击文件的处理 ──
            recorded = []
            opened = []
            frame.record_accessed_path = lambda p: recorded.append(p)
            frame.open_folder = lambda p: opened.append(p)
            frame._call_later = lambda ms, fn=None: None
            frame.confirm_remove_invalid_path = lambda p: None

            class _Evt:
                def GetItem(self):
                    return node

                def Veto(self):
                    pass

                def Skip(self):
                    pass

            frame.on_dir_item_activated(_Evt())
            check("⑦ (a) 双击**文件** ⇒ 打开并记录它的**父目录**",
                  opened == [root] and recorded == [root],
                  f"打开 {[o[-20:] for o in opened]}｜记录 "
                  f"{[r[-20:] for r in recorded]}")

    frame.store.close()
    frame.Destroy()

print()
passed = sum(1 for ok, _, _ in results if ok)
for ok, name, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
    if detail:
        print(f"       {detail}")
print()
print(f"  合计 {len(results)} 条：{passed} 通过，{len(results) - passed} 失败")
